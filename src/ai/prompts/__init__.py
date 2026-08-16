"""Versioned prompt registry (feature #7)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parent

# Built-in prompt bodies (also written as files for auditability)
_BUILTIN = {
    "intake_phrasing": {
        "version": "1.0.0",
        "body": (
            "You rephrase a single customer-support intake question. "
            "Stay under 40 words. No inventing facts or IDs."
        ),
    },
    "investigator_brief": {
        "version": "1.0.0",
        "body": (
            "You write a two-sentence RCA brief for a supervisor console. "
            "Only use the numbers given. Cite evidence IDs if provided. No speculation."
        ),
    },
    "followup_draft": {
        "version": "1.0.0",
        "body": (
            "You draft a short operator follow-up note (≤60 words). "
            "Do not invent case numbers, remedies, or promises."
        ),
    },
}


def _ensure_files() -> None:
    for name, meta in _BUILTIN.items():
        path = PROMPTS_DIR / f"{name}.v{meta['version']}.txt"
        if not path.exists():
            path.write_text(meta["body"].strip() + "\n", encoding="utf-8")


def load_prompt(name: str) -> dict[str, Any]:
    _ensure_files()
    meta = _BUILTIN.get(name)
    if not meta:
        raise KeyError(f"unknown prompt: {name}")
    path = PROMPTS_DIR / f"{name}.v{meta['version']}.txt"
    body = path.read_text(encoding="utf-8").strip() if path.exists() else meta["body"]
    ph = hashlib.sha256(f"{name}:{meta['version']}:{body}".encode("utf-8")).hexdigest()[:16]
    return {
        "name": name,
        "version": meta["version"],
        "body": body,
        "prompt_hash": ph,
        "path": str(path),
    }


def policy_token(
    *,
    prompt_name: str,
    prompt_hash: str,
    model_id: str = "deterministic",
    used_llm: bool = False,
) -> str:
    return f"{'llm' if used_llm else 'deterministic'}:{prompt_name}:{prompt_hash}:{model_id}"


def stamp_prompt_use(
    interaction_id: str,
    *,
    prompt_name: str,
    model_id: str = "deterministic",
    used_llm: bool = False,
) -> dict[str, Any]:
    """INSERT-or-update prompt version on interaction_version_stamps.

    Mid-call stamps must create a row if create_interaction left none.
    Appends prompt tokens into model_policy (comma-separated) so finalize
    cannot erase earlier hashes by overwriting with bare 'deterministic'.
    """
    p = load_prompt(prompt_name)
    token = policy_token(
        prompt_name=prompt_name,
        prompt_hash=p["prompt_hash"],
        model_id=model_id,
        used_llm=used_llm,
    )
    try:
        from src.data.timeutil import utc_now
        from src.data.warehouse import ops_con

        now = utc_now()
        with ops_con() as con:
            row = con.execute(
                """
                SELECT model_policy, pack_id, pack_version
                FROM interaction_version_stamps
                WHERE interaction_id = ?
                """,
                [interaction_id],
            ).fetchone()
            if row:
                prev = (row[0] or "").strip()
                # Append unique token; keep prior prompt hashes
                parts = [x for x in prev.split(",") if x]
                if token not in parts:
                    parts.append(token)
                # Drop bare 'deterministic' placeholder once real tokens exist
                if len(parts) > 1:
                    parts = [x for x in parts if x != "deterministic"]
                new_policy = ",".join(parts)[:500]
                con.execute(
                    """
                    UPDATE interaction_version_stamps
                    SET model_policy = ?, stamped_at = ?
                    WHERE interaction_id = ?
                    """,
                    [new_policy, now, interaction_id],
                )
            else:
                # Pull pack from interaction header when available
                pack_id, pack_version = None, None
                try:
                    h = con.execute(
                        """
                        SELECT pack_id, pack_version FROM interactions
                        WHERE interaction_id = ?
                        """,
                        [interaction_id],
                    ).fetchone()
                    if h:
                        pack_id, pack_version = h[0], h[1]
                except Exception:
                    pass
                con.execute(
                    """
                    INSERT INTO interaction_version_stamps
                    (interaction_id, stamped_at, pack_id, pack_version, deployment_id,
                     experiment_id, artifact_versions_json, model_policy)
                    VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)
                    """,
                    [
                        interaction_id,
                        now,
                        pack_id,
                        pack_version,
                        json.dumps({}),
                        token,
                    ],
                )
    except Exception:
        pass
    return {**p, "policy_token": token}


__all__ = ["load_prompt", "stamp_prompt_use", "policy_token", "PROMPTS_DIR"]
