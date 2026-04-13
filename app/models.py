# filepath: d:\Projects\aziro-hiring-platform\app\models.py
from datetime import datetime, timezone
from app.extensions import db


class Candidate(db.Model):
    __tablename__ = "candidates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    test_sessions = db.relationship("TestSession", backref="candidate", lazy=True)

    def __repr__(self):
        return f"<Candidate {self.name} ({self.email})>"


class TestSession(db.Model):
    __tablename__ = "test_sessions"

    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidates.id"), nullable=False)
    role_key = db.Column(db.String(100), nullable=False)
    role_label = db.Column(db.String(200), nullable=False, default="")
    batch_id = db.Column(db.String(100), nullable=False, default="")
    created_by = db.Column(db.String(200), nullable=True, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    round_results = db.relationship("RoundResult", backref="test_session", lazy=True)

    def __repr__(self):
        return f"<TestSession {self.id} role={self.role_key}>"


class RoundResult(db.Model):
    __tablename__ = "round_results"

    id = db.Column(db.Integer, primary_key=True)
    test_session_id = db.Column(db.Integer, db.ForeignKey("test_sessions.id"), nullable=False)
    session_uuid = db.Column(db.String(100), nullable=True, default="")
    round_key = db.Column(db.String(20), nullable=False)
    round_type = db.Column(db.String(20), nullable=True, default="mcq")
    round_label = db.Column(db.String(200), nullable=False, default="")
    test_link = db.Column(db.String(500), nullable=True, default="")
    total_questions = db.Column(db.Integer, default=0)
    attempted = db.Column(db.Integer, default=0)
    correct = db.Column(db.Integer, default=0)
    percentage = db.Column(db.Float, default=0.0)
    pass_threshold = db.Column(db.Float, default=70.0)
    status = db.Column(db.String(20), default="Pending")
    time_taken_seconds = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<RoundResult {self.round_key} {self.status}>"


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    candidate_email = db.Column(db.String(200), nullable=False, default="")
    test_session_id = db.Column(db.Integer, db.ForeignKey("test_sessions.id"), nullable=True)
    filename = db.Column(db.String(500), nullable=False)
    generated_by = db.Column(db.String(200), nullable=True, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    test_session = db.relationship("TestSession", backref="reports", lazy=True)

    def __repr__(self):
        return f"<Report {self.filename}>"

class ProctoringScreenshot(db.Model):
    __tablename__ = "proctoring_screenshots"

    id = db.Column(db.Integer, primary_key=True)
    session_uuid = db.Column(db.String(100), nullable=True, index=True, default="")
    candidate_email = db.Column(db.String(200), nullable=True, index=True, default="")
    candidate_name = db.Column(db.String(200), nullable=True, default="")
    round_key = db.Column(db.String(20), nullable=True, default="")
    round_label = db.Column(db.String(200), nullable=True, default="")
    source = db.Column(db.String(20), nullable=False, default="mcq")
    event_type = db.Column(db.String(50), nullable=True, default="screenshot")
    mime_type = db.Column(db.String(50), nullable=False, default="image/png")
    image_bytes = db.Column(db.LargeBinary, nullable=False)
    image_size = db.Column(db.Integer, nullable=False, default=0)
    screenshot_path = db.Column(db.String(500), nullable=True, default="")
    captured_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<ProctoringScreenshot {self.id} {self.candidate_email}>"


class AccessApproval(db.Model):
    __tablename__ = "access_approvals"

    email = db.Column(db.String(320), primary_key=True)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    approved_by = db.Column(db.String(320), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    requested_at = db.Column(db.DateTime, nullable=True)
    last_notified_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<AccessApproval {self.email} active={self.is_active}>"


class TestLink(db.Model):
    __tablename__ = "test_links"

    session_id = db.Column(db.String(64), primary_key=True)
    test_type = db.Column(db.String(20), nullable=False, default="mcq")
    candidate_name = db.Column(db.String(200), nullable=True, default="")
    candidate_email = db.Column(db.String(200), nullable=False, index=True)
    role_key = db.Column(db.String(100), nullable=True, default="")
    role_label = db.Column(db.String(200), nullable=True, default="")
    round_key = db.Column(db.String(20), nullable=True, default="")
    round_label = db.Column(db.String(200), nullable=True, default="")
    batch_id = db.Column(db.String(100), nullable=True, default="")
    domain = db.Column(db.String(100), nullable=True)
    language = db.Column(db.String(50), nullable=True, default="")
    created_by = db.Column(db.String(200), nullable=True, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=True, index=True)

    def __repr__(self):
        return f"<TestLink {self.session_id} {self.test_type}>"


class AIProviderConfig(db.Model):
    __tablename__ = "ai_provider_configs"

    provider_key = db.Column(db.String(50), primary_key=True)
    is_enabled = db.Column(db.Boolean, nullable=False, default=False)
    api_key_encrypted = db.Column(db.Text, nullable=True, default="")
    api_key_last4 = db.Column(db.String(16), nullable=True, default="")
    default_model = db.Column(db.String(120), nullable=True, default="")
    updated_by = db.Column(db.String(320), nullable=True, default="")
    updated_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<AIProviderConfig {self.provider_key} enabled={self.is_enabled}>"


class AIFeatureSetting(db.Model):
    __tablename__ = "ai_feature_settings"

    feature_key = db.Column(db.String(80), primary_key=True)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)
    primary_provider = db.Column(db.String(50), nullable=True, default="")
    fallback_provider = db.Column(db.String(50), nullable=True, default="")
    model_override = db.Column(db.String(120), nullable=True, default="")
    fallback_model_override = db.Column(db.String(120), nullable=True, default="")
    updated_by = db.Column(db.String(320), nullable=True, default="")
    updated_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return (
            f"<AIFeatureSetting {self.feature_key} primary={self.primary_provider} "
            f"fallback={self.fallback_provider}>"
        )
