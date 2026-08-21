from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    # Supabase Auth JWT "sub" claim - the stable external identity. Never a
    # password or credential of any kind; Supabase owns authentication.
    external_auth_id = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    documents = relationship("Document", back_populates="owner")
    subscription = relationship(
        "Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True)
    stripe_customer_id = Column(String, unique=True, index=True, nullable=True)
    stripe_subscription_id = Column(String, unique=True, index=True, nullable=True)
    plan = Column(String, nullable=False, default="free")
    status = Column(String, nullable=False, default="inactive")
    current_period_end = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    user = relationship("User", back_populates="subscription")


class ProcessedStripeEvent(Base):
    """Idempotency ledger for Stripe webhook events - Stripe may deliver the
    same event more than once, and each event.id must be processed at most
    once."""

    __tablename__ = "processed_stripe_events"

    event_id = Column(String, primary_key=True)
    processed_at = Column(DateTime, default=_utcnow, nullable=False)


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True, nullable=False)
    filepath = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=_utcnow, nullable=False)
    status = Column(String, default="uploaded", nullable=False)
    text = Column(Text, nullable=True)
    character_count = Column(Integer, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Document Intelligence layer (all nullable: unset until the
    # deterministic post-processing engines run on an analyzed document).
    # LLM output is a signal only - these are the deterministic engines'
    # final classification, distinct from the free-form
    # DocumentAIAnalysis.document_type the LLM returns.
    sender_category = Column(String, nullable=True)
    sender_institution = Column(String, nullable=True)
    document_type = Column(String, nullable=True)
    priority_level = Column(String, nullable=True)  # critical/high/normal/low
    priority_reasoning = Column(Text, nullable=True)
    deadline_raw_text = Column(String, nullable=True)
    deadline_type = Column(String, nullable=True)  # absolute/relative/none
    deadline_estimated_date = Column(DateTime, nullable=True)
    deadline_certainty = Column(String, nullable=True)  # exact/estimated/unknown_needs_review
    requires_action = Column(Boolean, nullable=True)
    action_summary = Column(Text, nullable=True)

    owner = relationship("User", back_populates="documents")
    analyses = relationship(
        "DocumentAIAnalysis",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentAIAnalysis.created_at",
    )


class DocumentAIAnalysis(Base):
    __tablename__ = "document_ai_analyses"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    document_type = Column(String, nullable=True)
    language = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    turkish_explanation = Column(Text, nullable=True)
    important_dates = Column(Text, nullable=True)
    extracted_entities = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    document = relationship("Document", back_populates="analyses")
