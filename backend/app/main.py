"""FastAPI application factory, dependency wiring, and APScheduler lifecycle."""

import asyncio
from contextlib import asynccontextmanager
import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, ai_config, auth, chat, hotlist, reports, settings as settings_router, trends
from app.config import Settings
from app.models import ReportGenerateRequest
from app.repositories.chat_repo import ChatRepository
from app.repositories.db import Database
from app.repositories.event_repo import EventRepository
from app.repositories.invite_repo import InviteRepository
from app.repositories.news_repo import NewsRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.settings_repo import SettingsRepository
from app.repositories.user_repo import UserRepository
from app.security import LoginRateLimiter, SecretCipher, SessionManager
from app.services.admin_service import AdminService
from app.services.ai_gateway.gateway_service import AIGatewayService
from app.services.auth_service import AuthService
from app.services.bootstrap_service import BootstrapService
from app.services.chat_service import ChatService
from app.services.cluster_service import ClusterService
from app.services.crawl_service import CrawlAlreadyRunningError, CrawlService
from app.services.report_service import ReportService
from app.services.settings_service import SettingsService
from app.services.trend_service import TrendService
from app.services.webhook_service import WebhookService

logger = logging.getLogger(__name__)


def _scheduled_crawl_job(
    crawl_service: CrawlService,
    cluster_service: ClusterService,
    webhook_service: WebhookService,
) -> None:
    try:
        summary = crawl_service.run_once()
        clustered = asyncio.run(cluster_service.run_incremental_clustering())
        logger.info(
            "Scheduled crawl finished: hotlist=%d rss=%d foreign=%d clustered=%d errors=%d",
            summary.hotlist_count,
            summary.rss_count,
            summary.foreign_api_count,
            clustered,
            len(summary.errors),
        )
        webhook_service.push_incremental_for_all_users()
    except CrawlAlreadyRunningError:
        logger.info("Skipping scheduled crawl because another crawl run is already active")
    except Exception:
        logger.exception("Scheduled crawl job failed")


def _scheduled_daily_report_job(
    report_service: ReportService,
    gateway_service: AIGatewayService,
) -> None:
    if gateway_service.find_slot_by_role("summary_report") is None:
        return
    try:
        asyncio.run(report_service.generate_report(ReportGenerateRequest(mode="daily_overall")))
    except Exception:
        logger.exception("Scheduled daily report job failed")


def _parse_hh_mm(raw_time: str) -> tuple[int, int]:
    parts = str(raw_time or "22:00").strip().split(":")
    try:
        hour = max(0, min(23, int(parts[0])))
        minute = max(0, min(59, int(parts[1]))) if len(parts) > 1 else 0
        return hour, minute
    except (ValueError, IndexError):
        return 22, 0


