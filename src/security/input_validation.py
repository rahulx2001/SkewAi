"""Security validation for customer utterances + supervisor turns.

All customer utterances and supervisor turns pass through `validate_input()` before
any LLM prompt or slot extraction. This is the front-line defense against prompt
injection, control-character attacks, and oversized payloads.

The checks are deterministic and LLM-free. They run before any agent logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ── Limits ────────────────────────────────────────────────────────────────────

MAX_INPUT_LENGTH = 4000       # hard cap on any customer/supervisor utterance
MAX_INPUT_LINES = 50          # prevent flooding the transcript
MAX_INTERACTION_TURNS = 200   # hard cap on turns per interaction (safety net)


# ── Blocklist patterns ────────────────────────────────────────────────────────
# Patterns that suggest prompt injection or attempted SQL/code injection.
# We don't try to be exhaustive — just catch the obvious cases. Slot values are
# additionally validated against pack gazetteers, and all SQL is parameterized.

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    # Prompt-injection-ish phrases (case-insensitive)
    re.compile(r"ignore (all |previous |the above )?instructions", re.IGNORECASE),
    re.compile(r"disregard (all |previous |prior |above |the )*(instructions|directives|prompts)", re.IGNORECASE),
    re.compile(r"you are (now )?a (different|new|helpful) (ai|assistant|agent)", re.IGNORECASE),
    re.compile(r"forget (everything|all|your instructions)", re.IGNORECASE),
    re.compile(r"system prompt", re.IGNORECASE),
    re.compile(r"repeat (your|the) (system|initial|hidden) (prompt|instructions)", re.IGNORECASE),
    re.compile(r"do anything now|jailbreak|developer mode|ignore safety", re.IGNORECASE),
    # SQL injection attempts (parameterized queries make these safe, but reject anyway)
    re.compile(r";\s*(drop|alter|truncate|delete|update|insert)\s", re.IGNORECASE),
    re.compile(r"--\s*$", re.IGNORECASE),  # SQL comment at end
    re.compile(r"\bunion\s+select\b", re.IGNORECASE),
    # Shell injection (defensive; the server doesn't shell out, but reject)
    re.compile(r"\$\(", re.IGNORECASE),  # $(...)
    re.compile(r"`[^`]+`"),              # backticks (shell substitution)
]


@dataclass
class ValidationResult:
    """Result of validating one input."""

    ok: bool
    text: str            # cleaned text (control chars stripped)
    reason: str = ""     # empty if ok


def escape_untrusted(text: str) -> str:
    """HTML-escape untrusted text for non-React sinks (board: stored XSS).

    Split of duties (documented): ledger rows and turn transcripts keep
    VERBATIM evidence (audit hashes depend on it; React auto-escapes on
    render). Only server-composed strings that embed customer text into
    console/activity payloads consumed by custom renderers go through here.
    """
    import html as _html

    return _html.escape(str(text or ""), quote=True)


def validate_input(text: str) -> ValidationResult:
    """Validate a customer utterance or supervisor turn.

    Returns a ValidationResult with `ok=False` if the input is rejected.
    The cleaned text (control chars stripped, length capped) is returned even
    on rejection so the caller can log it.
    """
    if not isinstance(text, str):
        return ValidationResult(ok=False, text="", reason="input is not a string")

    # ── Strip control characters ──────────────────────────────────────────
    # Allow newlines (\n) and tabs (\t); strip other control chars.
    cleaned = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)

    # ── Length / line count ─────────────────────────────────────────────────
    if len(cleaned) > MAX_INPUT_LENGTH:
        return ValidationResult(
            ok=False,
            text=cleaned[:MAX_INPUT_LENGTH],
            reason=f"input exceeds max length {MAX_INPUT_LENGTH}",
        )
    if cleaned.count("\n") > MAX_INPUT_LINES:
        return ValidationResult(
            ok=False,
            text=cleaned,
            reason=f"input exceeds max lines {MAX_INPUT_LINES}",
        )

    # ── Injection patterns ──────────────────────────────────────────────────
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(cleaned):
            return ValidationResult(
                ok=False,
                text=cleaned,
                reason=f"input matched injection pattern: {pattern.pattern[:60]}",
            )

    return ValidationResult(ok=True, text=cleaned)


def validate_advisory_sql(sql: str) -> ValidationResult:
    """Lint an advisory_match SQL template at pack load time.

    Rejects any statement containing write keywords (INSERT/UPDATE/DELETE/DROP/
    ALTER/CREATE/TRUNCATE/MERGE/ATTACH). The schema validator already does this
    check; this function is the centralized place to call it.
    """
    if not isinstance(sql, str) or not sql.strip():
        return ValidationResult(ok=False, text="", reason="SQL template is empty")
    forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
                 "TRUNCATE", "MERGE", "ATTACH", "PRAGMA")
    upper_tokens = sql.upper().split()
    for kw in forbidden:
        if kw in upper_tokens:
            return ValidationResult(
                ok=False,
                text=sql,
                reason=f"advisory SQL contains forbidden keyword: {kw}",
            )
    return ValidationResult(ok=True, text=sql)


def sanitize_prompt_variable(val: Any, *, tag_name: str = "untrusted_input") -> str:
    """Isolate untrusted text inside rigid XML tags and neutralize prompt injection markers (audit 5.4).

    Strips delimiter tags to prevent tag-escaping attacks, strips meta-instruction
    tokens, and encapsulates text in <{tag_name}>...</{tag_name}>.
    """
    text = str(val or "").strip()
    # Strip opening/closing tag if user tries to close the block
    text = re.sub(rf"</?\s*{tag_name}\s*>", "", text, flags=re.IGNORECASE)
    # Neutralize instruction boundary tokens
    text = re.sub(r"\[/?INST\]|<system>|</system>|<<SYS>>|<</SYS>>", "", text, flags=re.IGNORECASE)
    return f"<{tag_name}>\n{text}\n</{tag_name}>"


__all__ = [
    "validate_input",
    "validate_advisory_sql",
    "sanitize_prompt_variable",
    "escape_untrusted",
    "ValidationResult",
    "MAX_INPUT_LENGTH",
    "MAX_INPUT_LINES",
    "MAX_INTERACTION_TURNS",
]
