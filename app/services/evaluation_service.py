from app.services.evaluation_store import EVALUATION_STORE
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services.coding_submission_store import get_latest_coding_submission
from app.services.mcq_submission_store import (
    get_latest_mcq_submission,
    save_mcq_submission,
)
from app.services.candidate_scope import matches_candidate_scope
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.ai_generator import (
    generate_evaluation_summary,
    generate_coding_round_summary,
    generate_consolidated_evaluation_summary,
)
from app.services.mcq_runtime_store import get_mcq_session_data, mcq_session_key
from app.utils.role_round_mapping import ROLE_ROUND_MAPPING
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING
from app.utils.round_order import (
    INTERNAL_ROUND_ORDER,
    ordered_present_round_keys,
    round_number_map,
    round_sort_key,
)
from flask import session
import logging
import re
import time
from datetime import datetime

log = logging.getLogger(__name__)


# ---------------------------------------------------------------
# Per-round pass percentage thresholds
# ---------------------------------------------------------------
# Aptitude (L1)       -> 60%  (general reasoning, slightly lenient)
# Technical Theory    -> 70%  (core knowledge, standard bar)
# Technical Practical -> 70%  (applied knowledge, standard bar)
# Soft Skills (L5)    -> 50%  (subjective, more lenient)
# Domain (L6)         -> 65%  (specialized but not core)
# ---------------------------------------------------------------
ROUND_PASS_PERCENTAGE = {
    "L1": 60,   # Aptitude - logical/quantitative reasoning
    "L2": 70,   # Technical Theory
    "L3": 70,   # Technical Fundamentals / Practical
    "L3A": 70,  # Technical Fundamentals / Practical
    "L5": 50,   # Soft Skills - subjective, keep lenient
    "L6": 65,   # Domain-specific knowledge
}

DEFAULT_PASS_PERCENTAGE = 70
SUMMARY_ROUNDS = INTERNAL_ROUND_ORDER


