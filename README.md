# Paperless Anomaly Detector

[![Docker Hub](https://img.shields.io/docker/v/dblagbro/paperless-anomaly-detector?label=Docker%20Hub)](https://hub.docker.com/r/dblagbro/paperless-anomaly-detector)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

Automated financial anomaly detection for [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx). Validates bank statements, invoices, and financial documents for arithmetic inconsistencies, formatting issues, and suspicious patterns. Features a web dashboard for monitoring and optional LLM enhancement for advanced analysis.

## 🌟 Key Features

- **🧮 Balance Validation**: Automatic verification of bank statement arithmetic
- **📐 Layout Analysis**: Detects formatting irregularities and structural issues
- **🔍 Pattern Detection**: Identifies duplicates, reversed columns, truncated totals
- **🤖 Optional LLM Enhancement**: Claude/GPT integration for advanced reasoning
- **📊 Web Dashboard**: Real-time monitoring with filters and statistics
- **🔄 Auto-Processing**: Background polling for new documents
- **🏷️ Smart Tagging**: Automatically adds anomaly tags to Paperless
- **📈 Custom Fields**: Writes detection results to Paperless custom fields

## 📋 Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Use Cases](#use-cases)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [How It Works](#how-it-works)
- [Web Dashboard](#web-dashboard)
- [API Reference](#api-reference)
- [Integration](#integration)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [FAQ](#faq)
- [License](#license)

## Features

### 🧮 Arithmetic Consistency Checking

Validates financial document math automatically:

- **Balance Verification**: `Beginning Balance + Credits - Debits = Ending Balance`
- **Running Totals**: Validates line-by-line balance progression
- **Page Totals**: Verifies subtotals match sum of transactions
- **Configurable Tolerance**: Customize acceptable variance (default: $0.01)

**Tags Generated**: `anomaly:balance_mismatch`
**Custom Fields**: `balance_check_status`, `balance_diff_amount`

### 📐 Layout Irregularity Detection

Identifies formatting and structural issues:

- **Column Alignment**: Detects misaligned data columns
- **Font Consistency**: Identifies suspicious font variations
- **Spacing Anomalies**: Finds unusual spacing patterns
- **Page Structure**: Validates consistent page layouts
- **Score-Based**: Produces 0-1 layout quality score

**Tags Generated**: `anomaly:layout_irregularity`
**Custom Fields**: `layout_score`

### 🔍 Pattern Detection

Regex-based detection for common issues:

- **Reversed Columns**: Debits and credits swapped
- **Duplicate Transactions**: Repeated lines (copy/paste errors)
- **Truncated Totals**: Missing or incomplete totals
- **Page Numbering Issues**: Out of order or missing pages
- **Date Sequence Problems**: Non-chronological transactions

**Tags Generated**: `anomaly:duplicate_lines`, `anomaly:reversed_columns`, `anomaly:truncated_total`

### 🤖 LLM Enhancement (Optional)

Advanced analysis using Claude or GPT:

- **Narrative Summaries**: Human-readable anomaly explanations
- **Context-Aware Analysis**: Considers document type and patterns
- **Confidence Scoring**: Provides confidence levels for findings
- **Evidence-Based**: Only analyzes extracted data, never invents

**Requirements**: `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`

### 📊 Web Dashboard

Real-time monitoring interface:

- **Document List**: View all processed documents with anomaly indicators
- **Filters**: By anomaly type, date range, amount threshold
- **Statistics**: Overall detection rates and trends
- **Quick Links**: Direct links to Paperless documents
- **Search**: Find specific documents by ID or content

**Access**: `http://localhost:8050`

### 🔄 Background Processing

Automated polling system:

- **Configurable Interval**: Default 5 minutes, customize as needed
- **State Persistence**: Remembers last processed document
- **Graceful Shutdown**: Finishes current document before stopping
- **Error Handling**: Continues processing after transient failures

## Architecture

```
┌──────────────────┐
│  Paperless-ngx   │
│      API         │
└────────┬─────────┘
         │ Poll for new documents
         ▼
┌──────────────────┐
│  Anomaly         │
│  Detector        │
│                  │
│  1. Fetch OCR    │
│  2. Infer Type   │──► Bank Statement
│  3. Extract Data │   Invoice
│  4. Validate     │   Receipt
└────────┬─────────┘
         │
         ├──────────────────────────────┐
         ▼                              ▼
┌─────────────────┐        ┌─────────────────────┐
│ Deterministic   │        │ Optional LLM        │
│ Checks          │        │ Analysis            │
│                 │        │                     │
│ - Balance math  │        │ - Narrative         │
│ - Layout score  │        │ - Context           │
│ - Patterns      │        │ - Confidence        │
└────────┬────────┘        └──────────┬──────────┘
         │                            │
         └────────────┬───────────────┘
                      ▼
           ┌────────────────────┐
           │ Results Storage    │
           │ (SQLite/Postgres)  │
           └──────────┬─────────┘
                      ▼
           ┌────────────────────┐
           │ Write to Paperless │
           │ - Tags             │
           │ - Custom Fields    │
           └────────────────────┘
```

## Use Cases

### 💰 Property Management Accounting
- **Scenario**: Managing properties in litigation/receivership
- **Benefit**: Automatically flag suspicious bank statements and rent rolls
- **Tags**: Perfect for legal discovery and audit preparation

### 🏦 Personal Finance Auditing
- **Scenario**: Reviewing monthly bank and credit card statements
- **Benefit**: Catch bank errors, duplicate charges, unauthorized transactions

### 📋 Accounts Payable/Receivable
- **Scenario**: Processing vendor invoices and customer payments
- **Benefit**: Detect duplicate invoices, math errors, fraudulent documents

### 🔍 Fraud Detection
- **Scenario**: Reviewing documents for tampering or manipulation
- **Benefit**: Layout irregularities often indicate modified PDFs

### 📊 Financial Due Diligence
- **Scenario**: M&A document review, loan applications
- **Benefit**: Automated validation of financial statements

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- Running Paperless-ngx instance (v1.10.0+)
- Paperless API token ([generate here](https://docs.paperless-ngx.com/api/))

### Installation

#### Using Docker Hub

```yaml
services:
  paperless-anomaly-detector:
    image: dblagbro/paperless-anomaly-detector:latest
    container_name: paperless-anomaly-detector
    restart: unless-stopped
    environment:
      PAPERLESS_API_BASE_URL: http://paperless-web:8000
      PAPERLESS_API_TOKEN: your_token_here
      POLLING_INTERVAL: 300
      BALANCE_TOLERANCE: 0.01
    volumes:
      - ./anomaly-detector/data:/app/data
    ports:
      - "8050:8050"
```

#### From Source

```bash
git clone https://github.com/dblagbro/paperless-anomaly-detector.git
cd paperless-anomaly-detector
docker build -t paperless-anomaly-detector .
```

### Initial Setup

1. **Create environment file**:
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` with your settings**:
   ```bash
   PAPERLESS_API_TOKEN=your_actual_token_here
   PAPERLESS_API_BASE_URL=http://paperless-web:8000
   ```

3. **Start the service**:
   ```bash
   docker compose up -d
   ```

4. **Verify it's running**:
   ```bash
   docker compose logs -f paperless-anomaly-detector
   ```

5. **Access the dashboard**:
   ```
   http://localhost:8050
   ```

6. **Trigger initial scan** (optional):
   ```bash
   curl -X POST http://localhost:8050/api/trigger-scan
   ```

## ⚙️ Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PAPERLESS_API_BASE_URL` | `http://paperless-web:8000` | Paperless API endpoint |
| `PAPERLESS_API_TOKEN` | *(required)* | API authentication token |
| `POLLING_INTERVAL` | `300` | Seconds between polling cycles |
| `BALANCE_TOLERANCE` | `0.01` | Dollar tolerance for balance checks |
| `LAYOUT_VARIANCE_THRESHOLD` | `0.3` | Layout score threshold (0-1) |
| `LLM_PROVIDER` | `None` | `anthropic` or `openai` |
| `LLM_API_KEY` | `None` | LLM API key (if enabled) |
| `LLM_MODEL` | *(auto)* | Override model name |
| `BATCH_SIZE` | `10` | Documents per polling batch |
| `DATABASE_URL` | `sqlite:///data/anomalies.db` | Database connection string |

### Enabling LLM Analysis

Add to your environment:

```yaml
environment:
  LLM_PROVIDER: anthropic
  LLM_API_KEY: sk-ant-api03-xxx
```

Or for OpenAI:

```yaml
environment:
  LLM_PROVIDER: openai
  LLM_API_KEY: sk-proj-xxx
  LLM_MODEL: gpt-4-turbo-preview
```

### Custom Fields Setup

The detector automatically creates these custom fields in Paperless:

1. **balance_check_status** (Text): PASS / FAIL / NOT_APPLICABLE
2. **balance_diff_amount** (Number): Dollar amount of mismatch
3. **layout_score** (Number): 0-1 quality score

These are created on first run. No manual setup needed.

## 🔍 How It Works

### Document Processing Flow

1. **Polling Phase**:
   - Queries Paperless API every `POLLING_INTERVAL` seconds
   - Fetches documents with `modified > last_seen`
   - Processes in batches of `BATCH_SIZE`

2. **Content Extraction**:
   - Retrieves OCR text via Paperless API
   - Extracts document metadata (title, date, tags)
   - Identifies document type (bank statement, invoice, etc.)

3. **Type Inference**:
   - Keyword matching for common document types
   - Pattern recognition in content
   - Falls back to generic analysis if unrecognized

4. **Anomaly Detection**:
   - **Balance Validation**: Extracts beginning/ending balances, credits, debits
   - **Layout Analysis**: Computes structural consistency score
   - **Pattern Matching**: Applies regex rules for common issues
   - **LLM Enhancement** (optional): Sends findings for analysis

5. **Results Storage**:
   - Saves to internal database (`processed_documents`, `anomaly_logs`)
   - Includes severity, description, amounts, timestamps

6. **Paperless Integration**:
   - Adds tags: `anomaly:detected`, `anomaly:balance_mismatch`, etc.
   - Updates custom fields with results
   - Never modifies original documents

### Tag Naming Scheme

| Tag | Meaning |
|-----|---------|
| `anomaly:detected` | At least one anomaly found |
| `anomaly:balance_mismatch` | Arithmetic inconsistency detected |
| `anomaly:layout_irregularity` | Formatting/structure issues |
| `anomaly:duplicate_lines` | Repeated transaction entries |
| `anomaly:truncated_total` | Missing or incomplete totals |
| `anomaly:reversed_columns` | Debit/credit columns swapped |
| `anomaly:page_numbering` | Page order issues |

**Manual Tags (Recommended)**:
- `property:<id>` - Property identifier
- `role:referee` or `role:receiver` - Your capacity
- `doc_type:bank_statement`, `doc_type:rent_roll` - Document type
- `period:YYYY-MM` - Time period

## 🖥️ Web Dashboard

### Main Dashboard (`/`)

- **Document Cards**: Visual cards for each processed document
- **Anomaly Indicators**: Red badges for detected issues
- **Quick Stats**: Total documents, anomalies found, success rate
- **Filters**: Type, date range, amount threshold

### Statistics (`/api/stats`)

JSON response with:
```json
{
  "total_documents": 1234,
  "documents_with_anomalies": 45,
  "anomaly_rate": 3.6,
  "by_type": {
    "balance_mismatch": 20,
    "layout_irregularity": 15,
    "duplicate_lines": 10
  }
}
```

### Document List (`/api/documents`)

Query parameters:
- `anomaly_type`: Filter by specific anomaly
- `min_amount`: Minimum balance discrepancy
- `max_amount`: Maximum balance discrepancy
- `start_date`: ISO format (2024-01-01)
- `end_date`: ISO format (2024-12-31)
- `limit`: Results per page (default: 50)
- `offset`: Pagination offset

Example:
```bash
curl "http://localhost:8050/api/documents?anomaly_type=balance_mismatch&min_amount=100"
```

## 🔌 API Reference

### `GET /health`

Health check endpoint.

**Response**: `{"status": "healthy"}`

### `GET /api/stats`

Overall statistics.

**Response**:
```json
{
  "total_documents": 1234,
  "documents_with_anomalies": 45,
  "anomaly_rate": 3.6,
  "by_type": {...}
}
```

### `GET /api/documents`

List processed documents.

**Query Params**: See [Document List](#document-list-apidocuments) section

**Response**:
```json
{
  "documents": [...],
  "total": 1234,
  "limit": 50,
  "offset": 0
}
```

### `GET /api/anomalies`

List all anomaly logs.

**Query Params**: `document_id`, `severity`, `resolved`

**Response**:
```json
{
  "anomalies": [
    {
      "id": 123,
      "document_id": 456,
      "anomaly_type": "balance_mismatch",
      "severity": "high",
      "description": "Beginning + Credits - Debits != Ending",
      "amount": 150.00,
      "detected_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### `POST /api/trigger-scan`

Manually trigger document polling.

**Response**: `{"status": "scan_initiated"}`

## 🔗 Integration

### NGINX Reverse Proxy

Add to your `nginx.conf`:

```nginx
location /paperless-anomaly-detector/ {
    proxy_pass http://localhost:8050/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # URL rewriting for subpath
    sub_filter_once off;
    sub_filter 'href="/' 'href="/paperless-anomaly-detector/';
    sub_filter 'src="/' 'src="/paperless-anomaly-detector/';
    sub_filter 'action="/' 'action="/paperless-anomaly-detector/';
}
```

Then access at: `https://yourdomain.com/paperless-anomaly-detector/`

### Paperless Workflow Integration

Create saved searches in Paperless:

1. **High-Priority Anomalies**:
   ```
   tags:anomaly:balance_mismatch AND balance_diff_amount:>100
   ```

2. **Recent Anomalies**:
   ```
   tags:anomaly:detected AND created:[now-7d TO now]
   ```

3. **Unresolved Issues**:
   ```
   tags:anomaly:detected AND NOT tags:reviewed
   ```

## 🔧 Troubleshooting

### No Documents Being Processed

**Symptoms**: Dashboard shows 0 documents

**Solutions**:
1. Verify API connectivity:
   ```bash
   docker exec paperless-anomaly-detector curl -H "Authorization: Token YOUR_TOKEN" \
     http://paperless-web:8000/api/documents/?page_size=1
   ```

2. Check logs for errors:
   ```bash
   docker compose logs -f paperless-anomaly-detector
   ```

3. Manually trigger scan:
   ```bash
   curl -X POST http://localhost:8050/api/trigger-scan
   ```

4. Check API token permissions in Paperless

### False Positives

**Symptoms**: Too many anomalies detected

**Solutions**:
1. Increase `BALANCE_TOLERANCE`:
   ```yaml
   environment:
     BALANCE_TOLERANCE: 0.05  # $0.05 instead of $0.01
   ```

2. Adjust `LAYOUT_VARIANCE_THRESHOLD`:
   ```yaml
   environment:
     LAYOUT_VARIANCE_THRESHOLD: 0.5  # More lenient
   ```

3. Review pattern detection rules in `app/detector.py`

4. Use LLM enhancement for better context understanding

### Performance Issues

**Symptoms**: Slow processing, high CPU usage

**Solutions**:
1. Reduce batch size:
   ```yaml
   environment:
     BATCH_SIZE: 5
   ```

2. Increase polling interval:
   ```yaml
   environment:
     POLLING_INTERVAL: 600  # 10 minutes
   ```

3. Disable LLM if not needed:
   ```yaml
   environment:
     LLM_PROVIDER: ""
   ```

4. Use PostgreSQL instead of SQLite:
   ```yaml
   environment:
     DATABASE_URL: postgresql://user:pass@postgres:5432/anomalies
   ```

### LLM Not Working

**Symptoms**: No LLM-enhanced analysis, errors in logs

**Solutions**:
1. Verify API key:
   ```bash
   docker exec paperless-anomaly-detector printenv | grep LLM
   ```

2. Test API key manually:
   ```bash
   curl -H "x-api-key: YOUR_KEY" https://api.anthropic.com/v1/messages
   ```

3. Check rate limits in provider dashboard

4. Ensure `LLM_PROVIDER` is set correctly

## 💻 Development

### Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
cd app
python main.py
```

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run tests
pytest tests/

# With coverage
pytest --cov=app tests/
```

### Adding New Detection Algorithms

1. Edit `app/detector.py`
2. Add method to `AnomalyDetector` class:
   ```python
   def detect_my_anomaly(self, content, metadata):
       """Detect my custom anomaly."""
       findings = []
       # Your logic here
       return findings
   ```
3. Update `detect_all_anomalies()` to call your method
4. Add corresponding tag handling
5. Test thoroughly

### Database Schema

**processed_documents**:
```sql
CREATE TABLE processed_documents (
    id INTEGER PRIMARY KEY,
    paperless_doc_id INTEGER UNIQUE,
    title TEXT,
    processed_at TIMESTAMP,
    has_anomalies BOOLEAN,
    balance_status TEXT,
    balance_diff REAL,
    layout_score REAL
);
```

**anomaly_logs**:
```sql
CREATE TABLE anomaly_logs (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES processed_documents(id),
    anomaly_type TEXT,
    severity TEXT,
    description TEXT,
    amount REAL,
    detected_at TIMESTAMP,
    resolved BOOLEAN DEFAULT 0
);
```

## 📈 Performance

### Resource Usage

- **Memory**: 200-500MB depending on document volume
- **CPU**: Low during polling, spikes during processing
- **Disk**: SQLite database grows ~10KB per document

### Benchmarks

Typical processing times (Intel i7, 16GB RAM):

| Document Type | Pages | Processing Time |
|---------------|-------|-----------------|
| Bank Statement | 2 | 2-4 seconds |
| Invoice | 1 | 1-2 seconds |
| Credit Card | 5 | 5-8 seconds |

*With LLM enabled, add 1-3 seconds per document*

### Optimization

For high-volume deployments:
- Use PostgreSQL instead of SQLite
- Increase `BATCH_SIZE` for better throughput
- Run multiple instances with partitioned document sets
- Consider async processing with message queue

## 🔒 Security Notes

1. **API Token**: Never logged or exposed in responses. Store in environment variable.

2. **Database**: SQLite by default. Use PostgreSQL with encrypted connections for production.

3. **HTTPS**: Always use NGINX reverse proxy with TLS in production.

4. **Access Control**: Add HTTP basic auth via NGINX for additional security.

5. **Read-Only**: Service only reads documents and writes tags/fields. Never modifies originals.

6. **Audit Trail**: All actions logged with timestamps in application logs.

## ❓ FAQ

**Q: Can I reprocess documents?**
A: Yes, clear the database and restart: `docker exec paperless-anomaly-detector rm /app/data/anomalies.db`

**Q: Does this work with scanned documents?**
A: Yes, as long as Paperless has performed OCR. Quality depends on scan quality.

**Q: Can I customize which anomalies are detected?**
A: Yes, edit `app/detector.py` to add/remove detection rules.

**Q: What document types are supported?**
A: Bank statements, credit cards, invoices, receipts. Easily extensible.

**Q: How accurate is the balance validation?**
A: Very accurate for properly formatted statements. Configure tolerance for edge cases.

**Q: Can I use this without LLM?**
A: Yes, deterministic checks work fine without LLM. LLM is optional enhancement.

**Q: Does this modify my documents?**
A: No, it only adds tags and custom fields. Original PDFs are never modified.

**Q: Can I run this on multiple Paperless instances?**
A: Run separate containers with different `PAPERLESS_API_TOKEN` values.

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a Pull Request

## 📜 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Credits

- Built for property management and financial auditing use cases
- Integrates with [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx)
- Optional LLM support via [Anthropic Claude](https://anthropic.com/) or [OpenAI](https://openai.com/)

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/dblagbro/paperless-anomaly-detector/issues)
- **Discussions**: [GitHub Discussions](https://github.com/dblagbro/paperless-anomaly-detector/discussions)
- **Documentation**: See [CHANGELOG.md](CHANGELOG.md) for version history

---

**Perfect for property managers, accountants, auditors, and anyone who needs automated financial document validation.**
