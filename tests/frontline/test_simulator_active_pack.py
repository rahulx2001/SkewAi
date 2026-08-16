"""H3: Simulator default pack follows resolve_active_pack_id (Settings switch)."""

from __future__ import annotations

import pytest

from src.data.warehouse import ops_con
from src.domains.active_pack import clear_active_pack_override, set_active_pack_id
from src.frontline.simulator import simulate


@pytest.fixture
def both_packs(reset_ops_db, seed_automotive_pack):
    from scripts.seed_domains import build as build_domain

    build_domain("finance_cfpb")
    clear_active_pack_override()
    yield
    clear_active_pack_override()


@pytest.mark.asyncio
async def test_simulate_uses_active_pack_override(both_packs):
    set_active_pack_id("finance_cfpb")
    # No pack_id override — must use active_pack.json
    result = await simulate(count=2, pack_id=None, seed=7)
    assert not result.errors or result.completed + result.abandoned + result.escalated > 0

    with ops_con(read_only=True) as con:
        rows = con.execute(
            """
            SELECT pack_id FROM interactions
            WHERE channel = 'simulated'
            ORDER BY started_at DESC
            LIMIT 5
            """
        ).fetchall()
    assert rows, "expected simulated interactions"
    pack_ids = {r[0] for r in rows}
    assert pack_ids == {"finance_cfpb"}, f"simulator ignored active pack: {pack_ids}"
