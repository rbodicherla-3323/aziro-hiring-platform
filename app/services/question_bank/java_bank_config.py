from app.services.question_bank.enterprise_bank_config import (
    ENTERPRISE_BALANCED_DIFFICULTY_MIX,
    ENTERPRISE_BANK_POLICIES,
    ENTERPRISE_ROLE_ROUND_BANKS,
    get_enterprise_bank_policy,
)

JAVA_BANK_VERSION = 'enterprise_java_v2'
JAVA_ENTERPRISE_ROLE_KEYS = {'java_entry', 'java_qa', 'java_aws'}
JAVA_BALANCED_DIFFICULTY_MIX = dict(ENTERPRISE_BALANCED_DIFFICULTY_MIX)
JAVA_ROLE_ROUND_BANKS = {
    key: value
    for key, value in ENTERPRISE_ROLE_ROUND_BANKS.items()
    if key[0] in JAVA_ENTERPRISE_ROLE_KEYS
}
JAVA_BANK_POLICIES = {
    source_name: policy
    for source_name, policy in ENTERPRISE_BANK_POLICIES.items()
    if policy.get('role_key') in JAVA_ENTERPRISE_ROLE_KEYS or policy.get('role_key') == 'java_shared_senior'
}


def get_java_bank_files(role_key, round_key):
    return JAVA_ROLE_ROUND_BANKS.get((role_key, round_key), [])


def get_java_bank_policy(source_name=None, role_key=None, round_key=None):
    return get_enterprise_bank_policy(source_name=source_name, role_key=role_key, round_key=round_key)


def is_enterprise_java_role(role_key):
    return role_key in JAVA_ENTERPRISE_ROLE_KEYS
