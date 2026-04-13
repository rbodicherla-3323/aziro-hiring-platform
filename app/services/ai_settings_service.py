import base64
import hashlib
import os
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import AIProviderConfig, AIFeatureSetting


PROVIDER_CATALOG = {
    "gemini": {
        "label": "Google Gemini",
        "api_key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-2.5-flash",
    },
    "openai": {
        "label": "OpenAI / GPT",
        "api_key_env": "OPENAI_API_KEY",
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-4.1-mini",
    },
    "claude": {
        "label": "Anthropic Claude",
        "api_key_env": "ANTHROPIC_API_KEY",
        "model_env": "ANTHROPIC_MODEL",
        "default_model": "claude-3-5-sonnet-latest",
    },
}

FEATURE_CATALOG = {
    "overall_summary": {
        "label": "Overall Summary Report",
        "group": "summaries",
        "provider_env": "SUMMARY_AI_PROVIDER",
    },
    "coding_summary": {
        "label": "Coding Round Summary",
        "group": "summaries",
        "provider_env": "SUMMARY_AI_PROVIDER",
    },
    "consolidated_summary": {
        "label": "Consolidated Summary",
        "group": "summaries",
        "provider_env": "SUMMARY_AI_PROVIDER",
    },
    "resume_identity": {
        "label": "Resume Parsing / Identity Extraction",
        "group": "document_intelligence",
        "provider_env": "DOCINT_AI_PROVIDER",
    },
    "jd_role_match": {
        "label": "JD Parsing / Role Match",
        "group": "document_intelligence",
        "provider_env": "DOCINT_AI_PROVIDER",
    },
}

_ENV_GROUP_PROVIDER = {
    "summaries": "SUMMARY_AI_PROVIDER",
    "document_intelligence": "DOCINT_AI_PROVIDER",
}


def _utcnow():
    return datetime.now(timezone.utc)


def _normalize_provider_key(value: str) -> str:
    return str(value or "").strip().lower()


def _normalize_feature_key(value: str) -> str:
    return str(value or "").strip().lower()


def list_supported_providers() -> list[dict]:
    return [
        {"provider_key": key, **meta}
        for key, meta in PROVIDER_CATALOG.items()
    ]


def list_supported_features() -> list[dict]:
    return [
        {"feature_key": key, **meta}
        for key, meta in FEATURE_CATALOG.items()
    ]


def _get_secret_material():
    for env_name in ("AI_SETTINGS_MASTER_KEY", "APP_SECRETS_MASTER_KEY"):
        value = str(os.getenv(env_name, "") or "").strip()
        if value:
            return value, env_name

    try:
        secret_key = str(current_app.secret_key or "").strip()
    except RuntimeError:
        secret_key = ""
    if secret_key:
        return secret_key, "FLASK_SECRET_KEY"

    env_secret = str(os.getenv("SECRET_KEY", "") or "").strip()
    if env_secret:
        return env_secret, "SECRET_KEY"

    return "", ""


def get_key_storage_status() -> dict:
    secret, source = _get_secret_material()
    if not secret:
        return {
            "ready": False,
            "source": "",
            "warning": "Encrypted key storage is unavailable until AI_SETTINGS_MASTER_KEY is configured.",
        }
    warning = ""
    if source in {"FLASK_SECRET_KEY", "SECRET_KEY"}:
        warning = "Using application secret fallback. Configure AI_SETTINGS_MASTER_KEY for stable encrypted storage."
    return {"ready": True, "source": source, "warning": warning}


def _get_fernet():
    secret, _ = _get_secret_material()
    if not secret:
        return None
    raw = secret.encode("utf-8")
    try:
        if len(secret) == 44 and secret.endswith("="):
            return Fernet(raw)
    except Exception:
        pass
    derived = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(derived)


def _encrypt_api_key(api_key: str) -> str:
    fernet = _get_fernet()
    if not fernet:
        raise RuntimeError("AI key encryption is unavailable. Configure AI_SETTINGS_MASTER_KEY.")
    return fernet.encrypt(str(api_key or "").encode("utf-8")).decode("utf-8")


def _decrypt_api_key(token: str) -> str:
    value = str(token or "").strip()
    if not value:
        return ""
    fernet = _get_fernet()
    if not fernet:
        return ""
    try:
        return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return ""


