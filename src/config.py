"""Central configuration for Skew AI.

Every module reads runtime knobs from `settings` here. The settings object is
populated from environment variables (with safe defaults so `make contact`
works out of the box).

Design notes
------------
- Settings are immutable after first load (frozen dataclass).
- All paths are resolved relative to the repo root (the parent of `src/`).
- Agents default to **deterministic** templates. Optional LLM narration lives in
  ``src/ai/`` and only runs when ``FRONTLINE_LLM_ENABLED=1`` **and** a provider
  key is set, subject to ``FRONTLINE_LLM_TURN_CAP`` / daily cost. On any miss,
  agents fall back to the same deterministic text as before.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# Repo root = parent of this file's `src/` directory.
REPO_ROOT = Path(__file__).resolve().parent.parent

# Canonical pilot paths (never wiped by tests unless explicitly allowed).
DEFAULT_OPS_DB = (REPO_ROOT / "data" / "frontline.duckdb").resolve()
DEFAULT_DOMAIN_DB_DIR = (REPO_ROOT / "data" / "domains").resolve()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def resolve_frontline_db_path() -> Path:
    """Ops warehouse path. Reads FRONTLINE_DB_PATH live (not frozen at import)."""
    raw = (os.getenv("FRONTLINE_DB_PATH") or "data/frontline.duckdb").strip()
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (REPO_ROOT / p).resolve()


def resolve_domain_db_dir() -> Path:
    """Domain warehouses directory. Reads DOMAIN_DB_PATH live."""
    raw = (os.getenv("DOMAIN_DB_PATH") or "data/domains").strip()
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (REPO_ROOT / p).resolve()


def is_default_pilot_ops_path(path: Path | None = None) -> bool:
    p = (path or resolve_frontline_db_path()).resolve()
    return p == DEFAULT_OPS_DB


def is_default_pilot_domain_path(path: Path | None = None) -> bool:
    """True when *path* lives under the default pilot ``data/domains/`` tree.

    Isolated test/CI paths (``DOMAIN_DB_PATH`` pointing outside the repo pilot
    dir) return False so fixtures can rebuild freely without an allow flag.
    """
    p = (path or resolve_domain_db_dir()).resolve()
    default = DEFAULT_DOMAIN_DB_DIR
    if p == default:
        return True
    try:
        p.relative_to(default)
        return True
    except ValueError:
        return False


def allow_default_db_reset() -> bool:
    """True only when operator explicitly allows wiping pilot data/."""
    return _env_bool("FRONTLINE_ALLOW_DEFAULT_DB_RESET", False)


def allow_domain_db_reset() -> bool:
    """True when operator allows wiping pilot domain warehouses under data/domains/.

    Accepts the same intentional rebuild flag as ops (``FRONTLINE_ALLOW_DEFAULT_DB_RESET``)
    or the domain-specific ``FRONTLINE_ALLOW_DOMAIN_DB_RESET``.
    """
    return allow_default_db_reset() or _env_bool("FRONTLINE_ALLOW_DOMAIN_DB_RESET", False)


@dataclass(frozen=True)
class Settings:
    # ── Active pack ────────────────────────────────────────────────────────
    domain_pack: str = field(default_factory=lambda: os.getenv("DOMAIN_PACK", "automotive_nhtsa"))
    frontline_enabled: bool = field(default_factory=lambda: _env_bool("FRONTLINE_ENABLED", True))

    # ── Orchestrator knobs ─────────────────────────────────────────────────
    max_turns: int = field(default_factory=lambda: _env_int("FRONTLINE_MAX_TURNS", 12))
    enrich_timeout_s: int = field(default_factory=lambda: _env_int("FRONTLINE_ENRICH_TIMEOUT_S", 10))
    llm_turn_cap: int = field(default_factory=lambda: _env_int("FRONTLINE_LLM_TURN_CAP", 6))

    # ── Sentiment / handoff ────────────────────────────────────────────────
    frustration_threshold: float = field(
        default_factory=lambda: _env_float("FRONTLINE_FRUSTRATION_THRESHOLD", 0.65)
    )

    # ── Investigations ─────────────────────────────────────────────────────
    investigation_min_cases: int = field(
        default_factory=lambda: _env_int("FRONTLINE_INVESTIGATION_MIN_CASES", 3)
    )

    # ── Early warning ──────────────────────────────────────────────────────
    early_warning_alert_threshold: float = field(
        default_factory=lambda: _env_float("EARLY_WARNING_ALERT_THRESHOLD", 0.7)
    )

    # ── Alerts ─────────────────────────────────────────────────────────────
    alert_webhook_url: str = field(default_factory=lambda: os.getenv("ALERT_WEBHOOK_URL", ""))

    # ── Outbound connector (generic HTTP / dry-run outbox; not CRM SDKs) ───
    connector_enabled: bool = field(
        default_factory=lambda: _env_bool("CONNECTOR_ENABLED", False)
    )
    connector_webhook_url: str = field(
        default_factory=lambda: os.getenv("CONNECTOR_WEBHOOK_URL", "").strip()
    )
    connector_shared_secret: str = field(
        default_factory=lambda: os.getenv("CONNECTOR_SHARED_SECRET", "").strip()
    )

    # ── LLM providers (reserved — not shipped) ────────────────────────────
    # Keys may be present in env for future wiring; agents ignore them today.
    claude_api_key: str = field(default_factory=lambda: os.getenv("CLAUDE_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    max_daily_claude_cost: float = field(
        default_factory=lambda: _env_float("MAX_DAILY_CLAUDE_COST", 5.0)
    )

    # ── API server ─────────────────────────────────────────────────────────
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "127.0.0.1"))
    api_port: int = field(default_factory=lambda: _env_int("API_PORT", 8000))
    # Single-tenant pilot secret. Empty = open (local/dev/tests).
    frontline_api_key: str = field(
        default_factory=lambda: os.getenv("FRONTLINE_API_KEY", "").strip()
    )

    # ── Convenience ────────────────────────────────────────────────────────
    @property
    def llm_available(self) -> bool:
        """True only when FRONTLINE_LLM_ENABLED=1 and a provider key is present.

        Env keys alone do not enable LLM turns — that would be dishonest.
        """
        try:
            from src.ai.provider import llm_enabled

            return llm_enabled()
        except Exception:
            return False

    @property
    def packs_root(self) -> Path:
        return REPO_ROOT / "domains"

    def pack_dir(self, pack_id: str) -> Path:
        return self.packs_root / pack_id

    # ── Databases (live env — so pytest can isolate without re-import) ────
    @property
    def frontline_db_path(self) -> Path:
        """Ops warehouse path. Honors FRONTLINE_DB_PATH (absolute or repo-relative)."""
        return resolve_frontline_db_path()

    @property
    def domain_db_dir(self) -> Path:
        """Per-pack domain warehouse directory. Honors DOMAIN_DB_PATH."""
        return resolve_domain_db_dir()

    def domain_db_path(self, pack_id: str) -> Path:
        return self.domain_db_dir / f"{pack_id}.duckdb"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Module-level singleton — import as `from src.config import settings`.
settings = get_settings()
