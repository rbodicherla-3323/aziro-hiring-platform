import json, statistics

with open('app/services/question_bank/data/python/python_theory.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

questions = data if isinstance(data, list) else data.get('questions', [])
print(f'Total questions: {len(questions)}')

# Difficulty distribution
diff_counts = {}
for q in questions:
    d = q.get('difficulty', 'MISSING')
    diff_counts[d] = diff_counts.get(d, 0) + 1
print(f'Difficulty distribution: {diff_counts}')

# Validate structure
errors = 0
for i, q in enumerate(questions):
    for key in ['question', 'options', 'correct_answer', 'topic', 'difficulty']:
        if key not in q:
            print(f'  Q{i+1}: MISSING field "{key}"')
            errors += 1
    opts = q.get('options', [])
    if len(opts) != 4:
        print(f'  Q{i+1}: has {len(opts)} options (expected 4)')
        errors += 1
    ca = q.get('correct_answer', '')
    if ca not in opts:
        print(f'  Q{i+1}: correct_answer not in options: {repr(ca)}')
        errors += 1
    if len(set(opts)) != len(opts):
        print(f'  Q{i+1}: duplicate options found')
        errors += 1

print(f'Structural errors: {errors}')

# Option length bias analysis
correct_lens = []
incorrect_lens = []
longest_is_correct = 0
for q in questions:
    opts = q.get('options', [])
    ca = q.get('correct_answer', '')
    correct_lens.append(len(ca))
    for o in opts:
        if o != ca:
            incorrect_lens.append(len(o))
    longest = max(opts, key=len)
    if longest == ca:
        longest_is_correct += 1

print()
print(f'Avg correct answer length: {statistics.mean(correct_lens):.1f} chars')
print(f'Avg incorrect answer length: {statistics.mean(incorrect_lens):.1f} chars')
print(f'Longest option is correct: {longest_is_correct}/{len(questions)} ({100*longest_is_correct/len(questions):.1f}%)')

# Correct answer position distribution
pos_counts = {0:0, 1:0, 2:0, 3:0}
for q in questions:
    opts = q.get('options', [])
    ca = q.get('correct_answer', '')
    if ca in opts:
        pos_counts[opts.index(ca)] += 1
print(f'Correct answer position distribution: {pos_counts}')

# Topics
topics = {}
for q in questions:
    t = q.get('topic', 'MISSING')
    topics[t] = topics.get(t, 0) + 1
print()
print(f'Topics ({len(topics)}):')
for t, c in sorted(topics.items(), key=lambda x: -x[1]):
    print(f'  {t}: {c}')

# Debugging questions
debug_qs = [q for q in questions if any(kw in q['question'].lower() for kw in ['output', 'print', 'what does', 'what will', 'debug', 'error', 'traceback', 'exception'])]
print()
print(f'Debugging/output questions: {len(debug_qs)}')
