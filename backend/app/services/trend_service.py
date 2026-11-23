"""Domain aggregation, trend chart time-series, and event detail service."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
import zoneinfo

from app.models import (
    DomainInfoDTO,
    DomainsResponse,
    EventDetailResponse,
    EventMetricHistoryDTO,
    HotEventDTO,
    NewsItemDTO,
    TrendPointDTO,
    TrendSeriesDTO,
    TrendsResponse,
)
from app.repositories.event_repo import EventRepository
from app.repositories.news_repo import NewsRepository
from app.repositories.report_repo import ReportRepository
from app.services.settings_service import SettingsService


class EventNotFoundError(Exception):
    """Raised when querying a non-existent hot event cluster."""


class TrendService:
    """Builds domain summaries, multi-day ECharts trend series, and event drilldowns."""

    def __init__(
        self,
        event_repo: EventRepository,
        news_repo: NewsRepository,
        report_repo: ReportRepository,
        settings_service: SettingsService,
        timezone_name: str,
    ) -> None:
        """Initialize the trend & domain query service.

        Args:
            event_repo: Event/metric repository.
            news_repo: News & RSS repository.
            report_repo: Report lookup repository for linking daily & event reports.
            settings_service: Settings service supplying domain dictionary and trend defaults.
            timezone_name: Application timezone name.
        """
        self._events = event_repo
        self._news = news_repo
        self._reports = report_repo
        self._settings = settings_service
        self._tz = zoneinfo.ZoneInfo(timezone_name)

    def _today_str(self) -> str:
        return datetime.now(self._tz).date().isoformat()

    def get_domains_view(
        self,
        target_date: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> DomainsResponse:
        """Return clustered events and RSS items grouped or filtered by domain.

        Args:
            target_date: Optional `YYYY-MM-DD` date; falls back to latest date with metrics.
            domain: Optional domain filter.

        Returns:
            DomainsResponse: Domain list with counts, ranked `HotEventDTO[]`, and domain RSS items.
        """
        resolved_date = target_date or self._events.latest_metric_date() or self._today_str()
        domains_cfg = self._settings.get_internal_section("domains")
        configured_domains = [
            d for d in (domains_cfg.get("items") or []) if isinstance(d, dict) and d.get("id")
        ]

        all_day_events = self._events.list_events_for_date(resolved_date, domain=None)
        counts_by_domain: Dict[str, int] = {}
        for ev in all_day_events:
            d_key = str(ev["domain"] or "其他")
            counts_by_domain[d_key] = counts_by_domain.get(d_key, 0) + 1

        domain_dtos = [
            DomainInfoDTO(
                id=str(d["id"]),
                name=str(d.get("name") or d["id"]),
                description=str(d.get("description") or ""),
                event_count=counts_by_domain.get(str(d["id"]), 0),
            )
            for d in configured_domains
        ]

        filtered_rows = (
            [ev for ev in all_day_events if str(ev["domain"]) == domain]
            if domain
            else all_day_events
        )
        event_ids = [int(ev["id"]) for ev in filtered_rows]
        items_by_event = self._events.get_items_for_events(event_ids)
        report_map = self._reports.find_event_report_map(event_ids)

        event_dtos = [
            HotEventDTO(
                id=int(ev["id"]),
                canonical_title=str(ev["canonical_title"]),
                domain=str(ev["domain"] or "其他"),
                summary=str(ev["summary"] or ""),
                hot_index=float(ev["hot_index"]),
                velocity=float(ev["velocity"] or 0.0),
                platform_count=int(ev["platform_count"]),
                daily_rank=int(ev["daily_rank"]),
                items=[NewsItemDTO(**it) for it in items_by_event.get(int(ev["id"]), [])],
                report_id=report_map.get(int(ev["id"])),
            )
            for ev in filtered_rows
        ]

        since_rss = (datetime.now(self._tz) - timedelta(days=3)).isoformat(timespec="seconds")
        rss_rows = self._news.list_rss(domain=domain or None, since_iso=since_rss, limit=60)
        return DomainsResponse(
            date=resolved_date,
            domains=domain_dtos,
            events=event_dtos,
            rss=[NewsItemDTO(**r) for r in rss_rows],
        )

    def get_trends_view(
        self,
        days: int = 14,
        top_n: Optional[int] = None,
        domain: Optional[str] = None,
    ) -> TrendsResponse:
        """Build multi-day trend series distinguishing multi-day polylines from single-day points.

        Args:
            days: Inclusive trailing day window ending on latest active date or today.
            top_n: Maximum daily rank threshold (`daily_rank <= top_n`); defaults to config.
            domain: Optional domain category filter.

        Returns:
            TrendsResponse: Ordered dates, event series, and date-to-daily-report map.
        """
        trends_cfg = self._settings.get_internal_section("trends")
        effective_top_n = top_n if top_n is not None else max(1, int(trends_cfg.get("daily_top_n", 10) or 10))
        anchor_str = self._events.latest_metric_date() or self._today_str()
        end_date = datetime.strptime(anchor_str, "%Y-%m-%d").date()
        start_date = end_date - timedelta(days=max(1, days) - 1)
        dates = [(start_date + timedelta(days=i)).isoformat() for i in range((end_date - start_date).days + 1)]

        raw_rows = self._events.list_trend_metrics(dates[0], dates[-1], domain=domain or None)
        if not raw_rows:
            daily_reports = self._reports.find_daily_report_map(dates)
            return TrendsResponse(dates=dates, series=[], daily_reports=daily_reports)

        # Include any event that cracked daily Top N on at least one day inside the window.
        qualified_event_ids = {
            int(r["event_id"])
            for r in raw_rows
            if int(r["daily_rank"]) <= effective_top_n
        }
        grouped: Dict[int, List[Dict[str, object]]] = {}
        meta_by_id: Dict[int, Dict[str, str]] = {}
        for row in raw_rows:
            eid = int(row["event_id"])
            if eid not in qualified_event_ids:
                continue
            grouped.setdefault(eid, []).append(row)
            meta_by_id[eid] = {
                "canonical_title": str(row["canonical_title"]),
                "domain": str(row["domain"] or "其他"),
            }

        daily_reports = self._reports.find_daily_report_map(dates)
        event_reports = self._reports.find_event_report_map(list(grouped.keys()))

        series_list: List[TrendSeriesDTO] = []
        for eid, rows in grouped.items():
            points = [
                TrendPointDTO(
                    date=str(r["metric_date"]),
                    hot_index=float(r["hot_index"]),
                    daily_rank=int(r["daily_rank"]),
                    platform_count=int(r["platform_count"]),
                    velocity=float(r["velocity"] or 0.0),
                    is_top_n=int(r["daily_rank"]) <= effective_top_n,
                    daily_report_id=daily_reports.get(str(r["metric_date"])),
                    event_report_id=event_reports.get(eid),
                )
                for r in rows
            ]
            meta = meta_by_id[eid]
            series_list.append(
                TrendSeriesDTO(
                    event_id=eid,
                    canonical_title=meta["canonical_title"],
                    domain=meta["domain"],
                    is_multi_day=len(points) >= 2,
                    points=points,
                )
            )

        series_list.sort(
            key=lambda s: (
                0 if s.is_multi_day else 1,
                -max(p.hot_index for p in s.points),
            )
        )
        return TrendsResponse(dates=dates, series=series_list, daily_reports=daily_reports)

    def get_event_detail(self, event_id: int) -> EventDetailResponse:
        """Fetch full detail, linked news items, metrics trajectory, and linked report ID for an event.

        Args:
            event_id: Hot event primary key.

        Returns:
            EventDetailResponse: Complete event detail payload.

        Raises:
            EventNotFoundError: If the event does not exist.
        """
        event = self._events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError(f"Hot event {event_id} not found")

        items = self._events.get_event_items(event_id)
        metrics_rows = self._events.list_event_metrics_history(event_id)
        report_map = self._reports.find_event_report_map([event_id])
        return EventDetailResponse(
            id=int(event["id"]),
            canonical_title=str(event["canonical_title"]),
            domain=str(event["domain"] or "其他"),
            summary=str(event["summary"] or ""),
            first_seen_date=str(event["first_seen_date"]),
            last_seen_date=str(event["last_seen_date"]),
            items=[NewsItemDTO(**it) for it in items],
            metrics=[
                EventMetricHistoryDTO(
                    metric_date=str(m["metric_date"]),
                    hot_index=float(m["hot_index"]),
                    daily_rank=int(m["daily_rank"]),
                    platform_count=int(m["platform_count"]),
                    velocity=float(m["velocity"] or 0.0),
                    is_top_n=bool(m["is_top_n"]),
                )
                for m in metrics_rows
            ],
            report_id=report_map.get(event_id),
        )