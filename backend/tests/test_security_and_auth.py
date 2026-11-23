"""Tests for security primitives, cookie authentication, rate limiting, and password rotation."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security import (
    CipherError,
    LoginRateLimiter,
    SecretCipher,
    SessionError,
    SessionManager,
    hash_password,
    verify_password,
)


def test_argon2_hashing_and_verification() -> None:
    hashed = hash_password("MySecretPass#2026")
    assert verify_password(hashed, "MySecretPass#2026") is True
    assert verify_password(hashed, "wrong") is False
    assert verify_password("corrupt-hash", "MySecretPass#2026") is False


def test_secret_cipher_roundtrip_and_masking() -> None:
    cipher = SecretCipher("test-master-key")
    encrypted = cipher.encrypt("sk-live-abcdef123456")
    assert encrypted != "sk-live-abcdef123456"
    assert cipher.decrypt(encrypted) == "sk-live-abcdef123456"
    assert SecretCipher.mask_secret("sk-live-abcdef123456") == "sk-***456"
    assert SecretCipher.mask_secret("1234") == "****"

    other_cipher = SecretCipher("different-master-key")
    with pytest.raises(CipherError):
        other_cipher.decrypt(encrypted)


def test_session_manager_roundtrip_and_tampering() -> None:
    mgr = SessionManager("signing-secret", max_age_sec=60)
    token = mgr.create_token(1, "admin")
    claims = mgr.verify_token(token)
    assert claims["uid"] == 1
    assert claims["sub"] == "admin"

    with pytest.raises(SessionError):
        mgr.verify_token(token + "tamper")


def test_unauthenticated_endpoints_require_login(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/hotlist").status_code == 401
    assert client.get("/api/settings/platforms").status_code == 401


def test_login_cookie_scope_logout_and_change_password(client: TestClient) -> None:
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401

    ok = client.post("/api/auth/login", json={"username": "admin", "password": "StrongPass123!"})
    assert ok.status_code == 200
    assert ok.json()["user"]["username"] == "admin"
    set_cookie = ok.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "Path=/" in set_cookie

    assert client.get("/api/auth/me").status_code == 200

    # Password rotation and re-login check
    chg = client.post(
        "/api/auth/change-password",
        json={"current_password": "StrongPass123!", "new_password": "NewStrongPass999!"},
    )
    assert chg.status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401

    relogin = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "NewStrongPass999!"},
    )
    assert relogin.status_code == 200


def test_subpath_cookie_scope_and_https_secure_flag(tmp_path) -> None:
    settings = Settings(
        app_base_path="/radar",
        db_path=tmp_path / "subpath.db",
        secret_key="subpath-secret",
        admin_pass="SubpathPass123!",
        enable_scheduler=False,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        resp = c.post(
            "/api/auth/login",
            json={"username": "admin", "password": "SubpathPass123!"},
            headers={"X-Forwarded-Proto": "https"},
        )
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert "Path=/radar/" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        token = resp.cookies.get("trendradar_session")
        assert token
        c.cookies.set("trendradar_session", token)
        me = c.get("/api/auth/me")
        assert me.status_code == 200


def test_login_rate_limiter_blocks_after_threshold(tmp_path) -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_sec=60)
    assert limiter.is_allowed("1.2.3.4") is True
    for _ in range(3):
        limiter.record_failure("1.2.3.4")
    assert limiter.is_allowed("1.2.3.4") is False
    limiter.reset("1.2.3.4")
    assert limiter.is_allowed("1.2.3.4") is True

    settings = Settings(
        db_path=tmp_path / "rate.db",
        admin_pass="Correct123!",
        enable_scheduler=False,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        for _ in range(10):
            r = c.post("/api/auth/login", json={"username": "admin", "password": "bad"})
            assert r.status_code == 401
        blocked = c.post("/api/auth/login", json={"username": "admin", "password": "Correct123!"})
        assert blocked.status_code == 429
