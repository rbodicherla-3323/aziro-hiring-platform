from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.extensions import oauth

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # SAME OLD LOGIC
        if username and username.endswith("@aziro.com"):
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("dashboard.dashboard"))

        return render_template(
            "login.html",
            error="Invalid credentials. Please try again."
        )

    return render_template("login.html")


@auth_bp.route("/google-login")
def google_login():
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri, prompt="login")


@auth_bp.route("/google-callback")
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
        user_info = oauth.google.get(
            "https://openidconnect.googleapis.com/v1/userinfo"
        ).json()

        email = user_info.get("email")

        if not email or not email.endswith("@aziro.com"):
            flash("Only aziro.com accounts are allowed.")
            return redirect(url_for("auth.login"))

        session["logged_in"] = True
        session["username"] = email

        return redirect(url_for("dashboard.dashboard"))

    except Exception as e:
        return f"OAuth failed: {e}", 400


@auth_bp.route("/forgot-password-google")
def forgot_password_google():
    # SAME AS OLD PROJECT
    return redirect(url_for("auth.google_login"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
