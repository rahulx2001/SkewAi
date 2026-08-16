"""Basic PII detection/redaction for pilot transcripts (regex, not NER)."""

from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def redact_pii(text: str) -> str:
    """Replace common PII patterns with placeholders."""
    if not text:
        return text
    out = _EMAIL.sub("[EMAIL]", text)
    out = _PHONE.sub("[PHONE]", out)
    out = _SSN.sub("[SSN]", out)
    out = _CC.sub("[CARD]", out)
    return out


def find_pii(text: str) -> list[str]:
    kinds: list[str] = []
    if _EMAIL.search(text or ""):
        kinds.append("email")
    if _PHONE.search(text or ""):
        kinds.append("phone")
    if _SSN.search(text or ""):
        kinds.append("ssn")
    return kinds


__all__ = ["redact_pii", "find_pii"]
