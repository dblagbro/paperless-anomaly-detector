# Changelog

All notable changes to the Paperless Anomaly Detector project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
