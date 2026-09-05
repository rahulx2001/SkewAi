"""Secrets management: providers, rotation, and log redaction (item 50).

- :func:`get_secret` reads through the configured backend
  (``FRONTLINE_SECRETS_BACKEND=env`` default; ``file:<dir>`` for mounted
  secret files; ``kms:`` reserves the cloud-KMS hook — boto3 optional).
- :func:`redact_secrets` scrubs secret VALUES from log lines so debug
  output and Docker logs can never leak credentials.
- :func:`rotate_file_secret` rotates a file-backed secret with 0600
  permissions, keeping the previous value under ``.prev`` for a grace
  window so rolling restarts do not lock operators out.
- Locker keypairs are always created 0600 (see ``src.qubot.locker``) and
  validated at startup (see ``src.security.harden``).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SECRET_NAMES = (
    "FRONTLINE_API_KEY",
    "SESSION_SECRET",
    "GOOGLE_CLIENT_SECRET",
    "STRIPE_WEBHOOK_SECRET",
    "CONNECTOR_SHARED_SECRET",
    "CLAUDE_API_KEY",
    "OPENAI_API_KEY",
)


def get_secret(name: str, *, default: str = "") -> str:
    """Read a secret through the configured backend (env default)."""
    backend = (os.getenv("FRONTLINE_SECRETS_BACKEND") or "env").strip()
    if backend.startswith("file:"):
        directory = Path(backend[5:]).expanduser()
        candidate = directory / name
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    if backend.startswith("kms:"):
        # Cloud-KMS hook: boto3 optional; falls back to env with a warning so
        # pilots without KMS keep working (never crash on secrets config).
        try:
            from src.security.kms import fetch_kms_secret  # type: ignore

            value = fetch_kms_secret(backend[4:], name)
            if value:
                return value
        except Exception as e:
            logger.warning("kms secret backend unavailable for %s: %s", name, e)
    return (os.getenv(name) or default).strip()


def _secret_values() -> list[str]:
    values: list[str] = []
    for name in _SECRET_NAMES:
        try:
            raw = os.getenv(name) or ""
        except Exception:
            raw = ""
        if raw and len(raw.strip()) >= 8:
            values.append(raw.strip())
    # Longest first so overlapping values redact fully.
    return sorted(set(values), key=len, reverse=True)


def redact_secrets(text: Any) -> Any:
    """Replace known secret VALUES in text with [REDACTED] (item 50).

    Matches values, not names: ``FRONTLINE_API_KEY=...`` labels stay (useful
    for debugging which secret is set) while the credential itself is cut.
    Also scrubs ``-----BEGIN ... PRIVATE KEY-----`` blocks.
    """
    if not isinstance(text, str) or not text:
        return text
    out = text
    for value in _secret_values():
        out = out.replace(value, "[REDACTED]")
    out = re.sub(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        "[REDACTED-PRIVATE-KEY]",
        out,
    )
    return out


class SecretRedactionFilter(logging.Filter):
    """Logging filter that redacts secret values from every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact_secrets(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: (redact_secrets(v) if isinstance(v, str) else v)
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        redact_secrets(a) if isinstance(a, str) else a
                        for a in record.args
                    )
        except Exception:
            pass
        return True


def install_secret_redaction(target: logging.Logger | None = None) -> SecretRedactionFilter:
    """Attach redaction to a logger (root by default). Idempotent-ish."""
    filt = SecretRedactionFilter()
    log = target or logging.getLogger()
    if not any(isinstance(f, SecretRedactionFilter) for f in log.filters):
        log.addFilter(filt)
    return filt


def rotate_file_secret(
    directory: str | Path,
    name: str,
    new_value: str,
    *,
    keep_previous: bool = True,
) -> dict[str, Any]:
    """Rotate a file-backed secret with owner-only permissions (item 50).

    Writes the new value with 0600 (atomic replace), moving the current
    value to ``<name>.prev`` for grace-period validation when asked.
    """
    d = Path(directory).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    target = d / name
    value = (new_value or "").strip()
    if len(value.encode("utf-8")) < 32:
        raise ValueError("refusing to rotate in a weak (<32 byte) secret")
    previous: str | None = None
    if target.is_file():
        try:
            previous = target.read_text(encoding="utf-8").strip() or None
        except OSError:
            previous = None
        if keep_previous and previous and previous != value:
            prev_path = d / f"{name}.prev"
            tmp_prev = d / f".{name}.prev.tmp"
            tmp_prev.write_text(previous, encoding="utf-8")
            os.chmod(tmp_prev, 0o600)
            os.replace(tmp_prev, prev_path)
    tmp = d / f".{name}.tmp"
    # Owner-only from creation: no umask window with world-readable bytes.
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value + "\n")
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)
    return {"name": name, "path": str(target), "rotated": True,
            "previous_kept": bool(keep_previous and previous and previous != value)}


__all__ = [
    "get_secret",
    "redact_secrets",
    "SecretRedactionFilter",
    "install_secret_redaction",
    "rotate_file_secret",
]
