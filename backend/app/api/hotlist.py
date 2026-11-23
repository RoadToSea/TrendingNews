"""Hotlist, rising velocity, RSS, and keyword statistics API endpoints."""

from datetime import datetime, timedelta
from typing import Optional
import zoneinfo

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user, get_news_repo, get_settings, get_settings_service
from app.config import Settings
from app.models import (
    HotlistResponse,
    KeywordGroupStatDTO,
    KeywordStatsResponse,
    NewsItemDTO,
    PlatformSummaryDTO,
    RisingResponse,
    RssFeedSummaryDTO,
    RssResponse,
)
from app.repositories.news_repo import NewsRepository
from app.repositories.user_repo import UserRecord
from app.services.keyword_service import match_items_by_keyword_groups
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api", tags=["hotlist"])


def _since_hours_iso(timezone_name: str, hours: int) -> str:
    now = datetime.now(zoneinfo.ZoneInfo(timezone_name))
    return (now - timedelta(hours=hours)).isoformat(timespec="seconds")


@router.get("/hotlist", response_model=HotlistResponse)
def list_hotlist(
    platform_id: Optional[str] = None,
    q: Optional[str] = None,
    hours: int = Query(default=48, ge=1, le=720),
    limit: int = Query(default=100, ge=1, le=500),
    _: UserRecord = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    news_repo: NewsRepository = Depends(get_news_repo),
) -> HotlistResponse:
    """List hotlist and official open API items with active platform summaries."""
    since_iso = _since_hours_iso(settings.timezone, hours)
    items = news_repo.list_hotlist(
        platform_id=platform_id or None,
        query=q or None,
        since_iso=since_iso,
        limit=limit,
    )
    platforms = news_repo.list_platforms(since_iso=since_iso)
    return HotlistResponse(
        items=[NewsItemDTO(**row) for row in items],
        platforms=[PlatformSummaryDTO(**p) for p in platforms],
    )


@router.get("/hotlist/rising", response_model=RisingResponse)
def list_rising(
    hours: int = Query(default=6, ge=1, le=72),
    limit: int = Query(default=50, ge=1, le=200),
    _: UserRecord = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    news_repo: NewsRepository = Depends(get_news_repo),
) -> RisingResponse:
    """List fast-rising items sorted by velocity descending."""
    since_iso = _since_hours_iso(settings.timezone, hours)
    items = news_repo.list_rising(since_iso=since_iso, limit=limit)
    return RisingResponse(items=[NewsItemDTO(**row) for row in items])


@router.get("/rss", response_model=RssResponse)
def list_rss(
    feed_id: Optional[str] = None,
    domain: Optional[str] = None,
    days: int = Query(default=3, ge=1, le=30),
    limit: int = Query(default=100, ge=1, le=500),
    _: UserRecord = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    news_repo: NewsRepository = Depends(get_news_repo),
) -> RssResponse:
    """List stored RSS items and feed summaries."""
    since_iso = _since_hours_iso(settings.timezone, days * 24)
    items = news_repo.list_rss(
        feed_id=feed_id or None,
        domain=domain or None,
        since_iso=since_iso,
        limit=limit,
    )
    feeds = news_repo.list_rss_feeds(since_iso=since_iso)
    return RssResponse(
        items=[NewsItemDTO(**row) for row in items],
        feeds=[RssFeedSummaryDTO(**f) for f in feeds],
    )


@router.get("/keywords/stats", response_model=KeywordStatsResponse)
def keyword_stats(
    hours: int = Query(default=24, ge=1, le=168),
    _: UserRecord = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    settings_service: SettingsService = Depends(get_settings_service),
    news_repo: NewsRepository = Depends(get_news_repo),
) -> KeywordStatsResponse:
    """Compute keyword group matches across recent hotlist and RSS items."""
    kw_cfg = settings_service.get_internal_section("keywords")
    raw_text = str(kw_cfg.get("raw_text") or "")
    include_rss = bool(kw_cfg.get("include_rss", True))
    since_iso = _since_hours_iso(settings.timezone, hours)

    items = news_repo.get_items_for_keywords(since_iso=since_iso, include_rss=include_rss)
    groups, total = match_items_by_keyword_groups(items, raw_text)
    return KeywordStatsResponse(
        groups=[
            KeywordGroupStatDTO(
                group_key=g["group_key"],
                display_name=g["display_name"],
                count=g["count"],
                items=[NewsItemDTO(**item) for item in g["items"]],
            )
            for g in groups
        ],
        total=total,
    )
