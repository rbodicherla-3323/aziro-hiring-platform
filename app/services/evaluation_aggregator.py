from collections import defaultdict
from app.services.evaluation_store import EVALUATION_STORE
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY


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

            candidates_map[email]["rounds"][result["round_key"]] = {
                "round_label": result["round_label"],
                "correct": result["correct"],
                "total": result["total_questions"],
                "percentage": result["percentage"],
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
                candidates_map[email]["rounds"][round_key] = {
                    "round_label": meta["round_label"],
                    "correct": 0,
                    "total": 15,
                    "percentage": 0,
                    "status": "No Response",
                    "time_taken_seconds": 0
                }

        # -------------------------------
        # 4️⃣ Sort rounds consistently
        # -------------------------------
        ordered_rounds = ["L1", "L2", "L3", "L5", "L6"]

        final_list = []

        for candidate in candidates_map.values():

            sorted_rounds = {}

            for rk in ordered_rounds:
                if rk in candidate["rounds"]:
                    sorted_rounds[rk] = candidate["rounds"][rk]

            candidate["rounds"] = sorted_rounds
            final_list.append(candidate)

        return final_list
