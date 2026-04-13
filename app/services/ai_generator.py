import os
import logging
import base64
import json
import sys
from pathlib import Path
from functools import lru_cache
from dotenv import load_dotenv, dotenv_values
import requests
from app.services.ai_settings_service import resolve_feature_execution_plan
from app.utils.round_order import ordered_present_round_keys, round_number_map, round_sort_key

# Load .env from project root deterministically (works in stdin / script / module runs).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")
AI_CLIENT = None
log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_dotenv_gemini_overrides() -> dict[str, str]:
    """Read Gemini-specific overrides from repo env files.

    Prefer `.env` as the single source of truth for Gemini settings when it
    contains any `GEMINI_*` keys. Otherwise fall back to `.env.production`.
    This prevents stale production-only Gemini flags from leaking into the app
    after an operator intentionally updates `.env` on the VM.
    """
    sources = (_PROJECT_ROOT / ".env", _PROJECT_ROOT / ".env.production")
    selected: dict[str, str] = {}

    for path in sources:
        if not path.exists():
            continue
        try:
            values = dotenv_values(path)
        except Exception:
            continue
        current: dict[str, str] = {}
        for key, value in values.items():
            if value is None:
                continue
            normalized_key = str(key or "")
            if not normalized_key:
                continue
            for candidate_key in (normalized_key, normalized_key.lstrip("\ufeff")):
                if candidate_key.startswith("GEMINI_"):
                    current[candidate_key] = str(value)
        if current:
            selected = current
            break

    return selected


def _get_env_value(name: str, default: str | None = None):
    """Read env var with fallback for BOM-prefixed keys."""
    if str(name or "").startswith("GEMINI_"):
        overrides = _get_dotenv_gemini_overrides()
        dotenv_value = overrides.get(name)
        if dotenv_value is not None:
            return dotenv_value
        bom_dotenv_value = overrides.get(f"\ufeff{name}")
        if bom_dotenv_value is not None:
            return bom_dotenv_value
        if overrides:
            return default
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


def reset_ai_runtime_state():
    """Clear cached AI clients and dotenv overrides after runtime config changes."""
    global AI_CLIENT
    AI_CLIENT = None
    _get_dotenv_gemini_overrides.cache_clear()


def _get_ai_client(api_key: str | None = None):
    """Lazily initialize Gemini client from environment or explicit runtime config."""
    global AI_CLIENT

    explicit_api_key = str(api_key or "").strip()
    use_cache = not explicit_api_key

    if use_cache and AI_CLIENT is not None:
        return AI_CLIENT

    resolved_api_key = explicit_api_key or str(_get_env_value("GEMINI_API_KEY") or "").strip()
    if not resolved_api_key:
        log.warning("GEMINI_API_KEY is not configured; AI summaries will use deterministic fallback text.")
        return None

    client_mode = str(_get_env_value("GEMINI_CLIENT_MODE", "auto") or "auto").strip().lower()
    prefer_rest = (
        client_mode == "rest"
        or sys.version_info >= (3, 14)
    )
    if prefer_rest:
        client = _build_rest_client(resolved_api_key)
        if use_cache:
            AI_CLIENT = client
        return client

    # Lazy import to avoid importing Google SDK when key is not configured.
    try:
        from google import genai
    except Exception as exc:
        log.debug("Gemini SDK unavailable; using REST fallback client: %s", exc)
        client = _build_rest_client(resolved_api_key)
        if use_cache:
            AI_CLIENT = client
        return client

    try:
        sdk_client = genai.Client(api_key=resolved_api_key)
    except Exception as exc:
        log.warning("Gemini SDK client initialization failed; trying REST fallback: %s", exc)
        client = _build_rest_client(resolved_api_key)
        if use_cache:
            AI_CLIENT = client
        return client

    rest_client = _build_rest_client(resolved_api_key)
    if rest_client is not None:
        client = _FallbackGeminiClient(primary_client=sdk_client, secondary_client=rest_client)
        if use_cache:
            AI_CLIENT = client
        return client

    if use_cache:
        AI_CLIENT = sdk_client
    return sdk_client


def _provider_http_session():
    session = requests.Session()
    session.trust_env = _should_trust_requests_env()
    return session


def _extract_openai_text(payload):
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part).strip()
    return ""


def _generate_openai_text(api_key: str, model: str, prompt: str, *, json_mode: bool = False, temperature: float | None = None):
    session = _provider_http_session()
    body = {
        "model": str(model or "gpt-4.1-mini").strip(),
        "messages": [{"role": "user", "content": str(prompt or "")}],
    }
    if temperature is not None:
        body["temperature"] = temperature
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    response = session.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {str(api_key or '').strip()}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=60,
    )
    response.raise_for_status()
    return _extract_openai_text(response.json())


