import base64
import json
import re
from datetime import datetime
from pathlib import Path

json_path = Path("app/mnh/cv_details/cv_details.json")
upload_dir = Path("app/uploads")

try:
    if not json_path.exists():
        raise FileNotFoundError(f"Input JSON not found: {json_path}")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    data = payload.get("data", {})

    source_file_name = data.get("fileName")
    cv_content = data.get("cvContent")

    candidate_stem = Path(source_file_name).stem
    candidate_name = re.sub(r"\[[^\]]*\]", "", candidate_stem).strip()
    candidate_name = re.sub(r"[^A-Za-z0-9_\- ]+", "", candidate_name).replace(" ", "_")
    if not candidate_name:
        candidate_name = "candidate"

    if not source_file_name:
        raise ValueError(f"Missing CV of the Candidate {candidate_name} in JSON")
    if not cv_content:
        raise ValueError("Missing data.cvContent in JSON")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"{candidate_name}_resume_{timestamp}.pdf"

    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / output_name
    target.write_bytes(base64.b64decode(cv_content))

    print(f"PDF uploaded to hiring app: {target}")

except Exception as e:
    print(f"Error: {e}")
