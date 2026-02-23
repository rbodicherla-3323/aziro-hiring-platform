import hashlib
import json
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.services.coding_submission_store import STORE_FILE as CODING_SUBMISSIONS_FILE
from app.services.proctoring_summary import (
    blank_proctoring_summary,
    build_proctoring_summary_by_email,
)

PROCTORING_EVENTS_JSONL = Path("app/runtime/proctoring/events.jsonl")
PLAGIARISM_CACHE_FILE = Path("app/runtime/plagiarism_cache.json")

ANALYSIS_VERSION = "v1.0.0"
K_GRAM = 5
PAIR_ALERT_THRESHOLD = 65.0
HIGH_RISK_THRESHOLD = 85.0
MEDIUM_RISK_THRESHOLD = 70.0
MIN_TOKENS_FOR_ANALYSIS = 20
MAX_TOP_MATCHES = 5

_CACHE_LOCK = threading.RLock()
_MEMORY_CACHE = {
    "fingerprint": "",
    "data": None,
}

_LANG_KEYWORDS = {
    "python": {
        "false", "none", "true", "and", "as", "assert", "async", "await", "break",
        "class", "continue", "def", "del", "elif", "else", "except", "finally",
        "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
        "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
    },
    "javascript": {
        "break", "case", "catch", "class", "const", "continue", "debugger", "default",
        "delete", "do", "else", "export", "extends", "finally", "for", "function",
        "if", "import", "in", "instanceof", "let", "new", "return", "super", "switch",
        "this", "throw", "try", "typeof", "var", "void", "while", "with", "yield",
        "true", "false", "null", "undefined", "await", "async",
    },
    "java": {
        "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
        "class", "const", "continue", "default", "do", "double", "else", "enum",
        "extends", "final", "finally", "float", "for", "goto", "if", "implements",
        "import", "instanceof", "int", "interface", "long", "native", "new", "package",
        "private", "protected", "public", "return", "short", "static", "strictfp",
        "super", "switch", "synchronized", "this", "throw", "throws", "transient",
        "try", "void", "volatile", "while", "true", "false", "null",
    },
    "cpp": {
        "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand", "bitor",
        "bool", "break", "case", "catch", "char", "class", "compl", "const",
        "constexpr", "continue", "default", "delete", "do", "double", "else", "enum",
        "explicit", "export", "extern", "false", "float", "for", "friend", "goto",
        "if", "inline", "int", "long", "mutable", "namespace", "new", "noexcept",
        "not", "not_eq", "nullptr", "operator", "or", "or_eq", "private", "protected",
        "public", "register", "reinterpret_cast", "return", "short", "signed",
        "sizeof", "static", "struct", "switch", "template", "this", "throw", "true",
        "try", "typedef", "typeid", "typename", "union", "unsigned", "using", "virtual",
        "void", "volatile", "while", "xor", "xor_eq",
    },
    "c": {
        "auto", "break", "case", "char", "const", "continue", "default", "do", "double",
        "else", "enum", "extern", "float", "for", "goto", "if", "inline", "int", "long",
        "register", "restrict", "return", "short", "signed", "sizeof", "static", "struct",
        "switch", "typedef", "union", "unsigned", "void", "volatile", "while", "_Bool",
        "_Complex", "_Imaginary",
    },
}

_LANG_ALIASES = {
    "js": "javascript",
    "javascript": "javascript",
    "python": "python",
    "java": "java",
    "cpp": "cpp",
    "c++": "cpp",
    "c": "c",
}


def blank_plagiarism_summary():
    return {
        "risk_level": "LOW",
        "risk_score": 0.0,
        "max_similarity": 0.0,
        "matched_submissions": 0,
        "compared_submissions": 0,
        "top_matches": [],
        "analysis_scope": {
            "batch_id": "",
            "role_key": "",
            "round_key": "L4",
            "language": "",
            "question_title": "",
        },
        "behavior_flags": {
            "copy_paste_blocks": 0,
            "keyboard_shortcuts_blocked": 0,
            "tab_switches": 0,
            "suspicion_score": 0,
        },
        "analysis_version": ANALYSIS_VERSION,
        "updated_at": "",
    }


def _normalize_language(language):
    raw = str(language or "").strip().lower()
    if not raw:
        return ""
    return _LANG_ALIASES.get(raw, raw)


