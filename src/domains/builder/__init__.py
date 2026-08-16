"""Pack Builder MVP — CSV → draft domain pack.

Public surface: ``profile_csv`` inspects a source CSV; ``build_draft_pack``
scaffolds a ready-to-lint pack. The generated mapping still requires human
review before lint/ship — no auto-accept.
"""

from src.domains.builder.pack_builder import build_draft_pack, profile_csv

__all__ = [
    "build_draft_pack",
    "profile_csv",
]
