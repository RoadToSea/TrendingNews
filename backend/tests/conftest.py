"""Pytest fixtures for TrendRadar backend tests."""

from pathlib import Path
from typing import Iterator

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    """Create isolated per-test application settings pointing to a temporary SQLite DB."""
    return Settings(
        app_base_path="/",
        db_path=tmp_path / "trendradar_test.db",
        secret_key="unit-test-secret-key-please-ignore",
        admin_user="admin",
        admin_pass="StrongPass123!",
        timezone="Asia/Shanghai",
        enable_scheduler=False,
    )


@pytest.fixture()
def client(test_settings: Settings) -> Iterator[TestClient]:
    """Provide an unauthenticated FastAPI TestClient with initialized schema and defaults."""
    app = create_app(test_settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_client(client: TestClient) -> TestClient:
    """Provide a logged-in TestClient carrying the HttpOnly session cookie."""
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "StrongPass123!"},
    )
    assert resp.status_code == 200
    return client