class EvaluationService:

    @staticmethod
    def get_pass_threshold(round_key: str) -> int:
        """Return the pass percentage for a given round."""
        return ROUND_PASS_PERCENTAGE.get(round_key, DEFAULT_PASS_PERCENTAGE)

    @staticmethod
    def _is_attempted_status(status: str) -> bool:
        return status not in ("Pending", "Not Attempted")

    @staticmethod
    def _build_mcq_submission_details(questions: list, answers: dict) -> list:
        """Build per-question response details for MCQ rounds."""
        details = []
        for idx, q in enumerate(questions or []):
            selected_value = answers.get(str(idx))
            correct_value = q.get("correct_answer")
            is_answered = selected_value is not None and str(selected_value).strip() != ""
            details.append({
                "question_no": idx + 1,
                "question": q.get("question", ""),
                "topic": q.get("topic", ""),
                "tags": list(q.get("tags", [])) if isinstance(q.get("tags"), list) else [],
                "options": list(q.get("options", [])) if isinstance(q.get("options"), list) else [],
                "selected_answer": selected_value if is_answered else "",
                "correct_answer": correct_value,
                "is_answered": is_answered,
                "is_correct": is_answered and selected_value == correct_value,
            })
        return details

    @staticmethod
    def _round_sort_key(round_key: str) -> tuple[int, str]:
        sort_parts = round_sort_key(round_key)
        return sort_parts[1], sort_parts[2]

    @staticmethod
    def _created_at_sort_value(value) -> float:
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except Exception:
                return 0.0
        return 0.0

    @staticmethod
    def _normalize_email(value: str) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _normalize_text(value: str) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _truncate_text(value: str, limit: int = 120) -> str:
        text = EvaluationService._normalize_text(value)
        if len(text) <= limit:
            return text
        trimmed = text[: max(0, limit - 3)].rstrip()
        if " " in trimmed:
            trimmed = trimmed.rsplit(" ", 1)[0]
        return f"{trimmed}..."

    @staticmethod
    def _merge_submission_details(primary, fallback) -> dict:
        merged = dict(primary) if isinstance(primary, dict) else {}
        fallback = fallback if isinstance(fallback, dict) else {}
        for key, value in fallback.items():
            if key == "responses":
                if isinstance(value, list) and not merged.get("responses"):
                    merged["responses"] = value
                continue

            existing = merged.get(key)
            if isinstance(value, dict):
                if value and not isinstance(existing, dict):
                    merged[key] = dict(value)
                elif value and isinstance(existing, dict) and not existing:
                    merged[key] = dict(value)
                continue

            if isinstance(value, list):
                if value and not existing:
                    merged[key] = list(value)
                continue

            if value not in (None, "") and not str(existing or "").strip():
                merged[key] = value
        return merged

    @staticmethod
    def _get_test_link_meta(session_id: str) -> dict:
        session_id = str(session_id or "").strip()
        if not session_id:
            return {}

        registry_meta = MCQ_SESSION_REGISTRY.get(session_id) or CODING_SESSION_REGISTRY.get(session_id)
        if isinstance(registry_meta, dict):
            return registry_meta

        try:
            from app.services import db_service
            meta = db_service.get_test_link_meta(session_id)
            return meta if isinstance(meta, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _get_latest_live_round_result(candidate_data: dict, round_key: str) -> dict | None:
        email_key = EvaluationService._normalize_email((candidate_data or {}).get("email", ""))
        if not email_key or not round_key:
            return None

        target_batch = str((candidate_data or {}).get("batch_id", "") or "").strip()
        target_role_key = str((candidate_data or {}).get("role_key", "") or "").strip()
        target_role = EvaluationService._normalize_text((candidate_data or {}).get("role", "") or "")

        fallback_match = None
        for session_id, result in reversed(list(EVALUATION_STORE.items())):
            if EvaluationService._normalize_email(result.get("email", "")) != email_key:
                continue
            if str(result.get("round_key", "") or "").strip() != round_key:
                continue

            if fallback_match is None:
                fallback_match = result

            meta = EvaluationService._get_test_link_meta(session_id)
            meta_batch = str(meta.get("batch_id", "") or "").strip()
            meta_role_key = str(meta.get("role_key", "") or "").strip()
            meta_role = EvaluationService._normalize_text(meta.get("role_label", "") or meta.get("role", "") or "")

            if target_batch and meta_batch and target_batch != meta_batch:
                continue
            if target_role_key and meta_role_key and target_role_key != meta_role_key:
                continue
            if target_role and meta_role and target_role != meta_role:
                continue
            return result

        return fallback_match

    @staticmethod
    def _resolve_round_submission_details(candidate_data: dict, round_key: str, round_data: dict) -> dict:
        base_details = {}
        session_id_hint = ""
        if isinstance(round_data, dict):
            raw_details = round_data.get("submission_details")
            if isinstance(raw_details, dict):
                base_details = dict(raw_details)
            session_id_hint = str(round_data.get("session_uuid", "") or "").strip()

        live_result = EvaluationService._get_latest_live_round_result(candidate_data, round_key)
        if isinstance(live_result, dict):
            base_details = EvaluationService._merge_submission_details(
                base_details,
                live_result.get("submission_details") or {},
            )

        if round_key != "L4":
            latest_submission = get_latest_mcq_submission(
                candidate_data.get("email", ""),
                round_key,
                role_key=str((candidate_data or {}).get("role_key", "") or "").strip(),
                batch_id=str((candidate_data or {}).get("batch_id", "") or "").strip(),
                session_id=session_id_hint,
            ) or {}
            latest_responses = latest_submission.get("responses", [])
            if isinstance(latest_responses, list) and latest_responses:
                # Always prefer the most recently persisted MCQ submission answers.
                base_details["responses"] = list(latest_responses)

            if not isinstance(base_details.get("responses"), list) or not base_details.get("responses"):
                mcq_runtime_data = get_mcq_session_data(session_id_hint) if session_id_hint else None
                if isinstance(mcq_runtime_data, dict):
                    runtime_questions = mcq_runtime_data.get("questions")
                    runtime_answers = mcq_runtime_data.get("answers")
                    if isinstance(runtime_questions, list) and isinstance(runtime_answers, dict):
                        base_details["responses"] = EvaluationService._build_mcq_submission_details(
                            runtime_questions,
                            runtime_answers,
                        )

        if round_key == "L4":
            latest_submission = get_latest_coding_submission(
                candidate_data.get("email", ""),
                round_key,
                role_key=str((candidate_data or {}).get("role_key", "") or "").strip(),
                batch_id=str((candidate_data or {}).get("batch_id", "") or "").strip(),
            ) or {}
            latest_summary = {
                "question_title": latest_submission.get("question_title", ""),
                "question_text": latest_submission.get("question_text", ""),
                "language": latest_submission.get("language", ""),
                "public_tests": latest_submission.get("public_tests", []) or [],
                "hidden_tests": latest_submission.get("hidden_tests", []) or [],
                "public_test_results": latest_submission.get("public_test_results", []) or [],
                "hidden_test_results": latest_submission.get("hidden_test_results", []) or [],
            }
            base_details = EvaluationService._merge_submission_details(base_details, latest_summary)

        return base_details

    @staticmethod
    def _live_result_matches_candidate(candidate_data: dict, result: dict, session_id: str = "") -> bool:
        if not isinstance(candidate_data, dict) or not isinstance(result, dict):
            return False

        candidate_email = EvaluationService._normalize_email(candidate_data.get("email", ""))
        if not candidate_email:
            return False
        if EvaluationService._normalize_email(result.get("email", "")) != candidate_email:
            return False

        link_meta = EvaluationService._get_test_link_meta(session_id) if session_id else {}
        scope_payload = {
            "email": result.get("email", "") or link_meta.get("email", ""),
            "role_key": result.get("role_key", "") or link_meta.get("role_key", ""),
            "role_label": result.get("role_label", "") or link_meta.get("role_label", ""),
            "role": result.get("role", "") or result.get("role_label", "") or link_meta.get("role_label", ""),
            "batch_id": result.get("batch_id", "") or link_meta.get("batch_id", ""),
        }
        return matches_candidate_scope(
            scope_payload,
            candidate_key=str((candidate_data or {}).get("candidate_key", "")).strip(),
            email=candidate_email,
            role_key=str((candidate_data or {}).get("role_key", "")).strip(),
            role_label=str((candidate_data or {}).get("role", "")).strip(),
            batch_id=str((candidate_data or {}).get("batch_id", "")).strip(),
        )

    @staticmethod
    def _gap_signal_label(response: dict) -> tuple[str, str, list[str]]:
        topic = EvaluationService._truncate_text(response.get("topic", ""), 80)
        tags = response.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        clean_tags = [
            EvaluationService._truncate_text(tag, 40)
            for tag in tags
            if EvaluationService._normalize_text(tag)
        ][:3]
        question_text = EvaluationService._truncate_text(
            response.get("question") or response.get("question_text") or "",
            120,
        )

        if topic:
            return topic, "topic", clean_tags
        if clean_tags:
            return clean_tags[0], "tag", clean_tags
        return question_text, "question", clean_tags

    @staticmethod
    def _resolve_generated_test_entry(candidate_data: dict) -> dict | None:
        email = str((candidate_data or {}).get("email", "")).strip().lower()
        if not email:
            return None

        candidates = [
            entry for entry in GENERATED_TESTS
            if str(entry.get("email", "")).strip().lower() == email
        ]
        if not candidates:
            return None

        batch_id = str((candidate_data or {}).get("batch_id", "")).strip()
        role_key = str((candidate_data or {}).get("role_key", "")).strip()

        if batch_id:
            exact_batch = [entry for entry in candidates if str(entry.get("batch_id", "")).strip() == batch_id]
            if exact_batch:
                return max(exact_batch, key=lambda e: EvaluationService._created_at_sort_value(e.get("created_at")))

        if role_key:
            exact_role = [entry for entry in candidates if str(entry.get("role_key", "")).strip() == role_key]
            if exact_role:
                return max(exact_role, key=lambda e: EvaluationService._created_at_sort_value(e.get("created_at")))

        return max(candidates, key=lambda e: EvaluationService._created_at_sort_value(e.get("created_at")))

    @staticmethod
    def _resolve_round_blueprint(candidate_data: dict) -> tuple[list[str], dict, dict]:
        """Resolve canonical round order/labels from generated tests, then role config, then existing rounds."""
        ordered_keys = []
        round_labels = {}
        round_totals = {}
        rounds = (candidate_data or {}).get("rounds", {}) or {}

        generated = EvaluationService._resolve_generated_test_entry(candidate_data)
        if generated:
            tests = generated.get("tests", {}) or {}
            for rk in INTERNAL_ROUND_ORDER:
                if rk not in tests:
                    continue
                ordered_keys.append(rk)
                test_info = tests.get(rk, {}) or {}
                round_labels[rk] = str(test_info.get("label") or rk)
                round_totals[rk] = 1 if str(test_info.get("type", "")).lower() == "coding" else 15

        role_key = str((candidate_data or {}).get("role_key", "")).strip()
        if not ordered_keys and role_key:
            role_cfg = ROLE_ROUND_MAPPING.get(role_key, {}) or {}
            display_map = ROUND_DISPLAY_MAPPING.get(role_key, {}) or {}

            for rk in list(role_cfg.get("rounds", [])) + list(role_cfg.get("coding_rounds", [])):
                if rk in ordered_keys:
                    continue
                ordered_keys.append(rk)
                round_labels[rk] = str(display_map.get(rk) or rk)
                round_totals[rk] = 1 if rk in role_cfg.get("coding_rounds", []) else 15

        for rk in ordered_present_round_keys(rounds):
            if rk in ordered_keys:
                continue
            ordered_keys.append(rk)
            existing = rounds.get(rk, {}) or {}
            round_labels[rk] = str(existing.get("round_label") or rk)
            round_totals[rk] = 1 if rk == "L4" else 15

        return ordered_keys, round_labels, round_totals

    @staticmethod
    def _prepare_l1_l4_summary_payload(candidate_data: dict) -> dict | None:
        """Build summary payload using role-accurate round labels and ordering."""
        if not candidate_data:
            return None

        rounds = candidate_data.get("rounds", {}) or {}
        ordered_rounds, round_labels, round_totals = EvaluationService._resolve_round_blueprint(candidate_data)
        if not ordered_rounds:
            ordered_rounds = ordered_present_round_keys(rounds)

        numbers = round_number_map(ordered_rounds)

        rounds_l1_l4 = {}
        for rk in ordered_rounds:
            existing = rounds.get(rk) or {}
            default_total = round_totals.get(rk, 1 if rk == "L4" else 15)

            rounds_l1_l4[rk] = {
                "round_label": existing.get("round_label") or round_labels.get(rk) or rk,
                "correct": existing.get("correct", 0),
                "total": existing.get("total", default_total),
                "attempted": existing.get("attempted", 0),
                "percentage": existing.get("percentage", 0),
                "pass_threshold": existing.get("pass_threshold", EvaluationService.get_pass_threshold(rk)),
                "status": existing.get("status", "Not Attempted"),
                "time_taken_seconds": existing.get("time_taken_seconds", 0),
                "session_uuid": existing.get("session_uuid", ""),
                "submission_details": existing.get("submission_details", {}),
                "round_number": numbers.get(rk, 0),
            }

        attempted_only = [
            r for r in rounds_l1_l4.values()
            if EvaluationService._is_attempted_status(r.get("status", "Not Attempted"))
        ]
        attempted_rounds = len(attempted_only)
        passed_rounds = sum(1 for r in attempted_only if r.get("status") == "PASS")
        failed_rounds = sum(1 for r in attempted_only if r.get("status") == "FAIL")
        attempted_percentages = [r.get("percentage", 0) for r in attempted_only]
        overall_percentage = round(sum(attempted_percentages) / attempted_rounds, 2) if attempted_rounds else 0

        if attempted_rounds == 0:
            overall_verdict = "Pending"
        elif failed_rounds > 0:
            overall_verdict = "Rejected"
        elif attempted_rounds < len(rounds_l1_l4):
            overall_verdict = "In Progress"
        else:
            overall_verdict = "Selected"

        return {
            "name": candidate_data.get("name", ""),
            "email": candidate_data.get("email", ""),
            "role": candidate_data.get("role", ""),
            "batch_id": candidate_data.get("batch_id", ""),
            "role_key": candidate_data.get("role_key", ""),
            "test_session_id": candidate_data.get("test_session_id"),
            "rounds": rounds_l1_l4,
            "summary": {
                "total_rounds": len(rounds_l1_l4),
                "attempted_rounds": attempted_rounds,
                "passed_rounds": passed_rounds,
                "failed_rounds": failed_rounds,
                "total_correct": sum(r.get("correct", 0) for r in attempted_only),
                "total_questions": sum(r.get("total", 0) for r in attempted_only),
                "overall_percentage": overall_percentage,
                "overall_verdict": overall_verdict,
            },
        }

    @staticmethod
    def _prepare_consolidated_summary_payload(candidates_data: list[dict], scope: dict | None = None) -> dict | None:
        """Build a compact multi-candidate payload for consolidated AI reporting."""
        if not isinstance(candidates_data, list):
            return None

        normalized_candidates = []
        round_stats_map = {}
        gap_signals_map = {}
        coding_signals_map = {}
        verdict_counts = {
            "Selected": 0,
            "Rejected": 0,
            "In Progress": 0,
            "Pending": 0,
        }
        score_total = 0.0
        score_count = 0
        attempted_candidate_count = 0
        batch_ids = set()
        role_labels = set()
        not_started_candidate_count = 0
        partially_completed_candidate_count = 0
        fully_completed_candidate_count = 0
        multiple_failed_round_candidates = 0
        total_round_slots = 0

        for candidate_data in candidates_data:
            prepared = EvaluationService._prepare_l1_l4_summary_payload(candidate_data)
            if not prepared:
                continue

            summary = prepared.get("summary", {}) or {}
            verdict = str(summary.get("overall_verdict", "Pending") or "Pending")
            verdict_counts.setdefault(verdict, 0)
            verdict_counts[verdict] += 1

            overall_percentage = float(summary.get("overall_percentage", 0) or 0)
            attempted_rounds = int(summary.get("attempted_rounds", 0) or 0)
            total_rounds = int(summary.get("total_rounds", 0) or len(prepared.get("rounds") or {}))
            failed_rounds = int(summary.get("failed_rounds", 0) or 0)
            email_key = EvaluationService._normalize_email(prepared.get("email", ""))

            if attempted_rounds > 0:
                attempted_candidate_count += 1
                score_total += overall_percentage
                score_count += 1
            if attempted_rounds == 0:
                not_started_candidate_count += 1
            elif attempted_rounds < total_rounds:
                partially_completed_candidate_count += 1
            else:
                fully_completed_candidate_count += 1
            if failed_rounds >= 2:
                multiple_failed_round_candidates += 1
            total_round_slots += total_rounds

            batch_id = str(prepared.get("batch_id", "") or "").strip()
            if batch_id:
                batch_ids.add(batch_id)

            role_label = str(prepared.get("role", "") or "").strip()
            if role_label:
                role_labels.add(role_label)

            rounds_payload = []
            for round_key, round_data in (prepared.get("rounds") or {}).items():
                round_label = str(round_data.get("round_label", "") or round_key).strip() or round_key
                round_number = int(round_data.get("round_number", 0) or 0)
                status = str(round_data.get("status", "Pending") or "Pending")
                percentage = float(round_data.get("percentage", 0) or 0)
                threshold = float(round_data.get("pass_threshold", 0) or 0)
                attempted = EvaluationService._is_attempted_status(status)

                stat = round_stats_map.setdefault(
                    round_label,
                    {
                        "round_key": round_key,
                        "round_label": round_label,
                        "round_number": round_number,
                        "candidate_count": 0,
                        "attempted_candidates": 0,
                        "passed_candidates": 0,
                        "failed_candidates": 0,
                        "pending_candidates": 0,
                        "below_threshold_candidates": 0,
                        "percentage_total": 0.0,
                        "detail_candidates": 0,
                        "incorrect_response_count": 0,
                        "unanswered_question_count": 0,
                        "coding_detail_candidates": 0,
                    },
                )
                stat["candidate_count"] += 1
                if attempted:
                    stat["attempted_candidates"] += 1
                    stat["percentage_total"] += percentage
                    if status.upper() == "PASS":
                        stat["passed_candidates"] += 1
                    elif status.upper() == "FAIL":
                        stat["failed_candidates"] += 1
                    if threshold and percentage < threshold:
                        stat["below_threshold_candidates"] += 1
                else:
                    stat["pending_candidates"] += 1

                submission_details = EvaluationService._resolve_round_submission_details(prepared, round_key, round_data)
                responses = submission_details.get("responses", []) if isinstance(submission_details, dict) else []
                incorrect_response_count = 0
                unanswered_question_count = 0

                if isinstance(responses, list) and responses:
                    stat["detail_candidates"] += 1
                    response_rows = [response for response in responses if isinstance(response, dict)]
                    has_explicit_answer_state = any("is_answered" in response for response in response_rows)
                    answered_responses = []
                    for response in response_rows:
                        if "is_answered" in response:
                            if bool(response.get("is_answered")):
                                answered_responses.append(response)
                            continue
                        if "selected_answer" in response:
                            selected_answer = response.get("selected_answer")
                            if selected_answer is not None and str(selected_answer).strip() != "":
                                answered_responses.append(response)
                            continue
                        # Legacy payloads may only carry is_correct/question fields.
                        if "is_correct" in response or "question" in response:
                            answered_responses.append(response)

                    for response in answered_responses:
                        if bool(response.get("is_correct")):
                            continue

                        incorrect_response_count += 1
                        signal_label, evidence_type, clean_tags = EvaluationService._gap_signal_label(response)
                        if not signal_label:
                            continue

                        signal_key = (
                            round_label.lower(),
                            evidence_type,
                            signal_label.lower(),
                        )
                        signal_entry = gap_signals_map.setdefault(
                            signal_key,
                            {
                                "round_key": round_key,
                                "round_label": round_label,
                                "signal_label": signal_label,
                                "evidence_type": evidence_type,
                                "occurrences": 0,
                                "candidate_emails": set(),
                                "evidence_examples": [],
                                "related_tags": {},
                            },
                        )
                        signal_entry["occurrences"] += 1
                        if email_key:
                            signal_entry["candidate_emails"].add(email_key)

                        question_excerpt = EvaluationService._truncate_text(
                            response.get("question") or response.get("question_text") or signal_label,
                            120,
                        )
                        if question_excerpt and question_excerpt not in signal_entry["evidence_examples"]:
                            if len(signal_entry["evidence_examples"]) < 2:
                                signal_entry["evidence_examples"].append(question_excerpt)

                        for tag in clean_tags:
                            tag_key = tag.lower()
                            signal_entry["related_tags"][tag_key] = signal_entry["related_tags"].get(tag_key, 0) + 1

                    total_questions = int(round_data.get("total", 0) or 0)
                    if has_explicit_answer_state:
                        unanswered_question_count = sum(
                            1 for response in response_rows if not bool(response.get("is_answered"))
                        )
                    else:
                        unanswered_question_count = max(0, total_questions - len(response_rows)) if total_questions else 0
                    stat["incorrect_response_count"] += incorrect_response_count
                    stat["unanswered_question_count"] += unanswered_question_count

                    if unanswered_question_count > 0:
                        completion_key = (round_label.lower(), "completion", "question completion / unanswered items")
                        completion_signal = gap_signals_map.setdefault(
                            completion_key,
                            {
                                "round_key": round_key,
                                "round_label": round_label,
                                "signal_label": "Question completion / unanswered items",
                                "evidence_type": "completion",
                                "occurrences": 0,
                                "candidate_emails": set(),
                                "evidence_examples": ["Some questions were left unanswered in this round."],
                                "related_tags": {},
                            },
                        )
                        completion_signal["occurrences"] += unanswered_question_count
                        if email_key:
                            completion_signal["candidate_emails"].add(email_key)

                question_title = EvaluationService._truncate_text(
                    submission_details.get("question_title", "") if isinstance(submission_details, dict) else "",
                    96,
                )
                question_text = EvaluationService._truncate_text(
                    submission_details.get("question_text", "") if isinstance(submission_details, dict) else "",
                    140,
                )
                language = EvaluationService._normalize_text(
                    submission_details.get("language", "") if isinstance(submission_details, dict) else ""
                ).lower()

                if round_key == "L4" and (question_title or question_text or language):
                    stat["coding_detail_candidates"] += 1
                    signal_title = question_title or question_text or round_label
                    coding_key = (round_label.lower(), signal_title.lower())
                    coding_signal = coding_signals_map.setdefault(
                        coding_key,
                        {
                            "round_key": round_key,
                            "round_label": round_label,
                            "question_title": signal_title,
                            "prompt_excerpt": question_text,
                            "candidate_emails": set(),
                            "attempted_candidates": set(),
                            "failed_candidates": set(),
                            "passed_candidates": set(),
                            "languages": {},
                            "percentage_total": 0.0,
                            "percentage_count": 0,
                        },
                    )
                    if email_key:
                        coding_signal["candidate_emails"].add(email_key)
                    if attempted:
                        if email_key:
                            coding_signal["attempted_candidates"].add(email_key)
                        coding_signal["percentage_total"] += percentage
                        coding_signal["percentage_count"] += 1
                    if status.upper() == "FAIL" and email_key:
                        coding_signal["failed_candidates"].add(email_key)
                    elif status.upper() == "PASS" and email_key:
                        coding_signal["passed_candidates"].add(email_key)
                    if language:
                        coding_signal["languages"][language] = coding_signal["languages"].get(language, 0) + 1

                rounds_payload.append({
                    "round_key": round_key,
                    "round_label": round_label,
                    "round_number": round_number,
                    "status": status,
                    "percentage": percentage,
                    "pass_threshold": threshold,
                    "correct": int(round_data.get("correct", 0) or 0),
                    "total": int(round_data.get("total", 0) or 0),
                    "question_detail_count": len(responses) if isinstance(responses, list) else 0,
                    "incorrect_response_count": incorrect_response_count,
                    "unanswered_question_count": unanswered_question_count,
                    "coding_question_title": question_title,
                    "coding_language": language,
                })

            normalized_candidates.append({
                "role": role_label,
                "batch_id": batch_id,
                "overall_verdict": verdict,
                "overall_percentage": overall_percentage,
                "attempted_rounds": attempted_rounds,
                "passed_rounds": int(summary.get("passed_rounds", 0) or 0),
                "failed_rounds": failed_rounds,
                "total_rounds": total_rounds,
                "rounds": rounds_payload,
            })

        if not normalized_candidates:
            return None

        round_stats = []
        for stat in round_stats_map.values():
            attempted_candidates = int(stat.get("attempted_candidates", 0) or 0)
            average_percentage = (
                round(float(stat.get("percentage_total", 0) or 0) / attempted_candidates, 2)
                if attempted_candidates > 0
                else 0.0
            )
            round_stats.append({
                "round_key": stat["round_key"],
                "round_label": stat["round_label"],
                "round_number": stat["round_number"],
                "candidate_count": stat["candidate_count"],
                "attempted_candidates": attempted_candidates,
                "passed_candidates": stat["passed_candidates"],
                "failed_candidates": stat["failed_candidates"],
                "pending_candidates": stat["pending_candidates"],
                "below_threshold_candidates": stat["below_threshold_candidates"],
                "average_percentage": average_percentage,
                "detail_candidates": stat["detail_candidates"],
                "incorrect_response_count": stat["incorrect_response_count"],
                "unanswered_question_count": stat["unanswered_question_count"],
                "coding_detail_candidates": stat["coding_detail_candidates"],
            })

        round_stats.sort(key=lambda item: (int(item.get("round_number", 0) or 0), item.get("round_label", "").lower()))

        raw_gap_signals = []
        for signal in gap_signals_map.values():
            related_tags = sorted(
                signal.get("related_tags", {}).items(),
                key=lambda item: (-int(item[1] or 0), item[0]),
            )
            raw_gap_signals.append({
                "round_key": signal.get("round_key", ""),
                "round_label": signal.get("round_label", ""),
                "signal_label": signal.get("signal_label", ""),
                "evidence_type": signal.get("evidence_type", "question"),
                "candidate_occurrences": len(signal.get("candidate_emails", set())),
                "occurrences": int(signal.get("occurrences", 0) or 0),
                "evidence_examples": list(signal.get("evidence_examples", []) or []),
                "related_tags": [item[0] for item in related_tags[:3]],
            })

        signal_priority = {
            "topic": 0,
            "tag": 1,
            "question": 2,
            "completion": 3,
        }
        raw_gap_signals.sort(
            key=lambda item: (
                int(signal_priority.get(item.get("evidence_type", "question"), 9)),
                -int(item.get("candidate_occurrences", 0) or 0),
                -int(item.get("occurrences", 0) or 0),
                str(item.get("round_label", "")).lower(),
                str(item.get("signal_label", "")).lower(),
            )
        )

        min_signal_candidate_occurrences = 2 if len(normalized_candidates) >= 3 else 1
        recurring_gap_signals = [
            item for item in raw_gap_signals
            if int(item.get("candidate_occurrences", 0) or 0) >= min_signal_candidate_occurrences
        ]
        if not recurring_gap_signals:
            recurring_gap_signals = raw_gap_signals[:]
        recurring_gap_signals = recurring_gap_signals[:6]

        coding_signals = []
        for signal in coding_signals_map.values():
            languages = sorted(
                signal.get("languages", {}).items(),
                key=lambda item: (-int(item[1] or 0), item[0]),
            )
            percentage_count = int(signal.get("percentage_count", 0) or 0)
            coding_signals.append({
                "round_key": signal.get("round_key", ""),
                "round_label": signal.get("round_label", ""),
                "question_title": signal.get("question_title", ""),
                "prompt_excerpt": signal.get("prompt_excerpt", ""),
                "candidate_occurrences": len(signal.get("candidate_emails", set())),
                "attempted_candidates": len(signal.get("attempted_candidates", set())),
                "failed_candidates": len(signal.get("failed_candidates", set())),
                "passed_candidates": len(signal.get("passed_candidates", set())),
                "average_percentage": round(
                    float(signal.get("percentage_total", 0) or 0) / percentage_count,
                    2,
                ) if percentage_count > 0 else 0.0,
                "languages": [item[0] for item in languages[:3]],
            })

        coding_signals.sort(
            key=lambda item: (
                -int(item.get("failed_candidates", 0) or 0),
                -int(item.get("candidate_occurrences", 0) or 0),
                float(item.get("average_percentage", 0) or 0),
                str(item.get("question_title", "")).lower(),
            )
        )
        coding_signals = coding_signals[:4]

        scope = scope or {}
        scope_role = str(scope.get("role", "") or "").strip()
        if not scope_role or scope_role.lower() == "all roles":
            scope_role = next(iter(role_labels), "Selected Candidates") if len(role_labels) == 1 else "Selected Candidates"
        total_attempted_rounds = sum(
            int(candidate.get("attempted_rounds", 0) or 0)
            for candidate in normalized_candidates
        )

        return {
            "scope": {
                "role": scope_role,
                "period_label": str(scope.get("period_label", "") or "").strip() or "Current Scope",
                "candidate_count": len(normalized_candidates),
                "attempted_candidate_count": attempted_candidate_count,
                "average_overall_percentage": round(score_total / score_count, 2) if score_count else 0.0,
                "batch_ids": sorted(batch_ids, key=lambda value: value.lower()),
                "search_global_mode": bool(scope.get("search_global_mode")),
                "search_query": str(scope.get("search_query", "") or "").strip(),
            },
            "aggregate": {
                "verdict_counts": verdict_counts,
                "round_stats": round_stats,
                "completion_stats": {
                    "fully_completed_candidates": fully_completed_candidate_count,
                    "partially_completed_candidates": partially_completed_candidate_count,
                    "not_started_candidates": not_started_candidate_count,
                    "multiple_failed_round_candidates": multiple_failed_round_candidates,
                    "average_rounds_attempted": round(
                        total_attempted_rounds / len(normalized_candidates),
                        2,
                    ) if normalized_candidates else 0.0,
                    "average_completion_ratio": round(
                        (
                            total_attempted_rounds
                            / total_round_slots
                        ) * 100,
                        2,
                    ) if total_round_slots > 0 else 0.0,
                },
                "recurring_gap_signals": recurring_gap_signals,
                "coding_signals": coding_signals,
            },
            "candidates": normalized_candidates,
        }

    @staticmethod
    def _enrich_l4_with_coding_submission(candidate_data: dict) -> dict:
        """Attach persisted L4 coding question/code details if available."""
        if not candidate_data:
            return candidate_data

        rounds = candidate_data.get("rounds") or {}
        l4 = rounds.get("L4")
        if not l4:
            return candidate_data

        latest_submission = get_latest_coding_submission(
            candidate_data.get("email", ""),
            "L4",
            role_key=str((candidate_data or {}).get("role_key", "") or "").strip(),
            batch_id=str((candidate_data or {}).get("batch_id", "") or "").strip(),
        )
        if not latest_submission:
            return candidate_data

        submission_details = l4.get("submission_details") or {}

        def _pick(existing, fallback):
            return existing if str(existing or "").strip() else fallback

        def _pick_list(existing, fallback):
            if isinstance(existing, list) and existing:
                return list(existing)
            if isinstance(fallback, list) and fallback:
                return list(fallback)
            return []

        submission_details["language"] = _pick(
            submission_details.get("language"), latest_submission.get("language", "")
        )
        submission_details["question_title"] = _pick(
            submission_details.get("question_title"), latest_submission.get("question_title", "")
        )
        submission_details["question_text"] = _pick(
            submission_details.get("question_text"), latest_submission.get("question_text", "")
        )
        submission_details["submitted_code"] = _pick(
            submission_details.get("submitted_code"), latest_submission.get("submitted_code", "")
        )
        submission_details["public_tests"] = _pick_list(
            submission_details.get("public_tests"), latest_submission.get("public_tests")
        )
        submission_details["hidden_tests"] = _pick_list(
            submission_details.get("hidden_tests"), latest_submission.get("hidden_tests")
        )
        submission_details["public_test_results"] = _pick_list(
            submission_details.get("public_test_results"), latest_submission.get("public_test_results")
        )
        submission_details["hidden_test_results"] = _pick_list(
            submission_details.get("hidden_test_results"), latest_submission.get("hidden_test_results")
        )
        l4["submission_details"] = submission_details
        rounds["L4"] = l4
        candidate_data["rounds"] = rounds
        return candidate_data

    @staticmethod
    def enrich_candidate_submission_details(candidate_data: dict) -> dict:
        """Attach round-wise submission artifacts (MCQ answers, coding payloads) for reporting."""
        if not isinstance(candidate_data, dict):
            return candidate_data

        rounds = candidate_data.get("rounds") or {}
        if not isinstance(rounds, dict):
            return candidate_data

        enriched = dict(candidate_data)
        enriched_rounds = {str(key): dict(value) if isinstance(value, dict) else value for key, value in rounds.items()}
        ordered_keys = ordered_present_round_keys(enriched_rounds)

        for round_key in ordered_keys:
            round_data = enriched_rounds.get(round_key)
            if not isinstance(round_data, dict):
                continue
            details = EvaluationService._resolve_round_submission_details(enriched, round_key, round_data)
            if isinstance(details, dict) and details:
                round_data["submission_details"] = details
                enriched_rounds[round_key] = round_data

        existing_coding_data = (
            dict(enriched.get("coding_round_data"))
            if isinstance(enriched.get("coding_round_data"), dict)
            else {}
        )

        l4_round = enriched_rounds.get("L4")
        email_key = EvaluationService._normalize_email(enriched.get("email", ""))
        if isinstance(l4_round, dict) and email_key:
            try:
                coding_data = EvaluationService.get_candidate_coding_round_data(
                    email_key,
                    candidate_data=enriched,
                ) or {}
            except Exception:
                coding_data = {}

            if coding_data:
                coding_for_pdf = dict(existing_coding_data)
                for key, value in coding_data.items():
                    if key not in coding_for_pdf:
                        coding_for_pdf[key] = value
                        continue
                    existing_value = coding_for_pdf.get(key)
                    if isinstance(existing_value, list):
                        if not existing_value and isinstance(value, list) and value:
                            coding_for_pdf[key] = list(value)
                        continue
                    if str(existing_value or "").strip():
                        continue
                    coding_for_pdf[key] = value

                submission_details = dict(l4_round.get("submission_details") or {})
                for key in (
                    "language",
                    "question_title",
                    "question_text",
                    "submitted_code",
                    "public_tests",
                    "hidden_tests",
                    "public_test_results",
                    "hidden_test_results",
                ):
                    value = coding_for_pdf.get(key)
                    if isinstance(value, list):
                        if value and not submission_details.get(key):
                            submission_details[key] = value
                        continue
                    if str(value or "").strip() and not str(submission_details.get(key, "") or "").strip():
                        submission_details[key] = value

                l4_round["submission_details"] = submission_details
                enriched_rounds["L4"] = l4_round
                enriched["coding_round_data"] = coding_for_pdf

        enriched["rounds"] = enriched_rounds
        return enriched

    @staticmethod
    def generate_candidate_overall_summary(candidate_email, candidate_data=None):
        """
        Generate an AI-based summary for candidate rounds using role-accurate labels/order.
        """
        candidate_email = EvaluationService._normalize_email(candidate_email)

        # Prefer caller-supplied candidate context so summary aligns with the selected report row.
        if (
            isinstance(candidate_data, dict)
            and EvaluationService._normalize_email(candidate_data.get("email", "")) == candidate_email
        ):
            try:
                candidate_data = EvaluationService._enrich_l4_with_coding_submission(candidate_data)
                summary_payload = EvaluationService._prepare_l1_l4_summary_payload(candidate_data)
                return generate_evaluation_summary(summary_payload) if summary_payload else None
            except Exception:
                pass

        # Prefer persisted DB report data when available.
        try:
            from app.services.db_service import get_candidate_report_data
            scoped_test_session_id = None
            scoped_role_key = ""
            scoped_batch_id = ""
            if isinstance(candidate_data, dict):
                scoped_test_session_id = candidate_data.get("test_session_id")
                scoped_role_key = str(candidate_data.get("role_key", "") or "").strip()
                scoped_batch_id = str(candidate_data.get("batch_id", "") or "").strip()

            db_candidate_data = get_candidate_report_data(
                candidate_email,
                test_session_id=scoped_test_session_id,
                role_key=scoped_role_key,
                batch_id=scoped_batch_id,
            )
            if db_candidate_data:
                db_candidate_data = EvaluationService._enrich_l4_with_coding_submission(db_candidate_data)
                summary_payload = EvaluationService._prepare_l1_l4_summary_payload(db_candidate_data)
                return generate_evaluation_summary(summary_payload) if summary_payload else None
        except Exception:
            pass

        # Aggregate in-memory round results for this candidate.
        all_round_results = [
            result for result in EVALUATION_STORE.values()
            if EvaluationService._normalize_email(result.get("email", "")) == candidate_email
        ]
        if not all_round_results:
            candidate_data = {
                "name": "Candidate",
                "email": candidate_email,
                "role": "N/A",
                "rounds": {},
            }
            summary_payload = EvaluationService._prepare_l1_l4_summary_payload(candidate_data)
            return generate_evaluation_summary(summary_payload) if summary_payload else None

        ordered = sorted(
            all_round_results,
            key=lambda r: round_sort_key(r.get("round_key", "")),
        )
        first = ordered[0]

        rounds = {}
        for r in ordered:
            rk = r.get("round_key", "")
            if not rk:
                continue
            rounds[rk] = {
                "round_label": r.get("round_label", rk),
                "correct": r.get("correct", 0),
                "total": r.get("total_questions", 0),
                "attempted": r.get("attempted", 0),
                "percentage": r.get("percentage", 0),
                "pass_threshold": r.get("pass_threshold", EvaluationService.get_pass_threshold(rk)),
                "status": r.get("status", "Pending"),
                "time_taken_seconds": r.get("time_taken_seconds", 0),
                "submission_details": r.get("submission_details", {}),
            }

        candidate_data = {
            "name": first.get("candidate_name", ""),
            "email": candidate_email,
            "role": first.get("role_label") or first.get("role_key", ""),
            "rounds": rounds,
        }
        candidate_data = EvaluationService._enrich_l4_with_coding_submission(candidate_data)
        summary_payload = EvaluationService._prepare_l1_l4_summary_payload(candidate_data)
        if not summary_payload:
            return None
        return generate_evaluation_summary(summary_payload)

    @staticmethod
    def generate_consolidated_summary(candidates_data: list[dict], scope: dict | None = None):
        """Generate one AI summary across multiple selected candidates."""
        summary_payload = EvaluationService._prepare_consolidated_summary_payload(candidates_data, scope)
        if not summary_payload:
            return None
        return generate_consolidated_evaluation_summary(summary_payload)

    @staticmethod
    def generate_candidate_coding_round_summary(candidate_email, candidate_data=None):
        """
        Generate a separate summary only for L4 coding round, including question and submitted code.
        Skip AI summary entirely if the coding round was not attempted.
        """
        coding_data = EvaluationService.get_candidate_coding_round_data(
            candidate_email,
            candidate_data=candidate_data,
        )
        if not coding_data:
            return None
        # If not attempted or no submitted code, don't generate AI summary
        status = str(coding_data.get("status", "")).strip()
        submitted_code = str(coding_data.get("submitted_code", "")).strip()
        if status in ("Not Attempted", "Pending", "") or not submitted_code:
            return None
        return generate_coding_round_summary(coding_data)

    @staticmethod
    def get_candidate_coding_round_data(candidate_email, candidate_data=None):
        """
        Return structured L4 coding round data (question + submitted code when available).
        """
        candidate_email = EvaluationService._normalize_email(candidate_email)
        scoped_candidate = {}
        if (
            isinstance(candidate_data, dict)
            and EvaluationService._normalize_email(candidate_data.get("email", "")) == candidate_email
        ):
            scoped_candidate = candidate_data

        scoped_test_session_id = scoped_candidate.get("test_session_id")
        scoped_role_key = str(scoped_candidate.get("role_key", "") or "").strip()
        scoped_batch_id = str(scoped_candidate.get("batch_id", "") or "").strip()

        overall_context = {}
        try:
            from app.services.db_service import get_candidate_report_data
            db_candidate_data = get_candidate_report_data(
                candidate_email,
                test_session_id=scoped_test_session_id,
                role_key=scoped_role_key,
                batch_id=scoped_batch_id,
            )
            if db_candidate_data:
                overall_context = {
                    "overall_summary": db_candidate_data.get("summary", {}),
                    "overall_rounds": db_candidate_data.get("rounds", {}),
                    "overall_role": db_candidate_data.get("role", "N/A"),
                    "overall_name": db_candidate_data.get("name", "Candidate"),
                }
        except Exception:
            pass

        # Prefer in-memory first for full submission details (question + code),
        # then fall back to DB round metrics if available.
        matching_live_results = []
        for session_id, result in EVALUATION_STORE.items():
            if result.get("round_key") != "L4":
                continue
            if EvaluationService._normalize_email(result.get("email", "")) != candidate_email:
                continue
            if scoped_candidate and not EvaluationService._live_result_matches_candidate(scoped_candidate, result, session_id):
                continue
            matching_live_results.append((session_id, result))

        if matching_live_results:
            latest_session_id, latest = matching_live_results[-1]

            submission_details = latest.get("submission_details") or {}
            latest_submission = get_latest_coding_submission(
                candidate_email,
                "L4",
                role_key=scoped_role_key,
                batch_id=scoped_batch_id,
                session_id=latest_session_id,
            ) or {}

            def _pick(existing, fallback):
                return existing if str(existing or "").strip() else fallback

            def _pick_list(existing, fallback):
                if isinstance(existing, list) and existing:
                    return list(existing)
                if isinstance(fallback, list) and fallback:
                    return list(fallback)
                return []

            coding_data = {
                "name": latest.get("candidate_name", "Candidate"),
                "email": candidate_email,
                "role": latest.get("role") or latest.get("role_label") or overall_context.get("overall_role", "N/A"),
                "round_label": latest.get("round_label", "Coding Challenge"),
                "status": latest.get("status", "Not Attempted"),
                "percentage": latest.get("percentage", 0),
                "correct": latest.get("correct", 0),
                "total": latest.get("total_questions", 0),
                "language": _pick(submission_details.get("language"), latest_submission.get("language", "")),
                "question_title": _pick(submission_details.get("question_title"), latest_submission.get("question_title", "")),
                "question_text": _pick(submission_details.get("question_text"), latest_submission.get("question_text", "")),
                "submitted_code": _pick(submission_details.get("submitted_code"), latest_submission.get("submitted_code", "")),
                "public_tests": _pick_list(submission_details.get("public_tests"), latest_submission.get("public_tests")),
                "hidden_tests": _pick_list(submission_details.get("hidden_tests"), latest_submission.get("hidden_tests")),
                "public_test_results": _pick_list(
                    submission_details.get("public_test_results"), latest_submission.get("public_test_results")
                ),
                "hidden_test_results": _pick_list(
                    submission_details.get("hidden_test_results"), latest_submission.get("hidden_test_results")
                ),
            }
            # If not attempted, clear submitted_code to prevent starter code leaking into AI summary
            if not latest.get("attempted") or coding_data["status"] in ("Not Attempted", "Pending"):
                coding_data["submitted_code"] = ""
            coding_data.update(overall_context)
            return coding_data

        try:
            from app.services.db_service import get_candidate_report_data
            db_candidate_data = get_candidate_report_data(
                candidate_email,
                test_session_id=scoped_test_session_id,
                role_key=scoped_role_key,
                batch_id=scoped_batch_id,
            )
            if db_candidate_data:
                l4 = (db_candidate_data.get("rounds") or {}).get("L4") or {}
                l4_submission_details = l4.get("submission_details") or {}
                latest_submission = get_latest_coding_submission(
                    candidate_email,
                    "L4",
                    role_key=scoped_role_key,
                    batch_id=scoped_batch_id,
                ) or {}

                def _pick(existing, fallback):
                    return existing if str(existing or "").strip() else fallback

                def _pick_list(existing, fallback):
                    if isinstance(existing, list) and existing:
                        return list(existing)
                    if isinstance(fallback, list) and fallback:
                        return list(fallback)
                    return []

                coding_data = {
                    "name": db_candidate_data.get("name", "Candidate"),
                    "email": candidate_email,
                    "role": db_candidate_data.get("role", "N/A"),
                    "round_label": l4.get("round_label", "Coding Challenge"),
                    "status": l4.get("status", "Not Attempted"),
                    "percentage": l4.get("percentage", 0),
                    "correct": l4.get("correct", 0),
                    "total": l4.get("total", 0),
                    "language": _pick(l4_submission_details.get("language"), latest_submission.get("language", "")),
                    "question_title": _pick(l4_submission_details.get("question_title"), latest_submission.get("question_title", "")),
                    "question_text": _pick(l4_submission_details.get("question_text"), latest_submission.get("question_text", "")),
                    "submitted_code": _pick(l4_submission_details.get("submitted_code"), latest_submission.get("submitted_code", "")),
                    "public_tests": _pick_list(l4_submission_details.get("public_tests"), latest_submission.get("public_tests")),
                    "hidden_tests": _pick_list(l4_submission_details.get("hidden_tests"), latest_submission.get("hidden_tests")),
                    "public_test_results": _pick_list(
                        l4_submission_details.get("public_test_results"), latest_submission.get("public_test_results")
                    ),
                    "hidden_test_results": _pick_list(
                        l4_submission_details.get("hidden_test_results"), latest_submission.get("hidden_test_results")
                    ),
                }
                # If not attempted, clear submitted_code to prevent starter code leaking into AI summary
                if not l4.get("attempted") or coding_data["status"] in ("Not Attempted", "Pending"):
                    coding_data["submitted_code"] = ""
                coding_data.update(overall_context)
                return coding_data
        except Exception:
            pass

        coding_data = {
            "name": "Candidate",
            "role": "N/A",
            "round_label": "Coding Challenge",
            "status": "Not Attempted",
            "percentage": 0,
            "correct": 0,
            "total": 0,
            "language": "",
            "question_title": "",
            "question_text": "",
            "submitted_code": "",
            "public_tests": [],
            "hidden_tests": [],
            "public_test_results": [],
            "hidden_test_results": [],
        }
        coding_data.update(overall_context)
        return coding_data

    @staticmethod
    def evaluate_mcq(session_id: str):

        mcq_data = get_mcq_session_data(session_id)
        if not mcq_data:
            legacy = session.get(mcq_session_key(session_id))
            if isinstance(legacy, dict) and "questions" in legacy and "answers" in legacy:
                mcq_data = legacy
        session_meta = MCQ_SESSION_REGISTRY.get(session_id)

        if not session_meta:
            return

        round_key = session_meta["round_key"]
        pass_threshold = EvaluationService.get_pass_threshold(round_key)        # Candidate never opened test
        if not mcq_data:
            result_data = {
                "candidate_name": session_meta["candidate_name"],
                "email": session_meta["email"],
                "role_key": session_meta.get("role_key", ""),
                "role_label": session_meta.get("role_label", ""),
                "batch_id": session_meta.get("batch_id", ""),
                "round_key": round_key,
                "round_label": session_meta["round_label"],
                "total_questions": 15,
                "attempted": 0,
                "correct": 0,
                "percentage": 0,
                "pass_threshold": pass_threshold,
                "status": "FAIL",
                "time_taken_seconds": 0
            }
            EVALUATION_STORE[session_id] = result_data
            EvaluationService._persist_result_to_db(session_meta, result_data)
            return

        questions = mcq_data["questions"]
        answers = mcq_data["answers"]

        correct = 0
        attempted = len(answers)

        for idx, q in enumerate(questions):

            if str(idx) not in answers:
                continue

            selected_value = answers[str(idx)]
            correct_value = q.get("correct_answer")

            # Correct comparison for JSON structure
            if selected_value == correct_value:
                correct += 1

        total_questions = len(questions)

        percentage = (
            round((correct / total_questions) * 100, 2)
            if total_questions > 0 else 0
        )

        status = "PASS" if percentage >= pass_threshold else "FAIL"

        # Calculate time taken
        start_time = mcq_data.get("start_time", 0)
        time_taken = int(time.time()) - start_time
        response_details = EvaluationService._build_mcq_submission_details(questions, answers)

        EVALUATION_STORE[session_id] = {
            "candidate_name": session_meta["candidate_name"],
            "email": session_meta["email"],
            "role_key": session_meta.get("role_key", ""),
            "role_label": session_meta.get("role_label", ""),
            "batch_id": session_meta.get("batch_id", ""),
            "round_key": round_key,
            "round_label": session_meta["round_label"],
            "total_questions": total_questions,
            "attempted": attempted,
            "correct": correct,
            "percentage": percentage,
            "pass_threshold": pass_threshold,
            "status": status,
            "time_taken_seconds": time_taken,
            "submission_details": {
                "responses": response_details
            },
        }

        try:
            save_mcq_submission(
                session_id=session_id,
                email=session_meta.get("email", ""),
                round_key=round_key,
                round_label=session_meta.get("round_label", round_key),
                role=session_meta.get("role_label", ""),
                role_key=session_meta.get("role_key", ""),
                batch_id=session_meta.get("batch_id", ""),
                responses=response_details,
                attempted=attempted,
                correct=correct,
                total_questions=total_questions,
                percentage=percentage,
                status=status,
            )
        except Exception as exc:
            log.warning("MCQ submission persist failed: %s", exc)


        # -------------------------------------------------
        # PERSIST to DB (best-effort, non-blocking)
        # -------------------------------------------------
        EvaluationService._persist_result_to_db(session_meta, {
            "round_key": round_key,
            "round_label": session_meta["round_label"],
            "total_questions": total_questions,
            "attempted": attempted,
            "correct": correct,
            "percentage": percentage,
            "pass_threshold": pass_threshold,
            "status": status,
            "time_taken_seconds": time_taken,
        })

    @staticmethod
    def _persist_result_to_db(session_meta: dict, result: dict):
        """Write a round result row into the database."""
        try:
            from app.services import db_service

            batch_id = session_meta.get("batch_id", "")
            email = session_meta.get("email", "")
            name = session_meta.get("candidate_name", "")

            if not batch_id or not email:
                return

            candidate = db_service.get_or_create_candidate(name, email)
            ts = db_service.get_or_create_test_session(
                candidate_id=candidate.id,
                role_key=session_meta.get("role_key", ""),
                role_label=session_meta.get("role_label", ""),
                batch_id=batch_id,
            )
            db_service.save_round_result(
                test_session_id=ts.id,
                round_key=result["round_key"],
                round_label=result["round_label"],
                total_questions=result["total_questions"],
                attempted=result["attempted"],
                correct=result["correct"],
                percentage=result["percentage"],
                pass_threshold=result["pass_threshold"],
                status=result["status"],
                time_taken_seconds=result.get("time_taken_seconds", 0),
                session_uuid=session_meta.get("session_id", ""),
                test_link=session_meta.get("test_url", ""),
            )
        except Exception as exc:
            log.warning("DB persist failed for round result: %s", exc)
