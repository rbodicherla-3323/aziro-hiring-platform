from app.services.evaluation_store import EVALUATION_STORE
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.coding_submission_store import get_latest_coding_submission
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.ai_generator import generate_evaluation_summary, generate_coding_round_summary
from app.services.mcq_runtime_store import get_mcq_session_data, mcq_session_key
from app.utils.role_round_mapping import ROLE_ROUND_MAPPING
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING
from flask import session
import logging
import time
from datetime import datetime

log = logging.getLogger(__name__)


# ---------------------------------------------------------------
# Per-round pass percentage thresholds
# ---------------------------------------------------------------
# Aptitude (L1)       → 60%  (general reasoning, slightly lenient)
# Technical Theory    → 70%  (core knowledge, standard bar)
# Technical Practical → 70%  (applied knowledge, standard bar)
# Soft Skills (L5)    → 50%  (subjective, more lenient)
# Domain (L6)         → 65%  (specialized but not core)
# ---------------------------------------------------------------
ROUND_PASS_PERCENTAGE = {
    "L1": 60,   # Aptitude – logical/quantitative reasoning
    "L2": 70,   # Technical Theory
    "L3": 70,   # Technical Fundamentals / Practical
    "L5": 50,   # Soft Skills – subjective, keep lenient
    "L6": 65,   # Domain-specific knowledge
}

