import uuid
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING


from app.utils.role_normalizer import normalize_role
from app.utils.role_round_mapping import ROLE_ROUND_MAPPING
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.coding_session_registry import CODING_SESSION_REGISTRY

tests_bp = Blueprint("tests", __name__)




@tests_bp.route("/create-test", methods=["GET", "POST"])
def create_test():

    if request.method == "POST":

        names = request.form.getlist("name[]")
        emails = request.form.getlist("email[]")
        roles = request.form.getlist("role[]")
        domains = request.form.getlist("domain[]")
        batch_id = datetime.now(timezone.utc).strftime("batch_%Y%m%d_%H%M%S")

        for name, email, role_label, domain in zip(names, emails, roles, domains):

            role_key = normalize_role(role_label)
            if not role_key:
                continue

            config = ROLE_ROUND_MAPPING[role_key]
            tests = {}

            # -------------------------------
            # MCQ ROUNDS (L1, L2, L3, L5)
            # -------------------------------
            for round_key in config["rounds"]:

                session_id = str(uuid.uuid4())

                MCQ_SESSION_REGISTRY[session_id] = {
                    "role_key": role_key,
                    "role_label": role_label,
                    "round_key": round_key,
                    "round_label": ROUND_DISPLAY_MAPPING
    .get(role_key, {})
    .get(round_key, round_key),

                    "batch_id": batch_id,
                    "domain": None,
                    "candidate_name": name,
                    "email": email
                }

                tests[round_key] = {
                    "label": ROUND_DISPLAY_MAPPING.get(role_key, {}).get(round_key, round_key),

                    "url": f"{request.host_url.rstrip('/')}/mcq/start/{session_id}"
                }

            # -------------------------------
            # CODING ROUND (L4)
            # -------------------------------
            coding_rounds = config.get("coding_rounds", [])
            coding_language = config.get("coding_language", "java")

            for round_key in coding_rounds:
                session_id = str(uuid.uuid4())

                CODING_SESSION_REGISTRY[session_id] = {
                    "role_key": role_key,
                    "role_label": role_label,
                    "round_key": round_key,
                    "round_label": ROUND_DISPLAY_MAPPING
    .get(role_key, {})
    .get(round_key, f"Coding Challenge ({round_key})"),
                    "language": coding_language,
                    "batch_id": batch_id,
                    "domain": None,
                    "candidate_name": name,
                    "email": email,
                }

                tests[round_key] = {
                    "label": ROUND_DISPLAY_MAPPING.get(role_key, {}).get(round_key, f"Coding Challenge ({round_key})"),
                    "url": f"{request.host_url.rstrip('/')}/coding/start/{session_id}"
                }

            # -------------------------------
            # DOMAIN ROUND (L6)
            # -------------------------------
            if config["allow_domain"] and domain and domain != "None":

                session_id = str(uuid.uuid4())

                MCQ_SESSION_REGISTRY[session_id] = {
                    "role_key": role_key,
                    "role_label": role_label,
                    "round_key": "L6",
                    "round_label": f"Domain – {domain}",
                    "domain": domain.lower(),
                    "batch_id": batch_id,
                    "candidate_name": name,
                    "email": email
                }

                tests["L6"] = {
                    "label": f"Domain – {domain}",
                    "url": f"{request.host_url.rstrip('/')}/mcq/start/{session_id}"
                }

            ROUND_ORDER = ["L1", "L2", "L3", "L4", "L5", "L6"]
            tests = dict(sorted(
                tests.items(),
                key=lambda x: ROUND_ORDER.index(x[0]) if x[0] in ROUND_ORDER else 99
            ))

            GENERATED_TESTS.append({
                "name": name,
                "email": email,
                "role": role_label,
                "tests": tests
            })

        return redirect(url_for("tests.generated_tests"))

    return render_template("test_create.html")


@tests_bp.route("/generated-tests")
def generated_tests():
    return render_template(
        "generated_tests.html",
        candidates=GENERATED_TESTS
    )
