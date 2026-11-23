"""FastAPI dependency injection helpers for authenticated routes and services."""

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings
from app.repositories.news_repo import NewsRepository
from app.repositories.user_repo import UserRecord
from app.services.admin_service import AdminService
from app.services.ai_gateway.gateway_service import AIGatewayService
from app.services.auth_service import AuthError, AuthService
from app.services.chat_service import ChatService
from app.services.cluster_service import ClusterService
from app.services.crawl_service import CrawlService
from app.services.report_service import ReportService
from app.services.settings_service import SettingsService
from app.services.trend_service import TrendService
from app.services.webhook_service import WebhookService

SESSION_COOKIE_NAME = "trendradar_session"


def get_settings(request: Request) -> Settings:
    """Retrieve application settings from FastAPI app state."""
    return request.app.state.settings


def get_auth_service(request: Request) -> AuthService:
    """Retrieve `AuthService` from FastAPI app state."""
    return request.app.state.auth_service


def get_admin_service(request: Request) -> AdminService:
    """Retrieve `AdminService` from FastAPI app state."""
    return request.app.state.admin_service


def get_news_repo(request: Request) -> NewsRepository:
    """Retrieve `NewsRepository` from FastAPI app state."""
    return request.app.state.news_repo


def get_settings_service(request: Request) -> SettingsService:
    """Retrieve `SettingsService` from FastAPI app state."""
    return request.app.state.settings_service


def get_crawl_service(request: Request) -> CrawlService:
    """Retrieve `CrawlService` from FastAPI app state."""
    return request.app.state.crawl_service


def get_webhook_service(request: Request) -> WebhookService:
    """Retrieve `WebhookService` from FastAPI app state."""
    return request.app.state.webhook_service


def get_gateway_service(request: Request) -> AIGatewayService:
    """Retrieve `AIGatewayService` from FastAPI app state."""
    return request.app.state.gateway_service


def get_cluster_service(request: Request) -> ClusterService:
    """Retrieve `ClusterService` from FastAPI app state."""
    return request.app.state.cluster_service


def get_trend_service(request: Request) -> TrendService:
    """Retrieve `TrendService` from FastAPI app state."""
    return request.app.state.trend_service


def get_report_service(request: Request) -> ReportService:
    """Retrieve `ReportService` from FastAPI app state."""
    return request.app.state.report_service


def get_chat_service(request: Request) -> ChatService:
    """Retrieve `ChatService` from FastAPI app state."""
    return request.app.state.chat_service


def get_current_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserRecord:
    """Authenticate the current request using the HttpOnly session cookie.

    Args:
        request: Incoming FastAPI request.
        auth_service: AuthService dependency.

    Returns:
        UserRecord: Authenticated active user.

    Raises:
        HTTPException: 401 Unauthorized when cookie is missing, invalid, or expired.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    try:
        return auth_service.verify_session(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def require_admin(
    current_user: UserRecord = Depends(get_current_user),
) -> UserRecord:
    """Restrict access to active accounts holding the `admin` role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可执行此操作",
        )
    return current_user