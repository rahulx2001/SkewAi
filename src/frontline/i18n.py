"""Multilingual intake (feature #13).

Pack-configured language, dual storage of original + English-normalized text.
Hermetic: offline dictionary + identity fallback (no cloud MT required).
"""

from __future__ import annotations

import re
from typing import Any

# Minimal bilingual glossary for pilot demos (es/hi particles + safety terms).
_GLOSSARY = {
    "es": {
        "frenos": "brakes",
        "airbag": "airbag",
        "motor": "engine",
        "dirección": "steering",
        "queja": "complaint",
        "peligro": "danger",
        "incendio": "fire",
    },
    "hi": {
        "ब्रेक": "brake",
        "शिकायत": "complaint",
        "खतरा": "danger",
        "इंजन": "engine",
    },
}

_PROMPT_TEMPLATES = {
    "en": {
        "greeting": "Hello — I'm here to document your issue.",
        "ask_entity": "Which product or vehicle is this about?",
        "thanks": "Thank you — I've logged that.",
    },
    "es": {
        "greeting": "Hola — estoy aquí para documentar su problema.",
        "ask_entity": "¿Sobre qué producto o vehículo se trata?",
        "thanks": "Gracias — lo he registrado.",
    },
    "hi": {
        "greeting": "नमस्ते — मैं आपकी समस्या दर्ज करूंगा।",
        "ask_entity": "यह किस उत्पाद या वाहन के बारे में है?",
        "thanks": "धन्यवाद — दर्ज कर लिया गया।",
    },
}


def detect_language(text: str) -> str:
    t = text or ""
    if re.search(r"[\u0900-\u097F]", t):
        return "hi"
    if re.search(r"[áéíóúñ¿¡]", t, re.I) or any(
        w in t.lower() for w in ("frenos", "queja", "hola", "gracias")
    ):
        return "es"
    return "en"


def normalize_to_english(text: str, *, lang: str | None = None) -> dict[str, Any]:
    """Return original + English-normalized text for corpus queryability."""
    original = text or ""
    lang = lang or detect_language(original)
    if lang == "en":
        return {
            "original": original,
            "normalized_en": original,
            "lang": "en",
            "method": "identity",
        }
    gloss = _GLOSSARY.get(lang, {})
    out = original
    for src, en in gloss.items():
        out = re.sub(re.escape(src), en, out, flags=re.I)
    # Hinglish/Spanglish: keep latin tokens
    return {
        "original": original,
        "normalized_en": out,
        "lang": lang,
        "method": "glossary" if gloss else "identity",
    }


def slot_prompt(key: str, *, lang: str = "en") -> str:
    bundle = _PROMPT_TEMPLATES.get(lang) or _PROMPT_TEMPLATES["en"]
    return bundle.get(key) or _PROMPT_TEMPLATES["en"].get(key, key)


def pack_language(pack: Any) -> str:
    """Read optional language from pack.yaml-like object or dict."""
    if pack is None:
        return "en"
    if isinstance(pack, dict):
        return str(pack.get("language") or pack.get("default_locale") or "en")[:8]
    return str(getattr(pack, "language", None) or getattr(pack, "default_locale", None) or "en")[:8]
