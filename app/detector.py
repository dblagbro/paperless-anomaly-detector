"""Anomaly detection logic for document analysis."""
import logging
import re
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
import json

from config import settings
from image_forensics import get_analyzer
from balance_checker import get_balance_checker

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Detect various types of anomalies in OCR-processed documents."""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def detect_all_anomalies(self, document: Dict, content: str, image_data: bytes = None) -> Dict[str, Any]:
        """
        Run all anomaly detection tests on a document.

        Args:
            document: Document metadata from Paperless API
            content: OCR text content
            image_data: Optional image/PDF file bytes for forensics analysis

        Returns:
            Dictionary with detection results
        """
        results = {
            "has_anomalies": False,
            "anomaly_types": [],
            "balance_check": None,
            "layout_check": None,
            "pattern_check": None,
            "llm_check": None,
            "image_forensics": None
        }

        try:
            # Determine document type
            doc_type = self._infer_document_type(document, content)
            results["document_type"] = doc_type

            # Run smart balance checking (for bank statements)
            if doc_type in ["bank_statement", "financial_statement"]:
                balance_checker = get_balance_checker()
                balance_result = balance_checker.check_balance(content)
                results["balance_check"] = balance_result

                if balance_result.get("status") == "FAIL":
                    results["has_anomalies"] = True
                    results["anomaly_types"].append("balance_mismatch")

                    # Add issues to pattern flags for display
                    if not results.get("pattern_check"):
                        results["pattern_check"] = {"flags": [], "patterns_checked": []}

                    logger.info(f"Balance check FAILED with {len(balance_result.get('issues', []))} issues")
                    for issue in balance_result.get("issues", []):
                        logger.info(f"Adding balance_mismatch flag: {issue[:80]}")
                        results["pattern_check"]["flags"].append({
                            "type": "balance_mismatch",
                            "description": issue,
                            "severity": balance_result.get("severity", "medium"),
                            "details": []
                        })
                    logger.info(f"After adding balance flags: {len(results['pattern_check']['flags'])} total flags")

                # Check for missing check numbers in sequence (separate from balance math)
                sequence_issues = self._check_check_sequence(content)
                if sequence_issues:
                    results["has_anomalies"] = True
                    results["anomaly_types"].append("check_sequence_gap")

                    if not results.get("pattern_check"):
                        results["pattern_check"] = {"flags": [], "patterns_checked": []}

                    for issue in sequence_issues:
                        results["pattern_check"]["flags"].append({
                            "type": "check_sequence_gap",
                            "description": issue,
                            "severity": "medium",
                            "details": []
                        })
            else:
                results["balance_check"] = {"status": "NOT_APPLICABLE"}

            # Run layout irregularity check
            layout_result = self.check_layout_irregularity(content)
            results["layout_check"] = layout_result
            if layout_result.get("status") == "FAIL":
                results["has_anomalies"] = True
                results["anomaly_types"].append("layout_irregularity")

            # Run pattern detection
            pattern_result = self.check_suspicious_patterns(content, doc_type, document)

            # Merge pattern results with existing pattern_check (from balance checker, etc.)
            if results.get("pattern_check"):
                # Append new flags to existing ones
                existing_flags = results["pattern_check"].get("flags", [])
                new_flags = pattern_result.get("flags", [])
                logger.info(f"MERGE: {len(existing_flags)} existing flags + {len(new_flags)} new flags")
                logger.info(f"MERGE: Existing types = {[f.get('type') for f in existing_flags]}")
                logger.info(f"MERGE: New types = {[f.get('type') for f in new_flags]}")
                results["pattern_check"]["flags"] = existing_flags + new_flags
                logger.info(f"MERGE: After merge = {len(results['pattern_check']['flags'])} flags")

                # Merge patterns_checked lists
                existing_patterns = results["pattern_check"].get("patterns_checked", [])
                new_patterns = pattern_result.get("patterns_checked", [])
                results["pattern_check"]["patterns_checked"] = list(set(existing_patterns + new_patterns))
            else:
                logger.info("MERGE: No existing pattern_check, using pattern_result directly")
                results["pattern_check"] = pattern_result

            if pattern_result.get("flags"):
                results["has_anomalies"] = True
                for flag in pattern_result["flags"]:
                    results["anomaly_types"].append(flag["type"])

            # Optional LLM-assisted detection
            if self.llm_client and settings.llm_provider:
                llm_result = self.check_with_llm(content, doc_type)
                results["llm_check"] = llm_result
                if llm_result.get("anomalies_detected"):
                    results["has_anomalies"] = True
                    results["anomaly_types"].extend(llm_result.get("anomaly_types", []))

            # Image forensics analysis (if image data provided)
            if image_data:
                try:
                    analyzer = get_analyzer()
                    filename = document.get("original_file_name", "unknown")
                    forensics_result = analyzer.analyze_image(image_data, filename)
                    results["image_forensics"] = forensics_result

                    if forensics_result.get("manipulations_detected"):
                        results["has_anomalies"] = True
                        # Add forensics flags to pattern check
                        if not results.get("pattern_check"):
                            results["pattern_check"] = {"flags": [], "patterns_checked": []}
                        results["pattern_check"]["flags"].extend(forensics_result.get("flags", []))

                        # Add anomaly types from forensics
                        for flag in forensics_result.get("flags", []):
                            anomaly_type = flag.get("type", "image_manipulation")
                            if anomaly_type not in results["anomaly_types"]:
                                results["anomaly_types"].append(anomaly_type)

                except Exception as e:
                    logger.error(f"Image forensics analysis failed: {e}")
                    results["image_forensics"] = {"error": str(e)}

        except Exception as e:
            logger.error(f"Error during anomaly detection: {e}")
            results["error"] = str(e)

        return results

    def _infer_document_type(self, document: Dict, content: str) -> str:
        """Infer document type from metadata and content."""
        title = document.get("title", "").lower()
        content_lower = content.lower()

        # Check title and content for keywords
        if any(kw in title or kw in content_lower for kw in ["statement", "bank", "account summary"]):
            return "bank_statement"
        elif any(kw in title or kw in content_lower for kw in ["invoice", "bill", "receipt"]):
            return "invoice"
        elif any(kw in title or kw in content_lower for kw in ["rent roll", "rental income"]):
            return "rent_roll"
        elif any(kw in title or kw in content_lower for kw in ["court", "filing", "legal"]):
            return "court_filing"
        else:
            return "unknown"

    def check_balance_arithmetic(self, content: str) -> Dict[str, Any]:
        """
        Check arithmetic consistency in financial documents.

        For bank statements: Ending = Beginning + Credits - Debits

        CURRENT STATUS: DISABLED - Too many false positives

        ISSUES WITH CURRENT IMPLEMENTATION:
        1. Regex patterns too loose - picks up page numbers, dates, account numbers
        2. Transaction extraction is naive - randomly assigns debits/credits
        3. No validation that extracted numbers make sense
        4. Doesn't account for different bank statement formats

        PROPER IMPLEMENTATION WOULD NEED:
        1. Bank-specific format detection (KeyBank, Chase, BofA, etc.)
        2. Table structure parsing (columns: date, description, debit, credit, balance)
        3. Validation: extracted balances should be in reasonable range (not $4.00 from page "1 of 4")
        4. Cross-check: running balance column should match calculated balance
        5. Handle edge cases: fees, interest, transfers
        """
        result = {
            "status": "NOT_APPLICABLE",
            "beginning_balance": None,
            "ending_balance": None,
            "calculated_balance": None,
            "difference": None,
            "credits_total": None,
            "debits_total": None
        }

        try:
            # Extract financial numbers using regex
            beginning = self._extract_balance(content, ["beginning balance", "opening balance", "previous balance"])
            ending = self._extract_balance(content, ["ending balance", "closing balance", "current balance", "new balance"])

            if beginning is None or ending is None:
                result["status"] = "NOT_APPLICABLE"
                return result

            result["beginning_balance"] = beginning
            result["ending_balance"] = ending

            # Extract transactions
            credits, debits = self._extract_transactions(content)
            result["credits_total"] = sum(credits) if credits else 0.0
            result["debits_total"] = sum(debits) if debits else 0.0

            # Calculate expected ending balance
            calculated = beginning + result["credits_total"] - result["debits_total"]
            result["calculated_balance"] = calculated

            # Check if balances match within tolerance
            difference = abs(ending - calculated)
            result["difference"] = difference

            if difference <= settings.balance_tolerance:
                result["status"] = "PASS"
            else:
                result["status"] = "FAIL"
                logger.warning(f"Balance mismatch detected: difference = ${difference:.2f}")

        except Exception as e:
            logger.error(f"Error in balance check: {e}")
            result["status"] = "ERROR"
            result["error"] = str(e)

        return result

    def _extract_balance(self, content: str, keywords: List[str]) -> Optional[float]:
        """Extract balance amount following specific keywords."""
        for keyword in keywords:
            # Pattern: keyword followed by optional colon/punctuation, then currency amount
            pattern = rf"{keyword}[\s:]*\$?\s*([\d,]+\.?\d*)"
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(",", "")
                try:
                    return float(amount_str)
                except ValueError:
                    continue
        return None

    def _extract_transactions(self, content: str) -> Tuple[List[float], List[float]]:
        """
        Extract credits and debits from transaction lines.
        Simple heuristic: look for two-column numbers (date, description, debit, credit pattern).
        """
        credits = []
        debits = []

        # Pattern for transaction lines with amounts
        # This is a simplified pattern - real implementation would be more sophisticated
        lines = content.split('\n')

        for line in lines:
            # Look for lines with currency amounts
            amounts = re.findall(r'\$?\s*([\d,]+\.\d{2})', line)

            if len(amounts) >= 2:
                # Assume last two numbers might be debit and credit
                try:
                    # Very simple heuristic - would need refinement
                    amt1 = float(amounts[-2].replace(",", ""))
                    amt2 = float(amounts[-1].replace(",", ""))

                    # If one is significantly larger, it might be a running balance
                    if amt1 > amt2:
                        debits.append(amt1)
                    else:
                        credits.append(amt2)
                except (ValueError, IndexError):
                    continue

        return credits, debits

    def _check_check_sequence(self, content: str) -> List[str]:
        """
        Check for gaps in check number sequences.

        Returns a list of issues describing missing check numbers.
        """
        issues = []

        # Find all check numbers
        check_pattern = r'\b(\d{4})\s+\d{1,2}[-/]\d{1,2}\s+\$?[\d,]+\.\d{2}'
        checks = re.findall(check_pattern, content)

        if not checks:
            return issues

        try:
            check_numbers = sorted([int(c) for c in checks])

            if len(check_numbers) < 2:
                return issues

            # Look for gaps in sequence
            missing = []
            for i in range(len(check_numbers) - 1):
                current = check_numbers[i]
                next_check = check_numbers[i + 1]

                # If there's a gap of more than 1
                if next_check - current > 1:
                    for missing_num in range(current + 1, next_check):
                        missing.append(missing_num)

            if missing:
                # Only report if gap is small (likely missing from this statement)
                if len(missing) <= 5:
                    missing_str = ', '.join([str(m) for m in missing])
                    issues.append(
                        f"Missing check numbers in sequence: {missing_str}. "
                        f"These checks may be unaccounted for on this statement."
                    )

        except (ValueError, TypeError):
            pass

        return issues

    def check_layout_irregularity(self, content: str) -> Dict[str, Any]:
        """
        Check for layout irregularities with specific locations and examples.

        Focuses on actual OCR/formatting problems rather than normal document variance.
        """
        result = {
            "status": "PASS",
            "score": 1.0,
            "issues": [],
            "details": []
        }

        try:
            lines = content.split('\n')
            total_lines = len(lines)

            # Only analyze if document has reasonable content
            if total_lines < 10:
                result["status"] = "NOT_APPLICABLE"
                return result

            # 1. Check for OCR artifacts (garbled text)
            garbled_lines = []
            for i, line in enumerate(lines, 1):
                if len(line.strip()) > 10:  # Only check substantial lines
                    # Count character types
                    alnum = sum(1 for c in line if c.isalnum())
                    special = sum(1 for c in line if not c.isalnum() and not c.isspace())

                    # If more than 40% special characters, likely garbled
                    if alnum > 0 and special / (alnum + special) > 0.4:
                        garbled_lines.append({
                            "line_num": i,
                            "text": line.strip()[:100],
                            "issue": "Excessive special characters (possible OCR error)"
                        })

            if len(garbled_lines) > 5:  # More than 5 garbled lines is a problem
                result["issues"].append(f"Found {len(garbled_lines)} lines with OCR artifacts")
                result["details"].extend(garbled_lines[:3])  # Show first 3 examples
                result["score"] *= 0.6
                result["status"] = "FAIL"

            # 2. Check for misaligned columns in tabular data
            # Look for lines that should be aligned (dollar amounts, dates)
            amount_lines = []
            for i, line in enumerate(lines, 1):
                # Find lines with dollar amounts
                if '$' in line or re.search(r'\d+\.\d{2}', line):
                    amount_pos = line.find('$')
                    if amount_pos < 0:
                        # Find decimal amounts
                        match = re.search(r'\d+\.\d{2}', line)
                        if match:
                            amount_pos = match.start()

                    if amount_pos >= 0:
                        amount_lines.append((i, amount_pos, line.strip()[:80]))

            # Check if amount columns are consistently aligned
            if len(amount_lines) > 10:  # Only check if we have enough data
                positions = [pos for _, pos, _ in amount_lines]
                # Calculate standard deviation of positions
                avg_pos = sum(positions) / len(positions)
                variance = sum((p - avg_pos) ** 2 for p in positions) / len(positions)
                std_dev = variance ** 0.5

                # If standard deviation is > 20 characters, columns are misaligned
                if std_dev > 20:
                    outliers = [(line_num, text) for line_num, pos, text in amount_lines
                               if abs(pos - avg_pos) > 30][:3]

                    if outliers:
                        result["issues"].append(f"Column misalignment detected (std dev: {std_dev:.1f})")
                        result["details"].extend([{
                            "line_num": ln,
                            "text": text,
                            "issue": "Amount not aligned with other rows"
                        } for ln, text in outliers])
                        result["score"] *= 0.8
                        if result["status"] == "PASS":
                            result["status"] = "WARNING"

            # 3. Check for truncated lines (cut off mid-word)
            truncated_lines = []
            for i, line in enumerate(lines, 1):
                stripped = line.rstrip()
                # If line ends with a word fragment (no punctuation, next line starts with lowercase)
                if len(stripped) > 50 and i < total_lines - 1:
                    if stripped and stripped[-1].isalnum():
                        next_line = lines[i].lstrip() if i < len(lines) else ""
                        if next_line and next_line[0].islower():
                            truncated_lines.append({
                                "line_num": i,
                                "text": stripped[-50:],
                                "issue": "Line appears truncated (continues on next line)"
                            })

            if len(truncated_lines) > 10:  # More than 10 is unusual
                result["issues"].append(f"Found {len(truncated_lines)} potentially truncated lines")
                result["details"].extend(truncated_lines[:2])
                result["score"] *= 0.9
                if result["status"] == "PASS":
                    result["status"] = "WARNING"

            # 4. Check for completely empty sections (missing content)
            consecutive_empty = 0
            max_empty_block = 0
            empty_block_location = None

            for i, line in enumerate(lines, 1):
                if not line.strip():
                    consecutive_empty += 1
                else:
                    if consecutive_empty > max_empty_block:
                        max_empty_block = consecutive_empty
                        empty_block_location = i - consecutive_empty
                    consecutive_empty = 0

            # More than 20 consecutive empty lines is suspicious
            if max_empty_block > 20:
                result["issues"].append(f"Large empty section ({max_empty_block} blank lines)")
                result["details"].append({
                    "line_num": empty_block_location,
                    "text": f"[{max_empty_block} blank lines]",
                    "issue": "Possible missing content or page break issue"
                })
                if result["status"] == "PASS":
                    result["status"] = "WARNING"

            # Only fail if we found actual problems
            if not result["issues"]:
                result["status"] = "PASS"
                result["score"] = 1.0

        except Exception as e:
            logger.error(f"Error in layout check: {e}")
            result["status"] = "ERROR"
            result["error"] = str(e)

        return result

    def check_suspicious_patterns(self, content: str, doc_type: str, document: Dict = None) -> Dict[str, Any]:
        """
        Detect suspicious patterns using regex and rules.
        """
        if document is None:
            document = {}

        result = {
            "flags": [],
            "patterns_checked": []
        }

        patterns_to_check = [
            # Reversed column patterns (amounts in description field)
            {
                "name": "reversed_columns",
                "pattern": r"^\$[\d,]+\.\d{2}\s+[A-Za-z]",
                "description": "Possible reversed column order detected"
            },
            # Truncated totals (Total/Sum without following number)
            {
                "name": "truncated_total",
                "pattern": r"(total|sum|subtotal)[\s:]*$",
                "description": "Total label without corresponding amount"
            },
            # Duplicate line detection (same line repeated)
            {
                "name": "duplicate_lines",
                "pattern": None,  # Handled separately
                "description": "Duplicate transaction lines detected"
            },
            # Missing page numbers or discontinuity
            {
                "name": "page_discontinuity",
                "pattern": r"page\s+(\d+)\s+of\s+(\d+)",
                "description": "Page numbering issues"
            }
        ]

        try:
            lines = content.split('\n')
            actual_page_count = document.get('page_count', 0)

            for pattern_def in patterns_to_check:
                result["patterns_checked"].append(pattern_def["name"])

                if pattern_def["name"] == "page_discontinuity":
                    # Enhanced page discontinuity check
                    page_matches = re.findall(r"page\s+(\d+)\s+of\s+(\d+)", content, re.IGNORECASE)
                    if page_matches:
                        # Collect all (page_num, max_page) pairs with their individual declared values
                        pairs = [(int(pn), int(mp)) for pn, mp in page_matches]
                        all_declared_vals = [mp for _, mp in pairs]
                        distinct_declared = set(all_declared_vals)
                        raw_declared_max = max(all_declared_vals)

                        # Resolve mixed numbering systems
                        # e.g., NYSCEF batch "page 16 of 17" mixed with bank statement "page 1 of 2"
                        # When actual page count matches one of the declared values, restrict to that context
                        if len(distinct_declared) > 1 and actual_page_count > 0 and actual_page_count in distinct_declared:
                            effective_declared = actual_page_count
                            effective_found = {pn for pn, mp in pairs if mp == actual_page_count}
                        else:
                            effective_declared = raw_declared_max
                            effective_found = {pn for pn, _ in pairs}

                        min_found = min(effective_found)
                        max_found = max(effective_found)

                        issues = []
                        severity = "low"

                        if actual_page_count > 0:
                            if actual_page_count > effective_declared:
                                # PDF has MORE pages than declared — embedded sub-document page refs
                                # (e.g., NYSCEF court filing contains a 4-page exhibit; actual=183, declared=4)
                                # Not a real anomaly — suppress.
                                pass

                            elif actual_page_count < effective_declared and min_found > 1:
                                # Continuation/excerpt: document starts at page 2+ (no page 1)
                                # This is a portion of a larger multi-part document — suppress.
                                pass

                            elif actual_page_count == effective_declared and min_found > 1:
                                # Cover page has no page stamp but rest are present — suppress.
                                pass

                            elif actual_page_count == effective_declared:
                                # PDF is the right length; only flag if internal gaps exist
                                # (pages missing in the middle of the stamped sequence)
                                if min_found == 1 and max_found > 1:
                                    expected = set(range(1, max_found + 1))
                                    internal_gaps = expected - effective_found
                                    if internal_gaps:
                                        issues.append(
                                            f"Page stamps missing for pages {sorted(internal_gaps)} "
                                            f"(PDF has correct {actual_page_count} pages)"
                                        )
                                        severity = "low"

                            elif actual_page_count < effective_declared and min_found == 1:
                                # Genuinely short PDF: starts at page 1 but fewer pages than declared
                                pages_missing = effective_declared - actual_page_count
                                issues.append(
                                    f"PDF has {actual_page_count} page(s) but page headers declare "
                                    f"{effective_declared} — {pages_missing} page(s) may be missing"
                                )
                                severity = "medium"

                                # Additionally flag internal gaps if any (e.g., found=[1,3], declared=4, actual=2)
                                expected = set(range(min_found, max_found + 1))
                                internal_gaps = expected - effective_found
                                if internal_gaps:
                                    issues.append(
                                        f"Non-sequential page stamps: pages {sorted(internal_gaps)} "
                                        f"not referenced between pages {min_found}–{max_found}"
                                    )
                                    severity = "high"

                        if issues:
                            result["flags"].append({
                                "type": "page_discontinuity",
                                "description": "Page numbering inconsistencies detected",
                                "severity": severity,
                                "details": issues,
                                "found_pages": sorted(effective_found),
                                "declared_max": effective_declared,
                                "actual_count": actual_page_count
                            })
                    # Documents without page number stamps are not flagged — that's normal.
                elif pattern_def["name"] == "duplicate_lines":
                    # Check for duplicate TRANSACTION lines (not headers/footers/addresses)
                    # Only flag lines that contain financial data (amounts, dates, check numbers)
                    seen_lines = {}
                    for line in lines:
                        line_clean = line.strip()

                        # Only check lines that contain financial transaction indicators:
                        # - Dollar amounts or decimal amounts
                        # - Date patterns
                        # - Check numbers (4 digits followed by date/amount)
                        has_amount = bool(re.search(r'\$\s*[\d,]+\.\d{2}|\b[\d,]+\.\d{2}\b', line_clean))
                        has_date = bool(re.search(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b', line_clean))
                        has_check_num = bool(re.search(r'\b\d{4}\b', line_clean))

                        # Line must have financial indicators to be considered
                        if len(line_clean) > 20 and (has_amount or (has_date and has_check_num)):
                            # Exclude common headers/footers by checking for keywords
                            lower_line = line_clean.lower()
                            is_header = any(keyword in lower_line for keyword in [
                                # Bank statement column headers / footers
                                'page', 'account', 'statement', 'balance', 'date', 'description',
                                'amount', 'check', 'deposit', 'withdrawal', 'branch', 'address',
                                'customer service', 'member fdic', 'routing', 'account number',
                                # Bank boilerplate that repeats on every page
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
                            ])

                            # Only track non-header lines with transaction data
                            if not is_header:
                                if line_clean in seen_lines:
                                    seen_lines[line_clean] += 1
                                else:
                                    seen_lines[line_clean] = 1

                    duplicates = {line: count for line, count in seen_lines.items() if count > 1}
                    if duplicates:
                        result["flags"].append({
                            "type": "duplicate_lines",
                            "description": f"Found {len(duplicates)} duplicate transaction lines",
                            "severity": "medium",
                            "details": list(duplicates.keys())[:3]  # First 3 examples
                        })
                else:
                    # Regex-based checks
                    if pattern_def["pattern"]:
                        matches = re.findall(pattern_def["pattern"], content, re.IGNORECASE | re.MULTILINE)
                        if matches:
                            result["flags"].append({
                                "type": pattern_def["name"],
                                "description": pattern_def["description"],
                                "severity": "medium",
                                "match_count": len(matches)
                            })

        except Exception as e:
            logger.error(f"Error in pattern check: {e}")
            result["error"] = str(e)

        return result

    def check_with_llm(self, content: str, doc_type: str) -> Dict[str, Any]:
        """
        Use LLM to analyze document for anomalies.
        Structured prompting to avoid hallucination.
        """
        result = {
            "anomalies_detected": False,
            "anomaly_types": [],
            "analysis": "",
            "confidence": 0.0
        }

        if not self.llm_client:
            return result

        try:
            # Truncate content to avoid token limits
            content_preview = content[:3000] if len(content) > 3000 else content

            prompt = f"""Analyze this {doc_type} document for financial anomalies.

Document text:
{content_preview}

Check for:
1. Arithmetic inconsistencies in totals or balances
2. Missing or unusual formatting in financial data
3. Suspicious patterns like duplicate entries or reversed columns

Respond in JSON format:
{{
  "anomalies_found": true/false,
  "anomaly_types": ["type1", "type2"],
  "explanation": "brief explanation",
  "confidence": 0.0-1.0
}}"""

            response_text = self.llm_client.analyze(prompt)

            # Parse JSON response
            response_data = json.loads(response_text)
            result["anomalies_detected"] = response_data.get("anomalies_found", False)
            result["anomaly_types"] = response_data.get("anomaly_types", [])
            result["analysis"] = response_data.get("explanation", "")
            result["confidence"] = response_data.get("confidence", 0.0)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            result["error"] = "Invalid LLM response format"
        except Exception as e:
            logger.error(f"Error in LLM check: {e}")
            result["error"] = str(e)

        return result
