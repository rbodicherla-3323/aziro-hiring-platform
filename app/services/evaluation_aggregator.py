from collections import defaultdict
from datetime import datetime, timezone

from app.services.evaluation_store import EVALUATION_STORE
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services.evaluation_service import EvaluationService
from app.utils.round_order import ordered_present_round_keys, round_number_map
from app.models import RoundResult, TestLink


class EvaluationAggregator:

    @staticmethod
    def _normalize_email(value):
        return str(value or "").strip().lower()

    @staticmethod
    def _parse_dt(value):
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None
        else:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _default_total(round_key, round_type="mcq"):
        rk = str(round_key or "").strip().upper()
        rt = str(round_type or "").strip().lower()
        if rt == "coding" or rk == "L4":
            return 1
        return 15

    @staticmethod
    def _ensure_candidate(candidates_map, email, **payload):
        entry = candidates_map.get(email)
        if entry is None:
            entry = {
                "name": payload.get("name", "") or email,
                "email": email,
                "role": payload.get("role", "") or "",
                "role_key": payload.get("role_key", "") or "",
                "batch_id": payload.get("batch_id", "") or "",
                "rounds": {},
                "_latest_created_at": payload.get("created_at"),
            }
            candidates_map[email] = entry
            return entry

        if payload.get("name"):
            entry["name"] = payload.get("name")
        if payload.get("role"):
            entry["role"] = payload.get("role")
        if payload.get("role_key"):
            entry["role_key"] = payload.get("role_key")
        if payload.get("batch_id"):
            entry["batch_id"] = payload.get("batch_id")

        incoming_dt = payload.get("created_at")
        existing_dt = entry.get("_latest_created_at")
        if incoming_dt and (existing_dt is None or incoming_dt > existing_dt):
            entry["_latest_created_at"] = incoming_dt

        return entry

    @staticmethod
    def _round_row(
        *,
        round_label,
        correct,
        total,
        attempted,
        percentage,
        pass_threshold,
        status,
        time_taken_seconds,
    ):
        return {
            "round_label": round_label,
            "correct": int(correct or 0),
            "total": int(total or 0),
            "attempted": int(attempted or 0),
            "percentage": float(percentage or 0),
            "pass_threshold": float(pass_threshold or 0),
            "status": status,
            "time_taken_seconds": int(time_taken_seconds or 0),
        }

    @staticmethod
    def get_candidates():
        candidates_map = {}
        planned_rounds = defaultdict(dict)
        link_by_session = {}

        # 1) In-memory generated tests (live UI state)
        for item in GENERATED_TESTS:
            email = EvaluationAggregator._normalize_email(item.get("email"))
            if not email:
                continue

            created_at = EvaluationAggregator._parse_dt(item.get("created_at"))
            candidate = EvaluationAggregator._ensure_candidate(
                candidates_map,
                email,
                name=str(item.get("name", "") or "").strip(),
                role=str(item.get("role", "") or "").strip(),
                role_key=str(item.get("role_key", "") or "").strip(),
                batch_id=str(item.get("batch_id", "") or "").strip(),
                created_at=created_at,
            )

            tests_map = item.get("tests", {}) or {}
            for round_key, test in tests_map.items():
                rk = str(round_key or "").strip()
                if not rk:
                    continue
                test_type = str((test or {}).get("type", "mcq") or "mcq").strip().lower()
                round_label = str((test or {}).get("label", "") or f"Round {rk}").strip()
                planned_rounds[email][rk] = {
                    "round_label": round_label,
                    "test_type": test_type,
                }
                session_id = str((test or {}).get("session_id", "") or "").strip().lower()
                if session_id:
                    link_by_session[session_id] = {
                        "email": email,
                        "candidate_name": candidate.get("name", ""),
                        "role_key": candidate.get("role_key", ""),
                        "role_label": candidate.get("role", ""),
                        "batch_id": candidate.get("batch_id", ""),
                        "round_key": rk,
                        "round_label": round_label,
                        "test_type": test_type,
                    }

        # 2) Persisted test links from DB (authoritative for generated rounds)
        try:
            db_links = TestLink.query.all()
        except Exception:
            db_links = []

        for link in db_links:
            email = EvaluationAggregator._normalize_email(getattr(link, "candidate_email", ""))
            if not email:
                continue

            created_at = getattr(link, "created_at", None)
            if created_at and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            role_key = str(getattr(link, "role_key", "") or "").strip()
            role_label = str(getattr(link, "role_label", "") or role_key).strip()
            candidate = EvaluationAggregator._ensure_candidate(
                candidates_map,
                email,
                name=str(getattr(link, "candidate_name", "") or email).strip(),
                role=role_label,
                role_key=role_key,
                batch_id=str(getattr(link, "batch_id", "") or "").strip(),
                created_at=created_at,
            )

            session_id = str(getattr(link, "session_id", "") or "").strip().lower()
            round_key = str(getattr(link, "round_key", "") or "").strip()
            round_label = str(getattr(link, "round_label", "") or f"Round {round_key}").strip()
            test_type = str(getattr(link, "test_type", "") or "mcq").strip().lower()

            if session_id:
                link_by_session[session_id] = {
                    "email": email,
                    "candidate_name": candidate.get("name", ""),
                    "role_key": role_key,
                    "role_label": role_label,
                    "batch_id": candidate.get("batch_id", ""),
                    "round_key": round_key,
                    "round_label": round_label,
                    "test_type": test_type,
                }

            if round_key:
                planned_rounds[email][round_key] = {
                    "round_label": round_label,
                    "test_type": test_type,
                }

        # 3) In-memory evaluation results (latest before persistence catches up)
        for session_id, result in EVALUATION_STORE.items():
            result_email = EvaluationAggregator._normalize_email(result.get("email"))
            link_meta = link_by_session.get(str(session_id or "").strip().lower(), {})
            email = result_email or EvaluationAggregator._normalize_email(link_meta.get("email"))
            if not email:
                continue

            candidate = EvaluationAggregator._ensure_candidate(
                candidates_map,
                email,
                name=str(result.get("candidate_name", "") or link_meta.get("candidate_name", "") or email).strip(),
                role=str(result.get("role_label", "") or link_meta.get("role_label", "")).strip(),
                role_key=str(result.get("role_key", "") or link_meta.get("role_key", "")).strip(),
                batch_id=str(result.get("batch_id", "") or link_meta.get("batch_id", "")).strip(),
            )

            round_key = str(result.get("round_key", "") or "").strip()
            if not round_key:
                continue

            pass_threshold = result.get("pass_threshold", EvaluationService.get_pass_threshold(round_key))
            candidate["rounds"][round_key] = EvaluationAggregator._round_row(
                round_label=str(result.get("round_label", "") or f"Round {round_key}").strip(),
                correct=result.get("correct", 0),
                total=result.get("total_questions", 0),
                attempted=result.get("attempted", 0),
                percentage=result.get("percentage", 0),
                pass_threshold=pass_threshold,
                status=str(result.get("status", "Pending") or "Pending"),
                time_taken_seconds=result.get("time_taken_seconds", 0),
            )

        # 4) Persisted round results from DB (authoritative for scores/status)
        try:
            db_round_results = RoundResult.query.order_by(RoundResult.created_at.desc()).all()
        except Exception:
            db_round_results = []

        for rr in db_round_results:
            round_key = str(getattr(rr, "round_key", "") or "").strip()
            if not round_key:
                continue

            session_uuid = str(getattr(rr, "session_uuid", "") or "").strip().lower()
            link_meta = link_by_session.get(session_uuid, {}) if session_uuid else {}

            email = EvaluationAggregator._normalize_email(link_meta.get("email"))
            candidate_name = str(link_meta.get("candidate_name", "") or "").strip()
            role_key = str(link_meta.get("role_key", "") or "").strip()
            role_label = str(link_meta.get("role_label", "") or role_key).strip()
            batch_id = str(link_meta.get("batch_id", "") or "").strip()

            if not email:
                ts = getattr(rr, "test_session", None)
                cand_obj = getattr(ts, "candidate", None) if ts else None
                email = EvaluationAggregator._normalize_email(getattr(cand_obj, "email", ""))
                candidate_name = candidate_name or str(getattr(cand_obj, "name", "") or "").strip()
                role_key = role_key or str(getattr(ts, "role_key", "") or "").strip()
                role_label = role_label or str(getattr(ts, "role_label", "") or role_key).strip()
                batch_id = batch_id or str(getattr(ts, "batch_id", "") or "").strip()

            if not email:
                continue

            candidate = EvaluationAggregator._ensure_candidate(
                candidates_map,
                email,
                name=candidate_name or email,
                role=role_label,
                role_key=role_key,
                batch_id=batch_id,
            )

            pass_threshold = (
                rr.pass_threshold
                if getattr(rr, "pass_threshold", None) is not None
                else EvaluationService.get_pass_threshold(round_key)
            )
            candidate["rounds"][round_key] = EvaluationAggregator._round_row(
                round_label=str(getattr(rr, "round_label", "") or f"Round {round_key}").strip(),
                correct=getattr(rr, "correct", 0),
                total=getattr(rr, "total_questions", 0),
                attempted=getattr(rr, "attempted", 0),
                percentage=getattr(rr, "percentage", 0),
                pass_threshold=pass_threshold,
                status=str(getattr(rr, "status", "Pending") or "Pending"),
                time_taken_seconds=getattr(rr, "time_taken_seconds", 0),
            )

        # 5) Ensure planned rounds appear as Not Attempted where no result exists
        for session_id, meta in MCQ_SESSION_REGISTRY.items():
            email = EvaluationAggregator._normalize_email(meta.get("email"))
            round_key = str(meta.get("round_key", "") or "").strip()
            if not email or not round_key:
                continue
            EvaluationAggregator._ensure_candidate(
                candidates_map,
                email,
                name=str(meta.get("candidate_name", "") or email).strip(),
                role=str(meta.get("role_label", "") or "").strip(),
                role_key=str(meta.get("role_key", "") or "").strip(),
                batch_id=str(meta.get("batch_id", "") or "").strip(),
            )
            planned_rounds[email].setdefault(
                round_key,
                {
                    "round_label": str(meta.get("round_label", "") or f"Round {round_key}").strip(),
                    "test_type": "mcq",
                },
            )

        for session_id, meta in CODING_SESSION_REGISTRY.items():
            email = EvaluationAggregator._normalize_email(meta.get("email"))
            round_key = str(meta.get("round_key", "") or "").strip()
            if not email or not round_key:
                continue
            EvaluationAggregator._ensure_candidate(
                candidates_map,
                email,
                name=str(meta.get("candidate_name", "") or email).strip(),
                role=str(meta.get("role_label", "") or "").strip(),
                role_key=str(meta.get("role_key", "") or "").strip(),
                batch_id=str(meta.get("batch_id", "") or "").strip(),
            )
            planned_rounds[email].setdefault(
                round_key,
                {
                    "round_label": str(meta.get("round_label", "") or f"Round {round_key}").strip(),
                    "test_type": "coding",
                },
            )

        for email, candidate in candidates_map.items():
            for round_key, plan in planned_rounds.get(email, {}).items():
                if round_key in candidate["rounds"]:
                    continue
                candidate["rounds"][round_key] = EvaluationAggregator._round_row(
                    round_label=str(plan.get("round_label", "") or f"Round {round_key}").strip(),
                    correct=0,
                    total=EvaluationAggregator._default_total(round_key, plan.get("test_type", "mcq")),
                    attempted=0,
                    percentage=0,
                    pass_threshold=EvaluationService.get_pass_threshold(round_key),
                    status="Not Attempted",
                    time_taken_seconds=0,
                )

        # 6) Stable round ordering + summary computation
        final_list = []
        for candidate in candidates_map.values():
            sorted_rounds = {}
            ordered_keys = ordered_present_round_keys(candidate["rounds"])
            numbers = round_number_map(ordered_keys)
            for rk in ordered_keys:
                if rk in candidate["rounds"]:
                    row = dict(candidate["rounds"][rk])
                    row["round_number"] = numbers.get(rk, 0)
                    sorted_rounds[rk] = row

            candidate["rounds"] = sorted_rounds

            total_rounds = len(sorted_rounds)
            attempted_rounds = sum(
                1
                for r in sorted_rounds.values()
                if str(r.get("status", "")).strip().lower() not in {"not attempted", "pending", ""}
            )
            passed_rounds = sum(
                1 for r in sorted_rounds.values() if str(r.get("status", "")).strip().upper() == "PASS"
            )
            failed_rounds = sum(
                1 for r in sorted_rounds.values() if str(r.get("status", "")).strip().upper() == "FAIL"
            )

            attempted_percentages = [
                float(r.get("percentage", 0) or 0)
                for r in sorted_rounds.values()
                if str(r.get("status", "")).strip().lower() not in {"not attempted", "pending", ""}
            ]
            overall_percentage = (
                round(sum(attempted_percentages) / len(attempted_percentages), 2)
                if attempted_percentages
                else 0
            )

            if attempted_rounds == 0:
                overall_verdict = "Pending"
            elif failed_rounds == 0 and attempted_rounds == total_rounds:
                overall_verdict = "Selected"
            elif failed_rounds > 0:
                overall_verdict = "Rejected"
            else:
                overall_verdict = "In Progress"

            candidate["summary"] = {
                "total_rounds": total_rounds,
                "attempted_rounds": attempted_rounds,
                "passed_rounds": passed_rounds,
                "failed_rounds": failed_rounds,
                "total_correct": sum(int(r.get("correct", 0) or 0) for r in sorted_rounds.values()),
                "total_questions": sum(int(r.get("total", 0) or 0) for r in sorted_rounds.values()),
                "overall_percentage": overall_percentage,
                "overall_verdict": overall_verdict,
            }

            final_list.append(candidate)

        def _sort_key(item):
            dt = item.get("_latest_created_at")
            return dt or datetime.min.replace(tzinfo=timezone.utc)

        final_list.sort(key=_sort_key, reverse=True)
        for candidate in final_list:
            candidate.pop("_latest_created_at", None)

        return final_list
