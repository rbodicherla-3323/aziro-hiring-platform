import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root deterministically (works in stdin / script / module runs).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")
AI_CLIENT = None


def _get_ai_client():
    """Lazily initialize Gemini client from environment."""
    global AI_CLIENT

    if AI_CLIENT is not None:
        return AI_CLIENT

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    # Lazy import to avoid importing Google SDK when key is not configured.
    from google import genai
    AI_CLIENT = genai.Client(api_key=api_key)
    return AI_CLIENT


def _build_fallback_summary(candidate_data):
    """Return deterministic summary text when AI is unavailable."""
    if not isinstance(candidate_data, dict):
        return "Evaluation data is available, but AI summary generation is not configured."

    name = candidate_data.get("name", "Candidate")
    role = candidate_data.get("role", "N/A")
    summary = candidate_data.get("summary", {}) or {}
    rounds = candidate_data.get("rounds", {}) or {}

    attempted_rounds = summary.get("attempted_rounds", 0)
    total_rounds = summary.get("total_rounds", len(rounds))
    passed_rounds = summary.get("passed_rounds", 0)
    failed_rounds = summary.get("failed_rounds", 0)

    lines = [
        (
            f"{name} was evaluated for the {role} role. "
            "This overall summary captures performance across all evaluation rounds for TA review."
        ),
        "",
        (
            f"The candidate attempted {attempted_rounds}/{total_rounds} rounds, "
            f"passing {passed_rounds} and failing {failed_rounds}."
        ),
        "",
        "**Round-wise Detailed Insights:**",
    ]
    ordered_rounds = ["L1", "L2", "L3", "L4", "L5"]
    for rk in ordered_rounds:
        rv = rounds.get(rk)
        if not rv:
            continue
        round_label = rv.get("round_label", rk)
        status = rv.get("status", "Pending")
        pct = rv.get("percentage", 0)
        correct = rv.get("correct", 0)
        total = rv.get("total", 0)
        threshold = rv.get("pass_threshold", 0)

        lines.append(
            f"- **{round_label} ({rk})**: Status = {status}; Score = {pct}% ({correct}/{total}); "
            f"Pass Threshold = {threshold}%."
        )

    return "\n".join(lines)


def _normalize_overall_summary(text: str) -> str:
    """Remove explicit Overall Evaluation heading while preserving content."""
    if not text:
        return text

    cleaned = []
    blocked = {
        "overall evaluation",
        "### overall evaluation",
        "**overall evaluation:**",
    }
    for line in str(text).splitlines():
        normalized = line.strip().lower()
        if normalized in blocked:
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _build_fallback_coding_summary(coding_data):
    """Return deterministic coding-only summary when AI is unavailable."""
    if not isinstance(coding_data, dict):
        return "Coding submission data is unavailable."
    
    round_label = coding_data.get("round_label", "Coding Round")
    status = coding_data.get("status", "Not Attempted")
    percentage = coding_data.get("percentage", 0)
    correct = coding_data.get("correct", 0)
    total = coding_data.get("total", 0)
    language = coding_data.get("language", "")
    question_title = coding_data.get("question_title", "")
    question_text = coding_data.get("question_text", "")
    submitted_code = coding_data.get("submitted_code", "")
    overall_rounds = coding_data.get("overall_rounds", {}) or {}

    insight_lines = []
    for rk in ["L1", "L2", "L3", "L4", "L5"]:
        rd = overall_rounds.get(rk)
        if not rd:
            continue
        insight_lines.append(
            f"- {rk} {rd.get('round_label', rk)}: {rd.get('status', 'Pending')} "
            f"({rd.get('percentage', 0)}%, {rd.get('correct', 0)}/{rd.get('total', 0)})"
        )
    key_insights = "\n".join(insight_lines) if insight_lines else "- Round-wise insights not available."

    return (
        "Key Insights:\n"
        f"{key_insights}\n\n"
        "Coding Round Summary\n"
        f"Round: {round_label}\n"
        f"Score: {percentage}% ({correct}/{total})\n"
        f"Language: {language}\n"
        f"Question: {question_title}\n"
        f"Problem Statement: {question_text}\n"
        f"Submitted Code:\n{submitted_code if submitted_code else 'No submitted code found.'}"
    )


