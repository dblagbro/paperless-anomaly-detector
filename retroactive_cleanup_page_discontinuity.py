#!/usr/bin/env python3
"""
Retroactive cleanup of false-positive anomaly:page_discontinuity tags.

Re-evaluates each document that was flagged with page_discontinuity using the
improved detection logic, which suppresses these common false-positive patterns:

  1. Embedded sub-docs: PDF has MORE pages than declared (e.g., court filing
     containing a 4-page exhibit, actual=183, declared=4).

  2. Continuation excerpts: Document starts at page 2+ (no page 1 stamp found),
     meaning it's a portion extracted from a larger multi-part document.

  3. Cover/trailing stamp missing: PDF has exactly the declared number of pages
     but the cover page or last page simply has no "page X of Y" stamp.

  4. NYSCEF batch contamination: Bank statement says "page 1 of 2" but the
     NYSCEF filing stamp adds "page 16 of 17", inflating declared_max to 17.
     Detected when found_pages = {1..actual} ∪ {declared-actual+1..declared}.

Real anomalies that remain flagged:
  - Genuinely short PDFs (actual < declared, starts at page 1).
  - Internal page gaps (pages missing in the middle of the stamped sequence).

Run inside the anomaly-detector container:
    python3 /app/retroactive_cleanup_page_discontinuity.py
"""

import os
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


def is_false_positive(found_pages: List[int], declared_max: int, actual_count: int) -> bool:
    """
    Return True if this page_discontinuity flag is a false positive under the new rules.

    Uses only the stored found_pages / declared_max / actual_count values.
    """
    if not found_pages or declared_max == 0 or actual_count == 0:
        return False  # Can't evaluate — leave it

    found_set = set(found_pages)
    min_found = min(found_set)

    # Rule 1: actual > declared => embedded sub-document page refs
    if actual_count > declared_max:
        return True

    # Rule 2: actual < declared AND min page > 1 => continuation excerpt
    if actual_count < declared_max and min_found > 1:
        return True

    # Rule 3: actual == declared AND min page > 1 => cover page without stamp
    if actual_count == declared_max and min_found > 1:
        return True

    # Rule 4: actual == declared AND min page == 1 => trailing stamp missing
    # (PDF is the right length; only real issue would be internal gaps, which
    # are kept as a low-severity flag and are not removed here)
    if actual_count == declared_max and min_found == 1:
        # Check for internal gaps — if none, it's just a trailing missing stamp
        max_found = max(found_set)
        expected = set(range(1, max_found + 1))
        internal_gaps = expected - found_set
        if not internal_gaps:
            return True  # Trailing stamp only — suppress

    # Rule 5: NYSCEF batch contamination
    # found_pages = {1..actual} union {declared-actual+1..declared}
    # e.g., found=[1,2,16,17], declared=17, actual=2
    if actual_count < declared_max and min_found == 1:
        lower_group = set(range(1, actual_count + 1))
        upper_group = set(range(declared_max - actual_count + 1, declared_max + 1))
        if found_set == lower_group | upper_group and len(found_set) == 2 * actual_count:
            return True

    return False


def remove_tag_from_paperless(doc_id: int, tag_name: str) -> bool:
    """Remove a specific tag from a Paperless document."""
    headers = {'Authorization': f'Token {PAPERLESS_TOKEN}'}

    resp = requests.get(f'{PAPERLESS_URL}/api/documents/{doc_id}/', headers=headers, timeout=10)
    if not resp.ok:
        logger.error(f'  Doc {doc_id}: failed to fetch from Paperless ({resp.status_code})')
        return False

    doc_data = resp.json()
    current_tag_ids = doc_data.get('tags', [])

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
        return True

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


def update_db_record(cursor, doc_id: int):
    """Remove page_discontinuity from anomaly_types and pattern_flags in DB."""
    cursor.execute(
        'SELECT anomaly_types, pattern_flags FROM processed_documents WHERE paperless_doc_id = ?',
        (doc_id,)
    )
    row = cursor.fetchone()
    if not row:
        return

    anomaly_types = json.loads(row[0] or '[]')
    pattern_flags = json.loads(row[1] or '[]')

    anomaly_types = [a for a in anomaly_types if a != 'page_discontinuity']
    pattern_flags = [f for f in pattern_flags if f.get('type') != 'page_discontinuity']
    has_anomalies = len(anomaly_types) > 0

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
        "SELECT paperless_doc_id, pattern_flags, title FROM processed_documents "
        "WHERE anomaly_types LIKE '%page_discontinuity%'"
    )
    rows = cursor.fetchall()
    logger.info(f'Found {len(rows)} documents with page_discontinuity flag')

    stats = {'removed': 0, 'kept': 0, 'errors': 0}

    for doc_id, flags_json, title in rows:
        flags = json.loads(flags_json or '[]')
        pf = next((f for f in flags if f.get('type') == 'page_discontinuity'), None)
        if not pf:
            continue

        found_pages = pf.get('found_pages', [])
        declared_max = pf.get('declared_max', 0)
        actual_count = pf.get('actual_count', 0)

        fp = is_false_positive(found_pages, declared_max, actual_count)

        if fp:
            logger.info(
                f'Doc {doc_id}: FALSE POSITIVE — found={found_pages}, '
                f'declared={declared_max}, actual={actual_count} | {(title or "")[:50]}'
            )
            if not DRY_RUN:
                ok = remove_tag_from_paperless(doc_id, 'anomaly:page_discontinuity')
                if ok:
                    update_db_record(cursor, doc_id)
                    stats['removed'] += 1
                else:
                    stats['errors'] += 1
            else:
                logger.info(f'  -> WOULD REMOVE tag')
                stats['removed'] += 1
        else:
            logger.info(
                f'Doc {doc_id}: REAL ANOMALY — kept. found={found_pages}, '
                f'declared={declared_max}, actual={actual_count}'
            )
            stats['kept'] += 1

    if not DRY_RUN:
        conn.commit()

    conn.close()

    logger.info('')
    logger.info('=== Cleanup complete ===')
    logger.info(f'  Tags removed (false positives):   {stats["removed"]}')
    logger.info(f'  Tags kept (real anomalies):        {stats["kept"]}')
    logger.info(f'  Errors:                            {stats["errors"]}')
    if DRY_RUN:
        logger.info('  (DRY RUN — nothing was actually changed)')


if __name__ == '__main__':
    main()