def _generate_claude_text(api_key: str, model: str, prompt: str, *, temperature: float | None = None):
    session = _provider_http_session()
    body = {
        "model": str(model or "claude-3-5-sonnet-latest").strip(),
        "max_tokens": 2500,
        "messages": [{"role": "user", "content": str(prompt or "")}],
    }
    if temperature is not None:
        body["temperature"] = temperature
    response = session.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": str(api_key or "").strip(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    texts = []
    for item in payload.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            texts.append(str(item.get("text", "")))
    return "\n".join(text for text in texts if text).strip()


def _generate_gemini_text(api_key: str, model: str, prompt: str, *, json_mode: bool = False, temperature: float | None = None):
    if str(api_key or "").strip():
        try:
            ai_client = _get_ai_client(api_key=api_key)
        except TypeError as exc:
            if "api_key" not in str(exc):
                raise
            ai_client = _get_ai_client()
    else:
        ai_client = _get_ai_client()
    if not ai_client:
        return ""

    config = None
    if json_mode or temperature is not None:
        config = {}
        if json_mode:
            config["response_mime_type"] = "application/json"
        if temperature is not None:
            config["temperature"] = temperature

    response = ai_client.models.generate_content(
        model=str(model or "gemini-2.5-flash").strip(),
        contents=prompt,
        config=config,
    )
    return str(getattr(response, "text", "") or "").strip()


