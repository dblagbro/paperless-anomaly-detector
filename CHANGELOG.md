# Changelog

All notable changes to the Paperless Anomaly Detector project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
