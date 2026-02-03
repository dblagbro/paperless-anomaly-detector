"""Database models for anomaly detection tracking."""
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ProcessedDocument(Base):
    """Track documents that have been processed for anomaly detection."""

    __tablename__ = "processed_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paperless_doc_id = Column(Integer, unique=True, nullable=False, index=True)
    title = Column(String(500))
    created_date = Column(DateTime)
    processed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Anomaly detection results
    has_anomalies = Column(Boolean, default=False, nullable=False)
    anomaly_types = Column(JSON, default=list)  # List of detected anomaly types

    # Balance check results
    balance_check_status = Column(String(20))  # PASS, FAIL, NOT_APPLICABLE, ERROR
    balance_diff_amount = Column(Float)
    beginning_balance = Column(Float)
    ending_balance = Column(Float)
    calculated_balance = Column(Float)

    # Layout check results
    layout_score = Column(Float)  # 0-1, higher is better
    layout_status = Column(String(20))  # PASS, FAIL, NOT_APPLICABLE
    layout_issues = Column(JSON, default=list)  # Detailed list of layout problems with line numbers

    # Pattern detection results
    pattern_flags = Column(JSON, default=list)  # List of pattern issues found with locations

    # LLM analysis results (if enabled)
    llm_analysis = Column(Text)
    llm_confidence = Column(Float)

    # Error tracking
    processing_error = Column(Text)
    retry_count = Column(Integer, default=0)

    # Metadata
    document_type = Column(String(100))  # e.g., "bank_statement", "invoice", etc.
    tags_written = Column(JSON, default=list)  # Tags written back to Paperless
    custom_fields_written = Column(JSON, default=dict)

    def __repr__(self):
        return f"<ProcessedDocument(paperless_id={self.paperless_doc_id}, has_anomalies={self.has_anomalies})>"


class AnomalyLog(Base):
    """Detailed log of individual anomalies detected."""

    __tablename__ = "anomaly_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    paperless_doc_id = Column(Integer, nullable=False, index=True)
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    anomaly_type = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), default="medium")  # low, medium, high, critical
    description = Column(Text)

    # Numeric context
    amount = Column(Float)  # For filtering by threshold

    # Additional context
    context = Column(JSON, default=dict)

    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)
    resolution_notes = Column(Text)

    def __repr__(self):
        return f"<AnomalyLog(doc_id={self.paperless_doc_id}, type={self.anomaly_type})>"
