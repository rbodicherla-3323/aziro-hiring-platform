"""Fix position bias in python_theory.json by shuffling option order per question."""
import json
import random

random.seed(42)  # reproducible

path = 'app/services/question_bank/data/python/python_theory.json'

with open(path, 'r', encoding='utf-8') as f:
    questions = json.load(f)

for q in questions:
    random.shuffle(q['options'])

# Verify correct_answer still in options
for i, q in enumerate(questions):
    assert q['correct_answer'] in q['options'], f"Q{i+1}: correct_answer missing after shuffle"

# Check new position distribution
pos_counts = {0: 0, 1: 0, 2: 0, 3: 0}
for q in questions:
    idx = q['options'].index(q['correct_answer'])
    pos_counts[idx] += 1
print(f"New position distribution: {pos_counts}")

with open(path, 'w', encoding='utf-8') as f:
    json.dump(questions, f, indent=2, ensure_ascii=False)

print(f"Done — {len(questions)} questions written with shuffled options.")
