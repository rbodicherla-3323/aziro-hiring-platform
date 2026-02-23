MCQ_RUNTIME_STORE = {}


def mcq_session_key(session_id):
    return f"mcq_{session_id}"


def get_mcq_session_data(session_id):
    return MCQ_RUNTIME_STORE.get(mcq_session_key(session_id))


def set_mcq_session_data(session_id, data):
    MCQ_RUNTIME_STORE[mcq_session_key(session_id)] = data


def clear_mcq_session_data(session_id):
    MCQ_RUNTIME_STORE.pop(mcq_session_key(session_id), None)
