"""Background job scheduler for polling Paperless and processing documents."""
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from database import get_db
from models import ProcessedDocument, AnomalyLog
from paperless_client import PaperlessClient
from detector import AnomalyDetector

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Process documents from Paperless and detect anomalies."""

    def __init__(self, paperless_client: PaperlessClient, detector: AnomalyDetector):
        self.paperless_client = paperless_client
        self.detector = detector

    def process_new_documents(self):
        """Poll Paperless for new documents and process them."""
        logger.info("Starting document processing job...")

        try:
            # Fetch recent documents from Paperless
            documents = self.paperless_client.get_recent_documents(
                minutes=settings.polling_interval // 60 + 10,  # Add buffer
                limit=settings.batch_size
            )

            if not documents:
                logger.info("No new documents to process")
                return

            logger.info(f"Found {len(documents)} documents to check")

            with get_db() as db:
                for doc in documents:
                    doc_id = doc["id"]

                    # Check if already processed
                    existing = db.query(ProcessedDocument).filter(
                        ProcessedDocument.paperless_doc_id == doc_id
                    ).first()

                    if existing:
                        logger.debug(f"Document {doc_id} already processed, skipping")
                        continue

                    # Process the document
                    logger.info(f"Processing document {doc_id}: {doc.get('title', 'Untitled')}")
                    self._process_document(db, doc)

                    # Commit after each document
                    try:
                        db.commit()
                    except Exception as commit_error:
                        logger.error(f"Commit failed for document {doc_id}: {commit_error}")
                        db.rollback()

            logger.info("Document processing job completed")

        except Exception as e:
            logger.error(f"Error in processing job: {e}", exc_info=True)

    def process_all_documents(self, batch_size: int = 50):
        """Process ALL documents in Paperless (backfill for existing documents)."""
        logger.info("Starting backfill of all documents...")

        try:
            # Fetch all documents without date filter
            all_documents = self.paperless_client.get_recent_documents(
                minutes=None,  # No time filter
                limit=None     # Paginate through all documents
            )

            if not all_documents:
                logger.info("No documents found in Paperless")
                return

            logger.info(f"Found {len(all_documents)} total documents in Paperless")

            processed_count = 0
            skipped_count = 0

            for doc in all_documents:
                doc_id = doc["id"]

                # Process each document in its own transaction
                with get_db() as db:
                    # Check if already processed
                    existing = db.query(ProcessedDocument).filter(
                        ProcessedDocument.paperless_doc_id == doc_id
                    ).first()

                    if existing:
                        skipped_count += 1
                        logger.debug(f"Document {doc_id} already processed, skipping")
                        continue

                    # Process the document
                    logger.info(f"Processing document {doc_id}: {doc.get('title', 'Untitled')[:50]}")
                    self._process_document(db, doc)
                    processed_count += 1
                    # Commit happens automatically when exiting the context manager

                # Log progress periodically
                if processed_count % batch_size == 0:
                    logger.info(f"Progress: {processed_count} processed, {skipped_count} skipped")

            logger.info(f"Backfill completed: {processed_count} documents processed, {skipped_count} already existed")

        except Exception as e:
            logger.error(f"Error in backfill job: {e}", exc_info=True)

    def _process_document(self, db, doc: dict):
        """Process a single document for anomaly detection."""
        doc_id = doc["id"]
        title = doc.get("title", "Untitled")

        try:
            # Get document content
            content = self.paperless_client.get_document_content(doc_id)
            if not content:
                logger.warning(f"No content available for document {doc_id}")
                content = ""

            # Get document file for image forensics (if it's an image/PDF)
            image_data = None
            mime_type = doc.get("mime_type", "")
            if mime_type and ("image" in mime_type or "pdf" in mime_type):
                try:
                    image_data = self.paperless_client.get_document_file(doc_id)
                except Exception as e:
                    logger.warning(f"Could not fetch file for forensics analysis: {e}")

            # Run anomaly detection
            detection_results = self.detector.detect_all_anomalies(doc, content, image_data)

            # Create database record
            processed_doc = ProcessedDocument(
                paperless_doc_id=doc_id,
                title=title,
                created_date=datetime.fromisoformat(doc["created"].replace("Z", "+00:00")) if doc.get("created") else None,
                has_anomalies=detection_results.get("has_anomalies", False),
                anomaly_types=detection_results.get("anomaly_types", []),
                document_type=detection_results.get("document_type", "unknown")
            )

            # Store balance check results
            if detection_results.get("balance_check"):
                bc = detection_results["balance_check"]
                processed_doc.balance_check_status = bc.get("status")
                processed_doc.balance_diff_amount = bc.get("difference")
                processed_doc.beginning_balance = bc.get("beginning_balance")
                processed_doc.ending_balance = bc.get("ending_balance")
                processed_doc.calculated_balance = bc.get("calculated_balance")

            # Store layout check results
            if detection_results.get("layout_check"):
                lc = detection_results["layout_check"]
                processed_doc.layout_status = lc.get("status")
                processed_doc.layout_score = lc.get("score")
                processed_doc.layout_issues = lc.get("details", [])

            # Store pattern flags
            if detection_results.get("pattern_check"):
                pc = detection_results["pattern_check"]
                processed_doc.pattern_flags = pc.get("flags", [])

            # Store LLM analysis
            if detection_results.get("llm_check"):
                llm = detection_results["llm_check"]
                processed_doc.llm_analysis = llm.get("analysis")
                processed_doc.llm_confidence = llm.get("confidence")

            # Create anomaly log entries
            for anomaly_type in detection_results.get("anomaly_types", []):
                anomaly_log = AnomalyLog(
                    paperless_doc_id=doc_id,
                    anomaly_type=anomaly_type,
                    description=self._get_anomaly_description(anomaly_type, detection_results),
                    severity=self._determine_severity(anomaly_type, detection_results),
                    amount=self._extract_amount(anomaly_type, detection_results)
                )
                db.add(anomaly_log)

            # Write results back to Paperless (gets tags/custom fields to store)
            self._write_to_paperless(doc_id, detection_results, processed_doc)

            # Save to database (ID will be assigned on commit)
            logger.debug(f"Adding processed_doc to session for doc_id={doc_id}, paperless_doc_id={processed_doc.paperless_doc_id}")
            db.add(processed_doc)
            logger.debug(f"Added processed_doc to session, pending={processed_doc in db.new}, dirty={processed_doc in db.dirty}")

            # Don't commit here - let the calling function handle batch commits
            logger.info(f"Successfully processed document {doc_id}: {len(detection_results.get('anomaly_types', []))} anomalies detected")

        except Exception as e:
            logger.error(f"Failed to process document {doc_id}: {e}", exc_info=True)
            # Rollback failed transaction
            db.rollback()
            # Create error record but don't commit - let calling function handle batch commits
            try:
                error_doc = ProcessedDocument(
                    paperless_doc_id=doc_id,
                    title=title,
                    processing_error=str(e),
                    retry_count=1
                )
                db.add(error_doc)
            except Exception as add_error:
                logger.error(f"Failed to add error record for document {doc_id}: {add_error}")

    def sync_all_tags_to_paperless(self):
        """Push stored anomaly results back to Paperless for every processed document.

        This is a non-destructive sync: no detection is re-run. For each document
        already in the local DB, it calls replace_document_anomaly_tags() using the
        stored anomaly_types. This simultaneously:
          - removes legacy bare tag names (balance_mismatch, etc.)
          - removes stale anomaly:* tags that no longer apply
          - re-adds the current correct set of anomaly:* tags

        Stale records (where the Paperless document was deleted) are removed from
        the local DB automatically.
        """
        logger.info("Starting tag sync: pushing stored results to Paperless for all processed documents...")
        synced = 0
        failed = 0
        removed_stale = 0

        with get_db() as db:
            docs = db.query(ProcessedDocument).all()
            total = len(docs)
            logger.info(f"Syncing tags for {total} documents...")

            for doc in docs:
                try:
                    # Check whether the document still exists in Paperless
                    paperless_doc = self.paperless_client.get_document(doc.paperless_doc_id)
                    if paperless_doc is None:
                        # Document deleted from Paperless — remove stale local record
                        logger.info(
                            f"Document {doc.paperless_doc_id} no longer exists in Paperless "
                            f"('{doc.title}') — removing stale DB record"
                        )
                        # Also remove associated anomaly log entries
                        db.query(AnomalyLog).filter(
                            AnomalyLog.paperless_doc_id == doc.paperless_doc_id
                        ).delete()
                        db.delete(doc)
                        db.commit()
                        removed_stale += 1
                        continue

                    tags_to_set = [
                        f"anomaly:{atype}"
                        for atype in (doc.anomaly_types or [])
                    ]
                    success = self.paperless_client.replace_document_anomaly_tags(
                        doc.paperless_doc_id, tags_to_set
                    )
                    if success:
                        synced += 1
                    else:
                        logger.warning(f"Tag sync failed for document {doc.paperless_doc_id}")
                        failed += 1
                    # Brief pause to avoid hammering the Paperless API
                    time.sleep(0.15)
                except Exception as e:
                    logger.error(f"Tag sync error for document {doc.paperless_doc_id}: {e}")
                    failed += 1

        logger.info(
            f"Tag sync complete: {synced} synced, {removed_stale} stale records removed, "
            f"{failed} failed out of {total} documents"
        )

    def reprocess_modified_documents(self):
        """Re-run full detection on documents whose Paperless modified date is newer than processed_at.

        Paperless is treated as the master: if a document has been updated in Paperless
        (re-OCR'd, content edited, etc.) since it was last processed here, it is re-queued
        for full anomaly detection.
        """
        logger.info("Checking for Paperless documents modified since last processing...")

        try:
            all_paperless_docs = self.paperless_client.get_recent_documents(
                minutes=None, limit=5000
            )
        except Exception as e:
            logger.error(f"Failed to fetch documents from Paperless: {e}")
            return

        if not all_paperless_docs:
            logger.info("No documents returned from Paperless")
            return

        reprocessed = 0
        with get_db() as db:
            for doc in all_paperless_docs:
                doc_id = doc["id"]
                existing = db.query(ProcessedDocument).filter(
                    ProcessedDocument.paperless_doc_id == doc_id
                ).first()

                if not existing:
                    continue  # New doc — handled by process_new_documents()

                # Parse Paperless modified timestamp
                modified_str = doc.get("modified") or doc.get("updated")
                if not modified_str:
                    continue
                try:
                    paperless_modified = datetime.fromisoformat(
                        modified_str.replace("Z", "+00:00")
                    )
                    # Make processed_at timezone-aware for comparison
                    processed_at = existing.processed_at
                    if processed_at.tzinfo is None:
                        processed_at = processed_at.replace(tzinfo=timezone.utc)
                    if paperless_modified <= processed_at:
                        continue  # Not modified since last processing
                except Exception:
                    continue

                logger.info(
                    f"Document {doc_id} modified in Paperless since last processing "
                    f"(modified={modified_str}, processed={existing.processed_at.isoformat()})"
                    f" — re-running detection"
                )
                try:
                    # Delete old record so _process_document can create a fresh one
                    db.delete(existing)
                    db.flush()
                    self._process_document(db, doc)
                    db.commit()
                    reprocessed += 1
                    time.sleep(0.15)
                except Exception as e:
                    logger.error(f"Failed to reprocess document {doc_id}: {e}")
                    db.rollback()

        if reprocessed:
            logger.info(f"Reprocessed {reprocessed} modified document(s)")
        else:
            logger.info("No modified documents found that need reprocessing")

    def _write_to_paperless(self, doc_id: int, results: dict, processed_doc: ProcessedDocument):
        """Write detection results back to Paperless as tags and custom fields."""
        try:
            tags_to_add = []

            # Add anomaly type tags (specific anomaly types are sufficient, no need for generic "detected" tag)
            for anomaly_type in results.get("anomaly_types", []):
                tag_name = f"anomaly:{anomaly_type}"
                tags_to_add.append(tag_name)

            # Replace anomaly tags on document (removes old anomaly tags, adds current ones)
            # Always call this, even if tags_to_add is empty, to clear old anomaly tags
            success = self.paperless_client.replace_document_anomaly_tags(doc_id, tags_to_add)
            if success:
                # Don't modify processed_doc after it's added to session
                # processed_doc.tags_written = tags_to_add
                if tags_to_add:
                    logger.info(f"Set {len(tags_to_add)} anomaly tags on document {doc_id}")
                else:
                    logger.info(f"Cleared anomaly tags from document {doc_id} (no anomalies detected)")

            # Update document type if detected
            if results.get("document_type") and results["document_type"] != "unknown":
                self.paperless_client.update_document_type(doc_id, results["document_type"])

            # Set custom fields
            custom_fields = {}

            # Balance check fields
            if results.get("balance_check"):
                bc = results["balance_check"]
                self.paperless_client.set_custom_field(
                    doc_id, "balance_check_status", bc.get("status", "UNKNOWN"), "string"
                )
                custom_fields["balance_check_status"] = bc.get("status")

                if bc.get("difference") is not None:
                    self.paperless_client.set_custom_field(
                        doc_id, "balance_diff_amount", round(bc["difference"], 2), "float"
                    )
                    custom_fields["balance_diff_amount"] = bc["difference"]

            # Layout score field
            if results.get("layout_check") and results["layout_check"].get("score") is not None:
                lc = results["layout_check"]
                self.paperless_client.set_custom_field(
                    doc_id, "layout_score", round(lc["score"], 2), "float"
                )
                custom_fields["layout_score"] = lc["score"]

            # Don't modify processed_doc after it's added to session
            # processed_doc.custom_fields_written = custom_fields

        except Exception as e:
            logger.error(f"Failed to write results to Paperless for document {doc_id}: {e}")

    def _get_anomaly_description(self, anomaly_type: str, results: dict) -> str:
        """Generate human-readable description for an anomaly."""
        if anomaly_type == "balance_mismatch":
            bc = results.get("balance_check", {})
            diff = bc.get("difference", 0)
            return f"Balance mismatch detected: difference of ${diff:.2f}"
        elif anomaly_type == "layout_irregularity":
            lc = results.get("layout_check", {})
            score = lc.get("score", 0)
            return f"Layout irregularity: score {score:.2f}"
        else:
            return f"Anomaly detected: {anomaly_type}"

    def _determine_severity(self, anomaly_type: str, results: dict) -> str:
        """Determine severity level for an anomaly."""
        if anomaly_type == "balance_mismatch":
            bc = results.get("balance_check", {})
            diff = bc.get("difference", 0)
            if diff > 1000:
                return "critical"
            elif diff > 100:
                return "high"
            elif diff > 10:
                return "medium"
            else:
                return "low"
        elif anomaly_type == "layout_irregularity":
            return "medium"
        else:
            return "medium"

    def _extract_amount(self, anomaly_type: str, results: dict) -> Optional[float]:
        """Extract relevant amount for filtering."""
        if anomaly_type == "balance_mismatch":
            bc = results.get("balance_check", {})
            return bc.get("difference")
        return None


class DocumentScheduler:
    """Manage scheduled background jobs."""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.processor: Optional[DocumentProcessor] = None

    def start(self, paperless_client: PaperlessClient, detector: AnomalyDetector):
        """Start the background scheduler."""
        self.processor = DocumentProcessor(paperless_client, detector)

        # Job 1: poll for new documents on the normal interval
        self.scheduler.add_job(
            func=self.processor.process_new_documents,
            trigger=IntervalTrigger(seconds=settings.polling_interval),
            id='process_documents',
            name='Process new documents from Paperless',
            replace_existing=True
        )

        # Job 2: sync all stored anomaly results → Paperless tags every 6 hours
        self.scheduler.add_job(
            func=self.processor.sync_all_tags_to_paperless,
            trigger=IntervalTrigger(hours=6),
            id='sync_tags',
            name='Sync anomaly tags to Paperless',
            replace_existing=True
        )

        # Job 3: re-detect documents modified in Paperless since last processing, every hour
        self.scheduler.add_job(
            func=self.processor.reprocess_modified_documents,
            trigger=IntervalTrigger(hours=1),
            id='reprocess_modified',
            name='Reprocess Paperless-modified documents',
            replace_existing=True
        )

        self.scheduler.start()
        logger.info(f"Scheduler started: polling every {settings.polling_interval} seconds; "
                    "tag sync every 6 h; modified-doc recheck every 1 h")

    def stop(self):
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler stopped")

    def trigger_now(self):
        """Manually trigger document processing."""
        if self.processor:
            logger.info("Manually triggering document processing...")
            self.processor.process_new_documents()

    def backfill_all_documents(self, batch_size: int = 50):
        """Process all documents in Paperless, not just recent ones."""
        if self.processor:
            logger.info("Starting backfill of all documents...")
            self.processor.process_all_documents(batch_size=batch_size)

    def trigger_sync(self):
        """Manually trigger a tag-sync pass against Paperless."""
        if self.processor:
            logger.info("Manually triggering tag sync...")
            self.processor.sync_all_tags_to_paperless()

    def trigger_reprocess_modified(self):
        """Manually trigger reprocessing of documents modified in Paperless."""
        if self.processor:
            logger.info("Manually triggering reprocess of modified documents...")
            self.processor.reprocess_modified_documents()
