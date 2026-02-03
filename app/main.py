"""Main FastAPI application for anomaly detection system."""
import logging
import sys
from datetime import datetime
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from config import settings
from database import init_db, get_db_session, engine
from models import ProcessedDocument, AnomalyLog
from paperless_client import PaperlessClient
from detector import AnomalyDetector
from scheduler import DocumentScheduler

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Global instances
scheduler = DocumentScheduler()
paperless_client = PaperlessClient()
detector = AnomalyDetector()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events."""
    # Startup
    logger.info("Starting Anomaly Detection System...")
    logger.info(f"Paperless API: {settings.paperless_api_base_url}")
    logger.info(f"Polling interval: {settings.polling_interval} seconds")

    # Initialize database
    init_db()

    # Start scheduler
    scheduler.start(paperless_client, detector)

    yield

    # Shutdown
    logger.info("Shutting down...")
    scheduler.stop()


# Create FastAPI app
app = FastAPI(
    title="Paperless Anomaly Detector",
    description="Automated anomaly detection for Paperless-ngx documents",
    version="1.0.0",
    lifespan=lifespan
)

# API Endpoints

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db_session)):
    """Get overall statistics."""
    try:
        total_docs = db.query(ProcessedDocument).count()
        docs_with_anomalies = db.query(ProcessedDocument).filter(
            ProcessedDocument.has_anomalies == True
        ).count()
        total_anomalies = db.query(AnomalyLog).count()

        # Anomalies by type
        from sqlalchemy import func
        anomaly_counts = db.query(
            AnomalyLog.anomaly_type,
            func.count(AnomalyLog.id).label('count')
        ).group_by(AnomalyLog.anomaly_type).all()

        return {
            "total_documents": total_docs,
            "documents_with_anomalies": docs_with_anomalies,
            "total_anomalies": total_anomalies,
            "anomaly_breakdown": {anom_type: count for anom_type, count in anomaly_counts}
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/documents")
def get_documents(
    anomaly_type: Optional[str] = Query(None, description="Filter by anomaly type"),
    min_amount: Optional[float] = Query(None, description="Minimum anomaly amount"),
    max_amount: Optional[float] = Query(None, description="Maximum anomaly amount"),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    has_anomalies: Optional[bool] = Query(None, description="Filter by anomaly presence"),
    limit: int = Query(100, le=1000, description="Maximum results"),
    offset: int = Query(0, description="Offset for pagination"),
    db: Session = Depends(get_db_session)
):
    """Get processed documents with filters."""
    try:
        query = db.query(ProcessedDocument)

        # Apply filters
        if has_anomalies is not None:
            query = query.filter(ProcessedDocument.has_anomalies == has_anomalies)

        if anomaly_type:
            query = query.filter(ProcessedDocument.anomaly_types.contains([anomaly_type]))

        if min_amount is not None:
            query = query.filter(ProcessedDocument.balance_diff_amount >= min_amount)

        if max_amount is not None:
            query = query.filter(ProcessedDocument.balance_diff_amount <= max_amount)

        if date_from:
            query = query.filter(ProcessedDocument.created_date >= datetime.fromisoformat(date_from))

        if date_to:
            query = query.filter(ProcessedDocument.created_date <= datetime.fromisoformat(date_to))

        # Order by most recent first
        query = query.order_by(ProcessedDocument.processed_at.desc())

        # Get total count before pagination
        total = query.count()

        # Apply pagination
        documents = query.offset(offset).limit(limit).all()

        # Convert to dict
        results = []
        for doc in documents:
            results.append({
                "id": doc.id,
                "paperless_doc_id": doc.paperless_doc_id,
                "title": doc.title,
                "created_date": doc.created_date.isoformat() if doc.created_date else None,
                "processed_at": doc.processed_at.isoformat() if doc.processed_at else None,
                "has_anomalies": doc.has_anomalies,
                "anomaly_types": doc.anomaly_types,
                "document_type": doc.document_type,
                "balance_check_status": doc.balance_check_status,
                "balance_diff_amount": doc.balance_diff_amount,
                "beginning_balance": doc.beginning_balance,
                "ending_balance": doc.ending_balance,
                "calculated_balance": doc.calculated_balance,
                "layout_score": doc.layout_score,
                "layout_status": doc.layout_status,
                "layout_issues": doc.layout_issues,
                "pattern_flags": doc.pattern_flags,
                "paperless_url": f"{settings.paperless_public_url}/documents/{doc.paperless_doc_id}"
            })

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "results": results
        }

    except Exception as e:
        logger.error(f"Error getting documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/anomalies")
def get_anomalies(
    anomaly_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    resolved: Optional[bool] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db_session)
):
    """Get anomaly logs with filters."""
    try:
        query = db.query(AnomalyLog)

        if anomaly_type:
            query = query.filter(AnomalyLog.anomaly_type == anomaly_type)

        if severity:
            query = query.filter(AnomalyLog.severity == severity)

        if resolved is not None:
            query = query.filter(AnomalyLog.resolved == resolved)

        query = query.order_by(AnomalyLog.detected_at.desc())

        total = query.count()
        anomalies = query.offset(offset).limit(limit).all()

        results = []
        for anom in anomalies:
            results.append({
                "id": anom.id,
                "paperless_doc_id": anom.paperless_doc_id,
                "detected_at": anom.detected_at.isoformat(),
                "anomaly_type": anom.anomaly_type,
                "severity": anom.severity,
                "description": anom.description,
                "amount": anom.amount,
                "resolved": anom.resolved
            })

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "results": results
        }

    except Exception as e:
        logger.error(f"Error getting anomalies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/trigger-scan")
def trigger_scan():
    """Manually trigger document scanning."""
    try:
        scheduler.trigger_now()
        return {"status": "triggered", "message": "Document scan started"}
    except Exception as e:
        logger.error(f"Error triggering scan: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/backfill")
def backfill_documents(batch_size: int = Query(50, description="Batch size for processing")):
    """Process all existing documents in Paperless (backfill)."""
    try:
        logger.info(f"Backfill requested with batch_size={batch_size}")
        scheduler.backfill_all_documents(batch_size=batch_size)
        return {
            "status": "triggered",
            "message": f"Backfill started - processing all documents in batches of {batch_size}"
        }
    except Exception as e:
        logger.error(f"Error triggering backfill: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=HTMLResponse)
def read_root():
    """Serve the main dashboard HTML."""
    with open("static/index.html", "r") as f:
        return f.read()


@app.get("/app.js")
def serve_app_js():
    """Serve the JavaScript file."""
    from fastapi.responses import FileResponse
    return FileResponse("static/app.js", media_type="application/javascript")


# Run the application
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.web_host,
        port=settings.web_port,
        reload=False,
        log_level=settings.log_level.lower()
    )
