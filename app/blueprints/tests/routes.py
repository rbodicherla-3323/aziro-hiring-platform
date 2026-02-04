import uuid
from flask import Blueprint, render_template, request, redirect, url_for
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING


from app.utils.role_normalizer import normalize_role
from app.utils.role_round_mapping import ROLE_ROUND_MAPPING
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY

tests_bp = Blueprint("tests", __name__)




@tests_bp.route("/create-test", methods=["GET", "POST"])
def create_test():

    if request.method == "POST":

        names = request.form.getlist("name[]")
        emails = request.form.getlist("email[]")
        roles = request.form.getlist("role[]")
        domains = request.form.getlist("domain[]")

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
                    "round_key": round_key,
                    "round_label": ROUND_DISPLAY_MAPPING
    .get(role_key, {})
    .get(round_key, round_key),

                    "domain": None,
                    "candidate_name": name,
                    "email": email
                }

                tests[round_key] = {
                    "label": ROUND_DISPLAY_MAPPING.get(role_key, {}).get(round_key, round_key),

                    "url": f"{request.host_url.rstrip('/')}/mcq/start/{session_id}"
                }

            # -------------------------------
            # DOMAIN ROUND (L6)
            # -------------------------------
            if config["allow_domain"] and domain and domain != "None":

                session_id = str(uuid.uuid4())

                MCQ_SESSION_REGISTRY[session_id] = {
                    "role_key": role_key,
                    "round_key": "L6",
                    "round_label": f"Domain – {domain}",
                    "domain": domain.lower(),
                    "candidate_name": name,
                    "email": email
                }

                tests["L6"] = {
                    "label": f"Domain – {domain}",
                    "url": f"{request.host_url.rstrip('/')}/mcq/start/{session_id}"
                }

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
