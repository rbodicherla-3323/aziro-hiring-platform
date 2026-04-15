import time
import random
import yaml
import os
import re
import copy
from flask import session

from app.services.coding_runtime_store import (
    clear_coding_session_data,
    coding_session_key,
    get_coding_session_data,
    set_coding_session_data,
)


QUESTION_COUNT = 1
DEFAULT_DURATION_MINUTES = 30


_JAVA_MODIFIERS = {
    "public", "private", "protected", "internal",
    "static", "final", "abstract", "synchronized",
    "virtual", "override", "async",
}


def _split_top_level_csv(raw_text):
    parts = []
    current = []
    angle_depth = 0
    paren_depth = 0
    for ch in str(raw_text or ""):
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


def _strip_leading_modifiers(text):
    tokens = str(text or "").strip().split()
    while tokens and tokens[0] in _JAVA_MODIFIERS:
        tokens.pop(0)
    return " ".join(tokens).strip()


def _java_type_to_csharp(type_name):
    raw = _strip_leading_modifiers(type_name).replace("...", "[]")
    raw = re.sub(r"\s+", "", raw)
    if not raw:
        return "object"

    array_suffix = ""
    while raw.endswith("[]"):
        array_suffix += "[]"
        raw = raw[:-2]

    if "<" in raw and raw.endswith(">"):
        base = raw[:raw.index("<")]
        inner = raw[raw.index("<") + 1:-1]
        args = _split_top_level_csv(inner)
        converted_args = [_java_type_to_csharp(arg) for arg in args]
        base_map = {
            "Map": "Dictionary",
            "HashMap": "Dictionary",
            "LinkedHashMap": "Dictionary",
            "TreeMap": "SortedDictionary",
            "List": "List",
            "ArrayList": "List",
            "LinkedList": "List",
            "Set": "HashSet",
            "HashSet": "HashSet",
            "Queue": "Queue",
            "Deque": "Queue",
        }
        mapped_base = base_map.get(base, base)
        return f"{mapped_base}<{', '.join(converted_args)}>{array_suffix}"

    scalar_map = {
        "Integer": "int",
        "Long": "long",
        "Double": "double",
        "Float": "float",
        "Boolean": "bool",
        "Byte": "byte",
        "Short": "short",
        "String": "string",
        "Object": "object",
        "Character": "char",
    }
    return f"{scalar_map.get(raw, raw)}{array_suffix}"


def _convert_java_method_to_csharp(method_sig):
    fallback = {
        "signature": "public static int solve(int n)",
        "name": "solve",
        "class": "Solution",
    }
    sig = str(method_sig or "").strip()
    match = re.match(r"\s*(.+?)\s+([A-Za-z_]\w*)\s*\((.*)\)\s*$", sig)
    if not match:
        return fallback

    return_type = _java_type_to_csharp(match.group(1))
    method_name = match.group(2).strip() or "solve"
    params_raw = match.group(3).strip()

    converted_params = []
    if params_raw:
        for idx, decl in enumerate(_split_top_level_csv(params_raw), start=1):
            cleaned = _strip_leading_modifiers(decl)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if not cleaned:
                continue
            if " " in cleaned:
                ptype, pname = cleaned.rsplit(" ", 1)
            else:
                ptype, pname = "object", f"arg{idx}"
            pname = re.sub(r"[^\w]", "", pname) or f"arg{idx}"
            converted_params.append(f"{_java_type_to_csharp(ptype)} {pname}")

    signature = f"public static {return_type} {method_name}({', '.join(converted_params)})"
    return {
        "signature": signature,
        "name": method_name,
        "class": "Solution",
    }


def _ensure_csharp_function(question):
    function_block = question.get("function")
    if not isinstance(function_block, dict):
        function_block = {}
        question["function"] = function_block

    existing = function_block.get("csharp")
    if isinstance(existing, dict) and existing.get("signature"):
        return

    java_info = function_block.get("java")
    if isinstance(java_info, dict):
        converted = _convert_java_method_to_csharp(java_info.get("method"))
        converted["class"] = str(java_info.get("class") or converted.get("class") or "Solution")
    else:
        converted = _convert_java_method_to_csharp(java_info)

    function_block["csharp"] = converted


