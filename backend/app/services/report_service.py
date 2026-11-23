"""AI report generation (`daily_overall`, `domain_trend`, `item_analysis`) and archive service."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import zoneinfo

from app.models import (
    ReportCreateRequest,
    ReportDTO,
    ReportGenerateRequest,
    ReportListResponse,
)
from app.repositories.event_repo import EventRepository
from app.repositories.news_repo import NewsRepository
from app.repositories.report_repo import ReportRepository
from app.services.ai_gateway.base import LLMConfigError
from app.services.ai_gateway.gateway_service import AIGatewayService
from app.services.report_prompts import (
    REPORT_SYSTEM_PROMPT,
    build_daily_overall_prompt,
    build_domain_trend_prompt,
    build_item_analysis_prompt,
)
from app.services.settings_service import SettingsService


class ReportNotFoundError(Exception):
    """Raised when a requested report record does not exist."""


class ReportValidationError(Exception):
    """Raised when a report generation request lacks required scope parameters or source items."""


class ReportService:
    """Coordinates structured AI report generation and SQLite report archiving."""

    def __init__(
        self,
        report_repo: ReportRepository,
        event_repo: EventRepository,
        news_repo: NewsRepository,
        settings_service: SettingsService,
        gateway_service: AIGatewayService,
        timezone_name: str,
    ) -> None:
        """Initialize the report service.

        Args:
            report_repo: Persistence repository for `reports`.
            event_repo: Event repository providing clustered daily metrics.
            news_repo: News & RSS repository providing underlying items.
            settings_service: Settings service for domain/top-n configuration.
            gateway_service: AI gateway resolving summary provider slots.
            timezone_name: Application timezone name.
        """
        self._reports = report_repo
        self._events = event_repo
        self._news = news_repo
        self._settings = settings_service
        self._gateway = gateway_service
        self._tz = zoneinfo.ZoneInfo(timezone_name)

    def _now(self) -> datetime:
        return datetime.now(self._tz)

    def list_reports(
        self,
        *,
        report_type: Optional[str] = None,
        domain: Optional[str] = None,
        report_date: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ReportListResponse:
        """Query archived reports with optional filters and pagination.

        Args:
            report_type: Optional report category filter.
            domain: Optional domain filter.
            report_date: Optional `YYYY-MM-DD` date filter.
            page: 1-based page number.
            page_size: Page size limit.

        Returns:
            ReportListResponse: Paginated report list and total matching count.
        """
        rows, total = self._reports.list_reports(
            report_type=report_type or None,
            domain=domain or None,
            report_date=report_date or None,
            page=page,
            page_size=page_size,
        )
        return ReportListResponse(items=[ReportDTO(**r) for r in rows], total=total)

    def get_report(self, report_id: int) -> ReportDTO:
        """Retrieve one report by primary key.

        Args:
            report_id: Report ID.

        Returns:
            ReportDTO: Stored report.

        Raises:
            ReportNotFoundError: If report does not exist.
        """
        row = self._reports.get_by_id(report_id)
        if row is None:
            raise ReportNotFoundError(f"Report {report_id} not found")
        return ReportDTO(**row)

    def create_manual_report(self, req: ReportCreateRequest) -> ReportDTO:
        """Save a user-authored or externally edited Markdown report to SQLite.

        Args:
            req: Validated manual report payload.

        Returns:
            ReportDTO: Newly created report record.
        """
        row = self._reports.create(
            report_type=req.report_type,
            report_date=req.report_date,
            domain=req.domain.strip(),
            title=req.title.strip(),
            content_md=req.content_md,
            related_event_ids=req.related_event_ids,
            related_news_ids=req.related_news_ids,
            source_session_id=None,
            provider_slot_id=None,
            now_iso=self._now().isoformat(timespec="seconds"),
        )
        return ReportDTO(**row)

    def delete_report(self, report_id: int) -> None:
        """Delete a stored report by ID.

        Args:
            report_id: Target report ID.

        Raises:
            ReportNotFoundError: If no report matches `report_id`.
        """
        if not self._reports.delete(report_id):
            raise ReportNotFoundError(f"Report {report_id} not found")

    async def generate_report(self, req: ReportGenerateRequest) -> ReportDTO:
        """Generate a structured Markdown report via LLM and persist it in `reports`.

        Args:
            req: Report mode (`daily_overall`, `domain_trend`, `item_analysis`) and target scope.

        Returns:
            ReportDTO: Newly persisted AI-generated report.

        Raises:
            ReportValidationError: If required parameters or backing data are missing.
            LLMConfigError: If no enabled AI slot is available.
            LLMGatewayError: On upstream AI errors.
        """
        now = self._now()
        target_date = req.date or self._events.latest_metric_date() or now.date().isoformat()
        title, domain, prompt, event_ids, news_ids = self._prepare_generation_context(req, target_date)

        slot, adapter = self._gateway.resolve_slot(
            slot_id=req.provider_slot_id,
            role="summary_report",
            fallback_any=req.provider_slot_id is None,
        )

        chunks: List[str] = []
        async for ev in adapter.stream_chat(
            messages=[{"role": "user", "content": prompt}],
            model=str(slot["model"]),
            system_prompt=REPORT_SYSTEM_PROMPT,
            extra_params=dict(slot.get("extra_params") or {}),
        ):
            if ev.type == "delta" and ev.text:
                chunks.append(ev.text)

        content_md = "".join(chunks).strip()
        if not content_md:
            raise LLMConfigError("AI provider returned empty report content")

        row = self._reports.create(
            report_type=req.mode,
            report_date=target_date,
            domain=domain,
            title=title,
            content_md=content_md,
            related_event_ids=event_ids,
            related_news_ids=news_ids,
            source_session_id=None,
            provider_slot_id=int(slot["id"]),
            now_iso=now.isoformat(timespec="seconds"),
        )
        return ReportDTO(**row)

    def _prepare_generation_context(
        self,
        req: ReportGenerateRequest,
        target_date: str,
    ) -> Tuple[str, str, str, List[int], List[int]]:
        if req.mode == "daily_overall":
            return self._build_daily_overall_context(target_date)
        if req.mode == "domain_trend":
            return self._build_domain_trend_context(target_date, req.domain)
        return self._build_item_analysis_context(req.news_ids, req.event_ids, target_date)

    def _build_daily_overall_context(self, target_date: str) -> Tuple[str, str, str, List[int], List[int]]:
        events = self._events.list_events_for_date(target_date)
        trends_cfg = self._settings.get_internal_section("trends")
        top_n = max(1, int(trends_cfg.get("daily_top_n", 10) or 10))
        top_events = events[:top_n]
        rising = self._news.list_rising(
            since_iso=(self._now() - timedelta(hours=24)).isoformat(timespec="seconds"),
            limit=20,
        )

        if not top_events and not rising:
            raise ReportValidationError(f"{target_date} 暂无热点数据，请先点击「更新数据」后再生成报告")

        event_ids = [int(ev["id"]) for ev in top_events]
        items_by_ev = self._events.get_items_for_events(event_ids)
        news_ids = [int(it["id"]) for it in rising[:12]]
        title = f"{target_date} 全网热点每日研判"
        prompt = build_daily_overall_prompt(title, top_events, items_by_ev, rising)
        return title, "", prompt, event_ids, news_ids

    def _build_domain_trend_context(
        self,
        target_date: str,
        domain: Optional[str],
    ) -> Tuple[str, str, str, List[int], List[int]]:
        domain_name = (domain or "").strip()
        if not domain_name:
            raise ReportValidationError("生成领域趋势报告需先指定领域名称")

        events = self._events.list_events_for_date(target_date, domain=domain_name)
        since_rss = (self._now() - timedelta(days=3)).isoformat(timespec="seconds")
        rss = self._news.list_rss(domain=domain_name, since_iso=since_rss, limit=25)
        if not events and not rss:
            raise ReportValidationError(f"「{domain_name}」领域暂无热点或订阅数据，请先更新数据")

        event_ids = [int(ev["id"]) for ev in events[:15]]
        title = f"{target_date} · {domain_name}领域趋势简报"
        prompt = build_domain_trend_prompt(title, domain_name, events, rss)
        return title, domain_name, prompt, event_ids, []

    def _build_item_analysis_context(
        self,
        news_ids: List[int],
        event_ids: List[int],
        target_date: str,
    ) -> Tuple[str, str, str, List[int], List[int]]:
        if not news_ids and not event_ids:
            raise ReportValidationError("item_analysis report requires non-empty 'news_ids' or 'event_ids'")

        news_items = self._news.get_news_items_by_ids(news_ids)
        events_data: List[Dict[str, Any]] = []
        inferred_domain = ""
        for eid in event_ids:
            ev = self._events.get_by_id(eid)
            if ev is None:
                continue
            inferred_domain = inferred_domain or str(ev.get("domain") or "")
            events_data.append(
                {
                    "event_id": int(ev["id"]),
                    "canonical_title": ev["canonical_title"],
                    "domain": ev["domain"],
                    "summary": ev["summary"],
                    "linked_items": [
                        {"platform": it["platform_name"], "title": it["title"], "url": it["url"]}
                        for it in self._events.get_event_items(eid)[:10]
                    ],
                }
            )

        if not news_items and not events_data:
            raise ReportValidationError("None of the specified news_ids or event_ids were found")

        if not inferred_domain and news_items:
            inferred_domain = str(news_items[0].get("domain") or "")

        focus_name = (
            str(events_data[0]["canonical_title"])
            if events_data
            else str(news_items[0]["title"])[:28]
        )
        title = f"专题深度分析：{focus_name}"
        prompt = build_item_analysis_prompt(events_data, news_items)
        return title, inferred_domain, prompt, [int(e["event_id"]) for e in events_data], [int(n["id"]) for n in news_items]