from app.services.session_registry import PersistentSessionRegistry

# In-memory cache with DB fallback for cross-worker access
MCQ_SESSION_REGISTRY = PersistentSessionRegistry("mcq")
