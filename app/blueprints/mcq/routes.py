import base64
import binascii
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import render_template, redirect, url_for, request, session, jsonify, current_app
from . import mcq_bp

from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from .services import MCQSessionService
from app.services.evaluation_service import EvaluationService

PROCTORING_EVENT_STORE = {}
PROCTORING_LOG_DIR = Path("app/runtime/proctoring")
PROCTORING_SCREENSHOT_DIR = PROCTORING_LOG_DIR / "screenshots"
PROCTORING_WEBCAM_DIR = PROCTORING_LOG_DIR / "webcam"
PROCTORING_EVENTS_JSONL = PROCTORING_LOG_DIR / "events.jsonl"
PROCTORING_EVENTS_CSV = PROCTORING_LOG_DIR / "events.csv"
MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024
MAX_WEBCAM_CHUNK_BYTES = 5 * 1024 * 1024


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _extract_session_id_from_context(payload):
    session_id = str(payload.get("session_id", "")).strip()
    if session_id:
        return session_id

    referer = request.headers.get("Referer", "")
    match = re.search(r"/mcq/(?:start|question|submit|completed)/([^/?#]+)", referer)
    if match:
        return match.group(1)

    return ""


def _ensure_proctoring_log_dir():
    PROCTORING_LOG_DIR.mkdir(parents=True, exist_ok=True)
    PROCTORING_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    PROCTORING_WEBCAM_DIR.mkdir(parents=True, exist_ok=True)


def _safe_slug(value, fallback):
    raw = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return slug or fallback


def _resolve_screenshot_bucket(session_id, ts=None):
    session_meta = MCQ_SESSION_REGISTRY.get(session_id, {})

    parsed_ts = None
    if isinstance(ts, str) and ts:
        try:
            parsed_ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            parsed_ts = None

    bucket_dt = parsed_ts.astimezone(timezone.utc) if parsed_ts else datetime.now(timezone.utc)

    role_label = session_meta.get("role_label") or session_meta.get("role_key") or "role_unknown"
    candidate_name = session_meta.get("candidate_name") or session_meta.get("email") or "candidate_unknown"
    batch_id = session_meta.get("batch_id") or "batch_unassigned"

    return {
        "date": bucket_dt.strftime("%Y-%m-%d"),
        "batch": _safe_slug(batch_id, "batch_unassigned"),
        "role": _safe_slug(role_label, "role_unknown"),
        "candidate_role": _safe_slug(f"{candidate_name}_{role_label}", "candidate_role_unknown"),
    }


def _persist_proctoring_event(event):
    try:
        _ensure_proctoring_log_dir()

        with PROCTORING_EVENTS_JSONL.open("a", encoding="utf-8") as f_jsonl:
            f_jsonl.write(json.dumps(event, ensure_ascii=False) + "\n")

        csv_exists = PROCTORING_EVENTS_CSV.exists()
        with PROCTORING_EVENTS_CSV.open("a", encoding="utf-8", newline="") as f_csv:
            writer = csv.DictWriter(
                f_csv,
                fieldnames=[
                    "event_id",
                    "ts",
                    "session_id",
                    "candidate_name",
                    "email",
                    "round_label",
                    "event_type",
                    "details_json",
                    "screenshot_path",
                ],
            )
            if not csv_exists:
                writer.writeheader()
            writer.writerow({
                "event_id": event["event_id"],
                "ts": event["ts"],
                "session_id": event["session_id"],
                "candidate_name": event.get("candidate_name", ""),
                "email": event.get("email", ""),
                "round_label": event.get("round_label", ""),
                "event_type": event["event_type"],
                "details_json": json.dumps(event.get("details", {}), ensure_ascii=False),
                "screenshot_path": event.get("screenshot_path", ""),
            })
    except OSError:
        # Keep proctoring flow non-blocking even if filesystem persistence fails.
        return


def _record_proctoring_event(session_id, event_type, details=None, ts=None, screenshot_path=""):
    session_meta = MCQ_SESSION_REGISTRY.get(session_id, {})
    event = {
        "event_id": uuid4().hex,
        "ts": ts or _utc_now_iso(),
        "session_id": session_id,
        "candidate_name": session_meta.get("candidate_name", ""),
        "email": session_meta.get("email", ""),
        "round_label": session_meta.get("round_label", ""),
        "event_type": event_type,
        "details": details or {},
        "screenshot_path": screenshot_path or "",
    }

    bucket = PROCTORING_EVENT_STORE.setdefault(session_id, [])
    bucket.append(event)
    if len(bucket) > 2000:
        del bucket[:-2000]

    _persist_proctoring_event(event)
    return event