def mask_api_key(api_key: str) -> str:
    key = str(api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * max(0, len(key) - 2) + key[-2:]
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


def _safe_provider_row(provider_key: str):
    try:
        return db.session.get(AIProviderConfig, provider_key)
    except (SQLAlchemyError, RuntimeError):
        return None


def _safe_feature_row(feature_key: str):
    try:
        return db.session.get(AIFeatureSetting, feature_key)
    except (SQLAlchemyError, RuntimeError):
        return None


def _env_provider_key(feature_key: str) -> str:
    feature_meta = FEATURE_CATALOG.get(feature_key) or {}
    direct_env = feature_meta.get("provider_env", "")
    if direct_env:
        direct = _normalize_provider_key(os.getenv(direct_env, ""))
        if direct in PROVIDER_CATALOG:
            return direct

    group_env = _ENV_GROUP_PROVIDER.get(feature_meta.get("group", ""), "")
    if group_env:
        grouped = _normalize_provider_key(os.getenv(group_env, ""))
        if grouped in PROVIDER_CATALOG:
            return grouped

    default_provider = _normalize_provider_key(os.getenv("AI_DEFAULT_PROVIDER", ""))
    if default_provider in PROVIDER_CATALOG:
        return default_provider
    return ""


def get_provider_runtime_config(provider_key: str) -> dict:
    provider = _normalize_provider_key(provider_key)
    meta = PROVIDER_CATALOG.get(provider)
    if not meta:
        return {
            "provider_key": provider,
            "available": False,
            "source": "unknown",
            "api_key": "",
            "masked_key": "",
            "model": "",
            "label": provider or "Unknown",
            "configured": False,
        }

    row = _safe_provider_row(provider)
    env_api_key = str(os.getenv(meta["api_key_env"], "") or "").strip()
    env_model = str(os.getenv(meta["model_env"], "") or "").strip()

    if row is not None:
        if not bool(row.is_enabled):
            return {
                "provider_key": provider,
                "label": meta["label"],
                "available": False,
                "configured": bool(row.api_key_encrypted or env_api_key),
                "source": "ui_disabled",
                "api_key": "",
                "masked_key": "",
                "model": str(row.default_model or env_model or meta["default_model"]).strip(),
            }

        decrypted = _decrypt_api_key(row.api_key_encrypted)
        if decrypted:
            return {
                "provider_key": provider,
                "label": meta["label"],
                "available": True,
                "configured": True,
                "source": "ui",
                "api_key": decrypted,
                "masked_key": mask_api_key(decrypted),
                "model": str(row.default_model or env_model or meta["default_model"]).strip(),
            }

        if env_api_key:
            return {
                "provider_key": provider,
                "label": meta["label"],
                "available": True,
                "configured": True,
                "source": "env",
                "api_key": env_api_key,
                "masked_key": mask_api_key(env_api_key),
                "model": str(row.default_model or env_model or meta["default_model"]).strip(),
            }

        return {
            "provider_key": provider,
            "label": meta["label"],
            "available": False,
            "configured": bool(row.default_model),
            "source": "ui_missing_key",
            "api_key": "",
            "masked_key": "",
            "model": str(row.default_model or meta["default_model"]).strip(),
        }

    if env_api_key:
        return {
            "provider_key": provider,
            "label": meta["label"],
            "available": True,
            "configured": True,
            "source": "env",
            "api_key": env_api_key,
            "masked_key": mask_api_key(env_api_key),
            "model": str(env_model or meta["default_model"]).strip(),
        }

    return {
        "provider_key": provider,
        "label": meta["label"],
        "available": False,
        "configured": False,
        "source": "none",
        "api_key": "",
        "masked_key": "",
        "model": str(env_model or meta["default_model"]).strip(),
    }


def list_provider_statuses() -> list[dict]:
    rows = []
    for provider_key, meta in PROVIDER_CATALOG.items():
        runtime = get_provider_runtime_config(provider_key)
        row = _safe_provider_row(provider_key)
        rows.append(
            {
                "provider_key": provider_key,
                "label": meta["label"],
                "default_model": meta["default_model"],
                "runtime_source": runtime["source"],
                "available": runtime["available"],
                "configured": runtime["configured"],
                "masked_key": runtime["masked_key"],
                "effective_model": runtime["model"],
                "is_enabled": bool(row.is_enabled) if row is not None else runtime["available"],
                "stored_model": str(row.default_model or "").strip() if row is not None else "",
                "updated_by": str(row.updated_by or "").strip() if row is not None else "",
                "updated_at": row.updated_at if row is not None else None,
            }
        )
    return rows


def _default_chain_without_row(feature_key: str) -> list[str]:
    explicit = _env_provider_key(feature_key)
    if explicit:
        return [explicit]

    chain = []
    for provider_key in ("gemini", "openai", "claude"):
        runtime = get_provider_runtime_config(provider_key)
        if runtime["available"]:
            chain.append(provider_key)
    return chain or ["gemini"]


def resolve_feature_execution_plan(feature_key: str) -> dict:
    feature = _normalize_feature_key(feature_key)
    meta = FEATURE_CATALOG.get(feature, {})
    row = _safe_feature_row(feature)
    if row is not None and not bool(row.is_enabled):
        return {
            "feature_key": feature,
            "label": meta.get("label", feature),
            "enabled": False,
            "providers": [],
            "model_override": str(row.model_override or "").strip(),
            "fallback_model_override": str(row.fallback_model_override or "").strip(),
        }

    if row is not None:
        raw_chain = [
            _normalize_provider_key(row.primary_provider),
            _normalize_provider_key(row.fallback_provider),
        ]
        if not any(raw_chain):
            raw_chain = _default_chain_without_row(feature)
    else:
        raw_chain = _default_chain_without_row(feature)

    seen = set()
    providers = []
    for idx, provider_key in enumerate(raw_chain):
        if provider_key not in PROVIDER_CATALOG or provider_key in seen:
            continue
        seen.add(provider_key)
        runtime = get_provider_runtime_config(provider_key)
        if not runtime["available"]:
            continue
        override = ""
        if row is not None:
            override = str(row.model_override or "").strip() if idx == 0 else str(row.fallback_model_override or "").strip()
        providers.append(
            {
                **runtime,
                "provider_key": provider_key,
                "model": override or runtime["model"],
            }
        )

    if not providers and raw_chain == ["gemini"]:
        runtime = get_provider_runtime_config("gemini")
        providers.append(
            {
                **runtime,
                "provider_key": "gemini",
                "model": runtime["model"] or PROVIDER_CATALOG["gemini"]["default_model"],
            }
        )

    return {
        "feature_key": feature,
        "label": meta.get("label", feature),
        "enabled": True,
        "providers": providers,
        "model_override": str(row.model_override or "").strip() if row is not None else "",
        "fallback_model_override": str(row.fallback_model_override or "").strip() if row is not None else "",
    }


def list_feature_statuses() -> list[dict]:
    rows = []
    for feature_key, meta in FEATURE_CATALOG.items():
        row = _safe_feature_row(feature_key)
        plan = resolve_feature_execution_plan(feature_key)
        providers = plan.get("providers", [])
        rows.append(
            {
                "feature_key": feature_key,
                "label": meta["label"],
                "group": meta["group"],
                "is_enabled": plan["enabled"],
                "primary_provider": str(row.primary_provider or "").strip() if row is not None else "",
                "fallback_provider": str(row.fallback_provider or "").strip() if row is not None else "",
                "effective_primary": providers[0]["provider_key"] if providers else "",
                "effective_fallback": providers[1]["provider_key"] if len(providers) > 1 else "",
                "model_override": str(row.model_override or "").strip() if row is not None else "",
                "fallback_model_override": str(row.fallback_model_override or "").strip() if row is not None else "",
                "updated_by": str(row.updated_by or "").strip() if row is not None else "",
                "updated_at": row.updated_at if row is not None else None,
            }
        )
    return rows


def upsert_provider_config(
    provider_key: str,
    *,
    api_key: str = "",
    default_model: str = "",
    is_enabled: bool = True,
    clear_api_key: bool = False,
    updated_by: str = "",
):
    provider = _normalize_provider_key(provider_key)
    if provider not in PROVIDER_CATALOG:
        raise ValueError("Unsupported AI provider.")

    row = _safe_provider_row(provider)
    if row is None:
        row = AIProviderConfig(provider_key=provider)

    row.is_enabled = bool(is_enabled)
    row.default_model = str(default_model or "").strip()
    row.updated_by = str(updated_by or "").strip()
    row.updated_at = _utcnow()

    if clear_api_key:
        row.api_key_encrypted = ""
        row.api_key_last4 = ""
    else:
        cleaned_key = str(api_key or "").strip()
        if cleaned_key:
            row.api_key_encrypted = _encrypt_api_key(cleaned_key)
            row.api_key_last4 = cleaned_key[-4:]

    db.session.add(row)
    db.session.commit()
    return row


def upsert_feature_setting(
    feature_key: str,
    *,
    primary_provider: str = "",
    fallback_provider: str = "",
    model_override: str = "",
    fallback_model_override: str = "",
    is_enabled: bool = True,
    updated_by: str = "",
):
    feature = _normalize_feature_key(feature_key)
    if feature not in FEATURE_CATALOG:
        raise ValueError("Unsupported AI feature.")

    primary = _normalize_provider_key(primary_provider)
    fallback = _normalize_provider_key(fallback_provider)
    if primary and primary not in PROVIDER_CATALOG:
        raise ValueError("Unsupported primary AI provider.")
    if fallback and fallback not in PROVIDER_CATALOG:
        raise ValueError("Unsupported fallback AI provider.")
    if primary and fallback and primary == fallback:
        fallback = ""

    row = _safe_feature_row(feature)
    if row is None:
        row = AIFeatureSetting(feature_key=feature)

    row.primary_provider = primary
    row.fallback_provider = fallback
    row.model_override = str(model_override or "").strip()
    row.fallback_model_override = str(fallback_model_override or "").strip()
    row.is_enabled = bool(is_enabled)
    row.updated_by = str(updated_by or "").strip()
    row.updated_at = _utcnow()

    db.session.add(row)
    db.session.commit()
    return row
