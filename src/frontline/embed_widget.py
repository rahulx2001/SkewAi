"""Contract for the embeddable <script> widget (no Node require/module)."""

from __future__ import annotations

from pathlib import Path

from src.config import REPO_ROOT

WIDGET_PATH = REPO_ROOT / "dashboard" / "public" / "skew-widget.js"


def widget_contract(path: Path | None = None) -> dict:
    p = path or WIDGET_PATH
    text = p.read_text(encoding="utf-8")
    return {
        "path": str(p),
        "has_global": "SkewVoiceWidget" in text,
        "has_install": "install" in text,
        "no_require": "require(" not in text,
        "no_module_exports": "module.exports" not in text,
        "no_import": "import " not in text.split("*/", 1)[-1],
        "bytes": len(text),
    }


__all__ = ["WIDGET_PATH", "widget_contract"]
