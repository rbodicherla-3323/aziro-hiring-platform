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
    test_session_id = db.Column(db.Integer, db.ForeignKey("test_sessions.id"), nullable=True)
    candidate_email = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(500), nullable=False)
    generated_by = db.Column(db.String(200), nullable=True, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Report {self.filename}>"
