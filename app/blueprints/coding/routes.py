import base64
import binascii
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import render_template, redirect, url_for, request, session, jsonify
from . import coding_bp

from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from .services import CodingSessionService

# -------------------------------------------------
# PROCTORING INFRASTRUCTURE (mirrors MCQ proctoring)
# -------------------------------------------------
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
    match = re.search(r"/coding/(?:start|editor|submit|completed)/([^/?#]+)", referer)
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
    session_meta = CODING_SESSION_REGISTRY.get(session_id, {})

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
        return


def _record_proctoring_event(session_id, event_type, details=None, ts=None, screenshot_path=""):
    session_meta = CODING_SESSION_REGISTRY.get(session_id, {})
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


# -------------------------------------------------
# START PAGE
# -------------------------------------------------
@coding_bp.route("/start/<session_id>")
def start_test(session_id):
    session_meta = CODING_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        return "Invalid or expired coding test link", 404

    # ✅ Clear ALL old test session data to keep cookie small
    stale_keys = [k for k in list(session.keys())
                  if k.startswith(("mcq_", "coding_"))]
    for k in stale_keys:
        session.pop(k)

    language = session_meta.get("language", "java")

    CodingSessionService.init_session(
        session_id=session_id,
        role_key=session_meta["role_key"],
        round_key=session_meta["round_key"],
        language=language,
        domain=session_meta.get("domain"),
    )

    question = CodingSessionService.get_question(session_id)

    return render_template(
        "coding/start.html",
        test={
            "session_id": session_id,
            "round_name": session_meta["round_label"],
            "language": language.upper(),
            "time_minutes": 20,
            "question_title": question["title"] if question else "Coding Challenge",
            "difficulty": question.get("difficulty", "MEDIUM") if question else "MEDIUM",
        },
        candidate_name=session_meta["candidate_name"],
    )


# -------------------------------------------------
# BEGIN TEST → redirects to editor
# -------------------------------------------------
@coding_bp.route("/begin/<session_id>", methods=["POST"])
def begin_test(session_id):
    if _is_ajax_request():
        return jsonify({"status": "ok", "editor_url": url_for("coding.editor", session_id=session_id)})
    return redirect(url_for("coding.editor", session_id=session_id))


# -------------------------------------------------
# EDITOR PAGE (Main coding interface)
# -------------------------------------------------
@coding_bp.route("/editor/<session_id>", methods=["GET", "POST"])
def editor(session_id):
    session_meta = CODING_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        return "Invalid or expired coding test link", 404

    if CodingSessionService.is_submitted(session_id):
        return redirect(url_for("coding.completed", session_id=session_id))

    question = CodingSessionService.get_question(session_id)
    if not question:
        return "Session not initialized", 400

    language = CodingSessionService.get_language(session_id)
    code = CodingSessionService.get_code(session_id)
    public_tests = CodingSessionService.get_public_tests(session_id)
    remaining = CodingSessionService.remaining_time(session_id)

    # Format public test cases for display
    formatted_tests = []
    for i, tc in enumerate(public_tests):
        formatted_tests.append({
            "index": i + 1,
            "input": tc.get("input", []),
            "expected": tc.get("expected", ""),
        })

    return render_template(
        "coding/editor.html",
        session_id=session_id,
        question=question,
        language=language,
        code=code,
        public_tests=formatted_tests,
        remaining_seconds=remaining,
        candidate_name=session_meta["candidate_name"],
        submit_url=url_for("coding.submit", session_id=session_id),
    )


# -------------------------------------------------
# SAVE CODE (Auto-save via AJAX)
# -------------------------------------------------
@coding_bp.route("/save/<session_id>", methods=["POST"])
def save_code(session_id):
    session_meta = CODING_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        return jsonify({"status": "error", "reason": "invalid_session"}), 404

    payload = request.get_json(silent=True) or {}
    code = payload.get("code", "")

    CodingSessionService.save_code(session_id, code)

    return jsonify({
        "status": "saved",
        "remaining_seconds": CodingSessionService.remaining_time(session_id),
    })


# -------------------------------------------------
# CODE EXECUTION HELPERS
# -------------------------------------------------
COMPILE_TIMEOUT = 15   # seconds
RUN_TIMEOUT = 10       # seconds per test case


