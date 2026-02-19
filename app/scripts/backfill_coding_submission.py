import argparse
import os
import sys
from datetime import datetime, timezone


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import create_app
from app.services.coding_submission_store import save_coding_submission
from app.services.db_service import get_candidate_report_data


def _default_session_id():
    return f"backfill_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def main():
    parser = argparse.ArgumentParser(
        description="One-time backfill for coding question/code into coding_submissions.jsonl"
    )
    parser.add_argument("--email", required=True, help="Candidate email")
    parser.add_argument("--question-title", required=True, help="Coding question title")
    parser.add_argument("--question-text", required=True, help="Coding problem statement")
    parser.add_argument("--language", default="python", help="Coding language (default: python)")
    parser.add_argument(
        "--code-file",
        help="Path to file containing submitted code. Use this or --code-text.",
    )
    parser.add_argument(
        "--code-text",
        help="Inline submitted code text. Use this or --code-file.",
    )
    parser.add_argument("--round-key", default="L4", help="Round key (default: L4)")
    parser.add_argument(
        "--round-label",
        default="Coding Challenge (Python)",
        help="Round label (default: Coding Challenge (Python))",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional session id. Default uses generated backfill timestamp id.",
    )
    parser.add_argument(
        "--role",
        default=None,
        help="Optional role label. If omitted, script tries DB candidate report role.",
    )

    args = parser.parse_args()

    if not args.code_file and not args.code_text:
        parser.error("Provide one of --code-file or --code-text")

    if args.code_file and args.code_text:
        parser.error("Use only one of --code-file or --code-text")

    if args.code_file:
        with open(args.code_file, "r", encoding="utf-8") as f:
            submitted_code = f.read()
    else:
        submitted_code = args.code_text or ""

    app = create_app()
    with app.app_context():
        role = args.role or "N/A"
        candidate_data = get_candidate_report_data(args.email)
        if candidate_data and candidate_data.get("role"):
            role = candidate_data["role"]

    save_coding_submission(
        session_id=args.session_id or _default_session_id(),
        email=args.email,
        round_key=args.round_key,
        round_label=args.round_label,
        role=role,
        language=args.language,
        question_title=args.question_title,
        question_text=args.question_text,
        submitted_code=submitted_code,
    )

    print("Backfill completed.")
    print(f"Email: {args.email}")
    print(f"Round: {args.round_key} ({args.round_label})")
    print("Saved to: app/runtime/coding_submissions.jsonl")


if __name__ == "__main__":
    main()