def _is_ajax_request():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _proctoring_enabled():
    return bool(current_app.config.get("PROCTORING_ENABLED", False))


def _question_payload(session_id, q_index):
    question = MCQSessionService.get_question(session_id, q_index)
    if not question:
        return None

    return {
        "q_index": q_index,
        "total_questions": MCQSessionService.total_questions(session_id),
        "remaining_seconds": MCQSessionService.remaining_time(session_id),
        "question_text": question.get("question") or question.get("text") or "",
        "options": question.get("options", []),
        "selected_answer": MCQSessionService.get_answer(session_id, q_index),
        "question_url": url_for("mcq.question", session_id=session_id, q=q_index),
        "submit_url": url_for("mcq.submit", session_id=session_id),
    }


# -------------------------------------------------
# START PAGE
# -------------------------------------------------
@mcq_bp.route("/start/<session_id>")
def start_test(session_id):

    session_meta = MCQ_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        return "Invalid or expired test link", 404

    # ✅ Clear ALL old test session data to keep cookie small
    #    (Flask's cookie-based session has a ~4 KB browser limit;
    #     accumulated question payloads from earlier rounds cause
    #     the Set-Cookie to be silently dropped.)
    stale_keys = [k for k in list(session.keys())
                  if k.startswith(("mcq_", "coding_"))]
    for k in stale_keys:
        session.pop(k)

    MCQSessionService.init_session(
        session_id=session_id,
        role_key=session_meta["role_key"],
        round_key=session_meta["round_key"],
        domain=session_meta.get("domain"),
        force_reset=True
    )

    return render_template(
        "mcq/start.html",
        test={
            "session_id": session_id,
            "round_name": session_meta["round_label"],
            "total_questions": MCQSessionService.total_questions(session_id),
            "time_minutes": 20
        },
        candidate_name=session_meta["candidate_name"],
        proctoring_enabled=_proctoring_enabled(),
    )


# -------------------------------------------------
# BEGIN TEST
# -------------------------------------------------
@mcq_bp.route("/begin/<session_id>", methods=["POST"])
def begin_test(session_id):
    return redirect(
        url_for("mcq.question", session_id=session_id, q=0)
    )


# -------------------------------------------------
# QUESTION PAGE (ONE QUESTION AT A TIME)
# -------------------------------------------------
@mcq_bp.route("/question/<session_id>", methods=["GET", "POST"])
def question(session_id):

    session_meta = MCQ_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        return "Invalid or expired test link", 404

    try:
        q_index = max(0, int(request.args.get("q", 0)))
    except (TypeError, ValueError):
        q_index = 0

    question = MCQSessionService.get_question(session_id, q_index)
    if not question:
        if _is_ajax_request():
            return jsonify({
                "done": True,
                "submit_url": url_for("mcq.submit", session_id=session_id)
            })
        return redirect(
            url_for("mcq.submit", session_id=session_id)
        )

    if request.method == "POST":
        selected_answer = request.form.get("answer")
        if selected_answer:
            MCQSessionService.save_answer(
                session_id,
                q_index,
                selected_answer
            )

        nav = request.form.get("nav", "next")
        if nav == "prev":
            next_index = max(0, q_index - 1)
        else:
            next_index = q_index + 1
            if next_index >= MCQSessionService.total_questions(session_id):
                if _is_ajax_request():
                    return jsonify({
                        "done": True,
                        "submit_url": url_for("mcq.submit", session_id=session_id)
                    })
                return redirect(
                    url_for("mcq.submit", session_id=session_id)
                )

        if _is_ajax_request():
            payload = _question_payload(session_id, next_index)
            if not payload:
                return jsonify({
                    "done": True,
                    "submit_url": url_for("mcq.submit", session_id=session_id)
                })
            return jsonify({
                "done": False,
                "question": payload
            })

        return redirect(
            url_for("mcq.question", session_id=session_id, q=next_index)
        )

    if _is_ajax_request():
        payload = _question_payload(session_id, q_index)
        if not payload:
            return jsonify({
                "done": True,
                "submit_url": url_for("mcq.submit", session_id=session_id)
            })
        return jsonify({
            "done": False,
            "question": payload
        })

    return render_template(
        "mcq/question.html",
        question=question,
        q_index=q_index,
        total_questions=MCQSessionService.total_questions(session_id),
        remaining_seconds=MCQSessionService.remaining_time(session_id),
        selected_answer=MCQSessionService.get_answer(session_id, q_index),
        session_id=session_id,
        candidate_name=session_meta["candidate_name"],
        proctoring_enabled=_proctoring_enabled(),
    )


