from app.services.runtime_session_store import (
    clear_runtime_session_data,
    get_runtime_session_data,
    set_runtime_session_data,
)


def coding_session_key(session_id):
    return f"coding_{session_id}"


def get_coding_session_data(session_id):
    return get_runtime_session_data("coding", session_id)


def set_coding_session_data(session_id, data):
    set_runtime_session_data("coding", session_id, data)


def clear_coding_session_data(session_id):
    clear_runtime_session_data("coding", session_id)
