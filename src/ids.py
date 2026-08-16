"""ULID helper — shields the rest of the codebase from the python-ulid API.

The `python-ulid` package exposes a `ULID` class; we want a simple string-returning
factory that matches v1's `ulid.new()` semantics. Centralize here so a future
swap (to `ulid-py` or stdlib uuid7) is a one-file change.
"""

from __future__ import annotations

import ulid as _ulid


def new_ulid() -> str:
    """Generate a new ULID as a lowercase string."""
    return str(_ulid.ULID()).lower()
