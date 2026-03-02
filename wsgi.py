"""Production WSGI entry point — used by Gunicorn / Docker."""
from app import create_app

app = create_app()