def _normalize_text(value):
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _safe_parse_iso(ts_value):
    ts_raw = str(ts_value or "").strip()
    if not ts_raw:
        return 0.0
    try:
        return datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _file_signature(path):
    try:
        stat = path.stat()
        return f"{int(stat.st_mtime_ns)}:{int(stat.st_size)}"
    except OSError:
        return "missing"


def _build_input_fingerprint():
    return "|".join([
        ANALYSIS_VERSION,
        _file_signature(CODING_SUBMISSIONS_FILE),
        _file_signature(PROCTORING_EVENTS_JSONL),
    ])


def _read_jsonl(path):
    if not path.exists():
        return []
    rows = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def _remove_comments(code, language):
    text = str(code or "")
    lang = _normalize_language(language)

    if lang == "python":
        text = re.sub(r"'''[\s\S]*?'''", " ", text)
        text = re.sub(r'"""[\s\S]*?"""', " ", text)
        text = re.sub(r"#.*", " ", text)
        return text

    text = re.sub(r"/\*[\s\S]*?\*/", " ", text)
    text = re.sub(r"//.*", " ", text)
    return text


def _remove_string_literals(code):
    text = str(code or "")
    text = re.sub(r'"(?:\\.|[^"\\])*"', " STR ", text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", " STR ", text)
    text = re.sub(r"`(?:\\.|[^`\\])*`", " STR ", text)
    return text


def _extract_effective_candidate_code(submitted_code, starter_code):
    submitted = str(submitted_code or "")
    starter = str(starter_code or "")
    if not submitted.strip() or not starter.strip():
        return submitted

    starter_lines = Counter(
        line.strip() for line in starter.splitlines() if line.strip()
    )
    effective = []
    for line in submitted.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if starter_lines[stripped] > 0:
            starter_lines[stripped] -= 1
            continue
        effective.append(line)

    if not effective:
        return submitted
    return "\n".join(effective)


def _tokenize(code):
    token_pattern = re.compile(
        r"[A-Za-z_]\w*|\d+\.\d+|\d+|==|!=|<=|>=|\+\+|--|&&|\|\||->|=>|[{}()[\];,.\+\-\*/%<>=!&|^~?:]"
    )
    return token_pattern.findall(code)


def _normalize_tokens(tokens, language):
    lang = _normalize_language(language)
    keywords = _LANG_KEYWORDS.get(lang, set())
    normalized = []
    for token in tokens:
        if re.fullmatch(r"\d+\.\d+|\d+", token):
            normalized.append("NUM")
            continue
        if re.fullmatch(r"[A-Za-z_]\w*", token):
            lowered = token.lower()
            if lowered in keywords:
                normalized.append(lowered)
            elif lowered in {"str"}:
                normalized.append("STR")
            else:
                normalized.append("ID")
            continue
        normalized.append(token)
    return normalized


def _build_fingerprint(tokens):
    if not tokens:
        return set()
    if len(tokens) < K_GRAM:
        digest = hashlib.blake2b(" ".join(tokens).encode("utf-8"), digest_size=8).hexdigest()
        return {digest}
    fp = set()
    for idx in range(len(tokens) - K_GRAM + 1):
        gram = " ".join(tokens[idx: idx + K_GRAM])
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).hexdigest()
        fp.add(digest)
    return fp


def _jaccard_similarity(fp_a, fp_b):
    if not fp_a or not fp_b:
        return 0.0
    inter = len(fp_a.intersection(fp_b))
    union = len(fp_a.union(fp_b))
    if union <= 0:
        return 0.0
    return (inter / union) * 100.0


def _containment_similarity(fp_a, fp_b):
    if not fp_a or not fp_b:
        return 0.0
    inter = len(fp_a.intersection(fp_b))
    smallest = min(len(fp_a), len(fp_b))
    if smallest <= 0:
        return 0.0
    return (inter / smallest) * 100.0


def _pair_similarity(fp_a, fp_b):
    jaccard = _jaccard_similarity(fp_a, fp_b)
    containment = _containment_similarity(fp_a, fp_b)
    return round(max(jaccard, containment * 0.92), 2)


def _risk_level_from_similarity(max_similarity):
    if max_similarity >= HIGH_RISK_THRESHOLD:
        return "HIGH"
    if max_similarity >= MEDIUM_RISK_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def _bump_risk_level(level):
    if level == "LOW":
        return "MEDIUM"
    if level == "MEDIUM":
        return "HIGH"
    return "HIGH"


