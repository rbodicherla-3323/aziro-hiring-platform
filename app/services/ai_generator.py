import os
import logging
import base64
import json
import sys
from pathlib import Path
from dotenv import load_dotenv
import requests

# Load .env from project root deterministically (works in stdin / script / module runs).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")
AI_CLIENT = None
log = logging.getLogger(__name__)


def _round_sort_key(round_key: str) -> tuple[int, str]:
    value = str(round_key or "").upper()
    if value.startswith("L") and value[1:].isdigit():
        return int(value[1:]), value
    return 999, value


def _get_env_value(name: str, default: str | None = None):
    """Read env var with fallback for BOM-prefixed keys."""
    value = os.getenv(name)
    if value is not None:
        return value
    bom_name = f"\ufeff{name}"
    bom_value = os.getenv(bom_name)
    if bom_value is not None:
        return bom_value
    return default


class _GeminiRestResponse:
    def __init__(self, text: str):
        self.text = text or ""


class _GeminiRestModels:
    def __init__(self, api_key: str):
        self._api_key = str(api_key or "").strip()
        self._session = requests.Session()
        # Avoid inheriting broken proxy env vars (seen in local debug setups).
        self._session.trust_env = False

    @staticmethod
    def _part_from_unknown(value):
        if value is None:
            return None

        if isinstance(value, str):
            return {"text": value}

        if isinstance(value, dict):
            if "text" in value:
                return {"text": str(value.get("text", ""))}
            if "inlineData" in value and isinstance(value.get("inlineData"), dict):
                inline = value.get("inlineData") or {}
                return {
                    "inlineData": {
                        "mimeType": str(inline.get("mimeType") or inline.get("mime_type") or "application/octet-stream"),
                        "data": str(inline.get("data") or ""),
                    }
                }
            if "inline_data" in value and isinstance(value.get("inline_data"), dict):
                inline = value.get("inline_data") or {}
                return {
                    "inlineData": {
                        "mimeType": str(inline.get("mime_type") or inline.get("mimeType") or "application/octet-stream"),
                        "data": str(inline.get("data") or ""),
                    }
                }
            if "parts" in value and isinstance(value["parts"], list):
                # Caller may pass a full content object; flatten first part set.
                return {"parts": value["parts"]}
            return None

        # Best-effort support for SDK objects (if passed across boundaries).
        for attr in ("text",):
            if hasattr(value, attr):
                text_value = getattr(value, attr, None)
                if text_value:
                    return {"text": str(text_value)}

        # Some SDK Part objects expose inline_data with data/mime_type.
        inline = getattr(value, "inline_data", None)
        if inline is not None:
            mime_type = getattr(inline, "mime_type", None)
            data = getattr(inline, "data", None)
            if mime_type and data:
                if isinstance(data, bytes):
                    encoded = base64.b64encode(data).decode("ascii")
                else:
                    encoded = str(data)
                return {"inlineData": {"mimeType": str(mime_type), "data": encoded}}

        return None

    @classmethod
    def _normalize_contents(cls, contents):
        # Gemini REST expects [{"role":"user","parts":[...]}]
        if isinstance(contents, str):
            return [{"role": "user", "parts": [{"text": contents}]}]

        if isinstance(contents, list):
            parts = []
            for item in contents:
                part = cls._part_from_unknown(item)
                if not part:
                    continue
                if "parts" in part and isinstance(part["parts"], list):
                    parts.extend(part["parts"])
                else:
                    parts.append(part)
            if not parts:
                parts = [{"text": ""}]
            # Keep prompt text first for better model adherence.
            text_parts = [p for p in parts if isinstance(p, dict) and "text" in p]
            media_parts = [p for p in parts if not (isinstance(p, dict) and "text" in p)]
            parts = text_parts + media_parts
            return [{"role": "user", "parts": parts}]

        # Unknown shape: stringify safely.
        return [{"role": "user", "parts": [{"text": str(contents)}]}]

    @staticmethod
    def _extract_text_from_response(payload):
        try:
            candidates = payload.get("candidates") or []
            if not candidates:
                return ""
            content = (candidates[0] or {}).get("content") or {}
            parts = content.get("parts") or []
            texts = [str(p.get("text", "")) for p in parts if isinstance(p, dict) and p.get("text") is not None]
            if texts:
                return "\n".join(t for t in texts if t).strip()
        except Exception:
            return ""
        return ""

    @staticmethod
    def _normalize_generation_config(config):
        if not config:
            return None

        source = {}
        if isinstance(config, dict):
            source = dict(config)
        else:
            # Best-effort extraction from SDK config objects.
            for name in (
                "response_mime_type",
                "responseMimeType",
                "temperature",
                "top_p",
                "topP",
                "top_k",
                "topK",
                "max_output_tokens",
                "maxOutputTokens",
            ):
                if hasattr(config, name):
                    value = getattr(config, name)
                    if value is not None:
                        source[name] = value

        if not source:
            return None

        out = {}
        if "responseMimeType" in source:
            out["responseMimeType"] = source["responseMimeType"]
        elif "response_mime_type" in source:
            out["responseMimeType"] = source["response_mime_type"]

        if "temperature" in source:
            out["temperature"] = source["temperature"]

        if "topP" in source:
            out["topP"] = source["topP"]
        elif "top_p" in source:
            out["topP"] = source["top_p"]

        if "topK" in source:
            out["topK"] = source["topK"]
        elif "top_k" in source:
            out["topK"] = source["top_k"]

        if "maxOutputTokens" in source:
            out["maxOutputTokens"] = source["maxOutputTokens"]
        elif "max_output_tokens" in source:
            out["maxOutputTokens"] = source["max_output_tokens"]

        return out or None

    def generate_content(self, model: str, contents, config=None, **kwargs):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {"contents": self._normalize_contents(contents)}
        generation_config = self._normalize_generation_config(
            config or kwargs.get("generation_config") or kwargs.get("generationConfig")
        )
        if generation_config:
            body["generationConfig"] = generation_config
        response = self._session.post(
            url,
            params={"key": self._api_key},
            json=body,
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        return _GeminiRestResponse(self._extract_text_from_response(payload))


class _GeminiRestClient:
    def __init__(self, api_key: str):
        self.models = _GeminiRestModels(api_key)


def _get_ai_client():
    """Lazily initialize Gemini client from environment."""
    global AI_CLIENT

    if AI_CLIENT is not None:
        return AI_CLIENT

    api_key = _get_env_value("GEMINI_API_KEY")
    if not api_key:
        return None

    client_mode = str(_get_env_value("GEMINI_CLIENT_MODE", "auto") or "auto").strip().lower()
    prefer_rest = (
        client_mode == "rest"
        or sys.version_info >= (3, 14)
    )
    if prefer_rest:
        try:
            AI_CLIENT = _GeminiRestClient(api_key=api_key)
            return AI_CLIENT
        except Exception as rest_exc:
            log.warning("Gemini REST client initialization failed: %s", rest_exc)
            return None

    # Lazy import to avoid importing Google SDK when key is not configured.
    try:
        from google import genai
    except Exception as exc:
        log.debug("Gemini SDK unavailable; using REST fallback client: %s", exc)
        try:
            AI_CLIENT = _GeminiRestClient(api_key=api_key)
            return AI_CLIENT
        except Exception as rest_exc:
            log.warning("Gemini REST fallback initialization failed: %s", rest_exc)
            return None

    try:
        AI_CLIENT = genai.Client(api_key=api_key)
        return AI_CLIENT
    except Exception as exc:
        log.warning("Gemini SDK client initialization failed; trying REST fallback: %s", exc)
        try:
            AI_CLIENT = _GeminiRestClient(api_key=api_key)
            return AI_CLIENT
        except Exception as rest_exc:
            log.warning("Gemini REST fallback initialization failed: %s", rest_exc)
            return None


def _build_fallback_summary(candidate_data):
    """Return deterministic summary text when AI is unavailable."""
    if not isinstance(candidate_data, dict):
        return "Evaluation data is available, but AI summary generation is not configured."

    name = candidate_data.get("name", "Candidate")
    role = candidate_data.get("role", "N/A")
    summary = candidate_data.get("summary", {}) or {}
    rounds = candidate_data.get("rounds", {}) or {}

    attempted_rounds = summary.get("attempted_rounds", 0)
    total_rounds = summary.get("total_rounds", len(rounds))
    passed_rounds = summary.get("passed_rounds", 0)
    failed_rounds = summary.get("failed_rounds", 0)

    lines = [
        (
            f"{name} was evaluated for the {role} role. "
            "This overall summary captures performance across all evaluation rounds for TA review."
        ),
        "",
        (
            f"The candidate attempted {attempted_rounds}/{total_rounds} rounds, "
            f"passing {passed_rounds} and failing {failed_rounds}."
        ),
        "",
        "**Round-wise Detailed Insights:**",
    ]
    for rk in sorted(rounds.keys(), key=_round_sort_key):
        rv = rounds.get(rk)
        if not rv:
            continue
        round_label = rv.get("round_label", rk)
        status = rv.get("status", "Pending")
        pct = rv.get("percentage", 0)
        correct = rv.get("correct", 0)
        total = rv.get("total", 0)
        threshold = rv.get("pass_threshold", 0)

        lines.append(
            f"- **{round_label} ({rk})**: Status = {status}; Score = {pct}% ({correct}/{total}); "
            f"Pass Threshold = {threshold}%."
        )

    return "\n".join(lines)


def _normalize_overall_summary(text: str) -> str:
    """Remove explicit Overall Evaluation heading while preserving content."""
    if not text:
        return text

    cleaned = []
    blocked = {
        "overall evaluation",
        "### overall evaluation",
        "**overall evaluation:**",
    }
    for line in str(text).splitlines():
        normalized = line.strip().lower()
        if normalized in blocked:
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _build_fallback_coding_summary(coding_data):
    """Return deterministic coding-only summary when AI is unavailable."""
    if not isinstance(coding_data, dict):
        return "Coding submission data is unavailable."
    
    round_label = coding_data.get("round_label", "Coding Round")
    status = coding_data.get("status", "Not Attempted")
    percentage = coding_data.get("percentage", 0)
    correct = coding_data.get("correct", 0)
    total = coding_data.get("total", 0)
    language = coding_data.get("language", "")
    question_title = coding_data.get("question_title", "")
    question_text = coding_data.get("question_text", "")
    submitted_code = coding_data.get("submitted_code", "")
    overall_rounds = coding_data.get("overall_rounds", {}) or {}

    insight_lines = []
    for rk in ["L1", "L2", "L3", "L4", "L5"]:
        rd = overall_rounds.get(rk)
        if not rd:
            continue
        insight_lines.append(
            f"- {rk} {rd.get('round_label', rk)}: {rd.get('status', 'Pending')} "
            f"({rd.get('percentage', 0)}%, {rd.get('correct', 0)}/{rd.get('total', 0)})"
        )
    key_insights = "\n".join(insight_lines) if insight_lines else "- Round-wise insights not available."

    return (
        "Key Insights:\n"
        f"{key_insights}\n\n"
        "Coding Round Summary\n"
        f"Round: {round_label}\n"
        f"Score: {percentage}% ({correct}/{total})\n"
        f"Language: {language}\n"
        f"Question: {question_title}\n"
        f"Problem Statement: {question_text}\n"
        f"Submitted Code:\n{submitted_code if submitted_code else 'No submitted code found.'}"
    )


def _strip_coding_overview_lines(text: str) -> str:
    """Remove high-level candidate/application overview lines from coding summary."""
    if not text:
        return text

    blocked_prefixes = (
        "Candidate:",
        "Role Applied For:",
        "Overall Application Status:",
        "Summary of Rounds:",
        "Total Rounds Attempted:",
        "Passed Rounds:",
        "Failed Rounds:",
        "Overall Correct Answers:",
        "Overall Percentage:",
    )

    cleaned_lines = []
    for line in str(text).splitlines():
        stripped = line.strip().lstrip("•").strip()
        if any(stripped.startswith(prefix) for prefix in blocked_prefixes):
            continue
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def generate_evaluation_summary(candidate_data):
    """
    Generate an AI-based summary for a candidate's evaluation.
    candidate_data: dict containing candidate's evaluation details.
    Returns a summary string or None.
    """
    ai_client = _get_ai_client()
    if not ai_client:
        print("Gemini AI client not initialized. Using fallback summary.")
        return _normalize_overall_summary(_build_fallback_summary(candidate_data))

    prompt = f""" 
    Create a professional overall evaluation summary for TA review from the candidate data below.

    Required structure:
    1) Intro paragraph with candidate name and role.
    2) One concise paragraph with overall performance snapshot (no heading for this paragraph).
    3) Section heading: "Round-wise Detailed Insights"
    4) Bullet points for every available round present in candidate_data["rounds"] in the exact given order/labels, each bullet must include:
       - One short narrative insight sentence about performance in that round.

    Constraints:
    - Use round labels exactly as provided; do not rename any round.
    - Do not provide verdicts or pass/fail labels in the bullet points; keep bullets narrative and factual.
    - Do not mention AI-generated content.
    - Do not include submitted code or submitted responses in this overall summary.
    - Do not output a table; use bullet points for round details.
    - Do not output a heading titled "Overall Evaluation".
    - Use only provided data; do not invent.

    Candidate data:
    {candidate_data} """

    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return _normalize_overall_summary(response.text.strip())
    except Exception as e:
        print(f"Error generating summary: {e}. Using fallback summary.")
        return _normalize_overall_summary(_build_fallback_summary(candidate_data))


def generate_coding_round_summary(coding_data):
    """
    Generate an AI-based summary for coding round with question and submitted code.
    """
    ai_client = _get_ai_client()
    if not ai_client:
        print("Gemini AI client not initialized. Using fallback coding summary.")
        return _strip_coding_overview_lines(_build_fallback_coding_summary(coding_data))

    prompt = f"""
    Rewrite the following coding round data into a professional, HR-readable summary.

    Requirements:
    - Do not mention AI or that this was generated by AI.
    - Do NOT include lines like:
      "Candidate: ...", "Role Applied For: ...", "Overall Application Status: ...",
      "Summary of Rounds: ...", "Total Rounds Attempted: ...", "Passed/Failed ...",
      "Overall Correct Answers ...", or "Overall Percentage ...".
    - Start with section title: "Key Insights"
    - Add section title: "Key Insights" one insight if code logic is correct but not able to fetch output, another insight if code is efficient or not based on time/space complexity.
    - Include coding question title and short problem statement.
    - Include submitted code exactly as provided under a "Submitted Code" section.
    - Keep tone factual and concise.

    Coding Round Data:
    {coding_data}
    """
    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return _strip_coding_overview_lines(response.text.strip())
    except Exception as e:
        print(f"Error generating coding summary: {e}. Using fallback coding summary.")
        return _strip_coding_overview_lines(_build_fallback_coding_summary(coding_data))