def _generate_text_for_feature(feature_key: str, prompt: str, *, json_mode: bool = False, temperature: float | None = None):
    execution_plan = resolve_feature_execution_plan(feature_key)
    provider_chain = execution_plan.get("providers", [])

    for provider in provider_chain:
        provider_key = str(provider.get("provider_key", "") or "").strip().lower()
        api_key = str(provider.get("api_key", "") or "").strip()
        model = str(provider.get("model", "") or "").strip()
        if not provider_key:
            continue
        try:
            if provider_key == "gemini":
                text = _generate_gemini_text(api_key, model, prompt, json_mode=json_mode, temperature=temperature)
            elif provider_key == "openai":
                text = _generate_openai_text(api_key, model, prompt, json_mode=json_mode, temperature=temperature)
            elif provider_key == "claude":
                if json_mode:
                    # Claude JSON mode stays prompt-driven for now; parsing remains best-effort.
                    text = _generate_claude_text(api_key, model, prompt, temperature=temperature)
                else:
                    text = _generate_claude_text(api_key, model, prompt, temperature=temperature)
            else:
                text = ""

            if text:
                return text
            raise RuntimeError(f"{provider_key} returned empty response text")
        except Exception as exc:
            log.warning(
                "AI provider %s failed for feature %s; trying next provider if available: %s",
                provider_key,
                feature_key,
                exc,
            )

    return ""


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
    overall_percentage = float(summary.get("overall_percentage", 0) or 0)

    def _round_narrative(round_label: str, status: str, pct: float, correct: int, total: int, threshold: float) -> str:
        if status == "PASS" and pct >= max(85.0, float(threshold)):
            insight = "The candidate demonstrated strong command in this area and cleared the round comfortably."
        elif status == "PASS":
            insight = "The candidate met the expected benchmark and showed workable role-aligned understanding in this round."
        elif pct >= max(float(threshold) - 10.0, 55.0):
            insight = "The candidate showed partial familiarity, but the round remained below the expected bar."
        elif pct >= 35.0:
            insight = "The result suggests limited working understanding, with noticeable gaps in the concepts assessed here."
        else:
            insight = "The score indicates a significant gap in this area and the current response quality remained well below expectation."

        return (
            f"**{round_label}**: {insight} "
            f"Final score was {pct:.2f}% ({correct}/{total}) against a pass threshold of {threshold:.1f}%."
        )

    strength_labels = []
    concern_labels = []
    for rk in ordered_present_round_keys(rounds):
        rv = rounds.get(rk) or {}
        label = str(rv.get("round_label", rk) or rk)
        status = str(rv.get("status", "") or "").strip().upper()
        pct = float(rv.get("percentage", 0) or 0)
        if status == "PASS" or pct >= 75.0:
            strength_labels.append(label)
        elif status == "FAIL" and pct < 50.0:
            concern_labels.append(label)

    if passed_rounds == total_rounds and total_rounds > 0:
        snapshot = (
            f"The candidate completed all {total_rounds} rounds successfully and delivered an overall score of "
            f"{overall_percentage:.2f}%, which indicates a consistently strong assessment profile."
        )
    elif passed_rounds > failed_rounds:
        snapshot = (
            f"The candidate attempted {attempted_rounds}/{total_rounds} rounds, passing {passed_rounds} and failing {failed_rounds}, "
            f"with an overall score of {overall_percentage:.2f}%. The profile shows more strengths than gaps, but still requires targeted review."
        )
    elif passed_rounds == failed_rounds and attempted_rounds:
        snapshot = (
            f"The candidate attempted {attempted_rounds}/{total_rounds} rounds with a mixed outcome, recording "
            f"{passed_rounds} passes and {failed_rounds} failures. The overall score of {overall_percentage:.2f}% suggests a partially aligned profile."
        )
    else:
        snapshot = (
            f"The candidate attempted {attempted_rounds}/{total_rounds} rounds, passing {passed_rounds} and failing {failed_rounds}. "
            f"With an overall score of {overall_percentage:.2f}%, the assessment indicates substantial improvement is still needed for this role."
        )

    context_notes = []
    if strength_labels:
        context_notes.append(f"Relative strengths were observed in {', '.join(strength_labels[:3])}.")
    if concern_labels:
        context_notes.append(f"The most visible gaps appeared in {', '.join(concern_labels[:3])}.")

    lines = [
        (
            f"{name} was evaluated for the {role} role. "
            "This summary is intended to give TA and hiring stakeholders a concise decision-support view of the candidate's performance."
        ),
        "",
        snapshot,
        *(["", " ".join(context_notes)] if context_notes else []),
        "",
        "### Round-wise Detailed Insights",
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

        lines.append(f"- **{round_number}. {round_label}**: {_round_narrative(round_label, status, float(pct or 0), int(correct or 0), int(total or 0), float(threshold or 0)).split(': ', 1)[1]}")

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

    code_text = str(submitted_code or "").strip()
    normalized_code = code_text.lower()
    has_todo = "todo" in normalized_code
    prints_output = "print(" in normalized_code
    returns_none = "return none" in normalized_code or "returnnull" in normalized_code.replace(" ", "")
    syntax_hint = ""

    if str(language or "").strip().lower() == "python" and code_text:
        try:
            compile(code_text, "<candidate_code>", "exec")
        except Exception as exc:
            syntax_hint = str(exc)

    insight_lines = []
    if status == "PASS" and percentage >= 90:
        insight_lines.append(
            "- The submitted solution aligns well with the expected outcome and the score suggests the implementation was functionally correct."
        )
    elif status == "PASS":
        insight_lines.append(
            "- The candidate produced a working or near-working solution, though the submission still appears to have room for refinement in structure or completeness."
        )
    elif percentage >= 50:
        insight_lines.append(
            "- The submission shows partial problem understanding, but the implementation still contains correctness or completeness gaps that prevented a full pass."
        )
    else:
        insight_lines.append(
            "- The current submission does not yet satisfy the core problem requirements and reflects a significant execution gap in the coding round."
        )

    if has_todo:
        insight_lines.append(
            "- The retained TODO markers suggest the problem was not fully completed before submission."
        )
    if prints_output:
        insight_lines.append(
            "- The code appears to rely on printed output, which may not satisfy the required return contract expected by the evaluator."
        )
    if returns_none and status != "PASS":
        insight_lines.append(
            "- The return path still points to a placeholder or incomplete result, which likely contributed to the low evaluation score."
        )
    if syntax_hint:
        insight_lines.append(
            f"- A syntax-level issue is likely present in the submission ({syntax_hint}), which would block reliable execution."
        )

    if not insight_lines:
        insight_lines.append("- Round-wise insights are available, but the coding submission did not expose enough detail for a deeper heuristic analysis.")

    assessment_line = (
        "Assessment: The submission shows a strong and largely correct implementation."
        if status == "PASS" and percentage >= 85
        else "Assessment: The submission shows workable intent, but the current implementation would still need refinement before it can be treated as a dependable solution."
        if percentage >= 50
        else "Assessment: The implementation remains incomplete or incorrect for the expected coding objective and would require rework."
    )

    return (
        "Key Insights:\n"
        f"{chr(10).join(insight_lines)}\n\n"
        "### Coding Round Summary\n"
        f"Round: {round_label}\n"
        f"Score: {percentage}% ({correct}/{total})\n"
        f"Language: {language}\n"
        f"Question: {question_title}\n"
        f"Problem Statement: {question_text}\n"
        f"Submitted Code:\n{submitted_code if submitted_code else 'No submitted code found.'}\n\n"
        f"{assessment_line}"
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
        text = _generate_text_for_feature("overall_summary", prompt)
        if not text:
            raise RuntimeError("AI provider returned empty overall summary text")
        return _normalize_overall_summary(text)
    except Exception as e:
        log.warning("Error generating overall summary; using fallback summary: %s", e)
        return _normalize_overall_summary(_build_fallback_summary(candidate_data))


def generate_coding_round_summary(coding_data):
    """
    Generate an AI-based summary for coding round with question and submitted code.
    """
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
        text = _generate_text_for_feature("coding_summary", prompt)
        if not text:
            raise RuntimeError("AI provider returned empty coding summary text")
        return _strip_coding_overview_lines(text)
    except Exception as e:
        log.warning("Error generating coding summary; using fallback coding summary: %s", e)
        return _strip_coding_overview_lines(_build_fallback_coding_summary(coding_data))


def generate_consolidated_evaluation_summary(consolidated_payload):
    """
    Generate an AI-based consolidated summary across multiple selected candidates.
    """
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
        text = _generate_text_for_feature("consolidated_summary", prompt)
        if not text:
            raise RuntimeError("AI provider returned empty consolidated summary text")
        return text
    except Exception as e:
        log.warning("Error generating consolidated summary; using fallback consolidated summary: %s", e)
        return _build_fallback_consolidated_summary(consolidated_payload)