def _apply_schedule_to_scheduler(
    scheduler: BackgroundScheduler,
    schedule_cfg: dict,
    *,
    crawl_service: CrawlService,
    cluster_service: ClusterService,
    webhook_service: WebhookService,
    settings_service: SettingsService,
    report_service: ReportService,
    gateway_service: AIGatewayService,
) -> None:
    """Register or reschedule periodic crawl and daily report jobs on `scheduler`."""
    interval_min = max(5, int(schedule_cfg.get("crawl_interval_minutes", 30) or 30))
    hour, minute = _parse_hh_mm(str(schedule_cfg.get("daily_report_time", "22:00")))
    scheduler.add_job(
        _scheduled_crawl_job,
        trigger="interval",
        minutes=interval_min,
        args=[crawl_service, cluster_service, webhook_service],
        id="crawl_job",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        _scheduled_daily_report_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        args=[report_service, gateway_service],
        id="daily_report_job",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Create and configure a FastAPI application instance.

    Args:
        settings: Optional settings override (used by tests); reads env vars if omitted.

    Returns:
        FastAPI: Configured ASGI application.
    """
    cfg = settings or Settings()

    db = Database(cfg.db_path)
    user_repo = UserRepository(db)
    news_repo = NewsRepository(db)
    settings_repo = SettingsRepository(db)
    event_repo = EventRepository(db)
    report_repo = ReportRepository(db)
    chat_repo = ChatRepository(db)
    invite_repo = InviteRepository(db)

    cipher = SecretCipher(cfg.secret_key)
    session_manager = SessionManager(cfg.secret_key, max_age_sec=cfg.session_max_age_sec)
    rate_limiter = LoginRateLimiter()
    register_rate_limiter = LoginRateLimiter(max_attempts=10, window_sec=300)

    auth_service = AuthService(
        user_repo,
        session_manager,
        rate_limiter,
        cfg.timezone,
        invite_repo=invite_repo,
        register_rate_limiter=register_rate_limiter,
    )
    admin_service = AdminService(invite_repo, user_repo, cfg.timezone)
    settings_service = SettingsService(settings_repo, cipher, cfg.timezone)
    gateway_service = AIGatewayService(chat_repo, cipher, cfg)
    crawl_service = CrawlService(settings_service, news_repo, cfg.timezone)
    cluster_service = ClusterService(event_repo, news_repo, settings_service, gateway_service, cfg.timezone)
    trend_service = TrendService(event_repo, news_repo, report_repo, settings_service, cfg.timezone)
    report_service = ReportService(
        report_repo, event_repo, news_repo, settings_service, gateway_service, cfg.timezone
    )
    chat_service = ChatService(chat_repo, report_repo, gateway_service, cfg.timezone)
    webhook_service = WebhookService(settings_service, settings_repo, news_repo, cfg.timezone)
    bootstrap_service = BootstrapService(cfg, db, user_repo, settings_repo, chat_repo, cipher)

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        bootstrap_service.run()
        scheduler: Optional[BackgroundScheduler] = None
        if cfg.enable_scheduler:
            schedule_cfg = settings_service.get_internal_section("schedule")
            scheduler = BackgroundScheduler(timezone=cfg.timezone)
            _apply_schedule_to_scheduler(
                scheduler,
                schedule_cfg,
                crawl_service=crawl_service,
                cluster_service=cluster_service,
                webhook_service=webhook_service,
                settings_service=settings_service,
                report_service=report_service,
                gateway_service=gateway_service,
            )
            app_instance.state.scheduler = scheduler
            scheduler.start()
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
                app_instance.state.scheduler = None

    application = FastAPI(
        title="TrendRadar API",
        version="0.1.0",
        lifespan=lifespan,
    )

    def reschedule_jobs(schedule_cfg: dict) -> bool:
        """Dynamically reschedule running APScheduler jobs after schedule updates."""
        scheduler = getattr(application.state, "scheduler", None)
        if scheduler is None or not scheduler.running:
            return False
        _apply_schedule_to_scheduler(
            scheduler,
            schedule_cfg,
            crawl_service=crawl_service,
            cluster_service=cluster_service,
            webhook_service=webhook_service,
            settings_service=settings_service,
            report_service=report_service,
            gateway_service=gateway_service,
        )
        return True

    application.state.scheduler = None
    application.state.reschedule_jobs = reschedule_jobs
    application.state.settings = cfg
    application.state.db = db
    application.state.auth_service = auth_service
    application.state.admin_service = admin_service
    application.state.invite_repo = invite_repo
    application.state.news_repo = news_repo
    application.state.event_repo = event_repo
    application.state.report_repo = report_repo
    application.state.chat_repo = chat_repo
    application.state.settings_service = settings_service
    application.state.gateway_service = gateway_service
    application.state.crawl_service = crawl_service
    application.state.cluster_service = cluster_service
    application.state.trend_service = trend_service
    application.state.report_service = report_service
    application.state.chat_service = chat_service
    application.state.webhook_service = webhook_service

    cors_list = [o.strip() for o in cfg.cors_origins.split(",") if o.strip()]
    if cors_list:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @application.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    application.include_router(auth.router)
    application.include_router(admin.router)
    application.include_router(hotlist.router)
    application.include_router(trends.router)
    application.include_router(reports.router)
    application.include_router(chat.router)
    application.include_router(ai_config.router)
    application.include_router(settings_router.router)
    return application


app = create_app()