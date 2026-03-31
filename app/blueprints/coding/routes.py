import base64
import binascii
import copy
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import time as _time
from threading import Thread
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import render_template, redirect, url_for, request, session, jsonify, current_app
from . import coding_bp

from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services.coding_submission_store import save_coding_submission
from app.services.evaluation_store import EVALUATION_STORE
from app.services.evaluation_service import EvaluationService
from app.services import db_service
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
CODING_EXEC_TMP_DIR = Path("app/runtime/coding_exec_tmp")
MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024
MAX_WEBCAM_CHUNK_BYTES = 5 * 1024 * 1024


def get_language_runtime_status(language: str):
    """
    Check if the required runtime/compiler exists for the given language.
    Returns (is_available: bool, requirement: str).
    """
    lang = str(language or "").strip().lower()
    requirements = {
        "python": "Python 3 runtime (python/py)",
        "javascript": "Node.js runtime (node)",
        "js": "Node.js runtime (node)",
        "java": "Java JDK (javac/java)",
        "c": "C compiler (gcc/clang)",
        "cpp": "C++ compiler (g++/clang++)",
        "csharp": "C# compiler/runtime (dotnet, mcs, or csc)",
    }
    candidates = {
        "python": ["python", "py"],
        "javascript": ["node"],
        "js": ["node"],
        "java": ["javac", "java"],
        "c": ["gcc", "clang"],
        "cpp": ["g++", "clang++"],
        "csharp": ["dotnet", "mcs", "csc"],
    }

    required = requirements.get(lang, "Runtime requirement not configured")
    for cmd in candidates.get(lang, []):
        if shutil.which(cmd):
            return True, required
    return False, required


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_ts(ts):
    if isinstance(ts, str) and ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


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


def _ensure_coding_exec_tmp_dir():
    CODING_EXEC_TMP_DIR.mkdir(parents=True, exist_ok=True)


def _create_execution_work_dir():
    _ensure_coding_exec_tmp_dir()
    for _ in range(5):
        candidate = CODING_EXEC_TMP_DIR / f"aziro_code_{uuid4().hex}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return str(candidate.resolve())
        except FileExistsError:
            continue
    raise OSError("Unable to allocate execution working directory.")


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


def _proctoring_enabled():
    return bool(current_app.config.get("PROCTORING_ENABLED", False))


# -------------------------------------------------
# START PAGE
# -------------------------------------------------
@coding_bp.route("/start/<session_id>")
def start_test(session_id):
    session_meta = CODING_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        return "Invalid or expired coding test link", 404
    if session_meta.get("started"):
        return "This test has already been started. Restart is not allowed.", 403

    # Clear ALL old test session data to keep cookie small
    stale_keys = [k for k in list(session.keys())
                  if k.startswith(("mcq_", "coding_"))]
    for k in stale_keys:
        if k.startswith("coding_"):
            stale_session_id = k.replace("coding_", "", 1)
            if stale_session_id:
                CodingSessionService.clear_session(stale_session_id)
        session.pop(k, None)

    language = session_meta.get("language", "java")

    CodingSessionService.init_session(
        session_id=session_id,
        role_key=session_meta["role_key"],
        round_key=session_meta["round_key"],
        language=language,
        domain=session_meta.get("domain"),
    )

    question = CodingSessionService.get_question(session_id)
    language_display = {
        "java": "Java",
        "python": "Python",
        "javascript": "JavaScript",
        "js": "JavaScript",
        "c": "C",
        "cpp": "C++",
        "csharp": "C#",
        "c#": "C#",
    }.get(str(language or "").lower(), str(language or "java").upper())

    return render_template(
        "coding/start.html",
        test={
            "session_id": session_id,
            "round_name": session_meta["round_label"],
            "language": language_display,
            "time_minutes": 30,
            "question_title": question["title"] if question else "Coding Challenge",
            "difficulty": question.get("difficulty", "MEDIUM") if question else "MEDIUM",
        },
        candidate_name=session_meta["candidate_name"],
        candidate_email=session_meta.get("email", ""),
        role_label=session_meta.get("role_label", session_meta.get("role_key", "")),
        proctoring_enabled=_proctoring_enabled(),
        body_class="mcq-start-page",
    )


# -------------------------------------------------
# BEGIN TEST -> redirects to editor
# -------------------------------------------------
@coding_bp.route("/begin/<session_id>", methods=["POST"])
def begin_test(session_id):
    session_meta = CODING_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        if _is_ajax_request():
            return jsonify({"status": "error", "reason": "invalid_session"}), 404
        return "Invalid or expired coding test link", 404
    if session_meta.get("started"):
        if _is_ajax_request():
            return jsonify({"status": "locked", "reason": "already_started"}), 403
        return "This test has already been started. Restart is not allowed.", 403

    session_meta["started"] = True
    session_meta["started_at"] = _utc_now_iso()
    CODING_SESSION_REGISTRY[session_id] = session_meta

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
    if not session_meta.get("started"):
        session_meta["started"] = True
        session_meta["started_at"] = _utc_now_iso()
        CODING_SESSION_REGISTRY[session_id] = session_meta

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
        proctoring_enabled=_proctoring_enabled(),
        submit_url=url_for("coding.submit", session_id=session_id),
        body_class="coding-editor-page",
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


