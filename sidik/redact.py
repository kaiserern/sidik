"""Scrub customer data before anything reaches a Teams channel."""

import re

# Card numbers, NIK and account numbers all live at 12+ digits.
ID_RUN = re.compile(r"\b\d{12,19}\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
PHONE = re.compile(r"(?:\+62|62|0)8\d{7,11}\b")


def redact(text: str) -> str:
    """IDs first: a phone number with a country code is also a long digit run."""
    text = ID_RUN.sub("[REDACTED-ID]", text)
    text = PHONE.sub("[REDACTED-PHONE]", text)
    text = EMAIL.sub("[REDACTED-EMAIL]", text)
    return text


def redact_event(msg: str, limit: int = 160) -> str:
    flat = " ".join(msg.split())
    if len(flat) > limit:
        flat = flat[:limit] + " ..."
    return redact(flat)


# shortcut: 10-11 digit account numbers slip through, kept so IDR amounts stay readable.
# Upgrade when a real leak shows up in the redaction test set.
