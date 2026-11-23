"""Tests for SQLite migration, invite-code registration, and admin RBAC management."""

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import zoneinfo

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.repositories.db import Database
from app.security import hash_password


def test_legacy_users_table_migration_promotes_existing_accounts_to_admin(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_upgrade.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            last_login_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    now_iso = "2026-11-22T12:00:00+08:00"
    conn.execute(
        """
        INSERT INTO users (username, password_hash, is_active, created_at, updated_at)
        VALUES (?, ?, 1, ?, ?)
        """,
        ("legacy_op", hash_password("LegacyPass#2026"), now_iso, now_iso),
    )
    conn.commit()
    conn.close()

    Database(db_path).init_schema()
    settings = Settings(
        app_base_path="/",
        db_path=db_path,
        secret_key="migration-secret-key",
        enable_scheduler=False,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        login = c.post("/api/auth/login", json={"username": "legacy_op", "password": "LegacyPass#2026"})
        assert login.status_code == 200
        assert login.json()["user"]["role"] == "admin"
        assert c.get("/api/admin/users").status_code == 200


def test_invite_lifecycle_registration_and_atomic_quota_protection(auth_client: TestClient) -> None:
    # 1. Create finite 1-use invite expiring in 24h
    create_resp = auth_client.post(
        "/api/admin/invite-codes",
        json={"note": "试用名额", "max_uses": 1, "expires_in_hours": 24},
    )
    assert create_resp.status_code == 200
    inv = create_resp.json()
    assert inv["code"].startswith("TR-")
    assert inv["max_uses"] == 1
    assert inv["used_count"] == 0
    assert inv["remaining_uses"] == 1
    assert inv["status"] == "active"

    # Reject invalid update shrinking max_uses below used_count later, and verify update works now
    patch_resp = auth_client.patch(
        f"/api/admin/invite-codes/{inv['id']}",
        json={"max_uses": 2, "note": "扩容两次"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["max_uses"] == 2
    assert patch_resp.json()["remaining_uses"] == 2

    # 2. Switch to an anonymous client to register alice (case-insensitive invite match)
    app = auth_client.app
    with TestClient(app) as reg_client:
        reg_ok = reg_client.post(
            "/api/auth/register",
            json={
                "username": "alice",
                "password": "AlicePass#2026",
                "invite_code": inv["code"].lower(),
            },
        )
        assert reg_ok.status_code == 200
        assert reg_ok.json()["user"]["username"] == "alice"
        assert reg_ok.json()["user"]["role"] == "user"
        assert "HttpOnly" in reg_ok.headers.get("set-cookie", "")

        # Auto-logged-in user can reach /me, /settings, and change password, NOT /admin/*
        assert reg_client.get("/api/auth/me").json()["role"] == "user"
        assert reg_client.get("/api/settings/platforms").status_code == 200
        assert reg_client.get("/api/admin/invite-codes").status_code == 403
        assert reg_client.post("/api/admin/invite-codes", json={"max_uses": 1}).status_code == 403
        assert reg_client.get("/api/admin/users").status_code == 403

        # Duplicate username (different case) must fail 409 WITHOUT burning remaining quota
        dup_resp = reg_client.post(
            "/api/auth/register",
            json={
                "username": "Alice",
                "password": "AlicePass#2026",
                "invite_code": inv["code"],
            },
        )
        assert dup_resp.status_code == 409

    # Verify used_count remained 1 after failed duplicate username attempt
    codes_after_dup = auth_client.get("/api/admin/invite-codes").json()
    current_inv = next(c for c in codes_after_dup if c["id"] == inv["id"])
    assert current_inv["used_count"] == 1
    assert current_inv["remaining_uses"] == 1
    assert current_inv["status"] == "active"

    # Shrinking max_uses below used_count=1 via PATCH must fail 400 (check unlimited 0 is rejected? no 0=unlimited; test finite < used)
    # Use second slot with bob
    with TestClient(app) as bob_client:
        bob_ok = bob_client.post(
            "/api/auth/register",
            json={
                "username": "bob",
                "password": "BobPass#2026",
                "invite_code": inv["code"],
            },
        )
        assert bob_ok.status_code == 200

        # Shrinking below used_count=2 now fails
        shrink_bad = auth_client.patch(
            f"/api/admin/invite-codes/{inv['id']}",
            json={"max_uses": 1},
        )
        assert shrink_bad.status_code == 400

        # Third signup on exhausted 2-use invite must fail 400
        exhausted = bob_client.post(
            "/api/auth/register",
            json={
                "username": "charlie",
                "password": "CharliePass#2026",
                "invite_code": inv["code"],
            },
        )
        assert exhausted.status_code == 400

    listed_exhausted = next(
        c for c in auth_client.get("/api/admin/invite-codes").json() if c["id"] == inv["id"]
    )
    assert listed_exhausted["status"] == "exhausted"
    assert listed_exhausted["remaining_uses"] == 0

    # Delete invite code cleans it up
    assert auth_client.delete(f"/api/admin/invite-codes/{inv['id']}").status_code == 200
    assert all(c["id"] != inv["id"] for c in auth_client.get("/api/admin/invite-codes").json())


def test_expired_disabled_and_unlimited_invite_codes(auth_client: TestClient) -> None:
    tz = zoneinfo.ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)

    # Custom past expiration rejected on create
    bad_past = auth_client.post(
        "/api/admin/invite-codes",
        json={
            "code": "PAST2026",
            "max_uses": 5,
            "expires_at": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
        },
    )
    assert bad_past.status_code == 400

    # Unlimited (max_uses=0) with future custom timestamp succeeds
    unlimited = auth_client.post(
        "/api/admin/invite-codes",
        json={
            "code": "TEAM-VIP-01",
            "max_uses": 0,
            "expires_at": (now + timedelta(days=7)).isoformat(timespec="seconds"),
        },
    )
    assert unlimited.status_code == 200
    u_data = unlimited.json()
    assert u_data["remaining_uses"] is None
    assert u_data["status"] == "active"

    # Disabling code blocks signup even when unlimited quota remains
    dis = auth_client.patch(f"/api/admin/invite-codes/{u_data['id']}", json={"is_active": False})
    assert dis.status_code == 200
    assert dis.json()["status"] == "disabled"

    with TestClient(auth_client.app) as c2:
        fail_disabled = c2.post(
            "/api/auth/register",
            json={"username": "dave", "password": "DavePass#2026", "invite_code": "TEAM-VIP-01"},
        )
        assert fail_disabled.status_code == 400

    # Re-enable + clear expiration, then simulate expiration directly in DB to verify expired block
    reenable = auth_client.patch(
        f"/api/admin/invite-codes/{u_data['id']}",
        json={"is_active": True, "clear_expires_at": True},
    )
    assert reenable.status_code == 200
    assert reenable.json()["expires_at"] is None
    assert reenable.json()["status"] == "active"

    past_iso = (now - timedelta(minutes=5)).isoformat(timespec="seconds")
    with auth_client.app.state.db.write_transaction() as conn:
        conn.execute(
            "UPDATE invite_codes SET expires_at = ? WHERE id = ?",
            (past_iso, u_data["id"]),
        )
    exp_list = next(c for c in auth_client.get("/api/admin/invite-codes").json() if c["id"] == u_data["id"])
    assert exp_list["status"] == "expired"

    with TestClient(auth_client.app) as c3:
        fail_expired = c3.post(
            "/api/auth/register",
            json={"username": "erin", "password": "ErinPass#2026", "invite_code": "TEAM-VIP-01"},
        )
        assert fail_expired.status_code == 400


def test_admin_user_management_session_revocation_and_lockout_guards(auth_client: TestClient) -> None:
    inv = auth_client.post("/api/admin/invite-codes", json={"max_uses": 5}).json()
    with TestClient(auth_client.app) as user_client:
        reg = user_client.post(
            "/api/auth/register",
            json={"username": "member1", "password": "MemberPass#1", "invite_code": inv["code"]},
        )
        assert reg.status_code == 200
        member_id = reg.json()["user"]["id"]
        assert user_client.get("/api/auth/me").status_code == 200

        users = auth_client.get("/api/admin/users").json()
        admin_row = next(u for u in users if u["username"] == "admin")
        member_row = next(u for u in users if u["id"] == member_id)
        assert member_row["invited_by_code"] == inv["code"]

        # Self-lockout protections on admin
        assert auth_client.patch(f"/api/admin/users/{admin_row['id']}", json={"is_active": False}).status_code == 400
        assert auth_client.patch(f"/api/admin/users/{admin_row['id']}", json={"role": "user"}).status_code == 400

        # Disable member1 -> active cookie session fails immediately and re-login is denied
        dis = auth_client.patch(f"/api/admin/users/{member_id}", json={"is_active": False})
        assert dis.status_code == 200
        assert dis.json()["is_active"] is False
        assert user_client.get("/api/auth/me").status_code == 401
        assert user_client.post(
            "/api/auth/login",
            json={"username": "member1", "password": "MemberPass#1"},
        ).status_code == 401


def test_registration_rate_limiter_blocks_excess_attempts(auth_client: TestClient) -> None:
    with TestClient(auth_client.app) as anon:
        for idx in range(10):
            resp = anon.post(
                "/api/auth/register",
                json={
                    "username": f"probe{idx}",
                    "password": "ProbePass#2026",
                    "invite_code": "INVALID-CODE",
                },
            )
            assert resp.status_code == 400
        blocked = anon.post(
            "/api/auth/register",
            json={
                "username": "probe_blocked",
                "password": "ProbePass#2026",
                "invite_code": "INVALID-CODE",
            },
        )
        assert blocked.status_code == 429
