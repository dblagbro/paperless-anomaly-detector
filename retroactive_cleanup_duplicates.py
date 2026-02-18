#!/usr/bin/env python3
"""
Retroactive cleanup of false-positive anomaly:duplicate_lines tags.

Reads every document in the anomaly-detector DB that was flagged with
duplicate_lines, re-evaluates whether the duplicates are still valid
under the expanded header-exclusion list, and:
  - Removes anomaly:duplicate_lines from Paperless if nothing real remains
  - Updates the DB record so future runs stay clean

Run inside the anomaly-detector container:
    python3 /app/retroactive_cleanup_duplicates.py
"""

import os
import re
import json
import logging
import sqlite3
import requests
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH = os.getenv('DB_PATH', '/app/data/anomaly_detector.db')
PAPERLESS_URL = os.getenv('PAPERLESS_API_BASE_URL', 'http://paperless-web:8000')
PAPERLESS_TOKEN = os.getenv('PAPERLESS_API_TOKEN', '')
DRY_RUN = os.getenv('DRY_RUN', '').lower() in ('1', 'true', 'yes')

# ── Expanded header exclusion list (must match detector.py) ───────────────────
HEADER_KEYWORDS = [
    # Bank statement column headers / footers
    'page', 'account', 'statement', 'balance', 'date', 'description',
    'amount', 'check', 'deposit', 'withdrawal', 'branch', 'address',
    'customer service', 'member fdic', 'routing', 'account number',
    # Bank boilerplate repeated on every page
    'annual percentage yield', 'apy earned', 'apy ',
    'interest paid', 'interest earned',
    'average daily balance', 'minimum balance',
    'overdraft', 'service charge', 'maintenance fee',
    # Court filing / NYSCEF stamp lines
    'nyscef', 'filed:', 'index no.', 'county clerk',
    'received nyscef', 'doc. no.', 'supreme court',
    'appellate division', 'court of appeals',
    # Generic document stamp patterns
    'confidential', 'draft', 'privileged',
]


def is_header_line(line: str) -> bool:
    lower = line.lower()
    return any(kw in lower for kw in HEADER_KEYWORDS)


def filter_real_duplicates(details: List[str]) -> List[str]:
    """Return only the duplicate texts that are NOT header/boilerplate lines."""
    return [d for d in details if not is_header_line(d)]


def remove_tag_from_paperless(doc_id: int, tag_name: str) -> bool:
    """Remove a specific tag from a Paperless document."""
    headers = {'Authorization': f'Token {PAPERLESS_TOKEN}'}

    # Get current document tags
    resp = requests.get(f'{PAPERLESS_URL}/api/documents/{doc_id}/', headers=headers, timeout=10)
    if not resp.ok:
        logger.error(f'  Doc {doc_id}: failed to fetch from Paperless ({resp.status_code})')
        return False

    doc_data = resp.json()
    current_tag_ids = doc_data.get('tags', [])

    # Resolve tag IDs to names
    all_tags_resp = requests.get(f'{PAPERLESS_URL}/api/tags/?page_size=500', headers=headers, timeout=10)
    if not all_tags_resp.ok:
        logger.error(f'  Doc {doc_id}: failed to fetch tags list')
        return False

    tag_id_by_name = {t['name']: t['id'] for t in all_tags_resp.json().get('results', [])}
    target_tag_id = tag_id_by_name.get(tag_name)
    if target_tag_id is None:
        logger.warning(f'  Tag "{tag_name}" not found in Paperless')
        return False

    if target_tag_id not in current_tag_ids:
        logger.info(f'  Doc {doc_id}: tag "{tag_name}" not present — skipping')
        return True  # Already clean

    new_tag_ids = [t for t in current_tag_ids if t != target_tag_id]
    patch_resp = requests.patch(
        f'{PAPERLESS_URL}/api/documents/{doc_id}/',
        headers=headers,
        json={'tags': new_tag_ids},
        timeout=10
    )
    if patch_resp.ok:
        logger.info(f'  Doc {doc_id}: removed "{tag_name}" ✓')
        return True
    else:
        logger.error(f'  Doc {doc_id}: PATCH failed ({patch_resp.status_code}): {patch_resp.text[:200]}')
        return False


