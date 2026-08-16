"""RFC 7807 Problem Details for HTTP APIs (pilot-compatible).

Returns JSON that is both:
  - FastAPI-compatible (``detail`` string for existing clients)
  - Problem Details (``type``, ``title``, ``status``, ``detail``)

Content-Type remains ``application/json`` so browsers and the dashboard keep
working; OpenAPI documents the shape as Problem.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class Problem(BaseModel):
    """RFC 7807 Problem Details body returned by every error response."""

    type: str
    title: str
    status: int
    detail: str
    instance: str | None = None
    errors: list[dict[str, Any]] | None = None

# Stable type URIs (relative to this product — not network-fetched).
ERROR_TYPES = {
    400: "about:blank#bad-request",
    401: "about:blank#unauthorized",
    403: "about:blank#forbidden",
    404: "about:blank#not-found",
    409: "about:blank#conflict",
    422: "about:blank#validation-error",
    429: "about:blank#rate-limited",
    500: "about:blank#internal-error",
    503: "about:blank#service-unavailable",
}

TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Validation Error",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def problem(
    status_code: int,
    detail: str,
    *,
    type_uri: str | None = None,
    title: str | None = None,
    instance: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a problem+compat body."""
    body: dict[str, Any] = {
        "type": type_uri or ERROR_TYPES.get(status_code, "about:blank"),
        "title": title or TITLES.get(status_code, "Error"),
        "status": status_code,
        # Human message; also FastAPI's traditional error field for clients.
        "detail": detail,
    }
    if instance:
        body["instance"] = instance
    if errors:
        body["errors"] = errors
    if extra:
        body.update(extra)
    return body


def problem_response(
    status_code: int,
    detail: str,
    *,
    request: Request | None = None,
    headers: dict[str, str] | None = None,
    errors: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    instance = None
    if request is not None:
        instance = str(request.url.path)
    body = problem(
        status_code,
        detail,
        instance=instance,
        errors=errors,
        extra=extra,
    )
    # Prefer problem+json when client asks for it; otherwise JSON with same body.
    media = "application/json"
    if request is not None:
        accept = (request.headers.get("accept") or "").lower()
        if "application/problem+json" in accept:
            media = "application/problem+json"
    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type=media,
        headers=headers,
    )


def _detail_to_str(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        # Validation-style list
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(x) for x in item.get("loc", []) if x != "body")
                msg = item.get("msg") or item.get("message") or str(item)
                parts.append(f"{loc}: {msg}" if loc else msg)
            else:
                parts.append(str(item))
        return "; ".join(parts) if parts else "Invalid request"
    return str(detail)


def register_exception_handlers(app: FastAPI) -> None:
    """Install global handlers for HTTP + validation errors."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        detail = _detail_to_str(exc.detail)
        headers = dict(exc.headers) if exc.headers else None
        return problem_response(
            exc.status_code,
            detail,
            request=request,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = []
        for err in exc.errors():
            loc = [str(x) for x in err.get("loc", ()) if x not in ("body", "query", "path")]
            errors.append(
                {
                    "field": ".".join(loc) if loc else str(err.get("loc")),
                    "message": err.get("msg", "invalid"),
                    "type": err.get("type"),
                }
            )
        return problem_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            _detail_to_str(exc.errors()),
            request=request,
            errors=errors,
        )


def install_openapi_problem(app: FastAPI) -> None:
    """Inject the shared RFC 7807 ``Problem`` component into ``app.openapi()``.

    The global handlers in :func:`register_exception_handlers` return this body
    for every HTTP/validation error, but FastAPI's default OpenAPI generation
    never documents it. Wrap ``app.openapi`` so the component is present and
    error responses can reference ``#/components/schemas/Problem``.
    """
    from fastapi.openapi.utils import get_openapi

    original = app.openapi

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )
        problem_schema = Problem.model_json_schema(ref_template="#/components/schemas/{model}")
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components["Problem"] = problem_schema
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


__all__ = [
    "problem",
    "problem_response",
    "register_exception_handlers",
    "install_openapi_problem",
    "Problem",
    "ERROR_TYPES",
    "TITLES",
]
