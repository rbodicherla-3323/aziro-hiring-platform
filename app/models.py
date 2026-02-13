from datetime import datetime, timezone
from app.extensions import db


class Candidate(db.Model):
    """Stores candidate info — one row per unique email."""

    __tablename__ = "candidates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False, unique=True, index=True)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    test_sessions = db.relationship(
        "TestSession", back_populates="candidate", lazy="dynamic"
    )

    def __repr__(self):
        return f"<Candidate {self.name} ({self.email})>"


class TestSession(db.Model):
    """One test session = one interview drive for a candidate."""

    __tablename__ = "test_sessions"

    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(
        db.Integer, db.ForeignKey("candidates.id"), nullable=False, index=True
    )
    role_key = db.Column(db.String(50), nullable=False)
    role_label = db.Column(db.String(200), nullable=False)
    batch_id = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    candidate = db.relationship("Candidate", back_populates="test_sessions")
    round_results = db.relationship(
        "RoundResult", back_populates="test_session", lazy="dynamic"
    )

    def __repr__(self):
        return f"<TestSession {self.batch_id} – {self.role_label}>"


class RoundResult(db.Model):
    """Score for one round (L1, L2, L3, L5, L6) within a test session."""

    __tablename__ = "round_results"

    id = db.Column(db.Integer, primary_key=True)
    test_session_id = db.Column(
        db.Integer, db.ForeignKey("test_sessions.id"), nullable=False, index=True
    )
    round_key = db.Column(db.String(10), nullable=False)       # L1, L2, ...
    round_label = db.Column(db.String(200), nullable=False)     # "Aptitude"
    total_questions = db.Column(db.Integer, default=15)
    attempted = db.Column(db.Integer, default=0)
    correct = db.Column(db.Integer, default=0)
    percentage = db.Column(db.Float, default=0.0)
    pass_threshold = db.Column(db.Integer, default=70)
    status = db.Column(db.String(20), default="Not Attempted")  # PASS / FAIL / Not Attempted
    time_taken_seconds = db.Column(db.Integer, default=0)
    submitted_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    test_session = db.relationship("TestSession", back_populates="round_results")

    def __repr__(self):
        return f"<RoundResult {self.round_key}: {self.status}>"


class Report(db.Model):
    """Tracks generated PDF reports per candidate per session."""

    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    test_session_id = db.Column(
        db.Integer, db.ForeignKey("test_sessions.id"), nullable=False, index=True
    )
    generated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    pdf_filename = db.Column(db.String(300), nullable=False)

    # Relationships
    test_session = db.relationship("TestSession")

    def __repr__(self):
        return f"<Report {self.pdf_filename}>"
