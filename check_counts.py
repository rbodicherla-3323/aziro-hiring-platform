import json

files = [
    'app/services/question_bank/data/c/c_theory.json',
    'app/services/question_bank/data/bmc/bmc_firmware.json',
    'app/services/question_bank/data/linux/linux_kernel.json',
    'app/services/question_bank/data/device_driver/device_driver_basics.json',
    'app/services/question_bank/data/cpp/cpp_theory.json',
    'app/services/question_bank/data/system_design/system_design_architecture.json',
    'app/services/question_bank/data/soft_skills_leadership.json',
]

for f in files:
    try:
        data = json.load(open(f, encoding='utf-8'))
        if isinstance(data, dict):
            data = data.get('questions', [])
        print(f'{f}: {len(data)} questions')
    except Exception as e:
        print(f'{f}: ERROR - {e}')
