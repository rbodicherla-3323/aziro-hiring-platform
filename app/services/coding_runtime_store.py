CODING_RUNTIME_STORE = {}


def coding_session_key(session_id):
    return f"coding_{session_id}"


def get_coding_session_data(session_id):
    return CODING_RUNTIME_STORE.get(coding_session_key(session_id))


def set_coding_session_data(session_id, data):
    CODING_RUNTIME_STORE[coding_session_key(session_id)] = data


def clear_coding_session_data(session_id):
    CODING_RUNTIME_STORE.pop(coding_session_key(session_id), None)
