import os
import logging
import base64
import json
import sys
from pathlib import Path
from dotenv import load_dotenv
import requests
from app.utils.round_order import ordered_present_round_keys, round_number_map, round_sort_key

# Load .env from project root deterministically (works in stdin / script / module runs).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")
AI_CLIENT = None
log = logging.getLogger(__name__)


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


def _env_flag(name: str, default: bool | None = None) -> bool | None:
    value = _get_env_value(name)
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _should_trust_requests_env() -> bool:
    explicit = _env_flag("GEMINI_TRUST_ENV", None)
    if explicit is not None:
        return explicit

    # Auto-enable env-backed requests behavior when the runtime is configured
    # through proxy or certificate env vars (common in production VMs).
    env_markers = (
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "https_proxy",
        "http_proxy",
        "all_proxy",
        "no_proxy",
    )
    return any(bool(_get_env_value(name, "")) for name in env_markers)


class _GeminiRestResponse:
    def __init__(self, text: str):
        self.text = text or ""


class _GeminiRestModels:
    def __init__(self, api_key: str):
        self._api_key = str(api_key or "").strip()
        self._session = requests.Session()
        # Respect proxy/certificate env vars in production, while still allowing
        # local environments to opt out through GEMINI_TRUST_ENV=false.
        self._session.trust_env = _should_trust_requests_env()

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


class _FallbackGeminiModels:
    def __init__(self, primary_models=None, secondary_models=None):
        self._primary_models = primary_models
        self._secondary_models = secondary_models

    def generate_content(self, *args, **kwargs):
        primary_exc = None

        if self._primary_models is not None:
            try:
                response = self._primary_models.generate_content(*args, **kwargs)
                response_text = str(getattr(response, "text", "") or "").strip()
                if response_text:
                    return response
                primary_exc = RuntimeError("Primary Gemini client returned empty response text")
                log.warning("%s; trying REST fallback", primary_exc)
            except Exception as exc:
                primary_exc = exc
                log.warning("Primary Gemini client failed during generation; trying REST fallback: %s", exc)

        if self._secondary_models is not None:
            return self._secondary_models.generate_content(*args, **kwargs)

        if primary_exc is not None:
            raise primary_exc
        raise RuntimeError("Gemini client is unavailable")


class _FallbackGeminiClient:
    def __init__(self, primary_client=None, secondary_client=None):
        self.models = _FallbackGeminiModels(
            getattr(primary_client, "models", None),
            getattr(secondary_client, "models", None),
        )


