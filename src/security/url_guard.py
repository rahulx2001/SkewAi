"""Outbound URL guards — SSRF hardening for connector webhooks.

Blocks private, link-local, loopback, and cloud metadata targets.
HTTPS required unless FRONTLINE_OPEN_MODE=1 (local dev).

``resolve`` is injectable for hermetic tests (default: ``socket.getaddrinfo``).
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

# (host, port) → getaddrinfo-style list of tuples
Resolver = Callable[[str, int], list[Any]]

_default_resolver: Resolver | None = None


def set_url_resolver(resolver: Resolver | None) -> None:
    """Override DNS resolution (tests). Pass None to restore system getaddrinfo."""
    global _default_resolver
    _default_resolver = resolver


def _system_resolve(host: str, port: int) -> list[Any]:
    return socket.getaddrinfo(host, port)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (ip.version == 4 and ip == ipaddress.IPv4Address("169.254.169.254"))
        or (ip.version == 6 and ip in (
            ipaddress.IPv6Address("fd00:ec2::254"),  # AWS IMDS v2 style
        ))
    )


def validate_outbound_url(
    url: str,
    *,
    allow_http_local: bool | None = None,
    resolve: Resolver | None = None,
) -> str:
    """Return cleaned URL or raise ValueError with a stable reason.

    ``allow_http_local`` defaults to FRONTLINE_OPEN_MODE for localhost http.
    ``resolve`` defaults to the process override (tests) or ``socket.getaddrinfo``.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("url_empty")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url_scheme_not_allowed")
    if not parsed.hostname:
        raise ValueError("url_host_missing")

    host = parsed.hostname.lower()
    open_mode = _env_bool("FRONTLINE_OPEN_MODE", False)
    if allow_http_local is None:
        allow_http_local = open_mode

    if parsed.scheme == "http":
        if not allow_http_local or host not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("url_http_not_allowed")

    # Block obvious metadata / internal hostnames even before DNS
    blocked_hosts = {
        "metadata.google.internal",
        "metadata",
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
    }
    if host in blocked_hosts and not (
        allow_http_local and host in ("localhost", "127.0.0.1", "::1") and parsed.scheme == "http"
    ):
        if host in ("localhost", "127.0.0.1", "::1") and parsed.scheme == "https":
            raise ValueError("url_loopback_blocked")
        if host not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("url_metadata_host_blocked")

    # Literal IP host: no DNS needed
    try:
        lit = ipaddress.ip_address(host)
        if _is_blocked_ip(lit):
            if allow_http_local and lit.is_loopback and parsed.scheme == "http":
                return raw
            raise ValueError(f"url_private_or_blocked_ip:{lit}")
        return raw
    except ValueError as e:
        if str(e).startswith("url_"):
            raise
        # not a literal IP — continue to resolve

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    resolver = resolve or _default_resolver or _system_resolve
    try:
        infos = resolver(host, port)
    except socket.gaierror as e:
        raise ValueError(f"url_dns_failed:{e}") from e
    except OSError as e:
        raise ValueError(f"url_dns_failed:{e}") from e

    if not infos:
        raise ValueError("url_dns_empty")

    for info in infos:
        # getaddrinfo entries: (family, type, proto, canonname, sockaddr)
        if isinstance(info, (list, tuple)) and len(info) >= 5:
            sockaddr = info[4]
            ip_str = sockaddr[0] if isinstance(sockaddr, (list, tuple)) else sockaddr
        else:
            continue
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            if allow_http_local and ip.is_loopback and parsed.scheme == "http":
                continue
            raise ValueError(f"url_private_or_blocked_ip:{ip}")

    return raw


__all__ = ["validate_outbound_url", "set_url_resolver"]
