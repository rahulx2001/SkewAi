"""Basic PII detection/redaction for pilot transcripts (regex, not NER)."""

from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
# Conservative street-address pattern: house number + capitalized words +
# street suffix. Word-boundary anchored to avoid flagging prose.
_ADDRESS = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|"
    r"Court|Ct|Circle|Cir|Parkway|Pkwy|Terrace|Plaza|Way)\b"
)


def redact_pii(text: str) -> str:
    """Replace common PII patterns with placeholders."""
    if not text:
        return text
    out = _EMAIL.sub("[EMAIL]", text)
    out = _PHONE.sub("[PHONE]", out)
    out = _SSN.sub("[SSN]", out)
    out = _CC.sub("[CARD]", out)
    out = _ADDRESS.sub("[ADDRESS]", out)
    return out


def find_pii(text: str) -> list[str]:
    kinds: list[str] = []
    if _EMAIL.search(text or ""):
        kinds.append("email")
    if _PHONE.search(text or ""):
        kinds.append("phone")
    if _SSN.search(text or ""):
        kinds.append("ssn")
    if _ADDRESS.search(text or ""):
        kinds.append("address")
    return kinds


#: Free-text fields that may carry customer PII across read/export surfaces.
PII_TEXT_FIELDS = frozenset({
    "description",
    "description_summary",
    "followup_draft",
    "text",
    "note",
    "notes",
    "summary",
    "input_summary",
    "output_summary",
})


def redact_dict(row: dict[str, Any], fields: frozenset[str] = PII_TEXT_FIELDS) -> dict[str, Any]:
    """Return a copy of *row* with PII redacted in known free-text fields."""
    out = dict(row)
    for key in fields:
        val = out.get(key)
        if isinstance(val, str) and val:
            out[key] = redact_pii(val)
    return out


def redact_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Redact PII in conversation turn text (returns new list)."""
    redacted: list[dict[str, Any]] = []
    for turn in turns:
        t = dict(turn)
        if isinstance(t.get("text"), str):
            t["text"] = redact_pii(t["text"])
        redacted.append(t)
    return redacted


import base64
import hashlib
import secrets


class SubjectKeyStore:
    """Vault for per-subject data encryption keys enabling crypto-shredding (audit 5.1).

    Destroying the subject's DEK renders stored encrypted ciphertext permanently
    unrecoverable without breaking historical hash chains or Merkle tree leaves.
    """
    _keys: dict[str, bytes] = {}

    @classmethod
    def get_or_create_dek(cls, subject_id: str) -> bytes:
        if subject_id not in cls._keys:
            cls._keys[subject_id] = secrets.token_bytes(32)
        return cls._keys[subject_id]

    @classmethod
    def shred_dek(cls, subject_id: str) -> bool:
        """Permanently erase the subject's encryption key (GDPR Art. 17)."""
        if subject_id in cls._keys:
            del cls._keys[subject_id]
            return True
        return False

    @classmethod
    def has_dek(cls, subject_id: str) -> bool:
        return subject_id in cls._keys

    @classmethod
    def clear(cls) -> None:
        cls._keys.clear()


def encrypt_subject_pii(subject_id: str, plaintext: str) -> str:
    """Encrypt PII under the subject's dedicated DEK."""
    if not plaintext:
        return ""
    dek = SubjectKeyStore.get_or_create_dek(subject_id)
    nonce = secrets.token_bytes(12)
    stream_key = hashlib.blake2b(dek, key=nonce, digest_size=max(1, len(plaintext.encode()))).digest()
    cipher_bytes = bytes(b ^ k for b, k in zip(plaintext.encode("utf-8"), stream_key))
    payload = nonce + cipher_bytes
    return "enc:v1:" + base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt_subject_pii(subject_id: str, token: str) -> str:
    """Decrypt PII. Raises KeyError if the key has been shredded."""
    if not token or not token.startswith("enc:v1:"):
        return token
    if not SubjectKeyStore.has_dek(subject_id):
        raise KeyError(f"Subject DEK for '{subject_id}' has been shredded (GDPR/CCPA Art. 17)")
    dek = SubjectKeyStore.get_or_create_dek(subject_id)
    raw = base64.urlsafe_b64decode(token[len("enc:v1:"):].encode("ascii"))
    nonce, cipher_bytes = raw[:12], raw[12:]
    stream_key = hashlib.blake2b(dek, key=nonce, digest_size=max(1, len(cipher_bytes))).digest()
    return bytes(b ^ k for b, k in zip(cipher_bytes, stream_key)).decode("utf-8", errors="replace")


__all__ = [
    "redact_pii",
    "find_pii",
    "PII_TEXT_FIELDS",
    "redact_dict",
    "redact_turns",
    "SubjectKeyStore",
    "encrypt_subject_pii",
    "decrypt_subject_pii",
]