def update_db_record(cursor, doc_id: int, real_duplicates: List[str]):
    """Update the DB record for this document."""
    cursor.execute(
        'SELECT anomaly_types, pattern_flags FROM processed_documents WHERE paperless_doc_id = ?',
        (doc_id,)
    )
    row = cursor.fetchone()
    if not row:
        return

    anomaly_types = json.loads(row[0] or '[]')
    pattern_flags = json.loads(row[1] or '[]')

    if not real_duplicates:
        # Remove duplicate_lines entirely
        anomaly_types = [a for a in anomaly_types if a != 'duplicate_lines']
        pattern_flags = [f for f in pattern_flags if f.get('type') != 'duplicate_lines']
        has_anomalies = len(anomaly_types) > 0
    else:
        # Update flag to only show real duplicates
        for f in pattern_flags:
            if f.get('type') == 'duplicate_lines':
                f['details'] = real_duplicates[:3]
                f['description'] = f'Found {len(real_duplicates)} duplicate transaction lines'
        has_anomalies = True

    cursor.execute(
        '''UPDATE processed_documents
           SET anomaly_types = ?, pattern_flags = ?, has_anomalies = ?
           WHERE paperless_doc_id = ?''',
        (json.dumps(anomaly_types), json.dumps(pattern_flags), has_anomalies, doc_id)
    )


def main():
    if DRY_RUN:
        logger.info('=== DRY RUN mode — no changes will be written ===')

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT paperless_doc_id, pattern_flags FROM processed_documents "
        "WHERE anomaly_types LIKE '%duplicate_lines%'"
    )
    rows = cursor.fetchall()
    logger.info(f'Found {len(rows)} documents with duplicate_lines flag')

    stats = {'removed': 0, 'updated': 0, 'kept': 0, 'errors': 0}

    for doc_id, flags_json in rows:
        flags = json.loads(flags_json or '[]')
        dup_flag = next((f for f in flags if f.get('type') == 'duplicate_lines'), None)
        if not dup_flag:
            continue

        all_details = dup_flag.get('details', [])
        real_dupes = filter_real_duplicates(all_details)
        removed_count = len(all_details) - len(real_dupes)

        if removed_count == 0:
            # Nothing changed for this doc
            stats['kept'] += 1
            continue

        logger.info(f'Doc {doc_id}: {len(all_details)} duplicates → {len(real_dupes)} real after filtering')
        for d in all_details:
            marker = '✓ keep' if d in real_dupes else '✗ remove (header/boilerplate)'
            logger.info(f'  [{marker}] "{d[:80]}"')

        if not DRY_RUN:
            if not real_dupes:
                # Remove the Paperless tag entirely
                ok = remove_tag_from_paperless(doc_id, 'anomaly:duplicate_lines')
                if ok:
                    update_db_record(cursor, doc_id, [])
                    stats['removed'] += 1
                else:
                    stats['errors'] += 1
            else:
                # Keep tag but update DB to only show real duplicates
                update_db_record(cursor, doc_id, real_dupes)
                stats['updated'] += 1
                logger.info(f'  Doc {doc_id}: tag kept — {len(real_dupes)} real duplicate(s) remain')
        else:
            action = 'WOULD REMOVE tag' if not real_dupes else f'WOULD UPDATE to {len(real_dupes)} real dupes'
            logger.info(f'  -> {action}')
            if not real_dupes:
                stats['removed'] += 1
            else:
                stats['updated'] += 1

    if not DRY_RUN:
        conn.commit()

    conn.close()

    logger.info('')
    logger.info('=== Cleanup complete ===')
    logger.info(f'  Tags removed (no real dupes):     {stats["removed"]}')
    logger.info(f'  Records updated (mixed dupes):    {stats["updated"]}')
    logger.info(f'  Unchanged (already correct):      {stats["kept"]}')
    logger.info(f'  Errors:                           {stats["errors"]}')
    if DRY_RUN:
        logger.info('  (DRY RUN — nothing was actually changed)')


if __name__ == '__main__':
    main()
