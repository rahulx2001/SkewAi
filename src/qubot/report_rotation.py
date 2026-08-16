"""Bound the on-disk Qubot report tree (contacts + digests).

Deletes oldest files when the tree exceeds ``max_files``, and files older than
``max_age_days``. Safe to call after each audit write or on a timer.
"""

from __future__ import annotations

import time
from pathlib import Path

from src.qubot.auditor import DIGESTS_DIR, REPORTS_DIR

# Defaults: keep a few hundred recent contact reports; drop older than 14 days.
DEFAULT_MAX_FILES = 500
DEFAULT_MAX_AGE_DAYS = 14


def rotate_reports(
    *,
    reports_dir: Path | None = None,
    digests_dir: Path | None = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> dict[str, int]:
    """Rotate contact + digest markdown trees. Returns deletion counts."""
    deleted = 0
    deleted += _rotate_dir(reports_dir or REPORTS_DIR, max_files, max_age_days)
    deleted += _rotate_dir(digests_dir or DIGESTS_DIR, max(50, max_files // 10), max_age_days)
    return {"deleted": deleted}


def _rotate_dir(directory: Path, max_files: int, max_age_days: int) -> int:
    if not directory.exists():
        return 0
    files = [p for p in directory.iterdir() if p.is_file()]
    if not files:
        return 0
    now = time.time()
    max_age_s = max_age_days * 86400
    deleted = 0
    # Age-based first
    for p in files:
        try:
            if now - p.stat().st_mtime > max_age_s:
                p.unlink(missing_ok=True)
                deleted += 1
        except OSError:
            pass
    # Recount after age purge
    files = [p for p in directory.iterdir() if p.is_file()]
    if len(files) <= max_files:
        return deleted
    files.sort(key=lambda p: p.stat().st_mtime)
    excess = len(files) - max_files
    for p in files[:excess]:
        try:
            p.unlink(missing_ok=True)
            deleted += 1
        except OSError:
            pass
    return deleted


__all__ = ["rotate_reports", "DEFAULT_MAX_FILES", "DEFAULT_MAX_AGE_DAYS"]
