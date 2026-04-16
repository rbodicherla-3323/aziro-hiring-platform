import json
from pathlib import Path

PROCTORING_EVENTS_JSONL = Path("app/runtime/proctoring/events.jsonl")


def blank_proctoring_summary():
    return {
        "tab_switches": 0,
        "fullscreen_exits": 0,
        "multi_monitor_events": 0,
        "keyboard_shortcuts_blocked": 0,
        "copy_paste_blocks": 0,
        "right_click_blocks": 0,
        "screenshot_captures": 0,
        "webcam_stream_interruptions": 0,
        "webcam_stream_mute_events": 0,
        "webcam_recording_errors": 0,
        "external_device_events": 0,
        "multi_face_events": 0,
        "no_face_events": 0,
        "no_face_duration_seconds": 0.0,
        "attention_deviation_count": 0,
        "suspicion_score": 0,
        "suspicion_threshold_exceeded": False,
        "suspicion_threshold_event_count": 0,
        "total_count": 0,
    }


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_session_scope(session_ids_by_email):
    scope = {}
    if not isinstance(session_ids_by_email, dict):
        return scope

    for raw_email, raw_sessions in session_ids_by_email.items():
        email_key = str(raw_email or "").strip().lower()
        if not email_key:
            continue
        values = set()
        if isinstance(raw_sessions, (set, list, tuple)):
            for sid in raw_sessions:
                sid_key = str(sid or "").strip().lower()
                if sid_key:
                    values.add(sid_key)
        # Treat empty/invalid session scopes as "no filter" so reports still aggregate
        # available proctoring events for that candidate email.
        if values:
            scope[email_key] = values
    return scope


def build_proctoring_summary_by_email(
    emails,
    events_file=PROCTORING_EVENTS_JSONL,
    session_ids_by_email=None,
):
    normalized = {
        str(email or "").strip().lower()
        for email in emails
        if str(email or "").strip()
    }
    if not normalized:
        return {}

    summaries = {email: blank_proctoring_summary() for email in normalized}
    if not events_file.exists():
        return summaries

    scoped_sessions = _normalize_session_scope(session_ids_by_email)

    try:
        with events_file.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                email = str(event.get("email") or "").strip().lower()
                if not email or email not in summaries:
                    continue

                if email in scoped_sessions:
                    session_id = str(event.get("session_id") or "").strip().lower()
                    if not session_id or session_id not in scoped_sessions[email]:
                        continue

                summary = summaries[email]
                event_type = str(event.get("event_type") or "").strip().lower()
                details = event.get("details")
                if not isinstance(details, dict):
                    details = {}

                summary["total_count"] += 1

                if event_type == "tab switching detected":
                    summary["tab_switches"] += 1
                elif event_type == "fullscreen exited":
                    summary["fullscreen_exits"] += 1
                elif event_type == "multi-monitor activity detected":
                    summary["multi_monitor_events"] += 1
                elif event_type == "keyboard shortcut blocked":
                    summary["keyboard_shortcuts_blocked"] += 1
                elif event_type in {"copy blocked", "paste blocked"}:
                    summary["copy_paste_blocks"] += 1
                elif event_type == "right click blocked":
                    summary["right_click_blocks"] += 1
                elif event_type == "webcam stream interrupted":
                    summary["webcam_stream_interruptions"] += 1
                elif event_type in {"webcam stream muted", "webcam stream unmuted"}:
                    summary["webcam_stream_mute_events"] += 1
                elif event_type == "webcam recording error":
                    summary["webcam_recording_errors"] += 1
                elif event_type == "external device activity detected":
                    summary["external_device_events"] += 1
                elif event_type == "multiple faces detected":
                    summary["multi_face_events"] += 1
                elif event_type == "no face detected":
                    summary["no_face_events"] += 1
                    summary["no_face_duration_seconds"] += _to_float(details.get("no_face_duration_seconds"), 0.0)
                elif event_type == "attention deviation detected":
                    summary["attention_deviation_count"] += 1

                if event_type == "suspicion threshold exceeded":
                    summary["suspicion_threshold_exceeded"] = True
                    summary["suspicion_threshold_event_count"] += 1

                if event_type.startswith("screenshot:"):
                    summary["screenshot_captures"] += 1

                if event_type in {"suspicion score updated", "suspicion threshold exceeded"}:
                    score = _to_int(details.get("suspicion_score"), 0)
                    if score > summary["suspicion_score"]:
                        summary["suspicion_score"] = score
    except OSError:
        return summaries

    return summaries
