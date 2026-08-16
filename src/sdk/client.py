"""Thin Python SDK over shipped Skew functions (no extra HTTP required)."""

from __future__ import annotations

from typing import Any

from src.enterprise.grounded_nl import grounded_query
from src.frontline.billing import usage_dashboard
from src.frontline.provenance import figure_lineage, list_kpis
from src.frontline.sandbox import boot_sandbox
from src.frontline.validation_queue import list_queue_all
from src.security.scoped_keys import authenticate_scoped, create_scoped_key


class SkewClient:
    def __init__(self, token: str | None = None, tenant_id: str = "default"):
        self.token = token
        self.tenant_id = tenant_id

    def require(self, scope: str) -> dict[str, Any]:
        if not self.token:
            return {"ok": True, "reason": "open_mode"}
        return authenticate_scoped(self.token, scope)

    def kpis(self) -> list[dict[str, Any]]:
        gate = self.require("kpi:read")
        if not gate.get("ok"):
            raise PermissionError(gate)
        return list_kpis()

    def figure(self, kpi_id: str) -> dict[str, Any]:
        gate = self.require("kpi:read")
        if not gate.get("ok"):
            raise PermissionError(gate)
        return figure_lineage(kpi_id)

    def usage(self) -> dict[str, Any]:
        return usage_dashboard(self.tenant_id)

    def sandbox(self) -> dict[str, Any]:
        return boot_sandbox()

    def queue(self) -> list[dict[str, Any]]:
        return list_queue_all()

    def ask(self, question: str, pack_id: str = "automotive_nhtsa") -> dict[str, Any]:
        return grounded_query(question, pack_id=pack_id)

    def mint_key(self, scopes: list[str]) -> dict[str, Any]:
        return create_scoped_key(scopes, tenant_id=self.tenant_id)


def sdk_call(method: str, **kwargs: Any) -> dict[str, Any]:
    client = SkewClient(token=kwargs.pop("token", None), tenant_id=kwargs.pop("tenant_id", "default"))
    fn = getattr(client, method)
    result = fn(**kwargs) if kwargs else fn()
    if isinstance(result, list):
        return {"ok": True, "result": result}
    return {"ok": True, **(result if isinstance(result, dict) else {"result": result})}


__all__ = ["SkewClient", "sdk_call"]