# -------------------------------------------------
# PROCTORING EVENTS
# -------------------------------------------------
@mcq_bp.route("/proctoring/violation", methods=["POST"])
def proctoring_violation():
    if not _proctoring_enabled():
        return jsonify({"status": "disabled"})

    payload = request.get_json(silent=True) or {}
    session_id = _extract_session_id_from_context(payload)
    if not session_id:
        return jsonify({"status": "ignored", "reason": "missing_session_id"})

    details = payload.get("details")
    if not isinstance(details, dict):
        details = {}

    event_type = str(payload.get("violation_type") or payload.get("event_type") or "proctoring_event")
    ts = payload.get("ts") or _utc_now_iso()

    event = _record_proctoring_event(
        session_id=session_id,
        event_type=event_type,
        details=details,
        ts=ts,
        screenshot_path=str(payload.get("screenshot_path", "")),
    )

    return jsonify({"status": "logged", "event_id": event["event_id"]})


@mcq_bp.route("/proctoring/screenshot", methods=["POST"])
def proctoring_screenshot():
    if not _proctoring_enabled():
        return jsonify({"status": "disabled"})

    payload = request.get_json(silent=True) or {}
    session_id = _extract_session_id_from_context(payload)
    if not session_id:
        return jsonify({"status": "ignored", "reason": "missing_session_id"})

    image_data = str(payload.get("image_data", ""))
    details = payload.get("details")
    if not isinstance(details, dict):
        details = {}

    event_type = str(payload.get("event_type") or "screenshot")
    ts = payload.get("ts") or _utc_now_iso()

    screenshot_path = ""

    try:
        if image_data.startswith("data:image/") and "," in image_data:
            header, encoded = image_data.split(",", 1)
            mime_type = header.split(";")[0].replace("data:", "").strip().lower()
            extension = "jpg" if "jpeg" in mime_type or "jpg" in mime_type else "png"

            image_bytes = base64.b64decode(encoded, validate=True)
            if len(image_bytes) > MAX_SCREENSHOT_BYTES:
                details["screenshot_rejected"] = "payload_too_large"
            else:
                _ensure_proctoring_log_dir()
                bucket = _resolve_screenshot_bucket(session_id, ts)
                session_dir = (
                    PROCTORING_SCREENSHOT_DIR
                    / bucket["date"]
                    / bucket["batch"]
                    / bucket["role"]
                    / bucket["candidate_role"]
                    / session_id
                )
                session_dir.mkdir(parents=True, exist_ok=True)

                filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex[:8]}.{extension}"
                screenshot_file = session_dir / filename
                screenshot_file.write_bytes(image_bytes)

                screenshot_path = screenshot_file.as_posix()
                details["screenshot_bytes"] = len(image_bytes)
                details["capture_event"] = event_type
                details["screenshot_bucket"] = bucket
        else:
            details["screenshot_rejected"] = "invalid_payload"
    except (binascii.Error, OSError, ValueError):
        details["screenshot_rejected"] = "decode_or_write_failed"

    event = _record_proctoring_event(
        session_id=session_id,
        event_type=f"screenshot:{event_type}",
        details=details,
        ts=ts,
        screenshot_path=screenshot_path,
    )

    return jsonify({
        "status": "logged",
        "event_id": event["event_id"],
        "screenshot_path": screenshot_path,
    })


