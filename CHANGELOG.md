# Changelog

All notable changes to the Paperless Anomaly Detector project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.1] - 2026-02-19

### Fixed
- **Stale record cleanup in tag sync**: `sync_all_tags_to_paperless()` now detects when a
  document no longer exists in Paperless (HTTP 404) and automatically removes the orphaned
  record (and its associated anomaly log entries) from the local database instead of counting
  it as a sync failure.
- **Backfill fetches all documents**: `process_all_documents()` now passes `limit=None` to
  `get_recent_documents()` so it paginates through the full Paperless corpus rather than
  capping at 1 000 documents.
- **Removed duplicate `return None` statements** in `get_or_create_tag()` and
  `get_or_create_document_type()` (dead code from earlier edits).

## [1.5] - 2026-02-19

### Fixed
- **Legacy bare tag cleanup**: `replace_document_anomaly_tags()` now also strips old bare tag names
  (`balance_mismatch`, `check_sequence_gap`, `layout_irregularity`, `page_discontinuity`,
  `duplicate_lines`, `reversed_columns`, `truncated_total`, `image_manipulation`, `detected`)
  that were written by pre-prefix versions of the code and were previously left stuck in Paperless.

### Added
- **`sync_all_tags_to_paperless()`**: Pushes stored anomaly results from the local database back
  to Paperless for every processed document without re-running detection. Simultaneously removes
  all legacy bare tags and stale `anomaly:*` tags, then re-applies the correct current tags.
- **Periodic tag sync job**: Runs automatically every 6 hours to keep Paperless tags in sync
  with the local database (catches any drift between restarts or manual Paperless edits).
- **`reprocess_modified_documents()`**: Re-runs full anomaly detection on any document whose
  Paperless `modified` timestamp is newer than `processed_at` in the local database. Treats
  Paperless as the master — if a document is re-OCR'd or updated in Paperless, it is
  automatically re-queued for detection.
- **Hourly modified-document recheck job**: Runs `reprocess_modified_documents()` every hour.
- **`POST /api/sync-tags`**: HTTP endpoint to manually trigger a tag-sync pass.
- **`POST /api/reprocess-modified`**: HTTP endpoint to manually trigger reprocessing of
  Paperless-modified documents.

## [1.2] - 2026-02-04

### Fixed
- **Improved page_discontinuity detection accuracy**
  - Removed false positive: Documents without page numbers are no longer flagged as anomalies
  - Now only flags documents with actual page numbering inconsistencies (e.g., "Page 2 of 4" but only 1 page exists)
  - Reduced false positives by 6 documents in test corpus

- **Improved duplicate_lines detection accuracy**
  - Now only flags duplicate transaction lines (checks, amounts in accounting lists)
  - Excludes headers, footers, and addresses that repeat on each page
  - Filters for lines containing financial data (dollar amounts, dates, check numbers)
  - Ignores common document structure elements (page headers, branch addresses, etc.)
  - Reduced false positives by 26 documents in test corpus (from 45 to 19)

### Changed
- Enhanced detection logic to focus on genuine anomalies rather than normal document variance
- Improved pattern matching to distinguish between document structure and transaction data

## [1.1] - 2026-02-03

### Fixed
- **Critical bug fix**: Tag synchronization between anomaly detector and Paperless-ngx
  - Implemented `replace_document_anomaly_tags()` method to properly replace tags instead of accumulating them
  - Fixed issue where old anomaly tags persisted in Paperless after reprocessing
  - Cleared stale database records and reprocessed all documents for clean state
  - Ensured tags with other prefixes (e.g., "aianomaly:") are preserved during tag replacement
  - Fixed 62 documents with tag mismatches to match UI/database state
  - Verified complete synchronization: all 73 documents now match perfectly between UI and Paperless
- Database cleanup removed orphaned records for deleted documents
- Tag replacement now correctly handles documents with no anomalies (clears all anomaly tags)

### Removed
- **Removed redundant "anomaly:detected" tag**
  - Specific anomaly type tags (e.g., "anomaly:page_discontinuity") already imply detection
  - No need for generic "detected" tag when specific anomaly types are present
  - Cleaned up all existing redundant tags from Paperless (47 documents)

### Changed
- Tag writing logic now replaces anomaly tags instead of appending to existing tags
- Improved tag synchronization to maintain consistency across systems
- Only writes specific anomaly type tags, not generic detection markers

## [1.0] - 2026-02-03

### Initial Release

#### Added
- Balance checking for bank statements with arithmetic validation
- Layout irregularity detection using multiple analysis methods
- Pattern detection for duplicate lines, reversed columns, truncated totals, and page discontinuities
- Integration with Paperless-ngx API for automatic tag and document type management
- Web dashboard with filtering capabilities and real-time statistics
- Background polling system for automatic document processing
- Optional LLM enhancement support (Claude/GPT)
- Docker containerized deployment with docker-compose
- SQLite and PostgreSQL database support
- Comprehensive logging system
- RESTful API integration with Paperless-ngx

#### Fixed
- Tag ID resolution now uses exact name matching instead of partial matching
- Document type creation and assignment improved
- Enhanced error handling and logging throughout the application

#### Technical Details
- Python 3.11+ support
- Dash-based web interface
- APScheduler for background jobs
- SQLAlchemy ORM for database operations
- httpx for API communications
