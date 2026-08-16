"""Process-stable bag-of-hash embeddings (Phase 0).

Calls the shipped ``embed_text`` / ``cosine`` — does not reimplement hashing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from src.ml_runtime.embeddings import cosine, embed_text

PHRASE = "front brake grinding on honda cr-v at low speed"
REPO = Path(__file__).resolve().parents[2]


def test_parent_and_child_process_vectors_match():
    parent = embed_text(PHRASE)
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "random"
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; from src.ml_runtime.embeddings import embed_text; "
                f"print(json.dumps(embed_text({PHRASE!r})))"
            ),
        ],
        cwd=str(REPO),
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    child_vec = json.loads(child.stdout.strip())
    assert len(parent) == len(child_vec)
    assert parent == child_vec


def test_persist_then_query_cosine_is_one():
    ingested = list(embed_text(PHRASE))
    queried = embed_text(PHRASE)
    assert ingested == queried
    score = cosine(ingested, queried)
    assert score > 0.999
    assert abs(score - 1.0) < 1e-9