@mcq_bp.route("/proctoring/webcam", methods=["POST"])
def proctoring_webcam():
    """Handle webcam video chunk uploads and finalization."""
    if not _proctoring_enabled():
        return jsonify({"status": "disabled"})

    session_id = request.form.get("session_id", "").strip()
    if not session_id:
        return jsonify({"status": "ignored", "reason": "missing_session_id"})

    recording_id = request.form.get("recording_id", "").strip()
    if not recording_id:
        return jsonify({"status": "ignored", "reason": "missing_recording_id"})

    is_final = request.form.get("final") == "1"
    mime_type = request.form.get("mime_type", "video/webm")
    ts = request.form.get("ts") or _utc_now_iso()

    _ensure_proctoring_log_dir()

    # Build session-specific webcam directory
    bucket = _resolve_screenshot_bucket(session_id, ts)
    session_webcam_dir = (
        PROCTORING_WEBCAM_DIR
        / bucket["date"]
        / bucket["batch"]
        / bucket["role"]
        / bucket["candidate_role"]
        / session_id
    )
    session_webcam_dir.mkdir(parents=True, exist_ok=True)

    recording_dir = session_webcam_dir / recording_id
    recording_dir.mkdir(parents=True, exist_ok=True)

    if is_final:
        # Finalize: merge all chunks into a single video file
        chunk_count = int(request.form.get("chunk_count", 0))
        chunks_dir = recording_dir / "chunks"

        final_video_path = ""
        merge_success = False

        if chunks_dir.exists():
            chunk_files = sorted(chunks_dir.glob("chunk_*.webm"))
            if chunk_files:
                extension = "webm"
                final_filename = f"recording_{recording_id}.{extension}"
                final_video_file = recording_dir / final_filename

                try:
                    with final_video_file.open("wb") as out_f:
                        for chunk_file in chunk_files:
                            out_f.write(chunk_file.read_bytes())
                    final_video_path = final_video_file.as_posix()
                    merge_success = True

                    # Clean up chunk files after successful merge
                    for chunk_file in chunk_files:
                        try:
                            chunk_file.unlink()
                        except OSError:
                            pass
                    try:
                        chunks_dir.rmdir()
                    except OSError:
                        pass
                except OSError:
                    merge_success = False

        event = _record_proctoring_event(
            session_id=session_id,
            event_type="webcam_recording_finalized",
            details={
                "recording_id": recording_id,
                "chunk_count": chunk_count,
                "mime_type": mime_type,
                "merge_success": merge_success,
                "video_path": final_video_path,
            },
            ts=ts,
        )

        return jsonify({
            "status": "finalized",
            "event_id": event["event_id"],
            "video_path": final_video_path,
            "merge_success": merge_success,
        })

    # Handle chunk upload
    chunk_index = request.form.get("chunk_index", "0")
    chunk_file = request.files.get("chunk")

    if not chunk_file:
        return jsonify({"status": "ignored", "reason": "missing_chunk_data"})

    chunk_bytes = chunk_file.read()
    if len(chunk_bytes) > MAX_WEBCAM_CHUNK_BYTES:
        return jsonify({"status": "ignored", "reason": "chunk_too_large"})

    chunks_dir = recording_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunk_filename = f"chunk_{str(chunk_index).zfill(6)}.webm"
    chunk_path = chunks_dir / chunk_filename

    try:
        chunk_path.write_bytes(chunk_bytes)
    except OSError:
        return jsonify({"status": "error", "reason": "write_failed"})

    event = _record_proctoring_event(
        session_id=session_id,
        event_type="webcam_chunk_received",
        details={
            "recording_id": recording_id,
            "chunk_index": chunk_index,
            "chunk_size": len(chunk_bytes),
            "mime_type": mime_type,
        },
        ts=ts,
    )

    return jsonify({
        "status": "chunk_saved",
        "event_id": event["event_id"],
        "chunk_index": chunk_index,
    })


# -------------------------------------------------
# SUBMIT CONFIRMATION
# -------------------------------------------------
@mcq_bp.route("/submit/<session_id>", methods=["GET", "POST"])
def submit(session_id):

    if request.method == "POST":
        # Evaluate only once here
        EvaluationService.evaluate_mcq(session_id)

        # Free cookie space immediately after evaluation
        MCQSessionService.clear_session(session_id)

        completed_url = url_for("mcq.completed", session_id=session_id)
        if _is_ajax_request():
            return jsonify({"redirect_url": completed_url})

        return redirect(
            completed_url
        )

    return render_template(
        "mcq/submit.html",
        proctoring_enabled=_proctoring_enabled(),
    )


# -------------------------------------------------
# COMPLETION PAGE
# -------------------------------------------------
@mcq_bp.route("/completed/<session_id>")
def completed(session_id):
    return render_template(
        "mcq/completed.html",
        proctoring_enabled=_proctoring_enabled(),
    )