def _coerce_candidate(candidate):
    if isinstance(candidate, dict):
        return {
            "email": str(candidate.get("email", "")).strip().lower(),
            "batch_id": str(candidate.get("batch_id", "")).strip().lower(),
            "role_key": str(candidate.get("role_key", "")).strip().lower(),
            "role": str(candidate.get("role", "")).strip().lower(),
        }
    email = str(candidate or "").strip().lower()
    return {"email": email, "batch_id": "", "role_key": "", "role": ""}


def _scope_key(submission):
    batch_id = str(submission.get("batch_id", "")).strip().lower()
    role_key = str(submission.get("role_key", "")).strip().lower()
    role = str(submission.get("role", "")).strip().lower()
    round_key = str(submission.get("round_key", "L4")).strip().upper() or "L4"
    language = _normalize_language(submission.get("language", ""))
    question_title = _normalize_text(submission.get("question_title", ""))
    ts_value = submission.get("ts", "")
    ts_date = str(ts_value).split("T")[0] if ts_value else "legacy"
    scoped_batch = batch_id or f"legacy_{ts_date}"
    scoped_role = role_key or role or "unknown_role"
    scoped_question = question_title or "unknown_question"
    return (
        scoped_batch,
        scoped_role,
        round_key,
        language,
        scoped_question,
    )


def _build_submission_records():
    raw_rows = _read_jsonl(CODING_SUBMISSIONS_FILE)
    if not raw_rows:
        return []

    latest_by_key = {}
    for row in raw_rows:
        email = str(row.get("email", "")).strip().lower()
        if not email:
            continue
        round_key = str(row.get("round_key", "L4")).strip().upper() or "L4"
        if round_key != "L4":
            continue

        language = _normalize_language(row.get("language", ""))
        if not language:
            continue

        question_title = str(row.get("question_title", "")).strip()
        ts_epoch = _safe_parse_iso(row.get("ts"))
        key = (
            email,
            str(row.get("batch_id", "")).strip().lower(),
            str(row.get("role_key", "")).strip().lower(),
            str(row.get("role", "")).strip().lower(),
            round_key,
            language,
            _normalize_text(question_title),
        )
        existing = latest_by_key.get(key)
        if not existing or ts_epoch >= existing["ts_epoch"]:
            clean_row = dict(row)
            clean_row["email"] = email
            clean_row["round_key"] = round_key
            clean_row["language"] = language
            clean_row["question_title"] = question_title
            clean_row["role_key"] = str(row.get("role_key", "")).strip().lower()
            clean_row["role"] = str(row.get("role", "")).strip()
            clean_row["batch_id"] = str(row.get("batch_id", "")).strip()
            clean_row["ts_epoch"] = ts_epoch
            latest_by_key[key] = clean_row

    prepared = []
    for row in latest_by_key.values():
        effective_code = _extract_effective_candidate_code(
            row.get("submitted_code", ""),
            row.get("starter_code", ""),
        )
        code_wo_comments = _remove_comments(effective_code, row.get("language"))
        code_wo_strings = _remove_string_literals(code_wo_comments)
        tokens = _normalize_tokens(_tokenize(code_wo_strings), row.get("language"))
        token_count = len(tokens)
        if token_count < MIN_TOKENS_FOR_ANALYSIS:
            fingerprint = set()
        else:
            fingerprint = _build_fingerprint(tokens)

        prepared.append({
            "email": row.get("email", ""),
            "batch_id": str(row.get("batch_id", "")).strip(),
            "role_key": str(row.get("role_key", "")).strip().lower(),
            "role": str(row.get("role", "")).strip(),
            "round_key": row.get("round_key", "L4"),
            "language": row.get("language", ""),
            "question_title": row.get("question_title", ""),
            "ts": row.get("ts", ""),
            "ts_epoch": row.get("ts_epoch", 0.0),
            "token_count": token_count,
            "fingerprint": fingerprint,
            "scope": _scope_key(row),
        })
    return prepared


def _push_top_match(bucket, match):
    bucket.append(match)
    bucket.sort(key=lambda item: item["similarity"], reverse=True)
    del bucket[MAX_TOP_MATCHES:]


