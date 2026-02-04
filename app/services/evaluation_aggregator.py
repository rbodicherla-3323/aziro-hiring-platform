from app.services.evaluation_store import EVALUATION_STORE


class EvaluationAggregator:
    """
    Groups evaluated results per candidate
    """

    @staticmethod
    def get_candidates():

        candidates = {}

        for result in EVALUATION_STORE.values():
            email = result["email"]

            if email not in candidates:
                candidates[email] = {
                    "name": result["candidate_name"],
                    "email": email,
                    "rounds": {}
                }

            candidates[email]["rounds"][result["round_key"]] = {
                "label": result["round_label"],
                "correct": result["correct"],
                "total": result["total_questions"],
                "percentage": result["percentage"],
                "attempted": result["attempted"]
            }

        return list(candidates.values())