DEFAULT_PASS_PERCENTAGE = 70
SUMMARY_ROUNDS = ("L1", "L2", "L3", "L4", "L5", "L6")


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
            if selected_value is None:
                continue
            correct_value = q.get("correct_answer")
            details.append({
                "question_no": idx + 1,
                "question": q.get("question", ""),
                "selected_answer": selected_value,
                "correct_answer": correct_value,
                "is_correct": selected_value == correct_value,
            })
        return details

    @staticmethod
    def _round_sort_key(round_key: str) -> tuple[int, str]:
        value = str(round_key or "").upper()
        if value.startswith("L") and value[1:].isdigit():
            return int(value[1:]), value
        return 999, value

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
            for rk in SUMMARY_ROUNDS:
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

        for rk in sorted(rounds.keys(), key=EvaluationService._round_sort_key):
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
            ordered_rounds = sorted(rounds.keys(), key=EvaluationService._round_sort_key)

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
                "submission_details": existing.get("submission_details", {}),
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
    def _enrich_l4_with_coding_submission(candidate_data: dict) -> dict:
        """Attach persisted L4 coding question/code details if available."""
        if not candidate_data:
            return candidate_data

        rounds = candidate_data.get("rounds") or {}
        l4 = rounds.get("L4")
        if not l4:
            return candidate_data

        latest_submission = get_latest_coding_submission(candidate_data.get("email", ""), "L4")
        if not latest_submission:
            return candidate_data

        submission_details = l4.get("submission_details") or {}

        def _pick(existing, fallback):
            return existing if str(existing or "").strip() else fallback

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
        l4["submission_details"] = submission_details
        rounds["L4"] = l4
        candidate_data["rounds"] = rounds
        return candidate_data

    @staticmethod
    def generate_candidate_overall_summary(candidate_email, candidate_data=None):
        """
        Generate an AI-based summary for candidate rounds using role-accurate labels/order.
        """
        if isinstance(candidate_email, str):
            candidate_email = candidate_email.strip()

        # Prefer caller-supplied candidate context so summary aligns with the selected report row.
        if isinstance(candidate_data, dict) and str(candidate_data.get("email", "")).strip() == candidate_email:
            try:
                candidate_data = EvaluationService._enrich_l4_with_coding_submission(candidate_data)
                summary_payload = EvaluationService._prepare_l1_l4_summary_payload(candidate_data)
                return generate_evaluation_summary(summary_payload) if summary_payload else None
            except Exception:
                pass

        # Prefer persisted DB report data when available.
        try:
            from app.services.db_service import get_candidate_report_data
            db_candidate_data = get_candidate_report_data(candidate_email)
            if db_candidate_data:
                db_candidate_data = EvaluationService._enrich_l4_with_coding_submission(db_candidate_data)
                summary_payload = EvaluationService._prepare_l1_l4_summary_payload(db_candidate_data)
                return generate_evaluation_summary(summary_payload) if summary_payload else None
        except Exception:
            pass

        # Aggregate in-memory round results for this candidate.
        all_round_results = [
            result for result in EVALUATION_STORE.values()
            if result.get("email") == candidate_email
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

        ordered = sorted(all_round_results, key=lambda r: r.get("round_key", ""))
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
    def generate_candidate_coding_round_summary(candidate_email):
        """
        Generate a separate summary only for L4 coding round, including question and submitted code.
        Skip AI summary entirely if the coding round was not attempted.
        """
        coding_data = EvaluationService.get_candidate_coding_round_data(candidate_email)
        if not coding_data:
            return None
        # If not attempted or no submitted code, don't generate AI summary
        status = str(coding_data.get("status", "")).strip()
        submitted_code = str(coding_data.get("submitted_code", "")).strip()
        if status in ("Not Attempted", "Pending", "") or not submitted_code:
            return None
        return generate_coding_round_summary(coding_data)

    @staticmethod
    def get_candidate_coding_round_data(candidate_email):
        """
        Return structured L4 coding round data (question + submitted code when available).
        """
        overall_context = {}
        try:
            from app.services.db_service import get_candidate_report_data
            db_candidate_data = get_candidate_report_data(candidate_email)
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
        coding_results = [
            result for result in EVALUATION_STORE.values()
            if result.get("email") == candidate_email and result.get("round_key") == "L4"
        ]

        if coding_results:
            latest = sorted(
                coding_results,
                key=lambda r: r.get("time_taken_seconds", 0),
                reverse=True
            )[0]

            submission_details = latest.get("submission_details") or {}
            latest_submission = get_latest_coding_submission(candidate_email, "L4") or {}

            def _pick(existing, fallback):
                return existing if str(existing or "").strip() else fallback

            coding_data = {
                "name": latest.get("candidate_name", "Candidate"),
                "email": candidate_email,
                "role": latest.get("role", "N/A"),
                "round_label": latest.get("round_label", "Coding Challenge"),
                "status": latest.get("status", "Not Attempted"),
                "percentage": latest.get("percentage", 0),
                "correct": latest.get("correct", 0),
                "total": latest.get("total_questions", 0),
                "language": _pick(submission_details.get("language"), latest_submission.get("language", "")),
                "question_title": _pick(submission_details.get("question_title"), latest_submission.get("question_title", "")),
                "question_text": _pick(submission_details.get("question_text"), latest_submission.get("question_text", "")),
                "submitted_code": _pick(submission_details.get("submitted_code"), latest_submission.get("submitted_code", "")),
            }
            # If not attempted, clear submitted_code to prevent starter code leaking into AI summary
            if not latest.get("attempted") or coding_data["status"] in ("Not Attempted", "Pending"):
                coding_data["submitted_code"] = ""
            coding_data.update(overall_context)
            return coding_data

        try:
            from app.services.db_service import get_candidate_report_data
            db_candidate_data = get_candidate_report_data(candidate_email)
            if db_candidate_data:
                l4 = (db_candidate_data.get("rounds") or {}).get("L4") or {}
                l4_submission_details = l4.get("submission_details") or {}
                latest_submission = get_latest_coding_submission(candidate_email, "L4") or {}

                def _pick(existing, fallback):
                    return existing if str(existing or "").strip() else fallback

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

            # ✅ Correct comparison for YOUR JSON structure
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

        EVALUATION_STORE[session_id] = {
            "candidate_name": session_meta["candidate_name"],
            "email": session_meta["email"],
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
                "responses": EvaluationService._build_mcq_submission_details(questions, answers)
            },
        }


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
            )
        except Exception as exc:
            log.warning("DB persist failed for round result: %s", exc)
