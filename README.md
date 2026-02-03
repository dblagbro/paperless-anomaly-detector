# Paperless Anomaly Detector

Automated anomaly detection system for Paperless-ngx documents with financial analysis, pattern detection, and optional LLM-enhanced checking.

## Features

### Anomaly Detection
- **Arithmetic Consistency**: Validates bank statement balances (Beginning + Credits - Debits = Ending)
- **Layout Irregularity**: Detects unusual formatting and structure in documents
- **Pattern Detection**: Identifies suspicious patterns like:
  - Reversed columns
  - Duplicate transaction lines
  - Truncated totals
  - Page numbering issues

### Integration
- **Paperless API**: Fetches documents, writes tags and custom fields back
- **Background Polling**: Automatically processes new documents at configurable intervals
- **LLM Enhancement** (optional): Uses Claude or GPT for advanced anomaly reasoning

### Web Dashboard
- Filter by anomaly type, amount threshold, date range
- View all processed documents with anomaly details
- Direct links back to Paperless documents
- Real-time statistics

## Quick Start

### Prerequisites
1. Running Paperless-ngx instance
2. Paperless API token (Settings → API Tokens)
3. Docker and Docker Compose

### Installation

1. **Create environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Configure `.env` with your Paperless API token:**
   ```bash
   PAPERLESS_API_TOKEN=your_actual_token_here
   ```

3. **Build and start:**
   ```bash
   docker compose up -d
   ```

4. **Access the dashboard:**
   Open http://your-server:8050

### Configuration

Key environment variables:

```bash
# Required
PAPERLESS_API_BASE_URL=http://paperless-web:8000
PAPERLESS_API_TOKEN=your_token_here

# Optional LLM (for enhanced detection)
LLM_PROVIDER=anthropic  # or 'openai'
LLM_API_KEY=your_llm_key

# Polling (default: 5 minutes)
POLLING_INTERVAL=300

# Detection sensitivity
BALANCE_TOLERANCE=0.01  # $0.01 tolerance for balance checks
LAYOUT_VARIANCE_THRESHOLD=0.3  # 0-1 scale
```

## How It Works

### Document Processing Flow

1. **Polling**: Every `POLLING_INTERVAL` seconds, queries Paperless for new documents
2. **Content Extraction**: Retrieves OCR text from each document
3. **Type Inference**: Determines document type (bank statement, invoice, etc.)
4. **Anomaly Detection**: Runs multiple detection algorithms:
   - Balance arithmetic validation
   - Layout consistency analysis
   - Pattern matching (regex-based)
   - Optional LLM analysis
5. **Results Storage**: Saves findings to internal database
6. **Paperless Integration**: Writes back to Paperless:
   - Tags: `anomaly:detected`, `anomaly:balance_mismatch`, etc.
   - Custom fields: `balance_check_status`, `balance_diff_amount`, `layout_score`

### API Endpoints

- `GET /` - Web dashboard
- `GET /health` - Health check
- `GET /api/stats` - Overall statistics
- `GET /api/documents` - List processed documents (with filters)
- `GET /api/anomalies` - List anomaly logs
- `POST /api/trigger-scan` - Manually trigger document scan

### Example API Usage

```bash
# Get documents with balance mismatches over $100
curl "http://localhost:8050/api/documents?anomaly_type=balance_mismatch&min_amount=100"

# Get statistics
curl "http://localhost:8050/api/stats"

# Trigger immediate scan
curl -X POST "http://localhost:8050/api/trigger-scan"
```

## Integration with NGINX

To expose the anomaly detector through your existing NGINX reverse proxy, add this location block to your `nginx.conf`:

```nginx
location /anomalies/ {
    proxy_pass http://anomaly-detector:8050/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Then access at: `https://voipguru.org/anomalies/`

## Database Schema

### processed_documents
- Tracks each processed document
- Stores detection results
- Links to Paperless document ID

### anomaly_logs
- Detailed log of each anomaly detected
- Includes severity, description, amount
- Supports resolution tracking

## Tagging Scheme for Legal Discovery

For your property management use case, documents will be automatically tagged:

**Anomaly Tags** (auto-generated):
- `anomaly:detected` - Any anomaly found
- `anomaly:balance_mismatch` - Arithmetic inconsistency
- `anomaly:layout_irregularity` - Formatting issues
- `anomaly:duplicate_lines` - Repeated entries
- `anomaly:truncated_total` - Missing totals
- `anomaly:reversed_columns` - Column order issues

**Suggested Manual Tags** (add in Paperless):
- `property:<id>` - Property identifier
- `role:referee` or `role:receiver` - Your capacity
- `doc_type:bank_statement`, `doc_type:rent_roll`, etc.
- `period:YYYY-MM` or `period:YYYY-Q#` - Time period

## Custom Fields

The system creates these custom fields in Paperless:

- `balance_check_status`: PASS/FAIL/NOT_APPLICABLE
- `balance_diff_amount`: Dollar amount of mismatch
- `layout_score`: 0-1 quality score

## Security Notes

- **Token Security**: API tokens are never logged
- **Database**: SQLite by default (use PostgreSQL for production)
- **HTTPS**: Use NGINX reverse proxy with TLS
- **Access Control**: Consider adding HTTP basic auth via NGINX

## Troubleshooting

### No documents being processed
1. Check Paperless API connectivity:
   ```bash
   docker exec anomaly-detector curl -H "Authorization: Token YOUR_TOKEN" http://paperless-web:8000/api/documents/
   ```

2. Check logs:
   ```bash
   docker compose logs -f anomaly-detector
   ```

3. Manually trigger a scan via web UI or API

### False positives
- Adjust `BALANCE_TOLERANCE` for balance checks
- Adjust `LAYOUT_VARIANCE_THRESHOLD` for layout detection
- Review pattern detection rules in `detector.py`

### Performance
- Reduce `BATCH_SIZE` if processing is slow
- Increase `POLLING_INTERVAL` to reduce server load
- Consider PostgreSQL for better performance with many documents

## Development

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
cd app
python main.py
```

### Testing

```bash
pytest
```

### Adding New Detection Algorithms

Edit `app/detector.py` and add methods to the `AnomalyDetector` class.
Update `detect_all_anomalies()` to call your new detection method.

## License

MIT License - See LICENSE file for details

## Support

For issues, questions, or contributions, please open an issue on GitHub.
