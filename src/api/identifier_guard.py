"""ASGI gate: reject pack_id / interaction_id that cannot be a path or DB name."""

from __future__ import annotations

import re
from urllib.parse import parse_qs

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.security.identifiers import InvalidIdentifier, safe_pack_id, safe_token_id

_PACK_PATH = re.compile(r"/packs/([^/]+)")
_WS_INTERACTION = re.compile(r"^/ws/interaction/([^/]+)")
_HTTP_INTERACTION = re.compile(r"/interactions/([^/]+)")


class IdentifierGuardASGI:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        try:
            qs = (scope.get("query_string") or b"").decode("latin-1")
            params = parse_qs(qs, keep_blank_values=True)
            if "pack_id" in params and params["pack_id"]:
                raw = params["pack_id"][0]
                if raw:
                    safe_pack_id(raw)
            m = _PACK_PATH.search(path)
            if m and m.group(1) not in {"active", ""}:
                safe_pack_id(m.group(1))
            if scope["type"] == "websocket":
                wm = _WS_INTERACTION.match(path)
                if wm:
                    safe_token_id(wm.group(1), kind="interaction_id")
            else:
                im = _HTTP_INTERACTION.search(path)
                if im and im.group(1) not in {"", "start", "ingest"}:
                    safe_token_id(im.group(1), kind="interaction_id")
        except InvalidIdentifier as e:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            response = JSONResponse({"detail": str(e)}, status_code=400)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