def _build_driver_code(language, code, question, test_inputs):
    """Wrap candidate code with a main() driver that reads stdin and calls their function."""
    func_info = question.get("function", {}).get(language, {})

    if language == "java":
        method_sig = func_info.get("method", "") if isinstance(func_info, dict) else str(func_info)
        # Extract method name from signature like "public static int solve(int n)"
        import re as _re
        m = _re.search(r'(\w+)\s*\(', method_sig)
        method_name = m.group(1) if m else "solve"
        class_name = func_info.get("class", "Solution") if isinstance(func_info, dict) else "Solution"

        driver = (
            "import java.util.*;\n"
            "import java.util.stream.*;\n\n"
            f"{code}\n\n"
            "class Main {\n"
            "    public static void main(String[] args) {\n"
            "        Scanner sc = new Scanner(System.in);\n"
            "        String line = sc.nextLine().trim();\n"
            "        // Parse input - handle comma-separated values\n"
            "        if (line.startsWith(\"[\")) {\n"
            "            // Array input\n"
            "            line = line.substring(1, line.length()-1);\n"
            "            String[] parts = line.split(\",\");\n"
            "            int[] arr = new int[parts.length];\n"
            "            for(int i=0;i<parts.length;i++) arr[i]=Integer.parseInt(parts[i].trim());\n"
            f"            Object result = {class_name}.{method_name}(arr);\n"
            "            System.out.println(result);\n"
            "        } else {\n"
            "            // Single value input\n"
            "            try {\n"
            "                int val = Integer.parseInt(line);\n"
            f"                Object result = {class_name}.{method_name}(val);\n"
            "                System.out.println(result);\n"
            "            } catch(Exception e) {\n"
            f"                Object result = {class_name}.{method_name}(line);\n"
            "                System.out.println(result);\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        return driver

    elif language == "c":
        signature = func_info.get("signature", str(func_info)) if isinstance(func_info, dict) else str(func_info)
        import re as _re
        m = _re.search(r'(\w+)\s*\(', signature)
        func_name = m.group(1) if m else "solve"
        # Detect return type
        ret_type = signature.split(func_name)[0].strip() if func_name in signature else "int"

        driver = (
            f"{code}\n\n"
            "int main() {\n"
            "    int n;\n"
            "    scanf(\"%d\", &n);\n"
        )
        if "void" in ret_type:
            driver += f"    {func_name}(n);\n"
        else:
            driver += f"    printf(\"%d\\n\", {func_name}(n));\n"
        driver += "    return 0;\n}\n"
        return driver

    elif language == "cpp":
        signature = func_info.get("signature", str(func_info)) if isinstance(func_info, dict) else str(func_info)
        import re as _re
        m = _re.search(r'(\w+)\s*\(', signature)
        func_name = m.group(1) if m else "solve"
        ret_type = signature.split(func_name)[0].strip() if func_name in signature else "int"

        driver = (
            f"{code}\n\n"
            "int main() {\n"
            "    int n;\n"
            "    cin >> n;\n"
        )
        if "void" in ret_type:
            driver += f"    {func_name}(n);\n"
        else:
            driver += f"    cout << {func_name}(n) << endl;\n"
        driver += "    return 0;\n}\n"
        return driver

    return code


def _compile_and_run(language, code, stdin_input, work_dir):
    """Compile (if needed) and run the code, returning (success, stdout, stderr, exec_time_ms)."""
    start_t = _time.time()

    if language == "java":
        src_file = os.path.join(work_dir, "Main.java")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write(code)

        # Compile
        comp = subprocess.run(
            ["javac", src_file],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT, cwd=work_dir
        )
        if comp.returncode != 0:
            return False, "", f"Compilation Error:\n{comp.stderr}", 0

        # Run
        run = subprocess.run(
            ["java", "-cp", work_dir, "Main"],
            input=stdin_input, capture_output=True, text=True,
            timeout=RUN_TIMEOUT, cwd=work_dir
        )
        elapsed = int((_time.time() - start_t) * 1000)
        if run.returncode != 0:
            return False, run.stdout, f"Runtime Error:\n{run.stderr}", elapsed
        return True, run.stdout, run.stderr, elapsed

    elif language == "c":
        src_file = os.path.join(work_dir, "solution.c")
        exe_file = os.path.join(work_dir, "solution.exe" if os.name == "nt" else "solution")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write(code)

        comp = subprocess.run(
            ["gcc", src_file, "-o", exe_file, "-lm"],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT, cwd=work_dir
        )
        if comp.returncode != 0:
            return False, "", f"Compilation Error:\n{comp.stderr}", 0

        run = subprocess.run(
            [exe_file],
            input=stdin_input, capture_output=True, text=True,
            timeout=RUN_TIMEOUT, cwd=work_dir
        )
        elapsed = int((_time.time() - start_t) * 1000)
        if run.returncode != 0:
            return False, run.stdout, f"Runtime Error:\n{run.stderr}", elapsed
        return True, run.stdout, run.stderr, elapsed

    elif language == "cpp":
        src_file = os.path.join(work_dir, "solution.cpp")
        exe_file = os.path.join(work_dir, "solution.exe" if os.name == "nt" else "solution")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write(code)

        comp = subprocess.run(
            ["g++", src_file, "-o", exe_file, "-std=c++17"],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT, cwd=work_dir
        )
        if comp.returncode != 0:
            return False, "", f"Compilation Error:\n{comp.stderr}", 0

        run = subprocess.run(
            [exe_file],
            input=stdin_input, capture_output=True, text=True,
            timeout=RUN_TIMEOUT, cwd=work_dir
        )
        elapsed = int((_time.time() - start_t) * 1000)
        if run.returncode != 0:
            return False, run.stdout, f"Runtime Error:\n{run.stderr}", elapsed
        return True, run.stdout, run.stderr, elapsed

    return False, "", "Unsupported language", 0


def _format_test_input(inputs):
    """Convert test case input list to stdin string."""
    parts = []
    for val in inputs:
        if isinstance(val, list):
            parts.append("[" + ",".join(str(v) for v in val) + "]")
        else:
            parts.append(str(val))
    return "\n".join(parts)


def _normalize_output(s):
    """Normalize output for comparison — strip, collapse whitespace."""
    return str(s).strip().replace("\r\n", "\n").strip()


# -------------------------------------------------
# RUN CODE (Execute against public test cases)
# -------------------------------------------------
@coding_bp.route("/run/<session_id>", methods=["POST"])
def run_code(session_id):
    """Compile and run the candidate's code against public test cases."""
    session_meta = CODING_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        return jsonify({"status": "error", "reason": "invalid_session"}), 404

    payload = request.get_json(silent=True) or {}
    code = payload.get("code", "")
    custom_input = payload.get("custom_input", "")

    # Save the code
    CodingSessionService.save_code(session_id, code)

    language = CodingSessionService.get_language(session_id)
    question = CodingSessionService.get_question(session_id)
    public_tests = CodingSessionService.get_public_tests(session_id)

    if not code.strip():
        return jsonify({
            "status": "error",
            "output": "Error: No code to execute. Please write your solution first.",
            "test_results": [],
        })

    work_dir = tempfile.mkdtemp(prefix="aziro_code_")
    try:
        # Build full driver code (candidate code + main that reads stdin)
        driver_code = _build_driver_code(language, code, question, public_tests)

        # If custom input is provided, just run with that input
        if custom_input.strip():
            try:
                success, stdout, stderr, elapsed = _compile_and_run(
                    language, driver_code, custom_input.strip(), work_dir
                )
                output_text = ""
                if stderr:
                    output_text += stderr + "\n"
                if stdout:
                    output_text += stdout
                if not output_text.strip():
                    output_text = "(no output)"

                return jsonify({
                    "status": "error" if not success else "executed",
                    "output": output_text.strip(),
                    "execution_time": f"{elapsed}ms",
                    "test_results": [],
                })
            except subprocess.TimeoutExpired:
                return jsonify({
                    "status": "error",
                    "output": "Error: Time Limit Exceeded (TLE). Your code took too long to execute.",
                    "test_results": [],
                })
            except FileNotFoundError:
                compiler_info = {"java": "JDK (javac + java)", "c": "GCC (gcc)", "cpp": "G++ (g++)"}
                return jsonify({
                    "status": "error",
                    "output": f"⚠️  {language.upper()} compiler not found on this machine.\n\n"
                              f"Required: {compiler_info.get(language, language.upper() + ' compiler')}\n"
                              f"Your code has been saved and will be evaluated after submission.",
                    "test_results": [],
                })

        # Run against public test cases
        test_results = []
        total_passed = 0
        total_time = 0
        compilation_done = False
        compilation_error = None

        for i, tc in enumerate(public_tests):
            tc_input = _format_test_input(tc.get("input", []))
            tc_expected = _normalize_output(tc.get("expected", ""))

            try:
                success, stdout, stderr, elapsed = _compile_and_run(
                    language, driver_code, tc_input, work_dir
                )
                total_time += elapsed

                if not success and "Compilation Error" in stderr:
                    # Compilation failed — report it and stop
                    compilation_error = stderr
                    break

                actual = _normalize_output(stdout)
                passed = (actual == tc_expected)
                if passed:
                    total_passed += 1

                test_results.append({
                    "index": i + 1,
                    "passed": passed,
                    "input": tc.get("input", []),
                    "expected": tc_expected,
                    "actual": actual if not passed else tc_expected,
                    "error": stderr if (not success and "Runtime Error" in stderr) else "",
                    "time_ms": elapsed,
                })

            except subprocess.TimeoutExpired:
                test_results.append({
                    "index": i + 1,
                    "passed": False,
                    "input": tc.get("input", []),
                    "expected": tc_expected,
                    "actual": "TLE",
                    "error": "Time Limit Exceeded",
                    "time_ms": RUN_TIMEOUT * 1000,
                })
            except FileNotFoundError:
                compiler_info = {"java": "JDK (javac + java)", "c": "GCC (gcc)", "cpp": "G++ (g++)"}
                return jsonify({
                    "status": "error",
                    "output": f"⚠️  {language.upper()} compiler not found on this machine.\n\n"
                              f"Required: {compiler_info.get(language, language.upper() + ' compiler')}\n"
                              f"Your code has been saved and will be evaluated after submission.",
                    "test_results": [],
                })

        # Build the output summary
        if compilation_error:
            return jsonify({
                "status": "error",
                "output": compilation_error,
                "test_results": [],
            })

        total = len(test_results)
        summary = f"Test Results: {total_passed}/{total} passed"
        if total_time:
            summary += f"  |  Total time: {total_time}ms"

        output_lines = [summary, "─" * 40]
        for tr in test_results:
            status = "✅ PASSED" if tr["passed"] else "❌ FAILED"
            output_lines.append(f"\nTest Case {tr['index']}: {status}")
            output_lines.append(f"  Input:    {tr['input']}")
            output_lines.append(f"  Expected: {tr['expected']}")
            if not tr["passed"]:
                output_lines.append(f"  Actual:   {tr['actual']}")
                if tr["error"]:
                    output_lines.append(f"  Error:    {tr['error']}")
            if tr.get("time_ms"):
                output_lines.append(f"  Time:     {tr['time_ms']}ms")

        return jsonify({
            "status": "executed" if total_passed == total else "partial",
            "output": "\n".join(output_lines),
            "execution_time": f"{total_time}ms",
            "test_results": test_results,
            "passed": total_passed,
            "total": total,
        })

    finally:
        # Clean up temp directory
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass


# -------------------------------------------------
# SUBMIT CONFIRMATION
# -------------------------------------------------
@coding_bp.route("/submit/<session_id>", methods=["GET", "POST"])
def submit(session_id):
    session_meta = CODING_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        return "Invalid or expired coding test link", 404

    if request.method == "POST":
        # Save final code if provided
        payload = request.get_json(silent=True) or {}
        if payload.get("code"):
            CodingSessionService.save_code(session_id, payload["code"])

        CodingSessionService.mark_submitted(session_id)

        # Free cookie space immediately after submission
        session.pop(f"coding_{session_id}", None)

        completed_url = url_for("coding.completed", session_id=session_id)
        if _is_ajax_request():
            return jsonify({"redirect_url": completed_url})

        return redirect(completed_url)

    return render_template(
        "coding/submit.html",
        session_id=session_id,
        candidate_name=session_meta.get("candidate_name", "Candidate"),
    )


# -------------------------------------------------
# COMPLETION PAGE
# -------------------------------------------------
@coding_bp.route("/completed/<session_id>")
def completed(session_id):
    return render_template(
        "coding/completed.html",
        candidate_name=CODING_SESSION_REGISTRY.get(session_id, {}).get("candidate_name", "Candidate"),
    )


# -------------------------------------------------
# PROCTORING ENDPOINTS (mirrors MCQ proctoring)
# -------------------------------------------------
@coding_bp.route("/proctoring/violation", methods=["POST"])
def proctoring_violation():
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


@coding_bp.route("/proctoring/screenshot", methods=["POST"])
def proctoring_screenshot():
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


@coding_bp.route("/proctoring/webcam", methods=["POST"])
def proctoring_webcam():
    """Handle webcam video chunk uploads and finalization."""
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
