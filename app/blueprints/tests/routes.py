from flask import Blueprint, render_template

tests_bp = Blueprint("tests", __name__)

@tests_bp.route("/create-test")
def create_test():
    return render_template("test_create.html")

@tests_bp.route("/generated-tests")
def generated_tests():
    return render_template("generated_tests.html", candidates=[])
