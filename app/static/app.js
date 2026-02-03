// API base URL - use relative path for current location
const API_BASE = '.';

// State
let currentFilters = {};
let currentOffset = 0;
const LIMIT = 50;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadDocuments();

    // Refresh every 30 seconds
    setInterval(() => {
        loadStats();
        loadDocuments();
    }, 30000);
});

// Load statistics
async function loadStats() {
    try {
        const response = await fetch(`${API_BASE}/api/stats`);
        const data = await response.json();

        document.getElementById('stat-total').textContent = data.total_documents || 0;
        document.getElementById('stat-anomalies').textContent = data.documents_with_anomalies || 0;
        document.getElementById('stat-flags').textContent = data.total_anomalies || 0;

        const rate = data.total_documents > 0
            ? ((data.documents_with_anomalies / data.total_documents) * 100).toFixed(1)
            : 0;
        document.getElementById('stat-rate').textContent = `${rate}%`;
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Load documents with filters
async function loadDocuments(offset = 0) {
    try {
        const params = new URLSearchParams({
            limit: LIMIT,
            offset: offset,
            ...currentFilters
        });

        const response = await fetch(`${API_BASE}/api/documents?${params}`);
        const data = await response.json();

        renderDocumentsTable(data.results);
        renderPagination(data.total, offset);
    } catch (error) {
        console.error('Error loading documents:', error);
        document.getElementById('table-container').innerHTML =
            '<div class="empty-state"><h3>Error loading documents</h3></div>';
    }
}

// Render documents table
function renderDocumentsTable(documents) {
    const container = document.getElementById('table-container');

    if (!documents || documents.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <h3>No documents found</h3>
                <p>Try adjusting your filters or trigger a new scan.</p>
            </div>
        `;
        return;
    }

    let html = `
        <table>
            <thead>
                <tr>
                    <th>Document</th>
                    <th>Type</th>
                    <th>Anomalies</th>
                    <th>Balance Check</th>
                    <th>Layout Score</th>
                    <th>Processed</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
    `;

    documents.forEach(doc => {
        const anomalyBadges = doc.has_anomalies && doc.anomaly_types
            ? doc.anomaly_types.map(type => `<span class="badge anomaly">${formatAnomalyType(type)}</span>`).join('')
            : '<span class="badge clean">✓ Clean</span>';

        const balanceStatus = formatBalanceStatus(doc.balance_check_status, doc.balance_diff_amount);
        const layoutScore = doc.layout_score !== null ? `${(doc.layout_score * 100).toFixed(0)}%` : '-';
        const processedDate = doc.processed_at ? new Date(doc.processed_at).toLocaleString() : '-';

        html += `
            <tr>
                <td>
                    <strong>${escapeHtml(doc.title || 'Untitled')}</strong><br>
                    <small style="color: #666;">ID: ${doc.paperless_doc_id}</small>
                </td>
                <td>${escapeHtml(doc.document_type || 'unknown')}</td>
                <td>${anomalyBadges}</td>
                <td>${balanceStatus}</td>
                <td>${layoutScore}</td>
                <td><small>${processedDate}</small></td>
                <td>
                    <a href="${doc.paperless_url}" target="_blank" class="link">View in Paperless</a>
                </td>
            </tr>
        `;
    });

    html += `
            </tbody>
        </table>
    `;

    container.innerHTML = html;
}

// Render pagination
function renderPagination(total, offset) {
    const container = document.getElementById('table-container');
    const totalPages = Math.ceil(total / LIMIT);
    const currentPage = Math.floor(offset / LIMIT) + 1;

    if (totalPages <= 1) return;

    let paginationHtml = '<div class="pagination">';

    if (currentPage > 1) {
        paginationHtml += `<button class="secondary" onclick="loadDocuments(${(currentPage - 2) * LIMIT})">← Previous</button>`;
    }

    paginationHtml += `<span>Page ${currentPage} of ${totalPages} (${total} total)</span>`;

    if (currentPage < totalPages) {
        paginationHtml += `<button class="secondary" onclick="loadDocuments(${currentPage * LIMIT})">Next →</button>`;
    }

    paginationHtml += '</div>';
    container.innerHTML += paginationHtml;
}

// Apply filters
function applyFilters() {
    currentFilters = {};
    currentOffset = 0;

    const anomalyType = document.getElementById('filter-anomaly-type').value;
    if (anomalyType) currentFilters.anomaly_type = anomalyType;

    const minAmount = document.getElementById('filter-min-amount').value;
    if (minAmount) currentFilters.min_amount = minAmount;

    const maxAmount = document.getElementById('filter-max-amount').value;
    if (maxAmount) currentFilters.max_amount = maxAmount;

    const dateFrom = document.getElementById('filter-date-from').value;
    if (dateFrom) currentFilters.date_from = dateFrom;

    const dateTo = document.getElementById('filter-date-to').value;
    if (dateTo) currentFilters.date_to = dateTo;

    const hasAnomalies = document.getElementById('filter-has-anomalies').value;
    if (hasAnomalies) currentFilters.has_anomalies = hasAnomalies;

    loadDocuments();
}

// Clear filters
function clearFilters() {
    document.getElementById('filter-anomaly-type').value = '';
    document.getElementById('filter-min-amount').value = '';
    document.getElementById('filter-max-amount').value = '';
    document.getElementById('filter-date-from').value = '';
    document.getElementById('filter-date-to').value = '';
    document.getElementById('filter-has-anomalies').value = '';

    currentFilters = {};
    currentOffset = 0;
    loadDocuments();
}

// Trigger manual scan
async function triggerScan() {
    try {
        const response = await fetch(`${API_BASE}/api/trigger-scan`, {
            method: 'POST'
        });

        if (response.ok) {
            alert('Scan triggered successfully! Results will appear shortly.');
            setTimeout(() => {
                loadStats();
                loadDocuments();
            }, 5000);
        } else {
            alert('Failed to trigger scan');
        }
    } catch (error) {
        console.error('Error triggering scan:', error);
        alert('Error triggering scan');
    }
}

// Utility functions
function formatAnomalyType(type) {
    return type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function formatBalanceStatus(status, diff) {
    if (!status || status === 'NOT_APPLICABLE') {
        return '<span style="color: #999;">N/A</span>';
    }

    if (status === 'PASS') {
        return '<span class="status-pass">✓ Pass</span>';
    }

    if (status === 'FAIL') {
        const diffText = diff !== null ? ` ($${Math.abs(diff).toFixed(2)})` : '';
        return `<span class="status-fail">✗ Fail${diffText}</span>`;
    }

    if (status === 'WARNING') {
        return '<span class="status-warning">⚠ Warning</span>';
    }

    return `<span>${status}</span>`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
