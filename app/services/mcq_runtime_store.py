from app.services.runtime_session_store import (
    clear_runtime_session_data,
    get_runtime_session_data,
    set_runtime_session_data,
)


def mcq_session_key(session_id):
    return f"mcq_{session_id}"


def get_mcq_session_data(session_id):
    return get_runtime_session_data("mcq", session_id)


def set_mcq_session_data(session_id, data):
    set_runtime_session_data("mcq", session_id, data)


def clear_mcq_session_data(session_id):
    clear_runtime_session_data("mcq", session_id)
