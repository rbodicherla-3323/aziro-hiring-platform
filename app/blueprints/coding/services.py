import time
import random
import yaml
import os
import re
from flask import session


QUESTION_COUNT = 1
DEFAULT_DURATION_MINUTES = 20


class CodingSessionService:
    """
    Handles L4 coding session lifecycle:
    - loads YAML coding questions per role
    - randomly selects 1 question per candidate
    - stores code submissions
    - enforces timer
    """

    @staticmethod
    def _load_yaml_questions(language):
        """Load coding questions from YAML file for the given language."""
        base = os.path.join("app", "services", "question_bank", "data", "l4_coding")
        lang_map = {
            "c": "c",
            "cpp": "cpp",
            "java": "java",
        }
        lang_dir = lang_map.get(language.lower())
        if not lang_dir:
            return []

        file_path = os.path.join(base, lang_dir, "questions.yaml")
        if not os.path.exists(file_path):
            return []

        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "questions" in data:
            return data["questions"]
        return []

    @staticmethod
    def init_session(session_id, role_key, round_key, language="java", domain=None):
        """Initialize a coding session: load 1 random question for the candidate."""
        session_key = f"coding_{session_id}"

        if session_key in session:
            return

        questions = CodingSessionService._load_yaml_questions(language)
        if not questions:
            raise ValueError(
                f"No coding questions found for language={language}"
            )

        selected = random.sample(questions, min(QUESTION_COUNT, len(questions)))

        # Prepare the question with language-specific function template
        question = selected[0]
        func_info = question.get("function", {}).get(language.lower(), {})

        # Build the starter code template
        starter_code = CodingSessionService._build_starter_code(
            language, func_info, question
        )

        session[session_key] = {
            "question": question,
            "language": language.lower(),
            "starter_code": starter_code,
            "code": starter_code,
            "submitted": False,
            "start_time": int(time.time()),
            "duration_seconds": DEFAULT_DURATION_MINUTES * 60,
        }

    @staticmethod
    def _build_starter_code(language, func_info, question):
        """Generate the starter code template for the given language."""
        lang = language.lower()

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

        return "// Unsupported language\n"

    @staticmethod
    def get_question(session_id):
        """Return the coding question for this session."""
        data = session.get(f"coding_{session_id}")
        if not data:
            return None
        return data["question"]

    @staticmethod
    def get_language(session_id):
        """Return the programming language for this session."""
        data = session.get(f"coding_{session_id}")
        if not data:
            return None
        return data["language"]

    @staticmethod
    def get_starter_code(session_id):
        """Return the starter code template."""
        data = session.get(f"coding_{session_id}")
        if not data:
            return ""
        return data["starter_code"]

    @staticmethod
    def get_code(session_id):
        """Return the currently saved code."""
        data = session.get(f"coding_{session_id}")
        if not data:
            return ""
        return data["code"]

    @staticmethod
    def save_code(session_id, code):
        """Save candidate's code."""
        data = session.get(f"coding_{session_id}")
        if not data:
            return
        data["code"] = code
        session.modified = True

    @staticmethod
    def mark_submitted(session_id):
        """Mark the session as submitted."""
        data = session.get(f"coding_{session_id}")
        if not data:
            return
        data["submitted"] = True
        session.modified = True

    @staticmethod
    def is_submitted(session_id):
        """Check if the session has been submitted."""
        data = session.get(f"coding_{session_id}")
        if not data:
            return False
        return data.get("submitted", False)

    @staticmethod
    def remaining_time(session_id):
        """Return remaining seconds for the coding test."""
        data = session.get(f"coding_{session_id}")
        if not data:
            return 0
        elapsed = int(time.time()) - data["start_time"]
        return max(0, data["duration_seconds"] - elapsed)

    @staticmethod
    def get_public_tests(session_id):
        """Return the public test cases for the question."""
        data = session.get(f"coding_{session_id}")
        if not data:
            return []
        return data["question"].get("public_tests", [])

    @staticmethod
    def get_hidden_tests(session_id):
        """Return the hidden test cases for the question."""
        data = session.get(f"coding_{session_id}")
        if not data:
            return []
        return data["question"].get("hidden_tests", [])

    @staticmethod
    def get_session_data(session_id):
        """Return the full session data dict."""
        return session.get(f"coding_{session_id}")
