from collections import defaultdict
from app.services.evaluation_store import EVALUATION_STORE
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services.evaluation_service import EvaluationService


class EvaluationAggregator:

    @staticmethod
    def get_candidates():

        # -------------------------------
        # 1️⃣ Base candidates from test creation
        # -------------------------------
        candidates_map = {}

        for c in GENERATED_TESTS:
            candidates_map[c["email"]] = {
                "name": c["name"],
                "email": c["email"],
                "role": c["role"],
                "rounds": {}
            }

        # -------------------------------
        # 2️⃣ Attach evaluation results
        # -------------------------------
        for session_id, result in EVALUATION_STORE.items():

            email = result["email"]
            if email not in candidates_map:
                continue

            round_key = result["round_key"]
            pass_threshold = result.get(
                "pass_threshold",
                EvaluationService.get_pass_threshold(round_key)
            )

            candidates_map[email]["rounds"][round_key] = {
                "round_label": result["round_label"],
                "correct": result["correct"],
                "total": result["total_questions"],
                "attempted": result.get("attempted", 0),
                "percentage": result["percentage"],
                "pass_threshold": pass_threshold,
                "status": result["status"],
                "time_taken_seconds": result["time_taken_seconds"]
            }

        # -------------------------------
        # 3️⃣ Ensure ALL rounds appear
        # even if not attempted
        # -------------------------------
        for session_id, meta in MCQ_SESSION_REGISTRY.items():

            email = meta["email"]
            round_key = meta["round_key"]

            if email not in candidates_map:
                continue

            if round_key not in candidates_map[email]["rounds"]:
                pass_threshold = EvaluationService.get_pass_threshold(round_key)
                candidates_map[email]["rounds"][round_key] = {
                    "round_label": meta["round_label"],
                    "correct": 0,
                    "total": 15,
                    "attempted": 0,
                    "percentage": 0,
                    "pass_threshold": pass_threshold,
                    "status": "Not Attempted",
                    "time_taken_seconds": 0
                }

        for session_id, meta in CODING_SESSION_REGISTRY.items():

            email = meta["email"]
            round_key = meta["round_key"]

            if email not in candidates_map:
                continue

            if round_key not in candidates_map[email]["rounds"]:
                pass_threshold = EvaluationService.get_pass_threshold(round_key)
                candidates_map[email]["rounds"][round_key] = {
                    "round_label": meta["round_label"],
                    "correct": 0,
                    "total": 1,
                    "attempted": 0,
                    "percentage": 0,
                    "pass_threshold": pass_threshold,
                    "status": "Not Attempted",
                    "time_taken_seconds": 0
                }

        # -------------------------------
        # 4️⃣ Sort rounds & compute overall
        # -------------------------------
        ordered_rounds = ["L1", "L2", "L3", "L4", "L5", "L6"]

        final_list = []

        for candidate in candidates_map.values():

            sorted_rounds = {}

            for rk in ordered_rounds:
                if rk in candidate["rounds"]:
                    sorted_rounds[rk] = candidate["rounds"][rk]

            candidate["rounds"] = sorted_rounds

            # --- Overall summary ---
            total_rounds = len(sorted_rounds)
            attempted_rounds = sum(
                1 for r in sorted_rounds.values()
                if r["status"] not in ("Not Attempted",)
            )
            passed_rounds = sum(
                1 for r in sorted_rounds.values()
                if r["status"] == "PASS"
            )
            failed_rounds = sum(
                1 for r in sorted_rounds.values()
                if r["status"] == "FAIL"
            )

            # Overall percentage (average across attempted rounds)
            attempted_percentages = [
                r["percentage"] for r in sorted_rounds.values()
                if r["status"] not in ("Not Attempted",)
            ]
            overall_percentage = (
                round(sum(attempted_percentages) / len(attempted_percentages), 2)
                if attempted_percentages else 0
            )

            # Overall verdict
            if attempted_rounds == 0:
                overall_verdict = "Pending"
            elif failed_rounds == 0 and attempted_rounds == total_rounds:
                overall_verdict = "Selected"
            elif failed_rounds > 0:
                overall_verdict = "Rejected"
            else:
                overall_verdict = "In Progress"

            # Total correct / total questions
            total_correct = sum(r["correct"] for r in sorted_rounds.values())
            total_questions = sum(r["total"] for r in sorted_rounds.values())

            candidate["summary"] = {
                "total_rounds": total_rounds,
                "attempted_rounds": attempted_rounds,
                "passed_rounds": passed_rounds,
                "failed_rounds": failed_rounds,
                "total_correct": total_correct,
                "total_questions": total_questions,
                "overall_percentage": overall_percentage,
                "overall_verdict": overall_verdict
            }

            final_list.append(candidate)

        return final_list