def _build_rest_client(api_key: str):
    key = str(api_key or "").strip()
    if not key:
        return None
    try:
        return _GeminiRestClient(api_key=key)
    except Exception as exc:
        log.warning("Gemini REST client initialization failed: %s", exc)
        return None


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
        AI_CLIENT = _build_rest_client(api_key)
        return AI_CLIENT

    # Lazy import to avoid importing Google SDK when key is not configured.
    try:
        from google import genai
    except Exception as exc:
        log.debug("Gemini SDK unavailable; using REST fallback client: %s", exc)
        AI_CLIENT = _build_rest_client(api_key)
        return AI_CLIENT

    try:
        sdk_client = genai.Client(api_key=api_key)
    except Exception as exc:
        log.warning("Gemini SDK client initialization failed; trying REST fallback: %s", exc)
        AI_CLIENT = _build_rest_client(api_key)
        return AI_CLIENT

    rest_client = _build_rest_client(api_key)
    if rest_client is not None:
        AI_CLIENT = _FallbackGeminiClient(primary_client=sdk_client, secondary_client=rest_client)
        return AI_CLIENT

    AI_CLIENT = sdk_client
    return AI_CLIENT


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
    ordered_keys = ordered_present_round_keys(rounds)
    numbers = round_number_map(ordered_keys)
    for rk in ordered_keys:
        rv = rounds.get(rk)
        if not rv:
            continue
        round_label = rv.get("round_label", rk)
        round_number = rv.get("round_number", numbers.get(rk, 0))
        status = rv.get("status", "Pending")
        pct = rv.get("percentage", 0)
        correct = rv.get("correct", 0)
        total = rv.get("total", 0)
        threshold = rv.get("pass_threshold", 0)

        lines.append(
            f"- **{round_number}. {round_label}**: Status = {status}; Score = {pct}% ({correct}/{total}); "
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
    ordered_keys = ordered_present_round_keys(overall_rounds)
    numbers = round_number_map(ordered_keys)
    for rk in ordered_keys:
        rd = overall_rounds.get(rk)
        if not rd:
            continue
        number = rd.get("round_number", numbers.get(rk, 0))
        insight_lines.append(
            f"- {number}. {rd.get('round_label', rk)}: {rd.get('status', 'Pending')} "
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


def _build_fallback_consolidated_summary(consolidated_payload):
    """Return deterministic multi-candidate summary text when AI is unavailable."""
    if not isinstance(consolidated_payload, dict):
        return "Consolidated evaluation data is unavailable."

    scope = consolidated_payload.get("scope", {}) or {}
    aggregate = consolidated_payload.get("aggregate", {}) or {}
    verdict_counts = aggregate.get("verdict_counts", {}) or {}
    round_stats = aggregate.get("round_stats", []) or []
    completion_stats = aggregate.get("completion_stats", {}) or {}
    recurring_gap_signals = aggregate.get("recurring_gap_signals", []) or []
    coding_signals = aggregate.get("coding_signals", []) or []

    role = scope.get("role", "Selected Candidates")
    period_label = scope.get("period_label", "Current Scope")
    candidate_count = int(scope.get("candidate_count", 0) or 0)
    attempted_candidate_count = int(scope.get("attempted_candidate_count", 0) or 0)
    average_overall_percentage = float(scope.get("average_overall_percentage", 0) or 0)
    selected_count = int(verdict_counts.get("Selected", 0) or 0)
    rejected_count = int(verdict_counts.get("Rejected", 0) or 0)
    in_progress_count = int(verdict_counts.get("In Progress", 0) or 0)
    pending_count = int(verdict_counts.get("Pending", 0) or 0)
    batch_ids = [value for value in (scope.get("batch_ids", []) or []) if str(value or "").strip()]
    completion_ratio = float(completion_stats.get("average_completion_ratio", 0) or 0)
    partially_completed = int(completion_stats.get("partially_completed_candidates", 0) or 0)
    not_started = int(completion_stats.get("not_started_candidates", 0) or 0)
    multiple_failed = int(completion_stats.get("multiple_failed_round_candidates", 0) or 0)

    lines = [
        "Consolidated Interview Feedback",
        "",
        "Overall Outcome",
        (
            f"This summary covers {candidate_count} candidate(s) for the {role} role "
            f"in the {period_label} scope."
        ),
        (
            f"{attempted_candidate_count} candidate(s) attempted at least one round. "
            f"The overall average score across attempted candidates was {average_overall_percentage:.2f}%."
        ),
        (
            f"Verdict distribution: Selected = {selected_count}, Rejected = {rejected_count}, "
            f"In Progress = {in_progress_count}, Pending = {pending_count}."
        ),
        (
            f"Average round completion across the selected set was {completion_ratio:.2f}%."
        ),
    ]
    if batch_ids:
        lines.append(f"Batch coverage: {', '.join(batch_ids)}.")

    lines.extend(["", "Key Observations"])
    ranked_rounds = sorted(
        round_stats,
        key=lambda row: (
            -int(row.get("failed_candidates", 0) or 0),
            float(row.get("average_percentage", 0) or 0),
            row.get("round_label", ""),
        ),
    )

    observation_index = 1
    if ranked_rounds:
        for stat in ranked_rounds[:3]:
            lines.append(
                (
                    f"{observation_index}. {stat.get('round_label', 'Round')}: "
                    f"{int(stat.get('attempted_candidates', 0) or 0)} attempted, "
                    f"{int(stat.get('failed_candidates', 0) or 0)} failed, "
                    f"{int(stat.get('passed_candidates', 0) or 0)} passed, "
                    f"average score {float(stat.get('average_percentage', 0) or 0):.2f}%, "
                    f"with {int(stat.get('below_threshold_candidates', 0) or 0)} below threshold."
                )
            )
            observation_index += 1
    else:
        lines.append("1. Round-level trend data was not available for this candidate set.")
        observation_index = 2

    if partially_completed or not_started:
        lines.append(
            (
                f"{observation_index}. Interview readiness/completion: "
                f"{partially_completed} candidate(s) were still in progress and "
                f"{not_started} had not started any round in this scope."
            )
        )
        observation_index += 1

    if multiple_failed:
        lines.append(
            (
                f"{observation_index}. {multiple_failed} candidate(s) failed multiple rounds, "
                "which suggests the batch quality gap was not limited to a single stage."
            )
        )
        observation_index += 1

    for signal in recurring_gap_signals[:2]:
        label = str(signal.get("signal_label", "") or "").strip()
        if not label:
            continue
        examples = [value for value in (signal.get("evidence_examples", []) or []) if str(value or "").strip()]
        example_text = str(examples[0]).rstrip(". ") if examples else ""
        evidence = f" Example: {example_text}." if example_text else ""
        lines.append(
            (
                f"{observation_index}. Repeated gap in {signal.get('round_label', 'the batch')}: "
                f"\"{label}\" appeared across {int(signal.get('candidate_occurrences', 0) or 0)} candidate(s)."
                f"{evidence}"
            )
        )
        observation_index += 1

    for signal in coding_signals[:1]:
        title = str(signal.get("question_title", "") or "").strip() or "the coding challenge"
        languages = ", ".join(signal.get("languages", []) or [])
        language_clause = f" Common languages: {languages}." if languages else ""
        lines.append(
            (
                f"{observation_index}. Hands-on coding signal: \"{title}\" was attempted by "
                f"{int(signal.get('attempted_candidates', 0) or 0)} candidate(s), with "
                f"{int(signal.get('failed_candidates', 0) or 0)} failing and an average score of "
                f"{float(signal.get('average_percentage', 0) or 0):.2f}%."
                f"{language_clause}"
            )
        )
        observation_index += 1

    lines.extend([
        "",
        "Overall Assessment & Recommendations",
        "- Use the weakest rounds and repeated gap signals in this summary as the primary prescreening checkpoints for the next drive.",
        "- Focus candidate preparation on the repeated concept and coding patterns called out above rather than only on overall scores.",
        "- Recheck interview readiness before scheduling when completion is low or many candidates remain in progress.",
        "- Treat repeated multi-round failures as a sign to tighten shortlisting criteria for this role before the next batch is shared.",
    ])

    return "\n".join(lines)


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
        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            raise RuntimeError("Gemini returned empty overall summary text")
        return _normalize_overall_summary(text)
    except Exception as e:
        log.warning("Error generating overall summary; using fallback summary: %s", e)
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
        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            raise RuntimeError("Gemini returned empty coding summary text")
        return _strip_coding_overview_lines(text)
    except Exception as e:
        log.warning("Error generating coding summary; using fallback coding summary: %s", e)
        return _strip_coding_overview_lines(_build_fallback_coding_summary(coding_data))


def generate_consolidated_evaluation_summary(consolidated_payload):
    """
    Generate an AI-based consolidated summary across multiple selected candidates.
    """
    ai_client = _get_ai_client()
    if not ai_client:
        print("Gemini AI client not initialized. Using fallback consolidated summary.")
        return _build_fallback_consolidated_summary(consolidated_payload)

    prompt = f"""
    Create a professional consolidated interview-performance summary from the structured data below.

    Required structure:
    1) Title line: "Consolidated Interview Feedback"
    2) Section heading: "Overall Outcome"
       - One concise paragraph that summarizes candidate volume, verdict mix, completion status, and the overall signal.
    3) Section heading: "Key Observations"
       - 5 to 7 numbered observations covering recurring patterns across the batch.
       - Prioritize repeated weak rounds, low average-score rounds, completion/readiness issues, recurring knowledge gaps from repeated question evidence, and coding/performance trends when present.
    4) Section heading: "Overall Assessment & Recommendations"
       - 4 to 6 bullet points with practical next-step recommendations.

    Constraints:
    - Do not mention AI.
    - Do not mention candidate names or emails.
    - Use only the provided structured data.
    - If recurring_gap_signals include repeated question evidence, infer the underlying concept gap from that evidence instead of repeating raw question text verbatim.
    - Use recurring_gap_signals only when the evidence clearly supports the conclusion; otherwise stay generic and data-driven.
    - Use coding_signals to comment on hands-on implementation strength or weakness when present.
    - If round labels are generic and detailed evidence is weak, keep observations generic and data-driven.
    - Do not mention submitted code.
    - Do not output a table.
    - Keep the summary detailed but readable for HR/hiring review.

    Consolidated data:
    {consolidated_payload}
    """

    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            raise RuntimeError("Gemini returned empty consolidated summary text")
        return text
    except Exception as e:
        log.warning("Error generating consolidated summary; using fallback consolidated summary: %s", e)
        return _build_fallback_consolidated_summary(consolidated_payload)
