from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True, nullable=False)
    filepath = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=_utcnow, nullable=False)
    status = Column(String, default="uploaded", nullable=False)
    text = Column(Text, nullable=True)
    character_count = Column(Integer, nullable=True)

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
