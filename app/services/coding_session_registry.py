from app.services.session_registry import PersistentSessionRegistry

# In-memory cache with DB fallback for cross-worker access
CODING_SESSION_REGISTRY = PersistentSessionRegistry("coding")
