"""Node-driven tests for the shipped reconnect helpers in voiceHelpers.js."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HELPERS = REPO / "dashboard" / "src" / "voiceHelpers.js"
CALL = REPO / "dashboard" / "routes" / "CallWidget.jsx"

JS = r"""
import {
  isFatalWsError,
  fatalWsErrorMessage,
  transcriptFromResume,
} from './dashboard/src/voiceHelpers.js';

const out = {};

// Explicit server flag wins over detail sniffing.
out.explicitFatal = isFatalWsError({ recoverable: false, detail: 'whatever' });
out.explicitOk = isFatalWsError({ recoverable: true, detail: 'active interaction not found: x' });

// Legacy servers only send `detail`.
out.legacyNotFound = isFatalWsError({ detail: 'active interaction not found: int_1' });
out.legacyBusy = isFatalWsError({
  detail: 'interaction already has an active customer WebSocket: int_1',
});
out.legacyServerError = isFatalWsError({ detail: 'server error: RuntimeError' });
out.transientUnknown = isFatalWsError({ detail: 'interaction not active: int_1' });
out.notAnObject = isFatalWsError(null);

// Copy never leaks the raw interaction id.
out.msgBusy = fatalWsErrorMessage({ code: 'interaction_busy' });
out.msgGone = fatalWsErrorMessage({
  code: 'interaction_not_resumable',
  detail: 'active interaction not found: int_01m0528apsk5rbc2k4t0s121q0',
});
out.msgServer = fatalWsErrorMessage({ code: 'server_error' });

// Resume transcript rebuild.
out.resumeRows = transcriptFromResume([
  { id: 'a_t1', speaker: 'agent', text: 'Thanks for calling support.' },
  { turn_id: 'a_t2', speaker: 'customer', text: 'My brakes grind' },
  { speaker: 'agent', text: '   ' },
  null,
]);
out.resumeEmpty = transcriptFromResume([]);
out.resumeBad = transcriptFromResume('nope');

console.log(JSON.stringify(out));
"""


def _run_node() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    tmp = REPO / ".voice_reconnect_probe.mjs"
    tmp.write_text(JS, encoding="utf-8")
    try:
        proc = subprocess.run(
            [node, str(tmp)], cwd=str(REPO), capture_output=True, text=True, timeout=60
        )
    finally:
        tmp.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_fatal_ws_error_classification():
    out = _run_node()
    assert out["explicitFatal"] is True
    assert out["explicitOk"] is False
    assert out["legacyNotFound"] is True
    assert out["legacyBusy"] is True
    assert out["legacyServerError"] is True
    # An error the client can survive must not kill the call.
    assert out["transientUnknown"] is False
    assert out["notAnObject"] is False


def test_fatal_error_copy_hides_interaction_id():
    out = _run_node()
    assert "another tab" in out["msgBusy"]
    assert "int_01m0528" not in out["msgGone"]
    assert out["msgGone"]
    assert "server error" in out["msgServer"].lower()


def test_transcript_from_resume():
    out = _run_node()
    rows = out["resumeRows"]
    assert [r["speaker"] for r in rows] == ["agent", "customer"]
    assert rows[0]["id"] == "a_t1"
    assert rows[1]["id"] == "a_t2"
    assert all(r["interim"] is False for r in rows)
    # Nothing to restore → null so the widget keeps whatever it already has.
    assert out["resumeEmpty"] is None
    assert out["resumeBad"] is None


def test_callwidget_handles_resume_and_fatal_error():
    text = CALL.read_text(encoding="utf-8")
    assert 'case "resumed"' in text
    assert "transcriptFromResume" in text
    assert "isFatalWsError(msg)" in text
    assert "fatalWsErrorMessage(msg)" in text


def test_callwidget_reconnect_budget_fits_server_grace():
    """Client must give up well before the server's 120s reconnect grace."""
    text = CALL.read_text(encoding="utf-8")
    assert "RECONNECT_MAX_ATTEMPTS" in text
    assert "reconnectAttemptRef.current >= RECONNECT_MAX_ATTEMPTS" in text
    helpers = HELPERS.read_text(encoding="utf-8")
    assert "isFatalWsError" in helpers
