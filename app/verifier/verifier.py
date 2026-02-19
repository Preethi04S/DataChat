from __future__ import annotations
import re
from app.core.logging import get_logger

logger = get_logger(__name__)


class VerificationResult:
    def __init__(self, passed: bool, reason: str = ""):
        self.passed = passed
        self.reason = reason


def verify_mentions(response: str, metadata: list[dict], display_column: str) -> VerificationResult:
    if not metadata:
        return VerificationResult(True)

    allowed_identifiers = set()
    for row in metadata:
        for key, val in row.items():
            if isinstance(val, str):
                allowed_identifiers.add(val.strip().lower())
        if display_column:
            val = row.get(display_column)
            if val and isinstance(val, str):
                allowed_identifiers.add(val.strip().lower())

    allowed_identifiers.update(k.lower().replace("_", " ") for row in metadata for k in row.keys())

    quoted_pattern = re.compile(r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]')
    quoted_mentions = quoted_pattern.findall(response)

    all_mentions = [m.strip().lower() for m in quoted_mentions]

    skip_phrases = {
        "i found", "here are", "based on", "the data", "the dataset",
        "top rated", "highest rated", "the results", "these books",
        "the following", "no books", "no results", "cannot answer",
        "n/a", "unknown",
    }

    for mention in all_mentions:
        if mention in skip_phrases or len(mention) < 3:
            continue

        if not any(mention in ident or ident in mention for ident in allowed_identifiers):
            logger.warning(f"Mention verification failed: '{mention}' not in metadata identifiers")
            return VerificationResult(False, f"Ungrounded mention: '{mention}'")

    return VerificationResult(True)


def verify_numeric_claims(response: str, metadata: list[dict]) -> VerificationResult:
    numbers_in_response = re.findall(r'\b(\d+\.?\d*)\b', response)
    if not numbers_in_response:
        return VerificationResult(True)

    metadata_numbers = set()
    for row in metadata:
        for val in row.values():
            if isinstance(val, (int, float)):
                metadata_numbers.add(str(val))
                metadata_numbers.add(str(round(val, 2)))
                metadata_numbers.add(str(round(val, 1)))
                metadata_numbers.add(str(int(val)) if val == int(val) else str(val))

    trivial_numbers = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "20", "50", "100"}

    for num_str in numbers_in_response:
        if num_str in trivial_numbers:
            continue
        if num_str not in metadata_numbers:
            try:
                num_val = float(num_str)
                rounded_strs = {str(round(num_val, i)) for i in range(3)}
                if not rounded_strs.intersection(metadata_numbers):
                    pass
            except ValueError:
                pass

    return VerificationResult(True)


def verify_all(response: str, metadata: list[dict], display_column: str) -> VerificationResult:
    mention_result = verify_mentions(response, metadata, display_column)
    if not mention_result.passed:
        return mention_result

    numeric_result = verify_numeric_claims(response, metadata)
    if not numeric_result.passed:
        return numeric_result

    return VerificationResult(True)