def _strip_coding_overview_lines(text: str) -> str:
    """Remove high-level candidate/application overview lines from coding summary."""
    if not text:
        return text

    blocked_prefixes = (
        "Candidate:",
        "Role Applied For:",
        "Overall Application Status:",
        "Summary of Rounds:",
        "Total Rounds Attempted:",
        "Passed Rounds:",
        "Failed Rounds:",
        "Overall Correct Answers:",
        "Overall Percentage:",
    )

    cleaned_lines = []
    for line in str(text).splitlines():
        stripped = line.strip().lstrip("•").strip()
        if any(stripped.startswith(prefix) for prefix in blocked_prefixes):
            continue
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def generate_evaluation_summary(candidate_data):
    """
    Generate an AI-based summary for a candidate's evaluation.
    candidate_data: dict containing candidate's evaluation details.
    Returns a summary string or None.
    """
    ai_client = _get_ai_client()
    if not ai_client:
        print("Gemini AI client not initialized. Using fallback summary.")
        return _normalize_overall_summary(_build_fallback_summary(candidate_data))

    prompt = f""" 
    Create a professional overall evaluation summary for TA review from the candidate data below.

    Required structure:
    1) Intro paragraph with candidate name and role.
    2) One concise paragraph with overall performance snapshot (no heading for this paragraph).
    3) Section heading: "Round-wise Detailed Insights"
    4) Bullet points for every available round (L1 to L5), each bullet must include:
       - One short narrative insight sentence about performance in that round.

    Constraints:
    - Do not provide verdicts or pass/fail labels in the bullet points; keep bullets narrative and factual.
    - Do not mention AI-generated content.
    - Do not include submitted code or submitted responses in this overall summary.
    - Do not output a table; use bullet points for round details.
    - Do not output a heading titled "Overall Evaluation".
    - Use only provided data; do not invent.

    Candidate data:
    {candidate_data} """

    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return _normalize_overall_summary(response.text.strip())
    except Exception as e:
        print(f"Error generating summary: {e}. Using fallback summary.")
        return _normalize_overall_summary(_build_fallback_summary(candidate_data))


def generate_coding_round_summary(coding_data):
    """
    Generate an AI-based summary for coding round with question and submitted code.
    """
    ai_client = _get_ai_client()
    if not ai_client:
        print("Gemini AI client not initialized. Using fallback coding summary.")
        return _strip_coding_overview_lines(_build_fallback_coding_summary(coding_data))

    prompt = f"""
    Rewrite the following coding round data into a professional, HR-readable summary.

    Requirements:
    - Do not mention AI or that this was generated by AI.
    - Do NOT include lines like:
      "Candidate: ...", "Role Applied For: ...", "Overall Application Status: ...",
      "Summary of Rounds: ...", "Total Rounds Attempted: ...", "Passed/Failed ...",
      "Overall Correct Answers ...", or "Overall Percentage ...".
    - Start with section title: "Key Insights"
    - Add section title: "Key Insights" one insight if code logic is correct but not able to fetch output, another insight if code is efficient or not based on time/space complexity.
    - Include coding question title and short problem statement.
    - Include submitted code exactly as provided under a "Submitted Code" section.
    - Keep tone factual and concise.

    Coding Round Data:
    {coding_data}
    """
    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return _strip_coding_overview_lines(response.text.strip())
    except Exception as e:
        print(f"Error generating coding summary: {e}. Using fallback coding summary.")
        return _strip_coding_overview_lines(_build_fallback_coding_summary(coding_data))
