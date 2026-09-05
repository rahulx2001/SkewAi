"""Google OIDC authorization-code login — drives shipped oidc.py + routes."""

from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from src.api.main import app
from src.frontline.oidc import (
    begin_login,
    consume_handoff,
    finish_callback,
    provider_status,
    safe_post_login,
    set_http_hooks,
    verify_id_token,
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@pytest.fixture
def google_env(monkeypatch, reset_ops_db):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "http://127.0.0.1:8000/api/frontline/auth/oidc/callback")
    monkeypatch.setenv("FRONTLINE_OPEN_MODE", "1")
    yield
    set_http_hooks(None, None)


def _rsa_jwt(priv, *, kid, claims, extra_header=None):
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    if extra_header:
        header.update(extra_header)
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    sig = priv.sign(f"{h}.{p}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{h}.{p}.{_b64url(sig)}"


def test_safe_post_login_blocks_open_redirect():
    assert safe_post_login("https://evil.example/phish") == "/ui/#command"
    assert safe_post_login("http://127.0.0.1:8787/anything") == "http://127.0.0.1:8787/ui/#command"
    assert safe_post_login("http://127.0.0.1:8787/", page="signin") == "http://127.0.0.1:8787/ui/#signin"


def test_provider_status_unconfigured(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_SECRET", raising=False)
    st = provider_status()
    assert st["configured"] is False
    assert st["provider"] == "google"


def test_begin_login_points_at_google(google_env):
    begun = begin_login(next_url="http://127.0.0.1:8787/ui/")
    assert begun["authorize_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=google-client.apps.googleusercontent.com" in begun["authorize_url"]
    assert "state=" in begun["authorize_url"]
    assert "nonce=" in begun["authorize_url"]
    assert "code_challenge=" in begun["authorize_url"]
    assert "code_challenge_method=S256" in begun["authorize_url"]
    assert begun["next_url"] == "http://127.0.0.1:8787/ui/#command"


def test_verify_and_handoff_mint_session(google_env):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key().public_numbers()
    n = _b64url(pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big"))
    e = _b64url(pub.e.to_bytes((pub.e.bit_length() + 7) // 8, "big"))
    jwks = {"keys": [{"kty": "RSA", "kid": "k1", "n": n, "e": e, "alg": "RS256", "use": "sig"}]}
    begun = begin_login(next_url="http://127.0.0.1:8787/ui/")
    now = int(time.time())
    token = _rsa_jwt(
        priv,
        kid="k1",
        claims={
            "iss": "https://accounts.google.com",
            "aud": "google-client.apps.googleusercontent.com",
            "exp": now + 300,
            "iat": now,
            "nonce": begun["nonce"],
            "email": "rahul@gmail.com",
            "email_verified": True,
            "sub": "gid-1",
            "name": "Rahul",
        },
    )
    claims = verify_id_token(
        token,
        audience="google-client.apps.googleusercontent.com",
        issuer="https://accounts.google.com",
        nonce=begun["nonce"],
        jwks=jwks,
        now=now,
    )
    assert claims["email"] == "rahul@gmail.com"

    def fake_post(_url, _data):
        return {"id_token": token, "token_type": "Bearer"}

    def fake_get(_url):
        return jwks

    set_http_hooks(fake_post, fake_get)
    done = finish_callback(code="4/google-auth-code", state=begun["state"])
    assert done["subject"] == "rahul@gmail.com"
    sess = consume_handoff(done["handoff"])
    assert sess["token"]
    assert sess["subject"] == "rahul@gmail.com"
    assert sess["provider"] == "google"
    with pytest.raises(ValueError):
        consume_handoff(done["handoff"])


def test_oidc_http_start_and_complete(google_env):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key().public_numbers()
    n = _b64url(pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big"))
    e = _b64url(pub.e.to_bytes((pub.e.bit_length() + 7) // 8, "big"))
    jwks = {"keys": [{"kty": "RSA", "kid": "k1", "n": n, "e": e}]}

    with TestClient(app) as client:
        status = client.get("/api/frontline/auth/oidc/status")
        assert status.status_code == 200
        assert status.json()["configured"] is True
        assert status.json()["provider"] == "google"

        start = client.get(
            "/api/frontline/auth/oidc/start",
            params={"next": "http://127.0.0.1:8787/ui/"},
            follow_redirects=False,
        )
        assert start.status_code == 302
        loc = start.headers["location"]
        assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        # Pull state from the authorize URL
        from urllib.parse import parse_qs, urlparse

        state = parse_qs(urlparse(loc).query)["state"][0]
        nonce = parse_qs(urlparse(loc).query)["nonce"][0]
        now = int(time.time())
        id_token = _rsa_jwt(
            priv,
            kid="k1",
            claims={
                "iss": "https://accounts.google.com",
                "aud": "google-client.apps.googleusercontent.com",
                "exp": now + 300,
                "nonce": nonce,
                "email": "ops@gmail.com",
                "sub": "gid-2",
            },
        )
        set_http_hooks(lambda *_a, **_k: {"id_token": id_token}, lambda *_a, **_k: jwks)
        cb = client.get(
            "/api/frontline/auth/oidc/callback",
            params={"code": "4/ok", "state": state},
            follow_redirects=False,
        )
        assert cb.status_code == 302
        assert "handoff=" in cb.headers["location"]
        assert cb.cookies.get("frontline_session")
        hid = cb.headers["location"].split("handoff=")[1]
        done = client.post("/api/frontline/auth/oidc/complete", json={"handoff": hid})
        assert done.status_code == 200
        body = done.json()
        assert body["subject"] == "ops@gmail.com"
        assert "token" not in body
        assert done.cookies.get("frontline_session")
        me = client.get("/api/frontline/auth/me")
        assert me.json()["signed_in"] is True
        assert me.json()["subject"] == "ops@gmail.com"
