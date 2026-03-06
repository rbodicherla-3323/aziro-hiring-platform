import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

    # Static asset version — bump on deploy to bust browser cache
    ASSET_VERSION = "2"

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

    # 🔴 DEV MODE AUTH BYPASS
    AUTH_DISABLED = False

    # ---------------------------------------------------------------
    # DATABASE
    # ---------------------------------------------------------------
    # For local Windows dev  : sqlite (zero setup)
    # For Ubuntu VM (prod)   : postgresql
    #
    # Set DATABASE_URL in .env to override:
    #   DATABASE_URL=postgresql://aziro:yourpass@localhost/aziro_hiring
    # ---------------------------------------------------------------
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///aziro_hiring.db"           # fallback for local dev
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