class CodingSessionService:
    """
    Handles L4 coding session lifecycle:
    - loads YAML coding questions per role
    - randomly selects 1 question per candidate
    - stores code submissions
    - enforces timer
    """

    @staticmethod
    def _load_yaml_questions(language, role_key=None):
        """Load coding questions from YAML file for the given language or role."""
        normalized_language = str(language or "").lower()
        if normalized_language in ("c#", "cs"):
            normalized_language = "csharp"

        base = os.path.join("app", "services", "question_bank", "data", "l4_coding")
        lang_map = {
            "c": "c",
            "cpp": "cpp",
            "java": "java",
            "python": "python",
            "javascript": "javascript",
            "js": "javascript",
            # Reuse Java coding bank and convert signatures for C# runtime.
            "csharp": "java",
        }
        role_dir = str(role_key or "").strip().lower()
        role_path = os.path.join(base, role_dir, "questions.yaml") if role_dir else ""

        lang_dir = lang_map.get(normalized_language)
        file_path = ""
        if role_dir and role_path and os.path.exists(role_path):
            file_path = role_path
        elif lang_dir:
            file_path = os.path.join(base, lang_dir, "questions.yaml")
        else:
            return []

        if not os.path.exists(file_path):
            return []

        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if isinstance(data, list):
            questions = data
        elif isinstance(data, dict) and "questions" in data:
            questions = data["questions"]
        else:
            return []

        if normalized_language == "csharp":
            converted_questions = []
            for item in questions:
                q = copy.deepcopy(item)
                _ensure_csharp_function(q)
                converted_questions.append(q)
            return converted_questions

        return questions

    @staticmethod
    def init_session(session_id, role_key, round_key, language="java", domain=None):
        """Initialize a coding session: load 1 random question for the candidate."""
        session_key = coding_session_key(session_id)
        normalized_language = str(language or "java").lower()
        if normalized_language in ("c#", "cs"):
            normalized_language = "csharp"

        existing = get_coding_session_data(session_id)
        if existing:
            session[session_key] = {"runtime_store": True}
            session.modified = True
            return

        legacy = session.get(session_key)
        if isinstance(legacy, dict) and "question" in legacy and "language" in legacy:
            legacy["start_time"] = int(legacy.get("start_time", 0) or time.time())
            set_coding_session_data(session_id, legacy)
            session[session_key] = {"runtime_store": True}
            session.modified = True
            return

        questions = CodingSessionService._load_yaml_questions(normalized_language, role_key=role_key)
        if not questions:
            raise ValueError(
                f"No coding questions found for language={normalized_language}"
            )

        selected = random.sample(questions, min(QUESTION_COUNT, len(questions)))

        # Prepare the question with language-specific function template
        question = selected[0]
        func_info = question.get("function", {}).get(normalized_language, {})
        if not func_info and normalized_language == "csharp":
            func_info = question.get("function", {}).get("java", {})

        # Build the starter code template
        starter_code = CodingSessionService._build_starter_code(
            normalized_language, func_info, question
        )

        data = {
            "question": question,
            "language": normalized_language,
            "starter_code": starter_code,
            "code": starter_code,
            "submitted": False,
            "start_time": int(time.time()),
            "duration_seconds": DEFAULT_DURATION_MINUTES * 60,
        }
        set_coding_session_data(session_id, data)
        session[session_key] = {"runtime_store": True}
        session.modified = True

    @staticmethod
    def _build_starter_code(language, func_info, question):
        """Generate the starter code template for the given language."""
        lang = str(language or "").lower()
        if lang in ("c#", "cs"):
            lang = "csharp"

        def extract_return_type(signature, default_type="int"):
            m = re.match(r"\s*(.+?)\s+[A-Za-z_]\w*\s*\(.*\)\s*$", str(signature or ""))
            if not m:
                return default_type
            ret = m.group(1).strip()
            while True:
                updated = re.sub(
                    r"^(public|private|protected|internal|static|final|virtual|override|async)\s+",
                    "",
                    ret,
                )
                if updated == ret:
                    break
                ret = updated
            return ret.strip() or default_type

        def java_default_return(ret_type):
            t = re.sub(r"\s+", "", str(ret_type or ""))
            if t in ("void",):
                return ""
            if t in ("int", "Integer", "short", "Short", "long", "Long", "byte", "Byte"):
                return "        return 0;"
            if t in ("double", "Double", "float", "Float"):
                return "        return 0.0;"
            if t in ("boolean", "Boolean"):
                return "        return false;"
            if t == "String":
                return "        return \"\";"
            if t.endswith("[]"):
                return f"        return new {t[:-2]}[0];"
            if t.startswith("List<"):
                return "        return new ArrayList<>();"
            if t.startswith("Map<"):
                return "        return new HashMap<>();"
            return "        return null;"

        def cpp_default_return(ret_type):
            t = re.sub(r"\s+", "", str(ret_type or "")).replace("std::", "")
            if t == "void":
                return ""
            if t in ("int", "short", "long", "longlong"):
                return "    return 0;"
            if t in ("double", "float"):
                return "    return 0.0;"
            if t == "bool":
                return "    return false;"
            if t == "string":
                return "    return \"\";"
            if t.startswith("vector<") or t.startswith("map<"):
                return "    return {};"
            return "    return {};"

        def c_default_return(ret_type):
            t = re.sub(r"\s+", "", str(ret_type or ""))
            if t == "void":
                return ""
            if t in ("int", "short", "long"):
                return "    return 0;"
            if t in ("double", "float"):
                return "    return 0.0;"
            return "    return 0;"

        def csharp_default_return(ret_type):
            t = re.sub(r"\s+", "", str(ret_type or ""))
            if t == "void":
                return ""
            if t in ("int", "short", "long", "byte", "decimal"):
                return "        return 0;"
            if t in ("double", "float"):
                return "        return 0.0;"
            if t == "bool":
                return "        return false;"
            if t == "string":
                return "        return string.Empty;"
            if t.endswith("[]"):
                return f"        return Array.Empty<{t[:-2]}>();"
            if t.startswith("List<") or t.startswith("Dictionary<") or t.startswith("HashSet<"):
                return f"        return new {t}();"
            return "        return null;"

        def extract_name_and_params(signature, default_name="solve"):
            raw = str(signature or "").strip()
            m = re.search(r"([A-Za-z_]\w*)\s*\((.*)\)", raw)
            if not m:
                return default_name, []

            name = m.group(1).strip()
            params_raw = m.group(2).strip()
            if not params_raw:
                return name, []

            param_names = []
            for decl in params_raw.split(","):
                part = decl.strip()
                if not part:
                    continue
                part = part.split("=")[0].strip()
                token = re.search(r"([A-Za-z_]\w*)\s*(?:\[\s*\])?\s*$", part)
                if token:
                    param_names.append(token.group(1))
                else:
                    param_names.append(f"arg{len(param_names) + 1}")
            return name, param_names

        def extract_return_type(signature, default_type="int"):
            m = re.match(r"\s*(.+?)\s+[A-Za-z_]\w*\s*\(.*\)\s*$", str(signature or ""))
            if not m:
                return default_type
            ret = m.group(1).strip()
            # Java signatures may include modifiers in the return-type capture.
            ret = re.sub(r"^(public|private|protected)\s+", "", ret)
            ret = re.sub(r"^static\s+", "", ret)
            ret = re.sub(r"^final\s+", "", ret)
            return ret.strip() or default_type

        def java_default_return(ret_type):
            t = re.sub(r"\s+", "", str(ret_type or ""))
            if t in ("void",):
                return ""
            if t in ("int", "Integer", "short", "Short", "long", "Long", "byte", "Byte"):
                return "        return 0;"
            if t in ("double", "Double", "float", "Float"):
                return "        return 0.0;"
            if t in ("boolean", "Boolean"):
                return "        return false;"
            if t == "String":
                return "        return \"\";"
            if t.endswith("[]"):
                return f"        return new {t[:-2]}[0];"
            if t.startswith("List<"):
                return "        return new ArrayList<>();"
            if t.startswith("Map<"):
                return "        return new HashMap<>();"
            return "        return null;"

        def cpp_default_return(ret_type):
            t = re.sub(r"\s+", "", str(ret_type or "")).replace("std::", "")
            if t == "void":
                return ""
            if t in ("int", "short", "long", "longlong"):
                return "    return 0;"
            if t in ("double", "float"):
                return "    return 0.0;"
            if t == "bool":
                return "    return false;"
            if t == "string":
                return "    return \"\";"
            if t.startswith("vector<") or t.startswith("map<"):
                return "    return {};"
            return "    return {};"

        def c_default_return(ret_type):
            t = re.sub(r"\s+", "", str(ret_type or ""))
            if t == "void":
                return ""
            if t in ("int", "short", "long"):
                return "    return 0;"
            if t in ("double", "float"):
                return "    return 0.0;"
            return "    return 0;"

        if lang == "java":
            java_info = func_info if isinstance(func_info, dict) else {}
            class_name = java_info.get("class", "Solution")
            method_sig = java_info.get("method", str(func_info) if isinstance(func_info, str) else "public static int solve(int n)")
            ret_type = extract_return_type(method_sig, "int")
            ret_stmt = java_default_return(ret_type)
            ret_block = f"{ret_stmt}\n" if ret_stmt else ""
            return (
                "import java.util.*;\n\n"
                f"class {class_name} {{\n"
                f"    {method_sig} {{\n"
                f"        // TODO: Implement this method according to the problem statement.\n"
                f"        // Keep the method signature unchanged.\n"
                f"{ret_block}"
                f"    }}\n"
                f"}}\n"
            )

        elif lang == "cpp":
            cpp_info = func_info if isinstance(func_info, dict) else {}
            includes = cpp_info.get("includes", [])
            signature = cpp_info.get("signature", str(func_info) if isinstance(func_info, str) else "int solve(int n)")
            ret_type = extract_return_type(signature, "int")
            ret_stmt = cpp_default_return(ret_type)
            ret_block = f"{ret_stmt}\n" if ret_stmt else ""
            include_lines = "\n".join(f"#include <{inc}>" for inc in includes)
            if include_lines:
                include_lines += "\nusing namespace std;\n\n"
            else:
                include_lines = "#include <iostream>\nusing namespace std;\n\n"
            return (
                f"{include_lines}"
                f"{signature} {{\n"
                f"    // TODO: Implement this function according to the problem statement.\n"
                f"    // Keep the function signature unchanged.\n"
                f"{ret_block}"
                f"}}\n"
            )

        elif lang == "c":
            c_info = func_info if isinstance(func_info, dict) else {}
            includes = c_info.get("includes", [])
            signature = c_info.get("signature", str(func_info) if isinstance(func_info, str) else "int solve(int n)")
            ret_type = extract_return_type(signature, "int")
            ret_stmt = c_default_return(ret_type)
            ret_block = f"{ret_stmt}\n" if ret_stmt else ""
            include_lines = "\n".join(f"#include <{inc}>" for inc in includes)
            if not include_lines:
                include_lines = "#include <stdio.h>"
            return (
                f"{include_lines}\n\n"
                f"{signature} {{\n"
                f"    // TODO: Implement this function according to the problem statement.\n"
                f"    // Keep the function signature unchanged.\n"
                f"{ret_block}"
                f"}}\n"
            )

        elif lang == "python":
            py_info = func_info if isinstance(func_info, dict) else {}
            signature = py_info.get(
                "signature",
                str(func_info) if isinstance(func_info, str) else "def solve(arg1):",
            )
            fn_name, params = extract_name_and_params(signature, "solve")
            if not str(signature).strip().startswith("def "):
                signature = f"def {fn_name}({', '.join(params)}):"
            if not str(signature).rstrip().endswith(":"):
                signature = str(signature).rstrip() + ":"

            return (
                f"{signature}\n"
                f"    # TODO: Implement this function according to the problem statement.\n"
                f"    # Keep the function name and parameters unchanged.\n"
                f"    return None\n"
            )

        elif lang in ("javascript", "js"):
            js_info = func_info if isinstance(func_info, dict) else {}
            signature = js_info.get(
                "signature",
                str(func_info) if isinstance(func_info, str) else "function solve(arg1)",
            )
            fn_name, params = extract_name_and_params(signature, "solve")
            if "function" not in str(signature):
                signature = f"function {fn_name}({', '.join(params)})"

            return (
                f"{str(signature).rstrip()} {{\n"
                f"    // TODO: Implement this function according to the problem statement.\n"
                f"    // Keep the function name and parameters unchanged.\n"
                f"    return null;\n"
                f"}}\n"
            )

        elif lang == "csharp":
            cs_info = func_info if isinstance(func_info, dict) else {}
            signature = cs_info.get(
                "signature",
                str(func_info) if isinstance(func_info, str) else "public static int solve(int n)",
            )
            class_name = cs_info.get("class", "Solution")
            ret_type = extract_return_type(signature, "int")
            ret_stmt = csharp_default_return(ret_type)
            ret_block = f"{ret_stmt}\n" if ret_stmt else ""

            return (
                "using System;\n"
                "using System.Collections.Generic;\n"
                "using System.Linq;\n"
                "using System.Text;\n"
                "using System.Text.RegularExpressions;\n\n"
                f"public class {class_name} {{\n"
                f"    {signature} {{\n"
                f"        // TODO: Implement this method according to the problem statement.\n"
                f"        // Keep the method signature unchanged.\n"
                f"{ret_block}"
                f"    }}\n"
                f"}}\n"
            )

        return "// Unsupported language\n"

    @staticmethod
    def get_question(session_id):
        """Return the coding question for this session."""
        data = CodingSessionService.get_session_data(session_id)
        if not data:
            return None
        return data["question"]

    @staticmethod
    def get_language(session_id):
        """Return the programming language for this session."""
        data = CodingSessionService.get_session_data(session_id)
        if not data:
            return None
        return data["language"]

    @staticmethod
    def get_starter_code(session_id):
        """Return the starter code template."""
        data = CodingSessionService.get_session_data(session_id)
        if not data:
            return ""
        return data["starter_code"]

    @staticmethod
    def get_code(session_id):
        """Return the currently saved code."""
        data = CodingSessionService.get_session_data(session_id)
        if not data:
            return ""
        return data["code"]

    @staticmethod
    def save_code(session_id, code):
        """Save candidate's code."""
        data = CodingSessionService.get_session_data(session_id)
        if not data:
            return
        data["code"] = code
        set_coding_session_data(session_id, data)

    @staticmethod
    def mark_submitted(session_id):
        """Mark the session as submitted."""
        data = CodingSessionService.get_session_data(session_id)
        if not data:
            return
        data["submitted"] = True
        set_coding_session_data(session_id, data)

    @staticmethod
    def save_latest_run_summary(session_id, summary):
        """Persist the latest run summary for cross-worker production flows."""
        data = CodingSessionService.get_session_data(session_id)
        if not data:
            return
        data["latest_run_summary"] = dict(summary or {})
        set_coding_session_data(session_id, data)

    @staticmethod
    def is_submitted(session_id):
        """Check if the session has been submitted."""
        data = CodingSessionService.get_session_data(session_id)
        if not data:
            return False
        return data.get("submitted", False)

    @staticmethod
    def remaining_time(session_id):
        """Return remaining seconds for the coding test."""
        data = CodingSessionService.get_session_data(session_id)
        if not data:
            return 0
        start_time = int(data.get("start_time", 0) or 0)
        if not start_time:
            return data["duration_seconds"]
        elapsed = int(time.time()) - start_time
        return max(0, data["duration_seconds"] - elapsed)

    @staticmethod
    def get_public_tests(session_id):
        """Return the public test cases for the question."""
        data = CodingSessionService.get_session_data(session_id)
        if not data:
            return []
        return data["question"].get("public_tests", [])

    @staticmethod
    def get_hidden_tests(session_id):
        """Return the hidden test cases for the question."""
        data = CodingSessionService.get_session_data(session_id)
        if not data:
            return []
        return data["question"].get("hidden_tests", [])

    @staticmethod
    def get_session_data(session_id):
        """Return the full session data dict."""
        data = get_coding_session_data(session_id)
        if data:
            return data

        session_key = coding_session_key(session_id)
        legacy = session.get(session_key)
        if isinstance(legacy, dict) and "question" in legacy and "language" in legacy:
            set_coding_session_data(session_id, legacy)
            session[session_key] = {"runtime_store": True}
            session.modified = True
            return legacy
        return None

    @staticmethod
    def clear_session(session_id):
        session_key = coding_session_key(session_id)
        clear_coding_session_data(session_id)
        session.pop(session_key, None)
        session.modified = True