def _resolve_executable(cmd_name):
    """
    Resolve compiler/runtime command with Windows fallbacks
    and Linux alias awareness (e.g. python3 instead of python).
    """
    direct = shutil.which(cmd_name)
    if direct:
        return direct

    # ── Linux / macOS fallbacks ──────────────────────────
    if os.name != "nt":
        linux_aliases = {
            "python": ["python3"],
            "node": ["nodejs"],
        }
        for alias in linux_aliases.get(cmd_name, []):
            found = shutil.which(alias)
            if found:
                return found
        return cmd_name

    # ── Windows-specific resolution below ────────────────

    exe_name = f"{cmd_name}.exe"

    # Environment-driven hints first.
    hinted_roots = []
    for env_key in ("JAVA_HOME", "WINLIBS_HOME", "MINGW_HOME", "GCC_HOME", "PYTHON_HOME", "NODE_HOME"):
        env_val = (os.environ.get(env_key) or "").strip().strip('"')
        if env_val:
            hinted_roots.append(env_val)

    for root in hinted_roots:
        # Accept root as either <tool_home> or <tool_home>/bin
        candidates = [
            os.path.join(root, exe_name),
            os.path.join(root, "bin", exe_name),
            os.path.join(root, "mingw64", "bin", exe_name),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate

    # Common install patterns for local Windows machines.
    patterns_by_cmd = {
        "javac": [
            r"C:\Program Files\Eclipse Adoptium\jdk*\bin\javac.exe",
            r"C:\Program Files\Java\jdk*\bin\javac.exe",
        ],
        "java": [
            r"C:\Program Files\Eclipse Adoptium\jdk*\bin\java.exe",
            r"C:\Program Files\Java\jdk*\bin\java.exe",
        ],
        "gcc": [
            r"D:\winlibs*\mingw64\bin\gcc.exe",
            r"D:\Downloads\winlibs*\mingw64\bin\gcc.exe",
            r"C:\winlibs*\mingw64\bin\gcc.exe",
        ],
        "g++": [
            r"D:\winlibs*\mingw64\bin\g++.exe",
            r"D:\Downloads\winlibs*\mingw64\bin\g++.exe",
            r"C:\winlibs*\mingw64\bin\g++.exe",
        ],
        "python": [
            r"C:\Users\*\AppData\Local\Programs\Python\Python*\python.exe",
            r"C:\Python*\python.exe",
        ],
        "node": [
            r"C:\Program Files\nodejs\node.exe",
        ],
        "py": [
            r"C:\Windows\py.exe",
        ],
        "dotnet": [
            r"C:\Program Files\dotnet\dotnet.exe",
        ],
        "csc": [
            r"C:\Program Files\dotnet\sdk\*\Roslyn\bincore\csc.exe",
            r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
            r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
        ],
        "mcs": [
            r"C:\Program Files\Mono\bin\mcs.exe",
            r"C:\Program Files\Mono\bin\mcs.bat",
        ],
        "mono": [
            r"C:\Program Files\Mono\bin\mono.exe",
        ],
    }
    for pattern in patterns_by_cmd.get(cmd_name, []):
        matches = sorted(glob.glob(pattern))
        for match in matches:
            if os.path.isfile(match):
                return match

    # Keep old behavior if still unresolved (caller already handles FileNotFoundError).
    return cmd_name


def _compiler_commands():
    python_cmd = _resolve_executable("python")
    # On Linux "python" may not exist; _resolve_executable already tries
    # python3.  But if it fell through, do a final explicit check here.
    if python_cmd == "python" and os.name != "nt":
        py3 = shutil.which("python3")
        if py3:
            python_cmd = py3
    elif python_cmd == "python":
        # Windows: try py launcher
        py_launcher = _resolve_executable("py")
        if py_launcher != "py" or shutil.which("py"):
            python_cmd = py_launcher

    return {
        "javac": _resolve_executable("javac"),
        "java": _resolve_executable("java"),
        "gcc": _resolve_executable("gcc"),
        "g++": _resolve_executable("g++"),
        "python": python_cmd,
        "node": _resolve_executable("node"),
        "dotnet": _resolve_executable("dotnet"),
        "csc": _resolve_executable("csc"),
        "mcs": _resolve_executable("mcs"),
        "mono": _resolve_executable("mono"),
    }


def _command_available(command):
    if not command:
        return False
    if os.path.isfile(command):
        return True
    return shutil.which(command) is not None


def _split_top_level_csv(raw_text):
    parts = []
    current = []
    angle_depth = 0
    paren_depth = 0
    for ch in raw_text:
        if ch == "<":
            angle_depth += 1
        elif ch == ">" and angle_depth > 0:
            angle_depth -= 1
        elif ch == "(":
            paren_depth += 1
        elif ch == ")" and paren_depth > 0:
            paren_depth -= 1

        if ch == "," and angle_depth == 0 and paren_depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue

        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_function_signature(signature):
    match = re.match(r"\s*(.+?)\s+([A-Za-z_]\w*)\s*\((.*)\)\s*$", signature or "")
    if not match:
        raise ValueError(f"Invalid function signature: {signature}")

    return_type = match.group(1).strip()
    function_name = match.group(2).strip()
    params_raw = match.group(3).strip()

    params = []
    if params_raw:
        for param_decl in _split_top_level_csv(params_raw):
            tokens = param_decl.strip().split()
            if len(tokens) < 2:
                raise ValueError(f"Invalid parameter declaration: {param_decl}")
            param_name = tokens[-1].strip()
            param_type = " ".join(tokens[:-1]).strip()
            params.append((param_type, param_name))

    return return_type, function_name, params


def _normalize_type_name(type_name):
    return re.sub(r"\s+", "", str(type_name or ""))


def _java_escape(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _cpp_escape(value):
    return _java_escape(value)


def _c_escape(value):
    return _java_escape(value)


def _csharp_escape(value):
    return _java_escape(value)


def _resolve_callable_name(func_info, default_name="solve"):
    if isinstance(func_info, dict):
        name = str(func_info.get("name") or "").strip()
        if name:
            return name
        signature = str(func_info.get("signature") or func_info.get("method") or "")
    else:
        signature = str(func_info or "")

    match = re.search(r"([A-Za-z_]\w*)\s*\(", signature)
    if match:
        return match.group(1).strip()

    return default_name


def _java_object_literal(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f"\"{_java_escape(value)}\""
    if isinstance(value, list):
        if all(isinstance(v, int) for v in value):
            return "new int[]{" + ", ".join(str(v) for v in value) + "}"
        return "new Object[]{" + ", ".join(_java_object_literal(v) for v in value) + "}"
    if value is None:
        return "null"
    return f"\"{_java_escape(value)}\""


def _java_literal_for_param(value, param_type):
    t = _normalize_type_name(param_type)

    if t in ("int", "Integer"):
        return str(int(value))
    if t in ("double", "Double", "float", "Float"):
        return str(float(value))
    if t in ("boolean", "Boolean"):
        return "true" if bool(value) else "false"
    if t == "String":
        return f"\"{_java_escape(value)}\""
    if t == "int[]":
        if not isinstance(value, list):
            raise ValueError(f"Expected list for type int[] but got: {type(value).__name__}")
        return "new int[]{" + ", ".join(str(int(v)) for v in value) + "}"
    if t == "String[]":
        if not isinstance(value, list):
            raise ValueError(f"Expected list for type String[] but got: {type(value).__name__}")
        return "new String[]{" + ", ".join(f"\"{_java_escape(v)}\"" for v in value) + "}"
    if t == "Object[]":
        if not isinstance(value, list):
            raise ValueError(f"Expected list for type Object[] but got: {type(value).__name__}")
        return "new Object[]{" + ", ".join(_java_object_literal(v) for v in value) + "}"
    if t.startswith("List<") and t.endswith(">"):
        if not isinstance(value, list):
            raise ValueError(f"Expected list for type {param_type} but got: {type(value).__name__}")
        inner = t[5:-1]
        if inner in ("Integer", "int"):
            converted = []
            for v in value:
                if v is None:
                    converted.append("null")
                else:
                    converted.append(str(int(v)))
            return "new ArrayList<>(Arrays.asList(" + ", ".join(converted) + "))"
        if inner == "String":
            return "new ArrayList<>(Arrays.asList(" + ", ".join(f"\"{_java_escape(v)}\"" for v in value) + "))"
        return "new ArrayList<>(Arrays.asList(" + ", ".join(_java_object_literal(v) for v in value) + "))"

    return f"\"{_java_escape(value)}\""


def _cpp_literal_for_param(value, param_type):
    t = _normalize_type_name(param_type).replace("std::", "")

    if t in ("int", "long", "longint", "longlong"):
        return str(int(value))
    if t in ("double", "float"):
        return str(float(value))
    if t == "bool":
        return "true" if bool(value) else "false"
    if t == "string":
        return f"\"{_cpp_escape(value)}\""
    if t == "vector<int>":
        if not isinstance(value, list):
            raise ValueError(f"Expected list for type vector<int> but got: {type(value).__name__}")
        return "vector<int>{" + ", ".join(str(int(v)) for v in value) + "}"
    if t == "vector<string>":
        if not isinstance(value, list):
            raise ValueError(f"Expected list for type vector<string> but got: {type(value).__name__}")
        return "vector<string>{" + ", ".join(f"\"{_cpp_escape(v)}\"" for v in value) + "}"

    return f"\"{_cpp_escape(value)}\""


def _csharp_object_literal(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f"\"{_csharp_escape(value)}\""
    if isinstance(value, list):
        return "new object[]{" + ", ".join(_csharp_object_literal(v) for v in value) + "}"
    if isinstance(value, dict):
        entries = []
        for k, v in value.items():
            key = f"\"{_csharp_escape(k)}\""
            entries.append("{" + key + ", " + _csharp_object_literal(v) + "}")
        return "new Dictionary<string, object>{" + ", ".join(entries) + "}"
    return f"\"{_csharp_escape(value)}\""


def _csharp_literal_for_param(value, param_type):
    t = _normalize_type_name(param_type)

    if t in ("int", "long", "short", "byte"):
        return str(int(value))
    if t in ("double", "float", "decimal"):
        return str(float(value))
    if t == "bool":
        return "true" if bool(value) else "false"
    if t == "string":
        return f"\"{_csharp_escape(value)}\""
    if t == "object":
        return _csharp_object_literal(value)
    if t == "int[]":
        if not isinstance(value, list):
            raise ValueError(f"Expected list for type int[] but got: {type(value).__name__}")
        return "new int[]{" + ", ".join(str(int(v)) for v in value) + "}"
    if t == "string[]":
        if not isinstance(value, list):
            raise ValueError(f"Expected list for type string[] but got: {type(value).__name__}")
        return "new string[]{" + ", ".join(f"\"{_csharp_escape(v)}\"" for v in value) + "}"
    if t == "object[]":
        if not isinstance(value, list):
            raise ValueError(f"Expected list for type object[] but got: {type(value).__name__}")
        return "new object[]{" + ", ".join(_csharp_object_literal(v) for v in value) + "}"
    if t.startswith("List<") and t.endswith(">"):
        if not isinstance(value, list):
            raise ValueError(f"Expected list for type {param_type} but got: {type(value).__name__}")
        inner = t[5:-1]
        if inner in ("int", "long", "short", "byte"):
            return f"new List<{inner}>{{" + ", ".join(str(int(v)) for v in value) + "}"
        if inner in ("double", "float", "decimal"):
            return f"new List<{inner}>{{" + ", ".join(str(float(v)) for v in value) + "}"
        if inner == "string":
            return "new List<string>{" + ", ".join(f"\"{_csharp_escape(v)}\"" for v in value) + "}"
        if inner == "object":
            return "new List<object>{" + ", ".join(_csharp_object_literal(v) for v in value) + "}"
        return f"new List<{inner}>{{" + ", ".join(_csharp_object_literal(v) for v in value) + "}"

    return _csharp_object_literal(value)


def _build_java_driver(code, func_info, test_inputs):
    method_sig = func_info.get("method", "") if isinstance(func_info, dict) else str(func_info)
    class_name = func_info.get("class", "Solution") if isinstance(func_info, dict) else "Solution"
    _, method_name, params = _parse_function_signature(method_sig)

    if len(params) != len(test_inputs):
        raise ValueError(
            f"Java test input mismatch for {method_name}: expected {len(params)} args, got {len(test_inputs)}"
        )

    args = [
        _java_literal_for_param(test_inputs[i], params[i][0])
        for i in range(len(params))
    ]

    return (
        "import java.util.*;\n"
        "import java.util.stream.*;\n\n"
        f"{code}\n\n"
        "class Main {\n"
        "    private static String __esc(String s) {\n"
        "        return s.replace(\"\\\\\", \"\\\\\\\\\")\n"
        "                .replace(\"\\\"\", \"\\\\\\\"\")\n"
        "                .replace(\"\\n\", \"\\\\n\")\n"
        "                .replace(\"\\r\", \"\\\\r\")\n"
        "                .replace(\"\\t\", \"\\\\t\");\n"
        "    }\n"
        "\n"
        "    private static String __toJson(Object obj) {\n"
        "        if (obj == null) return \"null\";\n"
        "        if (obj instanceof String) return \"\\\"\" + __esc((String) obj) + \"\\\"\";\n"
        "        if (obj instanceof Number || obj instanceof Boolean) return String.valueOf(obj);\n"
        "        if (obj instanceof int[]) {\n"
        "            int[] arr = (int[]) obj;\n"
        "            StringBuilder sb = new StringBuilder(\"[\");\n"
        "            for (int i = 0; i < arr.length; i++) {\n"
        "                if (i > 0) sb.append(',');\n"
        "                sb.append(arr[i]);\n"
        "            }\n"
        "            sb.append(']');\n"
        "            return sb.toString();\n"
        "        }\n"
        "        if (obj instanceof Object[]) {\n"
        "            Object[] arr = (Object[]) obj;\n"
        "            StringBuilder sb = new StringBuilder(\"[\");\n"
        "            for (int i = 0; i < arr.length; i++) {\n"
        "                if (i > 0) sb.append(',');\n"
        "                sb.append(__toJson(arr[i]));\n"
        "            }\n"
        "            sb.append(']');\n"
        "            return sb.toString();\n"
        "        }\n"
        "        if (obj instanceof Iterable<?>) {\n"
        "            StringBuilder sb = new StringBuilder(\"[\");\n"
        "            boolean first = true;\n"
        "            for (Object item : (Iterable<?>) obj) {\n"
        "                if (!first) sb.append(',');\n"
        "                first = false;\n"
        "                sb.append(__toJson(item));\n"
        "            }\n"
        "            sb.append(']');\n"
        "            return sb.toString();\n"
        "        }\n"
        "        if (obj instanceof Map<?, ?>) {\n"
        "            StringBuilder sb = new StringBuilder(\"{\");\n"
        "            boolean first = true;\n"
        "            for (Map.Entry<?, ?> entry : ((Map<?, ?>) obj).entrySet()) {\n"
        "                if (!first) sb.append(',');\n"
        "                first = false;\n"
        "                sb.append(\"\\\"\").append(__esc(String.valueOf(entry.getKey()))).append(\"\\\":\");\n"
        "                sb.append(__toJson(entry.getValue()));\n"
        "            }\n"
        "            sb.append('}');\n"
        "            return sb.toString();\n"
        "        }\n"
        "        return \"\\\"\" + __esc(String.valueOf(obj)) + \"\\\"\";\n"
        "    }\n"
        "\n"
        "    public static void main(String[] args) {\n"
        f"        Object result = {class_name}.{method_name}({', '.join(args)});\n"
        "        System.out.print(__toJson(result));\n"
        "    }\n"
        "}\n"
    )


def _build_cpp_driver(code, func_info, test_inputs):
    signature = func_info.get("signature", str(func_info)) if isinstance(func_info, dict) else str(func_info)
    _, func_name, params = _parse_function_signature(signature)

    if len(params) != len(test_inputs):
        raise ValueError(
            f"C++ test input mismatch for {func_name}: expected {len(params)} args, got {len(test_inputs)}"
        )

    args = [
        _cpp_literal_for_param(test_inputs[i], params[i][0])
        for i in range(len(params))
    ]

    return (
        "#include <iostream>\n"
        "#include <vector>\n"
        "#include <map>\n"
        "#include <string>\n"
        "#include <sstream>\n"
        "#include <iomanip>\n"
        "#include <type_traits>\n"
        "using namespace std;\n\n"
        f"{code}\n\n"
        "string __esc(const string& s) {\n"
        "    string out;\n"
        "    out.reserve(s.size());\n"
        "    for (char c : s) {\n"
        "        if (c == '\\\\' || c == '\"') { out.push_back('\\\\'); out.push_back(c); }\n"
        "        else if (c == '\\n') out += \"\\\\n\";\n"
        "        else if (c == '\\r') out += \"\\\\r\";\n"
        "        else if (c == '\\t') out += \"\\\\t\";\n"
        "        else out.push_back(c);\n"
        "    }\n"
        "    return out;\n"
        "}\n\n"
        "inline string __to_json(const string& v) { return string(\"\\\"\") + __esc(v) + \"\\\"\"; }\n"
        "inline string __to_json(const char* v) { return string(\"\\\"\") + __esc(string(v)) + \"\\\"\"; }\n"
        "inline string __to_json(bool v) { return v ? \"true\" : \"false\"; }\n\n"
        "template <typename T>\n"
        "typename enable_if<is_arithmetic<T>::value && !is_same<T, bool>::value, string>::type\n"
        "__to_json(T v) {\n"
        "    ostringstream oss;\n"
        "    oss << setprecision(15) << v;\n"
        "    return oss.str();\n"
        "}\n\n"
        "template <typename T>\n"
        "string __to_json(const vector<T>& vec) {\n"
        "    string out = \"[\";\n"
        "    for (size_t i = 0; i < vec.size(); ++i) {\n"
        "        if (i) out += \",\";\n"
        "        out += __to_json(vec[i]);\n"
        "    }\n"
        "    out += \"]\";\n"
        "    return out;\n"
        "}\n\n"
        "template <typename K, typename V>\n"
        "string __to_json(const map<K, V>& mp) {\n"
        "    string out = \"{\";\n"
        "    bool first = true;\n"
        "    for (const auto& kv : mp) {\n"
        "        if (!first) out += \",\";\n"
        "        first = false;\n"
        "        ostringstream key_ss;\n"
        "        key_ss << kv.first;\n"
        "        out += string(\"\\\"\") + __esc(key_ss.str()) + \"\\\":\" + __to_json(kv.second);\n"
        "    }\n"
        "    out += \"}\";\n"
        "    return out;\n"
        "}\n\n"
        "int main() {\n"
        f"    auto result = {func_name}({', '.join(args)});\n"
        "    cout << __to_json(result);\n"
        "    return 0;\n"
        "}\n"
    )


def _build_c_driver(code, func_info, test_inputs, expected_output):
    signature = func_info.get("signature", str(func_info)) if isinstance(func_info, dict) else str(func_info)
    return_type, func_name, params = _parse_function_signature(signature)

    decl_lines = []
    call_args = []
    input_idx = 0
    last_array_len = None
    output_int_meta = None
    output_str_var = None
    expected_list_len = len(expected_output) if isinstance(expected_output, list) else 0

    for i, (param_type, param_name) in enumerate(params):
        t = _normalize_type_name(param_type)
        pname = str(param_name or "").strip().lower()

        if t == "int*" and pname == "result":
            out_len = max(expected_list_len, 1)
            var_name = f"__out_{i}"
            decl_lines.append(f"    int {var_name}[{out_len}] = {{0}};")
            call_args.append(var_name)
            output_int_meta = (var_name, out_len)
            continue

        if t == "char*" and pname == "result":
            out_len = max((len(str(expected_output)) if isinstance(expected_output, str) else 0) + 64, 256)
            var_name = f"__out_{i}"
            decl_lines.append(f"    char {var_name}[{out_len}] = {{0}};")
            call_args.append(var_name)
            output_str_var = var_name
            continue

        if t == "int*":
            value = test_inputs[input_idx]
            input_idx += 1
            if not isinstance(value, list):
                raise ValueError(f"Expected list for C pointer arg '{param_name}', got {type(value).__name__}")
            arr_values = ", ".join(str(int(v)) for v in value)
            var_name = f"__arg_{i}"
            decl_lines.append(f"    int {var_name}[] = {{{arr_values}}};")
            call_args.append(var_name)
            last_array_len = len(value)
            continue

        if t == "char*":
            value = test_inputs[input_idx]
            input_idx += 1
            var_name = f"__arg_{i}"
            decl_lines.append(f"    char {var_name}[] = \"{_c_escape(value)}\";")
            call_args.append(var_name)
            continue

        if t == "int" and pname == "size" and last_array_len is not None:
            var_name = f"__arg_{i}"
            decl_lines.append(f"    int {var_name} = {last_array_len};")
            call_args.append(var_name)
            continue

        if t == "int":
            value = test_inputs[input_idx]
            input_idx += 1
            var_name = f"__arg_{i}"
            decl_lines.append(f"    int {var_name} = {int(value)};")
            call_args.append(var_name)
            continue

        if t in ("double", "float"):
            value = test_inputs[input_idx]
            input_idx += 1
            var_name = f"__arg_{i}"
            decl_lines.append(f"    double {var_name} = {float(value)};")
            call_args.append(var_name)
            continue

        raise ValueError(f"Unsupported C parameter type '{param_type}' in signature '{signature}'")

    if input_idx != len(test_inputs):
        raise ValueError(
            f"C test input mismatch for {func_name}: consumed {input_idx} args, got {len(test_inputs)}"
        )

    call_expr = f"{func_name}({', '.join(call_args)})"

    output_lines = []
    ret_type_norm = _normalize_type_name(return_type)
    if ret_type_norm == "void":
        output_lines.append(f"    {call_expr};")
        if output_int_meta:
            output_lines.append(f"    __print_json_int_array({output_int_meta[0]}, {output_int_meta[1]});")
        elif output_str_var:
            output_lines.append(f"    __print_json_string({output_str_var});")
        else:
            output_lines.append("    printf(\"null\");")
    elif ret_type_norm == "int":
        output_lines.append(f"    int __ret = {call_expr};")
        if output_int_meta and isinstance(expected_output, list):
            output_lines.append("    int __n = __ret;")
            output_lines.append("    if (__n < 0) __n = 0;")
            output_lines.append(f"    if (__n > {output_int_meta[1]}) __n = {output_int_meta[1]};")
            output_lines.append(f"    __print_json_int_array({output_int_meta[0]}, __n);")
        else:
            output_lines.append("    printf(\"%d\", __ret);")
    elif ret_type_norm in ("double", "float"):
        output_lines.append(f"    double __ret = {call_expr};")
        output_lines.append("    printf(\"%.12g\", __ret);")
    else:
        raise ValueError(f"Unsupported C return type '{return_type}'")

    return (
        "#include <stdio.h>\n"
        "#include <string.h>\n\n"
        f"{code}\n\n"
        "void __print_json_int_array(const int* arr, int n) {\n"
        "    printf(\"[\");\n"
        "    for (int i = 0; i < n; i++) {\n"
        "        if (i > 0) printf(\",\");\n"
        "        printf(\"%d\", arr[i]);\n"
        "    }\n"
        "    printf(\"]\");\n"
        "}\n\n"
        "void __print_json_string(const char* s) {\n"
        "    printf(\"\\\"\");\n"
        "    for (const unsigned char* p = (const unsigned char*)s; *p; ++p) {\n"
        "        if (*p == '\\\\' || *p == '\"') {\n"
        "            printf(\"\\\\%c\", *p);\n"
        "        } else if (*p == '\\n') {\n"
        "            printf(\"\\\\n\");\n"
        "        } else if (*p == '\\r') {\n"
        "            printf(\"\\\\r\");\n"
        "        } else if (*p == '\\t') {\n"
        "            printf(\"\\\\t\");\n"
        "        } else {\n"
        "            printf(\"%c\", *p);\n"
        "        }\n"
        "    }\n"
        "    printf(\"\\\"\");\n"
        "}\n\n"
        "int main() {\n"
        + "\n".join(decl_lines) + "\n"
        + "\n".join(output_lines) + "\n"
        "    return 0;\n"
        "}\n"
    )


def _build_python_driver(code, func_info, test_inputs):
    func_name = _resolve_callable_name(func_info, "solve")
    args_json = json.dumps(test_inputs or [], ensure_ascii=False)

    return (
        f"{code}\n\n"
        "import json\n\n"
        "if __name__ == '__main__':\n"
        f"    __args = json.loads({args_json!r})\n"
        f"    __result = {func_name}(*__args)\n"
        "    print(json.dumps(__result, ensure_ascii=False))\n"
    )


def _build_javascript_driver(code, func_info, test_inputs):
    func_name = _resolve_callable_name(func_info, "solve")
    args_json = json.dumps(test_inputs or [], ensure_ascii=False)
    args_literal = json.dumps(args_json, ensure_ascii=False)

    return (
        f"{code}\n\n"
        "(async () => {\n"
        f"  const __args = JSON.parse({args_literal});\n"
        f"  const __result = await Promise.resolve({func_name}(...__args));\n"
        "  const __json = JSON.stringify(__result === undefined ? null : __result);\n"
        "  process.stdout.write(__json);\n"
        "})().catch((err) => {\n"
        "  console.error(err && err.stack ? err.stack : String(err));\n"
        "  process.exit(1);\n"
        "});\n"
    )


def _build_csharp_driver(code, func_info, test_inputs):
    signature = ""
    class_name = "Solution"
    if isinstance(func_info, dict):
        signature = str(func_info.get("signature") or func_info.get("method") or "")
        class_name = str(func_info.get("class") or "Solution")
    else:
        signature = str(func_info or "")

    if not signature:
        signature = "public static int solve(int n)"

    _, method_name, params = _parse_function_signature(signature)

    if len(params) != len(test_inputs):
        raise ValueError(
            f"C# test input mismatch for {method_name}: expected {len(params)} args, got {len(test_inputs)}"
        )

    args = [
        _csharp_literal_for_param(test_inputs[i], params[i][0])
        for i in range(len(params))
    ]

    return (
        "using System;\n"
        "using System.Collections;\n"
        "using System.Collections.Generic;\n"
        "using System.Globalization;\n"
        "using System.Linq;\n"
        "using System.Text;\n"
        "using System.Text.RegularExpressions;\n\n"
        f"{code}\n\n"
        "public class Program {\n"
        "    static string __esc(string s) {\n"
        "        if (s == null) return \"\";\n"
        "        return s.Replace(\"\\\\\", \"\\\\\\\\\")\n"
        "                .Replace(\"\\\"\", \"\\\\\\\"\")\n"
        "                .Replace(\"\\n\", \"\\\\n\")\n"
        "                .Replace(\"\\r\", \"\\\\r\")\n"
        "                .Replace(\"\\t\", \"\\\\t\");\n"
        "    }\n\n"
        "    static string __toJson(object obj) {\n"
        "        if (obj == null) return \"null\";\n"
        "        if (obj is string) return \"\\\"\" + __esc((string)obj) + \"\\\"\";\n"
        "        if (obj is bool) return ((bool)obj) ? \"true\" : \"false\";\n"
        "        if (obj is char) return \"\\\"\" + __esc(((char)obj).ToString()) + \"\\\"\";\n"
        "        if (obj is byte || obj is sbyte || obj is short || obj is ushort || obj is int || obj is uint || obj is long || obj is ulong || obj is float || obj is double || obj is decimal)\n"
        "            return Convert.ToString(obj, CultureInfo.InvariantCulture);\n"
        "        if (obj is IDictionary) {\n"
        "            IDictionary dict = (IDictionary)obj;\n"
        "            var parts = new List<string>();\n"
        "            foreach (DictionaryEntry entry in dict) {\n"
        "                parts.Add(\"\\\"\" + __esc(Convert.ToString(entry.Key, CultureInfo.InvariantCulture)) + \"\\\":\" + __toJson(entry.Value));\n"
        "            }\n"
        "            return \"{\" + string.Join(\",\", parts) + \"}\";\n"
        "        }\n"
        "        if (obj is IEnumerable && !(obj is string)) {\n"
        "            IEnumerable en = (IEnumerable)obj;\n"
        "            var parts = new List<string>();\n"
        "            foreach (var item in en) {\n"
        "                parts.Add(__toJson(item));\n"
        "            }\n"
        "            return \"[\" + string.Join(\",\", parts) + \"]\";\n"
        "        }\n"
        "        return \"\\\"\" + __esc(Convert.ToString(obj, CultureInfo.InvariantCulture)) + \"\\\"\";\n"
        "    }\n\n"
        "    public static void Main(string[] args) {\n"
        f"        object result = {class_name}.{method_name}({', '.join(args)});\n"
        "        Console.Write(__toJson(result));\n"
        "    }\n"
        "}\n"
    )


def _build_csharp_batch_driver(code, func_info, test_inputs_list):
    signature = ""
    class_name = "Solution"
    if isinstance(func_info, dict):
        signature = str(func_info.get("signature") or func_info.get("method") or "")
        class_name = str(func_info.get("class") or "Solution")
    else:
        signature = str(func_info or "")

    if not signature:
        signature = "public static int solve(int n)"

    _, method_name, params = _parse_function_signature(signature)

    test_blocks = []
    for inputs in test_inputs_list:
        if len(params) != len(inputs):
            raise ValueError(
                f"C# test input mismatch for {method_name}: expected {len(params)} args, got {len(inputs)}"
            )
        args = [
            _csharp_literal_for_param(inputs[i], params[i][0])
            for i in range(len(params))
        ]
        test_blocks.append(
            "        try {\n"
            f"            object result = {class_name}.{method_name}({', '.join(args)});\n"
            "            __results.Add(__wrapOk(result));\n"
            "        } catch (Exception ex) {\n"
            "            __results.Add(__wrapErr(ex));\n"
            "        }\n"
        )

    test_section = "".join(test_blocks) if test_blocks else "        __results.Add(__wrapOk(null));\n"

    return (
        "using System;\n"
        "using System.Collections;\n"
        "using System.Collections.Generic;\n"
        "using System.Globalization;\n"
        "using System.Linq;\n"
        "using System.Text;\n"
        "using System.Text.RegularExpressions;\n\n"
        f"{code}\n\n"
        "public class Program {\n"
        "    static string __esc(string s) {\n"
        "        if (s == null) return \"\";\n"
        "        return s.Replace(\"\\\\\", \"\\\\\\\\\")\n"
        "                .Replace(\"\\\"\", \"\\\\\\\"\")\n"
        "                .Replace(\"\\n\", \"\\\\n\")\n"
        "                .Replace(\"\\r\", \"\\\\r\")\n"
        "                .Replace(\"\\t\", \"\\\\t\");\n"
        "    }\n\n"
        "    static string __toJson(object obj) {\n"
        "        if (obj == null) return \"null\";\n"
        "        if (obj is string) return \"\\\"\" + __esc((string)obj) + \"\\\"\";\n"
        "        if (obj is bool) return ((bool)obj) ? \"true\" : \"false\";\n"
        "        if (obj is char) return \"\\\"\" + __esc(((char)obj).ToString()) + \"\\\"\";\n"
        "        if (obj is byte || obj is sbyte || obj is short || obj is ushort || obj is int || obj is uint || obj is long || obj is ulong || obj is float || obj is double || obj is decimal)\n"
        "            return Convert.ToString(obj, CultureInfo.InvariantCulture);\n"
        "        if (obj is IDictionary) {\n"
        "            IDictionary dict = (IDictionary)obj;\n"
        "            var parts = new List<string>();\n"
        "            foreach (DictionaryEntry entry in dict) {\n"
        "                parts.Add(\"\\\"\" + __esc(Convert.ToString(entry.Key, CultureInfo.InvariantCulture)) + \"\\\":\" + __toJson(entry.Value));\n"
        "            }\n"
        "            return \"{\" + string.Join(\",\", parts) + \"}\";\n"
        "        }\n"
        "        if (obj is IEnumerable && !(obj is string)) {\n"
        "            IEnumerable en = (IEnumerable)obj;\n"
        "            var parts = new List<string>();\n"
        "            foreach (var item in en) {\n"
        "                parts.Add(__toJson(item));\n"
        "            }\n"
        "            return \"[\" + string.Join(\",\", parts) + \"]\";\n"
        "        }\n"
        "        return \"\\\"\" + __esc(Convert.ToString(obj, CultureInfo.InvariantCulture)) + \"\\\"\";\n"
        "    }\n\n"
        "    static string __wrapOk(object obj) {\n"
        "        return \"{\\\"ok\\\":true,\\\"output\\\":\" + __toJson(obj) + \"}\";\n"
        "    }\n\n"
        "    static string __wrapErr(Exception ex) {\n"
        "        string msg = \"Error\";\n"
        "        if (ex != null) {\n"
        "            msg = ex.GetType().Name;\n"
        "            if (!string.IsNullOrWhiteSpace(ex.Message)) {\n"
        "                msg += \": \" + ex.Message;\n"
        "            }\n"
        "        }\n"
        "        return \"{\\\"ok\\\":false,\\\"error\\\":\\\"\" + __esc(msg) + \"\\\"}\";\n"
        "    }\n\n"
        "    public static void Main(string[] args) {\n"
        "        var __results = new List<string>();\n"
        f"{test_section}"
        "        Console.Write(\"[\" + string.Join(\",\", __results) + \"]\");\n"
        "    }\n"
        "}\n"
    )


def _build_driver_code(language, code, question, test_inputs, expected_output=None):
    """Build a strict typed driver around candidate code for one test case."""
    normalized_language = str(language or "").lower()
    if normalized_language == "js":
        normalized_language = "javascript"
    if normalized_language in ("c#", "cs"):
        normalized_language = "csharp"

    func_map = question.get("function", {}) or {}
    func_info = func_map.get(normalized_language, {})
    if not func_info and normalized_language == "csharp":
        # C# sessions may reuse Java coding bank and carry converted signatures.
        func_info = func_map.get("java", {})
    if normalized_language == "java":
        return _build_java_driver(code, func_info, test_inputs or [])
    if normalized_language == "cpp":
        return _build_cpp_driver(code, func_info, test_inputs or [])
    if normalized_language == "c":
        return _build_c_driver(code, func_info, test_inputs or [], expected_output)
    if normalized_language == "python":
        return _build_python_driver(code, func_info, test_inputs or [])
    if normalized_language == "javascript":
        return _build_javascript_driver(code, func_info, test_inputs or [])
    if normalized_language == "csharp":
        return _build_csharp_driver(code, func_info, test_inputs or [])
    return code


def _compile_and_run(language, code, stdin_input, work_dir):
    """Compile (if needed) and run the code, returning (success, stdout, stderr, exec_time_ms)."""
    start_t = _time.time()
    compilers = _compiler_commands()
    language = str(language or "").lower()
    if language == "js":
        language = "javascript"
    if language in ("c#", "cs"):
        language = "csharp"

    if language == "java":
        src_file = os.path.join(work_dir, "Main.java")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write(code)

        # Compile
        comp = subprocess.run(
            [compilers["javac"], src_file],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT, cwd=work_dir
        )
        if comp.returncode != 0:
            return False, "", f"Compilation Error:\n{comp.stderr}", 0

        # Run
        run = subprocess.run(
            [compilers["java"], "-cp", work_dir, "Main"],
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
            [compilers["gcc"], src_file, "-o", exe_file, "-lm"],
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
            [compilers["g++"], src_file, "-o", exe_file, "-std=c++17"],
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

    elif language == "python":
        src_file = os.path.join(work_dir, "solution.py")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write(code)

        run = subprocess.run(
            [compilers["python"], src_file],
            input=stdin_input, capture_output=True, text=True,
            timeout=RUN_TIMEOUT, cwd=work_dir
        )
        elapsed = int((_time.time() - start_t) * 1000)
        if run.returncode != 0:
            return False, run.stdout, f"Runtime Error:\n{run.stderr}", elapsed
        return True, run.stdout, run.stderr, elapsed

    elif language == "javascript":
        src_file = os.path.join(work_dir, "solution.js")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write(code)

        run = subprocess.run(
            [compilers["node"], src_file],
            input=stdin_input, capture_output=True, text=True,
            timeout=RUN_TIMEOUT, cwd=work_dir
        )
        elapsed = int((_time.time() - start_t) * 1000)
        if run.returncode != 0:
            return False, run.stdout, f"Runtime Error:\n{run.stderr}", elapsed
        return True, run.stdout, run.stderr, elapsed

    elif language == "csharp":
        src_file = os.path.join(work_dir, "Program.cs")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write(code)

        # ── Fast path: Mono mcs + mono runtime (preferred on Linux VMs) ──
        # Try mcs first — it compiles in < 2s and avoids dotnet's slow NuGet restore.
        if _command_available(compilers.get("mcs")):
            exe_file = os.path.join(work_dir, "solution.exe")
            comp = subprocess.run(
                [compilers["mcs"], "-out:" + exe_file,
                 "-r:System.Core",
                 "-r:System.Numerics",
                 src_file],
                capture_output=True, text=True, timeout=COMPILE_TIMEOUT, cwd=work_dir
            )
            if comp.returncode != 0:
                return False, "", f"Compilation Error:\n{comp.stderr or comp.stdout}", 0

            run_cmd = [exe_file]
            if os.name != "nt" and _command_available(compilers.get("mono")):
                run_cmd = [compilers["mono"], exe_file]
            elif os.name != "nt":
                # mono runtime missing — cannot execute .exe on Linux
                return False, "", "Runtime Error:\nmono runtime is not installed. Cannot execute compiled C# on Linux.\nPlease ask admin to install mono-runtime.", 0

            run = subprocess.run(
                run_cmd,
                input=stdin_input, capture_output=True, text=True,
                timeout=RUN_TIMEOUT, cwd=work_dir
            )
            elapsed = int((_time.time() - start_t) * 1000)
            if run.returncode != 0:
                return False, run.stdout, f"Runtime Error:\n{run.stderr}", elapsed
            return True, run.stdout, run.stderr, elapsed

        # ── Fallback: dotnet SDK build (slower, needs NuGet) ──
        dotnet_build_error = ""
        if _command_available(compilers.get("dotnet")):
            # Keep dotnet CLI state inside execution workspace to avoid profile permission issues.
            dotnet_env = os.environ.copy()
            dotnet_cli_home = os.path.join(work_dir, ".dotnet_cli_home")
            nuget_packages = os.path.join(work_dir, ".nuget", "packages")
            os.makedirs(dotnet_cli_home, exist_ok=True)
            os.makedirs(nuget_packages, exist_ok=True)
            dotnet_env["DOTNET_CLI_HOME"] = dotnet_cli_home
            dotnet_env.setdefault("DOTNET_SKIP_FIRST_TIME_EXPERIENCE", "1")
            dotnet_env.setdefault("DOTNET_CLI_TELEMETRY_OPTOUT", "1")
            dotnet_env.setdefault("DOTNET_NOLOGO", "1")
            dotnet_env.setdefault("NUGET_PACKAGES", nuget_packages)

            project_file = os.path.join(work_dir, "AziroSolution.csproj")
            frameworks = ["net8.0", "net6.0"]
            compile_error = "dotnet build failed for all supported target frameworks."
            for framework in frameworks:
                with open(project_file, "w", encoding="utf-8") as f:
                    f.write(
                        "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
                        "  <PropertyGroup>\n"
                        "    <OutputType>Exe</OutputType>\n"
                        f"    <TargetFramework>{framework}</TargetFramework>\n"
                        "    <ImplicitUsings>disable</ImplicitUsings>\n"
                        "    <Nullable>disable</Nullable>\n"
                        "  </PropertyGroup>\n"                        "</Project>\n"
                    )

                build_cmd = [compilers["dotnet"], "build", project_file, "-nologo", "-v", "q", "-c", "Release"]
                comp = subprocess.run(
                    build_cmd,
                    capture_output=True, text=True, timeout=60, cwd=work_dir, env=dotnet_env
                )
                if comp.returncode != 0:
                    compile_error = comp.stderr or comp.stdout
                    continue

                dll_path = os.path.join(work_dir, "bin", "Release", framework, "AziroSolution.dll")
                if not os.path.exists(dll_path):
                    compile_error = "Unable to locate built C# assembly."
                    continue

                run = subprocess.run(
                    [compilers["dotnet"], dll_path],
                    input=stdin_input, capture_output=True, text=True,
                    timeout=RUN_TIMEOUT, cwd=work_dir, env=dotnet_env
                )
                elapsed = int((_time.time() - start_t) * 1000)
                if run.returncode != 0:
                    return False, run.stdout, f"Runtime Error:\n{run.stderr}", elapsed
                return True, run.stdout, run.stderr, elapsed

            dotnet_build_error = compile_error

        # ── Last fallback: Roslyn csc (primarily Windows) ──
        if _command_available(compilers.get("csc")):
            exe_file = os.path.join(work_dir, "solution.exe")
            comp = subprocess.run(
                [compilers["csc"], "/nologo", "/t:exe", f"/out:{exe_file}", src_file],
                capture_output=True, text=True, timeout=COMPILE_TIMEOUT, cwd=work_dir
            )
            if comp.returncode != 0:
                return False, "", f"Compilation Error:\n{comp.stderr or comp.stdout}", 0

            run_cmd = [exe_file]
            if os.name != "nt" and _command_available(compilers.get("mono")):
                run_cmd = [compilers["mono"], exe_file]

            run = subprocess.run(
                run_cmd,
                input=stdin_input, capture_output=True, text=True,
                timeout=RUN_TIMEOUT, cwd=work_dir
            )
            elapsed = int((_time.time() - start_t) * 1000)
            if run.returncode != 0:
                return False, run.stdout, f"Runtime Error:\n{run.stderr}", elapsed
            return True, run.stdout, run.stderr, elapsed

        if dotnet_build_error:
            return (
                False,
                "",
                "Compilation Error:\n"
                + str(dotnet_build_error)
                + "\n\nDotnet build failed and fallback C# compilers were unavailable.",
                0,
            )

        raise FileNotFoundError("No C# compiler/runtime found (mcs, dotnet, csc).")

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
    """Normalize output for comparison - strip, collapse whitespace."""
    return str(s).strip().replace("\r\n", "\n").strip()


def _parse_candidate_output(raw_output):
    text = _normalize_output(raw_output)
    if not text:
        return ""

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except ValueError:
            return text

    if re.fullmatch(r"-?\d+\.\d+(e[+-]?\d+)?", lowered):
        try:
            return float(text)
        except ValueError:
            return text

    return text


def _parse_csharp_batch_output(raw_output):
    text = _normalize_output(raw_output)
    if not text:
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, list):
        return None

    return data


def _is_dynamic_syntax_error(language, stderr_text):
    lang = str(language or "").lower()
    if lang == "js":
        lang = "javascript"

    text = str(stderr_text or "")
    if not text:
        return False

    if lang == "python":
        return any(marker in text for marker in ("SyntaxError", "IndentationError", "TabError"))

    if lang == "javascript":
        return "SyntaxError" in text

    return False


def _outputs_match(expected, actual, float_tol=1e-6):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        expected_keys = {str(k) for k in expected.keys()}
        actual_keys = {str(k) for k in actual.keys()}
        if expected_keys != actual_keys:
            return False
        for key in expected.keys():
            actual_value = actual.get(str(key), actual.get(key))
            if not _outputs_match(expected[key], actual_value, float_tol):
                return False
        return True

    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        return all(_outputs_match(e, a, float_tol) for e, a in zip(expected, actual))

    if isinstance(expected, bool):
        if isinstance(actual, bool):
            return expected == actual
        if isinstance(actual, (int, float)):
            return int(actual) == int(expected)
        return False

    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= float_tol

    return str(expected) == str(actual)


def _display_value(value):
    if isinstance(value, (dict, list, bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _parse_custom_input(raw_input):
    raw = str(raw_input or "").strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    except json.JSONDecodeError:
        pass

    items = []
    for line in [ln.strip() for ln in raw.splitlines() if ln.strip()]:
        if re.fullmatch(r"-?\d+", line):
            items.append(int(line))
        elif re.fullmatch(r"-?\d+\.\d+(e[+-]?\d+)?", line.lower()):
            items.append(float(line))
        elif line.lower() in ("true", "false"):
            items.append(line.lower() == "true")
        else:
            items.append(line)
    return items


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
    run_hidden = bool(payload.get("run_hidden", False))

    # Save the code
    CodingSessionService.save_code(session_id, code)

    language = CodingSessionService.get_language(session_id)
    normalized_language = str(language or "").lower()
    if normalized_language == "js":
        normalized_language = "javascript"
    if normalized_language in ("c#", "cs"):
        normalized_language = "csharp"
    question = CodingSessionService.get_question(session_id)
    public_tests = CodingSessionService.get_public_tests(session_id)
    hidden_tests = CodingSessionService.get_hidden_tests(session_id)
    selected_tests = hidden_tests if run_hidden else public_tests

    if not code.strip():
        return jsonify({
            "status": "error",
            "output": "Error: No code to execute. Please write your solution first.",
            "test_results": [],
        })

    if not selected_tests:
        suite = "hidden" if run_hidden else "public"
        return jsonify({
            "status": "error",
            "output": f"No {suite} test cases configured for this question.",
            "test_results": [],
        })

    work_dir = None
    try:
        work_dir = _create_execution_work_dir()

        # If custom input is provided, run once with a typed wrapper.
        if custom_input.strip():
            try:
                custom_values = _parse_custom_input(custom_input)
                driver_code = _build_driver_code(
                    language,
                    code,
                    question,
                    custom_values,
                    None,
                )
                success, stdout, stderr, elapsed = _compile_and_run(
                    language, driver_code, "", work_dir
                )
                output_text = ""
                if stderr:
                    output_text += stderr + "\n"
                parsed_output = _parse_candidate_output(stdout)
                if parsed_output != "":
                    output_text += _display_value(parsed_output)
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
                lang_key = str(language or "").lower()
                lang_label = {
                    "java": "Java",
                    "c": "C",
                    "cpp": "C++",
                    "python": "Python",
                    "javascript": "JavaScript",
                    "js": "JavaScript",
                    "csharp": "C#",
                    "c#": "C#",
                }.get(lang_key, str(language).upper())
                compiler_info = {
                    "java": "JDK (javac + java)",
                    "c": "GCC (gcc)",
                    "cpp": "G++ (g++)",
                    "python": "Python 3 runtime (python/py)",
                    "javascript": "Node.js runtime (node)",
                    "js": "Node.js runtime (node)",
                    "csharp": "dotnet SDK 10.x (LTS, preferred) or dotnet SDK 8.x (LTS)",
                    "c#": "dotnet SDK 10.x (LTS, preferred) or dotnet SDK 8.x (LTS)",
                }
                return jsonify({
                    "status": "error",
                    "output": f"Warning: {lang_label} compiler not found on this machine.\n\n"
                              f"Required: {compiler_info.get(lang_key, lang_label + ' compiler')}\n"
                              f"Your code has been saved and will be evaluated after submission.",
                    "test_results": [],
                })
            except ValueError as ex:
                return jsonify({
                    "status": "error",
                    "output": f"Invalid custom input for this coding question.\n{ex}",
                    "test_results": [],
                })

        # C# optimization: compile once and run all tests in a single batch.
        if normalized_language == "csharp":
            func_map = question.get("function", {}) or {}
            func_info = func_map.get("csharp", {})
            if not func_info:
                func_info = func_map.get("java", {})

            test_inputs_list = [(tc.get("input", []) or []) for tc in selected_tests]
            try:
                driver_code = _build_csharp_batch_driver(code, func_info, test_inputs_list)
            except ValueError as ex:
                return jsonify({
                    "status": "error",
                    "output": f"Invalid question signature/input mapping.\n{ex}",
                    "test_results": [],
                })

            success, stdout, stderr, elapsed = _compile_and_run(
                language, driver_code, "", work_dir
            )

            if not success and "Compilation Error" in (stderr or ""):
                return jsonify({
                    "status": "error",
                    "output": stderr,
                    "test_results": [],
                })

            batch_results = _parse_csharp_batch_output(stdout) if success else None
            if batch_results is None:
                batch_results = []

            batch_error = ""
            if not success:
                batch_error = (stderr or "").strip() or "Runtime Error"

            test_results = []
            total_passed = 0
            total_time = elapsed

            for i, tc in enumerate(selected_tests):
                tc_input_values = tc.get("input", []) or []
                tc_expected_obj = tc.get("expected")
                result = batch_results[i] if i < len(batch_results) else None

                ok = isinstance(result, dict) and result.get("ok") is True
                if ok:
                    actual_obj = result.get("output")
                    passed = _outputs_match(tc_expected_obj, actual_obj)
                    if passed:
                        total_passed += 1
                    error_text = ""
                else:
                    passed = False
                    error_text = ""
                    if isinstance(result, dict):
                        error_text = str(result.get("error") or "").strip()
                    if not error_text:
                        error_text = batch_error or "Runtime Error"
                    actual_obj = "Runtime Error"

                test_results.append({
                    "index": i + 1,
                    "passed": passed,
                    "input": tc_input_values,
                    "expected": _display_value(tc_expected_obj),
                    "actual": _display_value(tc_expected_obj if passed else actual_obj),
                    "error": error_text if (not passed and error_text) else "",
                    "time_ms": None,
                })

            total = len(test_results)
            suite_label = "Hidden Test Results" if run_hidden else "Test Results"
            summary = f"{suite_label}: {total_passed}/{total} passed"
            if total_time:
                summary += f"  |  Total time: {total_time}ms"

            output_lines = [summary, "-" * 40]
            for tr in test_results:
                status = "PASSED" if tr["passed"] else "FAILED"
                output_lines.append(f"\nTest Case {tr['index']}: {status}")
                output_lines.append(f"  Input:    {tr['input']}")
                output_lines.append(f"  Expected: {tr['expected']}")
                if not tr["passed"]:
                    output_lines.append(f"  Actual:   {tr['actual']}")
                    if tr["error"]:
                        output_lines.append(f"  Error:    {tr['error']}")

            coding_data = CodingSessionService.get_session_data(session_id)
            if coding_data is not None:
                coding_data["latest_run_summary"] = {
                    "passed": total_passed,
                    "total": total,
                    "run_hidden": run_hidden,
                    "time_ms": total_time,
                    "status": "PASS" if total and total_passed == total else "FAIL",
                }

            return jsonify({
                "status": "executed" if total_passed == total else "partial",
                "output": "\n".join(output_lines),
                "execution_time": f"{total_time}ms",
                "test_results": test_results,
                "passed": total_passed,
                "total": total,
                "run_hidden": run_hidden,
            })

        # Run against selected test suite
        test_results = []
        total_passed = 0
        total_time = 0
        compilation_error = None

        for i, tc in enumerate(selected_tests):
            tc_input_values = tc.get("input", []) or []
            tc_expected_obj = tc.get("expected")

            try:
                driver_code = _build_driver_code(
                    language,
                    code,
                    question,
                    tc_input_values,
                    tc_expected_obj,
                )
                success, stdout, stderr, elapsed = _compile_and_run(
                    language, driver_code, "", work_dir
                )
                total_time += elapsed

                if not success:
                    # Static languages: stop at compilation errors.
                    if "Compilation Error" in stderr:
                        compilation_error = stderr
                        break

                    # Dynamic languages: treat syntax errors like compile-time errors.
                    if _is_dynamic_syntax_error(normalized_language, stderr):
                        compilation_error = stderr or "Syntax Error: Code execution failed."
                        break

                actual_obj = _parse_candidate_output(stdout)
                passed = success and _outputs_match(tc_expected_obj, actual_obj)
                if passed:
                    total_passed += 1

                test_results.append({
                    "index": i + 1,
                    "passed": passed,
                    "input": tc_input_values,
                    "expected": _display_value(tc_expected_obj),
                    "actual": _display_value(tc_expected_obj if passed else actual_obj),
                    "error": stderr if (not success and "Runtime Error" in stderr) else "",
                    "time_ms": elapsed,
                })

            except subprocess.TimeoutExpired:
                test_results.append({
                    "index": i + 1,
                    "passed": False,
                    "input": tc_input_values,
                    "expected": _display_value(tc_expected_obj),
                    "actual": "TLE",
                    "error": "Time Limit Exceeded",
                    "time_ms": RUN_TIMEOUT * 1000,
                })
            except FileNotFoundError:
                lang_key = str(language or "").lower()
                lang_label = {
                    "java": "Java",
                    "c": "C",
                    "cpp": "C++",
                    "python": "Python",
                    "javascript": "JavaScript",
                    "js": "JavaScript",
                    "csharp": "C#",
                    "c#": "C#",
                }.get(lang_key, str(language).upper())
                compiler_info = {
                    "java": "JDK (javac + java)",
                    "c": "GCC (gcc)",
                    "cpp": "G++ (g++)",
                    "python": "Python 3 runtime (python/py)",
                    "javascript": "Node.js runtime (node)",
                    "js": "Node.js runtime (node)",
                    "csharp": "dotnet SDK 10.x (LTS, preferred) or dotnet SDK 8.x (LTS)",
                    "c#": "dotnet SDK 10.x (LTS, preferred) or dotnet SDK 8.x (LTS)",
                }
                return jsonify({
                    "status": "error",
                    "output": f"Warning: {lang_label} compiler not found on this machine.\n\n"
                              f"Required: {compiler_info.get(lang_key, lang_label + ' compiler')}\n"
                              f"Your code has been saved and will be evaluated after submission.",
                    "test_results": [],
                })
            except ValueError as ex:
                return jsonify({
                    "status": "error",
                    "output": f"Invalid question signature/input mapping.\n{ex}",
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
        suite_label = "Hidden Test Results" if run_hidden else "Test Results"
        summary = f"{suite_label}: {total_passed}/{total} passed"
        if total_time:
            summary += f"  |  Total time: {total_time}ms"

        output_lines = [summary, "-" * 40]
        for tr in test_results:
            status = "PASSED" if tr["passed"] else "FAILED"
            output_lines.append(f"\nTest Case {tr['index']}: {status}")
            output_lines.append(f"  Input:    {tr['input']}")
            output_lines.append(f"  Expected: {tr['expected']}")
            if not tr["passed"]:
                output_lines.append(f"  Actual:   {tr['actual']}")
                if tr["error"]:
                    output_lines.append(f"  Error:    {tr['error']}")
            if tr.get("time_ms"):
                output_lines.append(f"  Time:     {tr['time_ms']}ms")

        coding_data = CodingSessionService.get_session_data(session_id)
        if coding_data is not None:
            coding_data["latest_run_summary"] = {
                "passed": total_passed,
                "total": total,
                "run_hidden": run_hidden,
                "time_ms": total_time,
                "status": "PASS" if total and total_passed == total else "FAIL",
            }

        return jsonify({
            "status": "executed" if total_passed == total else "partial",
            "output": "\n".join(output_lines),
            "execution_time": f"{total_time}ms",
            "test_results": test_results,
            "passed": total_passed,
            "total": total,
            "run_hidden": run_hidden,
        })
    except PermissionError:
        return jsonify({
            "status": "error",
            "output": (
                "Error: Code execution environment is not writable on this machine.\n"
                "Please contact admin to verify runtime folder permissions."
            ),
            "test_results": [],
        }), 500
    except OSError as ex:
        return jsonify({
            "status": "error",
            "output": f"Error: Could not execute code due to system I/O issue.\n{ex}",
            "test_results": [],
        }), 500
    except Exception as ex:
        return jsonify({
            "status": "error",
            "output": f"Error: Could not execute code due to server issue.\n{ex}",
            "test_results": [],
        }), 500

    finally:
        # Clean up temp directory
        if work_dir:
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass


# -------------------------------------------------
# SUBMIT CONFIRMATION
# -------------------------------------------------
def _evaluate_and_store_coding_result(session_id, session_meta=None, coding_data=None):
    session_meta = session_meta or CODING_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        return

    if coding_data is None:
        coding_data = CodingSessionService.get_session_data(session_id) or {}
    question = coding_data.get("question") or {}

    round_key = session_meta.get("round_key", "L4")
    round_label = session_meta.get("round_label", "Coding Round")
    pass_threshold = EvaluationService.get_pass_threshold(round_key)

    code = str(coding_data.get("code") or "")
    starter_code = str(coding_data.get("starter_code") or "")
    language = str(coding_data.get("language") or session_meta.get("language") or "java").lower()
    if language in ("c#", "cs"):
        language = "csharp"
    attempted = 1 if code.strip() and code.strip() != starter_code.strip() else 0

    hidden_tests = question.get("hidden_tests") or []
    public_tests = question.get("public_tests") or []

    latest_run_summary = coding_data.get("latest_run_summary") or {}
    if attempted and isinstance(latest_run_summary, dict):
        try:
            latest_total = int(latest_run_summary.get("total", 0) or 0)
            latest_passed = int(latest_run_summary.get("passed", 0) or 0)
            latest_run_hidden = bool(latest_run_summary.get("run_hidden", False))
        except (TypeError, ValueError):
            latest_total = 0
            latest_passed = 0
            latest_run_hidden = False

        # If hidden tests exist, use cached run summary only when it came from hidden suite.
        if latest_total > 0 and (latest_run_hidden or not hidden_tests):
            percentage = round((latest_passed / latest_total) * 100, 2)
            status = "PASS" if percentage >= pass_threshold else "FAIL"
            start_time = int(coding_data.get("start_time", 0) or 0)
            time_taken = max(0, int(_time.time()) - start_time) if start_time else 0

            result_data = {
                "candidate_name": session_meta.get("candidate_name", ""),
                "email": session_meta.get("email", ""),
                "round_key": round_key,
                "round_label": round_label,
                "total_questions": latest_total,
                "attempted": attempted,
                "correct": latest_passed,
                "percentage": percentage,
                "pass_threshold": pass_threshold,
                "status": status,
                "time_taken_seconds": time_taken,                "submission_details": {
                    "question_title": question.get("title", ""),
                    "question_text": question.get("description") or question.get("problem_statement") or "",
                    "language": language,
                    "submitted_code": code if attempted else "",
                },
            }
            EVALUATION_STORE[session_id] = result_data
            EvaluationService._persist_result_to_db(session_meta, result_data)
            if attempted:
                save_coding_submission(
                    session_id=session_id,
                    email=session_meta.get("email", ""),
                    round_key=round_key,
                    round_label=round_label,
                    role=session_meta.get("role_label", ""),
                    language=language,
                    question_title=question.get("title", ""),
                    question_text=question.get("description") or question.get("problem_statement") or "",
                    submitted_code=code,
                    starter_code=starter_code,
                    role_key=session_meta.get("role_key", ""),
                    batch_id=session_meta.get("batch_id", ""),
                )
            return

    test_suite = hidden_tests or public_tests

    total_questions = len(test_suite) if test_suite else 1
    correct = 0
    work_dir = None

    if attempted and test_suite:
        try:
            work_dir = _create_execution_work_dir()
            if language == "csharp":
                func_map = question.get("function", {}) or {}
                func_info = func_map.get("csharp", {}) or func_map.get("java", {})
                test_inputs_list = [(tc.get("input", []) or []) for tc in test_suite]
                driver_code = _build_csharp_batch_driver(code, func_info, test_inputs_list)
                success, stdout, stderr, _ = _compile_and_run(
                    language, driver_code, "", work_dir
                )
                if success:
                    batch_results = _parse_csharp_batch_output(stdout) or []
                    for idx, tc in enumerate(test_suite):
                        if idx >= len(batch_results):
                            continue
                        result = batch_results[idx]
                        if not isinstance(result, dict) or not result.get("ok"):
                            continue
                        actual_obj = result.get("output")
                        if _outputs_match(tc.get("expected"), actual_obj):
                            correct += 1
            else:
                for tc in test_suite:
                    tc_input_values = tc.get("input", []) or []
                    tc_expected_obj = tc.get("expected")

                    driver_code = _build_driver_code(
                        language,
                        code,
                        question,
                        tc_input_values,
                        tc_expected_obj,
                    )

                    success, stdout, stderr, elapsed = _compile_and_run(
                        language, driver_code, "", work_dir
                    )
                    if not success:
                        continue

                    actual_obj = _parse_candidate_output(stdout)
                    if _outputs_match(tc_expected_obj, actual_obj):
                        correct += 1
        except Exception:
            # Keep evaluation non-blocking for candidate submit flow.
            correct = 0
        finally:
            if work_dir:
                try:
                    shutil.rmtree(work_dir, ignore_errors=True)
                except Exception:
                    pass
    elif attempted and not test_suite:
        # If no test suite is configured, do not block evaluation visibility.
        correct = 1
        total_questions = 1

    percentage = round((correct / total_questions) * 100, 2) if total_questions else 0
    status = "PASS" if attempted and percentage >= pass_threshold else "FAIL"

    start_time = int(coding_data.get("start_time", 0) or 0)
    time_taken = max(0, int(_time.time()) - start_time) if start_time else 0

    result_data = {
        "candidate_name": session_meta.get("candidate_name", ""),
        "email": session_meta.get("email", ""),
        "round_key": round_key,
        "round_label": round_label,
        "total_questions": total_questions,
        "attempted": attempted,
        "correct": correct,
        "percentage": percentage,
        "pass_threshold": pass_threshold,
        "status": status,
        "time_taken_seconds": time_taken,
        "submission_details": {
            "question_title": question.get("title", ""),
            "question_text": question.get("description") or question.get("problem_statement") or "",
            "language": language,
            "submitted_code": code if attempted else "",
        },
    }

    EVALUATION_STORE[session_id] = result_data
    EvaluationService._persist_result_to_db(session_meta, result_data)
    if attempted:
        save_coding_submission(
            session_id=session_id,
            email=session_meta.get("email", ""),
            round_key=round_key,
            round_label=round_label,
            role=session_meta.get("role_label", ""),
            language=language,
            question_title=question.get("title", ""),
            question_text=question.get("description") or question.get("problem_statement") or "",
            submitted_code=code,
            starter_code=starter_code,
            role_key=session_meta.get("role_key", ""),
            batch_id=session_meta.get("batch_id", ""),
        )


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

        coding_snapshot = None
        try:
            coding_snapshot = CodingSessionService.get_session_data(session_id) or {}
            coding_snapshot = copy.deepcopy(coding_snapshot)
        except Exception:
            coding_snapshot = CodingSessionService.get_session_data(session_id) or {}

        session_meta_snapshot = {}
        try:
            session_meta_snapshot = copy.deepcopy(session_meta)
        except Exception:
            session_meta_snapshot = session_meta or {}

        app = current_app._get_current_object()

        def _run_async_eval():
            try:
                with app.app_context():
                    _evaluate_and_store_coding_result(
                        session_id,
                        session_meta=session_meta_snapshot,
                        coding_data=coding_snapshot,
                    )
            except Exception:
                # Submission must never be blocked by evaluation bookkeeping.
                pass

        Thread(target=_run_async_eval, daemon=True).start()

        # Free runtime/cookie space immediately after submission
        CodingSessionService.clear_session(session_id)

        # Invalidate link immediately after successful submission.
        db_service.expire_test_link_now(session_id)
        CODING_SESSION_REGISTRY.pop(session_id, None)

        completed_url = url_for("coding.completed", session_id=session_id)
        if _is_ajax_request():
            return jsonify({"redirect_url": completed_url})

        return redirect(completed_url)

    return render_template(
        "coding/submit.html",
        session_id=session_id,
        candidate_name=session_meta.get("candidate_name", "Candidate"),
        proctoring_enabled=_proctoring_enabled(),
        body_class="coding-start-page",
    )


# -------------------------------------------------
# COMPLETION PAGE
# -------------------------------------------------
@coding_bp.route("/completed/<session_id>")
def completed(session_id):
    candidate_name = CODING_SESSION_REGISTRY.get(session_id, {}).get("candidate_name", "")
    if not candidate_name:
        persisted_meta = db_service.get_test_link_meta(session_id) or {}
        candidate_name = persisted_meta.get("candidate_name", "")

    return render_template(
        "coding/completed.html",
        candidate_name=candidate_name or "Candidate",
        proctoring_enabled=_proctoring_enabled(),
        body_class="coding-start-page",
    )

# -------------------------------------------------
# PROCTORING ENDPOINTS (mirrors MCQ proctoring)
# -------------------------------------------------
@coding_bp.route("/proctoring/violation", methods=["POST"])
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


@coding_bp.route("/proctoring/screenshot", methods=["POST"])
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
    image_bytes = b""
    mime_type = "image/png"

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

    # Persist screenshot in DB for reports gallery (best-effort).
    if image_bytes and not details.get("screenshot_rejected"):
        try:
            session_meta = CODING_SESSION_REGISTRY.get(session_id, {})
            captured_at = _parse_iso_ts(ts)
            db_service.save_proctoring_screenshot(
                session_uuid=session_id,
                candidate_email=session_meta.get("email", ""),
                candidate_name=session_meta.get("candidate_name", ""),
                round_key=session_meta.get("round_key", ""),
                round_label=session_meta.get("round_label", ""),
                source="coding",
                event_type=event_type,
                mime_type=mime_type,
                image_bytes=image_bytes,
                image_size=len(image_bytes),
                captured_at=captured_at,
                screenshot_path=screenshot_path,
            )
        except Exception:
            pass

    return jsonify({
        "status": "logged",
        "event_id": event["event_id"],
        "screenshot_path": screenshot_path,
    })


@coding_bp.route("/proctoring/webcam", methods=["POST"])
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

