import json
import os

files = [
    'app/services/question_bank/data/c/c_theory.json',
    'app/services/question_bank/data/bmc/bmc_firmware.json',
    'app/services/question_bank/data/linux/linux_kernel.json',
    'app/services/question_bank/data/device_driver/device_driver_basics.json',
    'app/services/question_bank/data/cpp/cpp_theory.json',
    'app/services/question_bank/data/system_design/system_design_architecture.json',
    'app/services/question_bank/data/soft_skills_leadership.json',
]

all_ok = True
for f in files:
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data = data.get('questions', [])
        # Validate each question has required fields
        for i, q in enumerate(data):
            for key in ['question', 'options', 'correct_answer', 'topic', 'difficulty']:
                if key not in q:
                    print(f"  MISSING '{key}' in question {i+1} of {f}")
                    all_ok = False
            if len(q.get('options', [])) != 4:
                print(f"  Question {i+1} in {f} has {len(q['options'])} options (expected 4)")
                all_ok = False
            if q.get('correct_answer') not in q.get('options', []):
                print(f"  Question {i+1} in {f}: correct_answer not in options")
                print(f"    correct_answer: {q.get('correct_answer')}")
                all_ok = False
        print(f"OK: {f} - {len(data)} questions, all valid")
    except Exception as e:
        print(f"ERROR: {f} - {e}")
        all_ok = False

print()
if all_ok:
    print("ALL FILES VALID!")
else:
    print("SOME FILES HAVE ISSUES - see above")
