from flask import Blueprint, request, jsonify

proctoring_bp = Blueprint("proctoring", __name__)

@proctoring_bp.route("/mcq/proctoring/violation", methods=["POST"])
def violation():
	print("PROCTORING:", request.json)
	return jsonify({"status": "logged"})
from flask import Blueprint, request, jsonify

proctoring_bp = Blueprint("proctoring", __name__)

@proctoring_bp.route("/mcq/proctoring/violation", methods=["POST"])
def log_violation():
	data = request.get_json()
	# Store in memory (session-based)
	# Extend later to CSV / DB
	return jsonify({"status": "logged"})