def _compose_candidate_summary(candidate_entry, candidates_in_scope, by_email_proctoring):
    summary = blank_plagiarism_summary()
    email = candidate_entry.get("email", "")
    stats = candidate_entry.get("stats", {})

    proctoring = by_email_proctoring.get(email, blank_proctoring_summary())
    copy_paste_blocks = int(proctoring.get("copy_paste_blocks", 0) or 0)
    keyboard_shortcuts = int(proctoring.get("keyboard_shortcuts_blocked", 0) or 0)
    tab_switches = int(proctoring.get("tab_switches", 0) or 0)
    suspicion_score = int(proctoring.get("suspicion_score", 0) or 0)

    max_similarity = float(stats.get("max_similarity", 0.0) or 0.0)
    risk_level = _risk_level_from_similarity(max_similarity)
    behavior_boost = 0.0
    if copy_paste_blocks >= 2:
        behavior_boost += 8.0
        risk_level = _bump_risk_level(risk_level)
    if keyboard_shortcuts >= 3:
        behavior_boost += 5.0
    if tab_switches >= 5:
        behavior_boost += 4.0
    if suspicion_score >= 60:
        behavior_boost += 5.0

    risk_score = min(100.0, round(max_similarity + behavior_boost, 2))
    matched_submissions = int(stats.get("matched_submissions", 0) or 0)
    compared_submissions = max(0, int(candidates_in_scope) - 1)

    summary.update({
        "risk_level": risk_level,
        "risk_score": risk_score,
        "max_similarity": round(max_similarity, 2),
        "matched_submissions": matched_submissions,
        "compared_submissions": compared_submissions,
        "top_matches": stats.get("top_matches", []),
        "analysis_scope": {
            "batch_id": candidate_entry.get("scope", ("", "", "", "", ""))[0],
            "role_key": candidate_entry.get("scope", ("", "", "", "", ""))[1],
            "round_key": candidate_entry.get("scope", ("", "", "L4", "", ""))[2],
            "language": candidate_entry.get("scope", ("", "", "", "", ""))[3],
            "question_title": candidate_entry.get("question_title", ""),
        },
        "behavior_flags": {
            "copy_paste_blocks": copy_paste_blocks,
            "keyboard_shortcuts_blocked": keyboard_shortcuts,
            "tab_switches": tab_switches,
            "suspicion_score": suspicion_score,
        },
        "analysis_version": ANALYSIS_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return summary


def _compute_plagiarism_index():
    submissions = _build_submission_records()
    if not submissions:
        return {"by_email": {}}

    all_scoped_emails = {sub.get("email", "") for sub in submissions if sub.get("email")}
    by_email_proctoring = build_proctoring_summary_by_email(all_scoped_emails)

    by_scope = defaultdict(list)
    for sub in submissions:
        by_scope[sub["scope"]].append(sub)

    per_candidate = []
    for scope, scoped_submissions in by_scope.items():
        scoped_submissions.sort(key=lambda item: item["email"])
        scoped_count = len(scoped_submissions)
        if scoped_count <= 0:
            continue

        stats_by_idx = []
        for _ in scoped_submissions:
            stats_by_idx.append({
                "max_similarity": 0.0,
                "matched_submissions": 0,
                "top_matches": [],
            })

        for i in range(scoped_count):
            fp_i = scoped_submissions[i]["fingerprint"]
            if not fp_i:
                continue
            for j in range(i + 1, scoped_count):
                fp_j = scoped_submissions[j]["fingerprint"]
                if not fp_j:
                    continue
                similarity = _pair_similarity(fp_i, fp_j)

                if similarity > stats_by_idx[i]["max_similarity"]:
                    stats_by_idx[i]["max_similarity"] = similarity
                if similarity > stats_by_idx[j]["max_similarity"]:
                    stats_by_idx[j]["max_similarity"] = similarity

                if similarity >= PAIR_ALERT_THRESHOLD:
                    stats_by_idx[i]["matched_submissions"] += 1
                    stats_by_idx[j]["matched_submissions"] += 1

                match_i = {
                    "email": scoped_submissions[j]["email"],
                    "similarity": round(similarity, 2),
                    "batch_id": scoped_submissions[j]["batch_id"],
                    "role_key": scoped_submissions[j]["role_key"] or _normalize_text(scoped_submissions[j]["role"]),
                    "language": scoped_submissions[j]["language"],
                }
                match_j = {
                    "email": scoped_submissions[i]["email"],
                    "similarity": round(similarity, 2),
                    "batch_id": scoped_submissions[i]["batch_id"],
                    "role_key": scoped_submissions[i]["role_key"] or _normalize_text(scoped_submissions[i]["role"]),
                    "language": scoped_submissions[i]["language"],
                }
                _push_top_match(stats_by_idx[i]["top_matches"], match_i)
                _push_top_match(stats_by_idx[j]["top_matches"], match_j)

        for idx, sub in enumerate(scoped_submissions):
            entry = dict(sub)
            entry["stats"] = stats_by_idx[idx]
            per_candidate.append(
                _compose_candidate_summary(
                    candidate_entry=entry,
                    candidates_in_scope=scoped_count,
                    by_email_proctoring=by_email_proctoring,
                )
                | {
                    "email": sub.get("email", ""),
                    "scope": scope,
                    "ts_epoch": sub.get("ts_epoch", 0.0),
                }
            )

    by_email = defaultdict(list)
    for item in per_candidate:
        email = item.get("email", "")
        if not email:
            continue
        by_email[email].append(item)

    for email in list(by_email.keys()):
        by_email[email].sort(
            key=lambda item: (
                float(item.get("max_similarity", 0.0)),
                float(item.get("risk_score", 0.0)),
                float(item.get("ts_epoch", 0.0)),
            ),
            reverse=True,
        )

    return {"by_email": dict(by_email)}


def _load_cached_index():
    if not PLAGIARISM_CACHE_FILE.exists():
        return None
    try:
        with PLAGIARISM_CACHE_FILE.open("r", encoding="utf-8") as handle:
            cached = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(cached, dict):
        return None
    return cached


def _persist_cached_index(fingerprint, index):
    payload = {
        "fingerprint": fingerprint,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "index": index,
    }
    PLAGIARISM_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = PLAGIARISM_CACHE_FILE.with_suffix(".tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        temp_path.replace(PLAGIARISM_CACHE_FILE)
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _get_index(force_refresh=False):
    fingerprint = _build_input_fingerprint()
    with _CACHE_LOCK:
        if (
            not force_refresh
            and _MEMORY_CACHE.get("fingerprint") == fingerprint
            and isinstance(_MEMORY_CACHE.get("data"), dict)
        ):
            return _MEMORY_CACHE["data"]

        if not force_refresh:
            cached = _load_cached_index()
            if cached and cached.get("fingerprint") == fingerprint:
                index = cached.get("index", {"by_email": {}})
                _MEMORY_CACHE["fingerprint"] = fingerprint
                _MEMORY_CACHE["data"] = index
                return index

        index = _compute_plagiarism_index()
        _persist_cached_index(fingerprint, index)
        _MEMORY_CACHE["fingerprint"] = fingerprint
        _MEMORY_CACHE["data"] = index
        return index


def _pick_best_entry_for_candidate(entries, candidate):
    if not entries:
        return None
    desired_batch = str(candidate.get("batch_id", "")).strip().lower()
    desired_role = (
        str(candidate.get("role_key", "")).strip().lower()
        or str(candidate.get("role", "")).strip().lower()
    )

    best = entries[0]
    best_score = -1
    for entry in entries:
        scope = entry.get("analysis_scope", {}) or {}
        scope_batch = str(scope.get("batch_id", "")).strip().lower()
        scope_role = str(scope.get("role_key", "")).strip().lower()
        score = 0
        if desired_batch and desired_batch == scope_batch:
            score += 2
        if desired_role and desired_role == scope_role:
            score += 1
        score += float(entry.get("risk_score", 0.0)) / 1000.0
        if score > best_score:
            best = entry
            best_score = score
    return best


def build_plagiarism_summary_by_candidates(candidates, force_refresh=False):
    prepared_candidates = [_coerce_candidate(candidate) for candidate in (candidates or [])]
    prepared_candidates = [candidate for candidate in prepared_candidates if candidate.get("email")]
    if not prepared_candidates:
        return {}

    index = _get_index(force_refresh=force_refresh)
    by_email = index.get("by_email", {}) if isinstance(index, dict) else {}
    output = {}

    for candidate in prepared_candidates:
        email = candidate["email"]
        entries = by_email.get(email, [])
        if not entries:
            output[email] = blank_plagiarism_summary()
            continue
        selected = _pick_best_entry_for_candidate(entries, candidate)
        if not selected:
            output[email] = blank_plagiarism_summary()
            continue

        cleaned = dict(selected)
        cleaned.pop("email", None)
        cleaned.pop("scope", None)
        cleaned.pop("ts_epoch", None)
        output[email] = cleaned

    return output
