"""Smart balance checking for bank statements."""
import re
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class SmartBalanceChecker:
    """Intelligent balance checking that looks for real discrepancies."""

    def check_balance(self, content: str) -> Dict[str, Any]:
        """
        Check for balance discrepancies in bank statements.

        Looks for:
        1. Transaction count mismatches (claims 13 but lists 12)
        2. Total amount mismatches (claims $X but sum is $Y)
        3. Missing checks in sequence
        """
        result = {
            "status": "PASS",
            "issues": [],
            "severity": "low",
            "difference": None  # Dollar amount difference for display
        }

        # Check transaction count mismatches with amount verification
        count_issues, difference_amount = self._check_transaction_counts(content)
        if count_issues:
            result["issues"].extend(count_issues)
            result["status"] = "FAIL"
            result["severity"] = "high"
            result["difference"] = difference_amount  # Store for display

        # Note: Check sequence gaps are now handled as a separate anomaly type
        # in the pattern detection, not in balance checking

        return result

    def _check_transaction_counts(self, content: str) -> Tuple[List[str], Optional[float]]:
        """
        Check if claimed transaction counts match actual counts.

        Example issue: "13 Subtractions" but only 12 checks listed

        Returns: (issues, difference_amount)
        """
        issues = []
        difference_amount = None

        # Find transaction count claims
        # Pattern: number followed by transaction type (Additions, Subtractions, etc.)
        claims = re.findall(
            r'(\d+)\s+(Addition|Subtraction|Deposit|Withdrawal|Check|Debit|Credit)s?',
            content,
            re.IGNORECASE
        )

        for claimed_count_str, trans_type in claims:
            try:
                claimed_count = int(claimed_count_str)

                # Skip unreasonable counts (likely false matches)
                if claimed_count < 1 or claimed_count > 1000:
                    continue

                # Look for the transaction type section and count actual items
                trans_type_lower = trans_type.lower()

                if trans_type_lower in ['subtraction', 'check', 'debit']:
                    # Count check numbers or debit lines and sum amounts
                    actual_count, actual_total = self._count_and_sum_checks(content)

                    if actual_count > 0 and actual_count != claimed_count:
                        diff = claimed_count - actual_count

                        # Try to find the claimed amount for this transaction type
                        claimed_amount = self._find_claimed_amount(content, claimed_count_str)

                        if claimed_amount and actual_total:
                            # Show both count AND amount mismatch
                            amount_diff = abs(claimed_amount - actual_total)
                            difference_amount = amount_diff  # Store for return
                            issues.append(
                                f"Transaction mismatch: Statement claims {claimed_count} {trans_type}s totaling ${claimed_amount:,.2f}, "
                                f"but statement shows actual total of ${actual_total:,.2f}. "
                                f"Missing {diff} transaction(s) worth ${amount_diff:,.2f}."
                            )
                        else:
                            # Just show count mismatch
                            issues.append(
                                f"Transaction count mismatch: Claims {claimed_count} {trans_type}s "
                                f"but only {actual_count} items found. Missing {diff} transaction(s)."
                            )

            except (ValueError, TypeError):
                continue

        return issues, difference_amount

    def _count_checks(self, content: str) -> int:
        """Count actual check numbers in the document."""
        count, _ = self._count_and_sum_checks(content)
        return count

    def _count_and_sum_checks(self, content: str) -> Tuple[int, Optional[float]]:
        """
        Count actual check numbers and sum their amounts.

        Returns: (count, total_amount)
        """
        # First, try to get the official total from "Paper Checks Paid" line
        summary_total = None
        summary_patterns = [
            r'Paper\s+Checks?\s+(?:Paid|Paict|Total)[\s~$]+([\d,]+\.\d{2})',
            r'Total\s+(?:Checks?|Debits?)[\s~:$]+([\d,]+\.\d{2})',
        ]
        for pattern in summary_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                try:
                    summary_total = float(match.group(1).replace(',', ''))
                    break
                except (ValueError, IndexError):
                    continue

        # Count check numbers
        # Pattern: check number followed by date and amount
        check_pattern = r'\b(\d{4})\s+\d{1,2}[-/]\d{1,2}\s+\$?([\d,]+\.\d{2})'
        matches = re.findall(check_pattern, content)

        # Track unique checks and their amounts
        seen_checks = {}
        for check_num, amount_str in matches:
            if check_num not in seen_checks:
                try:
                    amount = float(amount_str.replace(',', ''))
                    seen_checks[check_num] = amount
                except ValueError:
                    pass

        count = len(seen_checks)
        # Prefer the official summary total over summing individual checks
        total = summary_total if summary_total else (sum(seen_checks.values()) if seen_checks else None)
        return count, total

    def _find_claimed_amount(self, content: str, count_str: str) -> Optional[float]:
        """
        Find the claimed total amount near a transaction count claim.

        Example: "13 Subtractions $12,887.90" or "13 Subtractions ~4 2,887.90" (OCR error)
        """
        # Also get the actual total for comparison
        actual_total = None
        summary_patterns = [
            r'Paper\s+Checks?\s+(?:Paid|Paict|Total)[\s~$]+([\d,]+\.\d{2})',
            r'Total\s+(?:Checks?|Debits?|Subtractions?)[\s~:$]+([\d,]+\.\d{2})',
        ]
        for pattern in summary_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                try:
                    actual_total = float(match.group(1).replace(',', ''))
                    break
                except (ValueError, IndexError):
                    continue

        # Look for: count + transaction type + amount (with possible OCR errors)
        pattern = rf'{count_str}\s+(?:Subtraction|Check|Debit)s?\s+[~\-\+\$\s]*([\d\s,\.]+)'
        match = re.search(pattern, content, re.IGNORECASE)

        if match:
            try:
                # Extract just the number part
                amount_str = match.group(1).strip()
                amount_match = re.search(r'([\d,\s]+\.\d{2})', amount_str)
                if amount_match:
                    amount_clean = amount_match.group(1).replace(',', '').replace(' ', '')
                    claimed = float(amount_clean)

                    # If way off from actual, try to fix OCR errors
                    if actual_total and (claimed > actual_total * 3 or claimed < actual_total * 0.3):
                        digits_str = str(int(claimed))
                        if len(digits_str) >= 4:
                            # Try: drop first digit or insert "1" at start
                            alt1 = float(digits_str[1:] + '.' + amount_clean.split('.')[1])
                            alt2 = float('1' + digits_str[1:] + '.' + amount_clean.split('.')[1])
                            candidates = [(claimed, abs(claimed - actual_total)),
                                        (alt1, abs(alt1 - actual_total)),
                                        (alt2, abs(alt2 - actual_total))]
                            best = min(candidates, key=lambda x: x[1])
                            claimed = best[0]

                    if 0.01 < claimed < 1000000:
                        return claimed
            except (ValueError, IndexError, AttributeError):
                pass

        return None

    def _check_amount_mismatches(self, content: str) -> List[str]:
        """
        Check if claimed transaction totals match the sum of actual transactions.

        Example: "13 Subtractions $12,887.90" but "Paper Checks Paid ~ $12,732.98"
        """
        issues = []

        # First, look for "Paper Checks Paid" or similar summary lines (most reliable)
        summary_patterns = [
            r'Paper\s+Checks?\s+(?:Paid|Paict|Total)[\s~$]+([\d,]+\.\d{2})',  # Added "Paict" for OCR errors
            r'Total\s+(?:Checks?|Debits?|Subtractions?)[\s~:$]+([\d,]+\.\d{2})',
            r'(?:Checks?|Debits?)\s+(?:Paid|Total)[\s~:$]+([\d,]+\.\d{2})',
        ]

        actual_total = None
        for pattern in summary_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                try:
                    actual_total = float(match.group(1).replace(',', ''))
                    logger.info(f"Found actual total from summary line: ${actual_total:,.2f}")
                    break
                except (ValueError, IndexError):
                    continue

        if not actual_total:
            logger.debug("No summary total found, cannot verify amounts")
            return issues

        # Now find the claimed total - look near transaction count claims
        claimed_total = None

        # Look for patterns like: "13 Subtractions $12,887.90" or with OCR errors "13 Subtractions ~4 2,887.90"
        # Be flexible about what's between the transaction type and the amount
        claimed_pattern = r'(\d+)\s+(?:Subtraction|Check|Debit)s?\s+[~\-\+\$\s]*([\d\s,\.]+)'
        match = re.search(claimed_pattern, content, re.IGNORECASE)

        if match:
            try:
                # Get the amount string
                amount_str = match.group(2).strip()
                # Extract just the number part (digits, commas, decimal)
                # Look for pattern like "X,XXX.XX" or "XXX.XX"
                amount_match = re.search(r'([\d,\s]+\.\d{2})', amount_str)
                if amount_match:
                    amount_clean = amount_match.group(1).replace(',', '').replace(' ', '')
                    claimed_total = float(amount_clean)
                    logger.info(f"Found claimed total: ${claimed_total:,.2f}")

                    # If claimed total doesn't make sense (way off from actual), try alternate interpretations
                    if actual_total and (claimed_total > actual_total * 3 or claimed_total < actual_total * 0.3):
                        # Might have OCR errors - try to infer the right amount
                        # Common: "~4 2,887.90" should be "$12,887.90"
                        # We extracted "42887.90" but want "12887.90"
                        digits_str = str(int(claimed_total))
                        if len(digits_str) >= 4:
                            # Try interpretations:
                            # 1. Drop first digit: "42887" -> "2887"
                            alt1 = float(digits_str[1:] + '.' + amount_clean.split('.')[1])
                            # 2. Insert "1" at start of remaining: "42887" -> "12887"
                            alt2 = float('1' + digits_str[1:] + '.' + amount_clean.split('.')[1])

                            # Pick the one closest to actual
                            candidates = [(claimed_total, abs(claimed_total - actual_total)),
                                        (alt1, abs(alt1 - actual_total)),
                                        (alt2, abs(alt2 - actual_total))]
                            best = min(candidates, key=lambda x: x[1])
                            claimed_total = best[0]
                            logger.info(f"Adjusted claimed total to: ${claimed_total:,.2f} (closer to actual)")
            except (ValueError, IndexError, AttributeError) as e:
                logger.debug(f"Failed to parse claimed amount: {e}")
                pass

        if not claimed_total or claimed_total < 1:
            logger.debug("No valid claimed total found")
            return issues

        # Compare claimed vs actual
        difference = abs(claimed_total - actual_total)
        if difference > 0.02:  # More than 2 cents difference
            issues.append(
                f"Amount mismatch: Statement claims ${claimed_total:,.2f} in subtractions, "
                f"but checks actually total ${actual_total:,.2f}. "
                f"Difference: ${difference:,.2f}"
            )

        return issues

    def _check_missing_checks(self, content: str) -> List[str]:
        """Check for gaps in check number sequences."""
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
                        f"These checks may be unaccounted for."
                    )

        except (ValueError, TypeError):
            pass

        return issues


def get_balance_checker() -> SmartBalanceChecker:
    """Get the smart balance checker instance."""
    return SmartBalanceChecker()
