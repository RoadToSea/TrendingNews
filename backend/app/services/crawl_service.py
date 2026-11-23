"""Progressive concurrent crawl orchestration service with incremental per-source DB persistence."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
import inspect
import threading
import time
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple
import uuid
import zoneinfo

from app.models import CrawlTriggerResponse
from app.repositories.news_repo import NewsRepository
from app.services.collectors.base import BaseCollector, CollectedItem, CollectionResult
from app.services.collectors.foreign_apis import (
    GitHubTrendingCollector,
    HackerNewsCollector,
    HuggingFaceCollector,
    RedditCollector,
    YouTubeMetricsCollector,
)
from app.services.collectors.newsnow import NewsNowCollector
from app.services.collectors.rss import RssCollector
from app.services.scoring_service import (
    compute_rank_velocity,
    compute_raw_interaction_rate,
    normalize_platform_interaction_velocities,
)
from app.services.settings_service import SettingsService

_INTERACTION_PLATFORMS = {"hackernews", "huggingface", "github", "reddit", "youtube"}


class CrawlAlreadyRunningError(Exception):
    """Raised when a crawl trigger is requested while another collection run is still in progress."""


@dataclass
class CrawlProgressEvent:
    """Real-time progress event emitted as each individual source finishes and persists."""

    stage: Literal["start", "source_done", "done"]
    source_kind: str = ""
    source_id: str = ""
    source_name: str = ""
    count: int = 0
    completed_sources: int = 0
    total_sources: int = 0
    error: Optional[str] = None
    summary: Optional[CrawlTriggerResponse] = None


def _supports_source_callback(collector: Any) -> bool:
    try:
        return "on_source_done" in inspect.signature(collector.collect).parameters
    except (TypeError, ValueError):
        return False


def _foreign_source_identity(collector: Any, fallback_idx: int) -> Tuple[str, str]:
    name_map = {
        "HackerNewsCollector": ("hackernews", "Hacker News"),
        "HuggingFaceCollector": ("huggingface", "Hugging Face"),
        "GitHubTrendingCollector": ("github", "GitHub Trending"),
        "RedditCollector": ("reddit", "Reddit"),
        "YouTubeMetricsCollector": ("youtube", "YouTube"),
    }
    return name_map.get(type(collector).__name__, (f"foreign_{fallback_idx}", type(collector).__name__))


class _CrawlRunState:
    """Thread-safe shared counters and persistence callbacks for one concurrent crawl run."""

    def __init__(
        self,
        *,
        total_sources: int,
        now: datetime,
        now_iso: str,
        persist_scored: Callable[[List[CollectedItem], datetime, str], int],
        persist_rss: Callable[[List[CollectedItem], str], int],
        on_progress: Optional[Callable[[CrawlProgressEvent], None]],
    ) -> None:
        self.total_sources = total_sources
        self.now = now
        self.now_iso = now_iso
        self.persist_scored = persist_scored
        self.persist_rss = persist_rss
        self.on_progress = on_progress
        self._lock = threading.Lock()
        self.completed_sources = 0
        self.hotlist_count = 0
        self.rss_count = 0
        self.foreign_count = 0
        self.errors: List[str] = []

    def emit(self, event: CrawlProgressEvent) -> None:
        if self.on_progress is not None:
            self.on_progress(event)

    def handle_hotlist_source(
        self,
        source_id: str,
        source_name: str,
        items: List[CollectedItem],
        error: Optional[str],
    ) -> None:
        persisted = self.persist_scored(items, self.now, self.now_iso) if items else 0
        with self._lock:
            self.completed_sources += 1
            self.hotlist_count += persisted
            if error:
                self.errors.append(error)
            done = self.completed_sources
            total = max(self.total_sources, done)
        self.emit(
            CrawlProgressEvent(
                stage="source_done",
                source_kind="hotlist",
                source_id=source_id,
                source_name=source_name,
                count=persisted,
                completed_sources=done,
                total_sources=total,
                error=error,
            )
        )

    def handle_rss_source(
        self,
        feed_id: str,
        feed_name: str,
        items: List[CollectedItem],
        error: Optional[str],
    ) -> None:
        persisted = self.persist_rss(items, self.now_iso) if items else 0
        with self._lock:
            self.completed_sources += 1
            self.rss_count += persisted
            if error:
                self.errors.append(error)
            done = self.completed_sources
            total = max(self.total_sources, done)
        self.emit(
            CrawlProgressEvent(
                stage="source_done",
                source_kind="rss",
                source_id=feed_id,
                source_name=feed_name,
                count=persisted,
                completed_sources=done,
                total_sources=total,
                error=error,
            )
        )

    def handle_foreign_collector(
        self,
        source_id: str,
        source_name: str,
        result: CollectionResult,
        advance_progress: bool = True,
    ) -> None:
        persisted = self.persist_scored(result.items, self.now, self.now_iso) if result.items else 0
        err_msg = result.errors[0] if result.errors else None
        with self._lock:
            if advance_progress:
                self.completed_sources += 1
            self.foreign_count += persisted
            self.errors.extend(result.errors)
            done = self.completed_sources
            total = max(self.total_sources, done)
        if not advance_progress and not result.items and not result.errors:
            return
        self.emit(
            CrawlProgressEvent(
                stage="source_done",
                source_kind="foreign_api",
                source_id=source_id,
                source_name=source_name,
                count=persisted,
                completed_sources=done,
                total_sources=total,
                error=err_msg,
            )
        )


class CrawlService:
    """Coordinates parallel scheduled and manual crawls with incremental per-source persistence."""

    def __init__(
        self,
        settings_service: SettingsService,
        news_repo: NewsRepository,
        timezone_name: str,
        hotlist_collector_factory: Optional[Callable[[Dict], BaseCollector]] = None,
        rss_collector_factory: Optional[Callable[[Dict, List[Dict]], BaseCollector]] = None,
        foreign_collectors_factory: Optional[Callable[[Dict], List[BaseCollector]]] = None,
        youtube_collector_factory: Optional[Callable[[Dict], YouTubeMetricsCollector]] = None,
    ) -> None:
        """Initialize the crawl coordinator with optional test collector factories.

        Args:
            settings_service: Settings service supplying decrypted source configurations.
            news_repo: Repository persisting news items, trajectories, and RSS items.
            timezone_name: Application timezone name.
            hotlist_collector_factory: Optional override factory for domestic hotlists.
            rss_collector_factory: Optional override factory for RSS feeds.
            foreign_collectors_factory: Optional override factory for foreign open APIs.
            youtube_collector_factory: Optional override factory for YouTube metrics enrichment.
        """
        self._settings = settings_service
        self._repo = news_repo
        self._tz_name = timezone_name
        self._tz = zoneinfo.ZoneInfo(timezone_name)
        self._hotlist_factory = hotlist_collector_factory
        self._rss_factory = rss_collector_factory
        self._foreign_factory = foreign_collectors_factory
        self._youtube_factory = youtube_collector_factory
        self._run_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """Return True while a crawl execution holds the concurrency lock."""
        return self._run_lock.locked()

    def run_once(self, on_progress: Optional[Callable[[CrawlProgressEvent], None]] = None) -> CrawlTriggerResponse:
        """Execute one parallel collection cycle, persisting and reporting each finished source immediately.

        Args:
            on_progress: Optional callback invoked for `start`, each `source_done`, and `done`.

        Returns:
            CrawlTriggerResponse: Summary counts, elapsed milliseconds, and non-fatal errors.

        Raises:
            CrawlAlreadyRunningError: If another collection run is currently executing.
        """
        if not self._run_lock.acquire(blocking=False):
            raise CrawlAlreadyRunningError("数据正在更新中，请稍后再试")

        started = time.monotonic()
        try:
            return self._execute_crawl(started, on_progress)
        finally:
            self._run_lock.release()

    def _execute_crawl(
        self,
        started: float,
        on_progress: Optional[Callable[[CrawlProgressEvent], None]],
    ) -> CrawlTriggerResponse:
        now = datetime.now(self._tz)
        now_iso = now.isoformat(timespec="seconds")

        platforms_cfg = self._settings.get_internal_section("platforms")
        rss_cfg = self._settings.get_internal_section("rss")
        foreign_cfg = self._settings.get_internal_section("foreign_sources")
        schedule_cfg = self._settings.get_internal_section("schedule")

        yt_collector = self._make_youtube_collector(foreign_cfg)
        hotlist_collector = self._make_hotlist_collector(platforms_cfg)
        rss_collector = self._make_rss_collector(rss_cfg, yt_collector.build_channel_rss_feeds())
        foreign_collectors = self._make_foreign_collectors(foreign_cfg)

        total_sources = self._estimate_total_sources(hotlist_collector, rss_collector, foreign_collectors)
        state = _CrawlRunState(
            total_sources=total_sources,
            now=now,
            now_iso=now_iso,
            persist_scored=self._persist_scored_items,
            persist_rss=self._persist_rss_items,
            on_progress=on_progress,
        )
        state.emit(CrawlProgressEvent(stage="start", completed_sources=0, total_sources=total_sources))

        rss_items = self._execute_parallel_collectors(hotlist_collector, rss_collector, foreign_collectors, state)
        yt_res = self._run_collector_safe_fn("foreign:youtube", lambda: yt_collector.collect_from_rss_items(rss_items))
        state.handle_foreign_collector("youtube", "YouTube", yt_res, advance_progress=False)

        retention_days = int(schedule_cfg.get("retention_days", 0) or 0)
        if retention_days > 0:
            cutoff = (now - timedelta(days=retention_days)).isoformat(timespec="seconds")
            self._repo.cleanup_older_than(cutoff)

        summary = CrawlTriggerResponse(
            job_id=uuid.uuid4().hex[:12],
            status="completed" if not state.errors else "partial",
            hotlist_count=state.hotlist_count,
            rss_count=state.rss_count,
            foreign_api_count=state.foreign_count,
            duration_ms=int((time.monotonic() - started) * 1000),
            errors=list(state.errors),
        )
        state.emit(
            CrawlProgressEvent(
                stage="done",
                completed_sources=state.completed_sources,
                total_sources=max(total_sources, state.completed_sources),
                summary=summary,
            )
        )
        return summary

    def _execute_parallel_collectors(
        self,
        hotlist_collector: BaseCollector,
        rss_collector: BaseCollector,
        foreign_collectors: List[BaseCollector],
        state: _CrawlRunState,
    ) -> List[CollectedItem]:
        total_tasks = 2 + len(foreign_collectors)
        rss_items: List[CollectedItem] = []

        with ThreadPoolExecutor(max_workers=min(6, max(1, total_tasks))) as pool:
            hotlist_fut = pool.submit(self._run_hotlist_collector, hotlist_collector, state)
            rss_fut = pool.submit(self._run_rss_collector, rss_collector, state)
            foreign_futs = {
                pool.submit(self._run_collector_safe, f"foreign:{idx}", col): _foreign_source_identity(col, idx)
                for idx, col in enumerate(foreign_collectors)
            }

            pending = {hotlist_fut: "hotlist", rss_fut: "rss", **{f: "foreign" for f in foreign_futs}}
            for fut in as_completed(pending):
                kind = pending[fut]
                if kind == "hotlist":
                    fut.result()
                elif kind == "rss":
                    rss_items = fut.result()
                else:
                    sid, sname = foreign_futs[fut]
                    state.handle_foreign_collector(sid, sname, fut.result(), advance_progress=True)
        return rss_items

    def _run_hotlist_collector(self, collector: BaseCollector, state: _CrawlRunState) -> None:
        try:
            if _supports_source_callback(collector):
                collector.collect(on_source_done=state.handle_hotlist_source)  # type: ignore[call-arg]
                return
            res = collector.collect()
            err = res.errors[0] if res.errors else None
            state.handle_hotlist_source("hotlist", "国内热榜", res.items, err)
            for extra_err in res.errors[1:]:
                state.errors.append(extra_err)
        except Exception as exc:
            state.handle_hotlist_source("hotlist", "国内热榜", [], f"hotlist: {exc}")

    def _run_rss_collector(self, collector: BaseCollector, state: _CrawlRunState) -> List[CollectedItem]:
        try:
            if _supports_source_callback(collector):
                res = collector.collect(on_source_done=state.handle_rss_source)  # type: ignore[call-arg]
                return res.items
            res = collector.collect()
            err = res.errors[0] if res.errors else None
            state.handle_rss_source("rss", "RSS 订阅", res.items, err)
            for extra_err in res.errors[1:]:
                state.errors.append(extra_err)
            return res.items
        except Exception as exc:
            state.handle_rss_source("rss", "RSS 订阅", [], f"rss: {exc}")
            return []

    @staticmethod
    def _estimate_total_sources(
        hotlist_collector: BaseCollector,
        rss_collector: BaseCollector,
        foreign_collectors: List[BaseCollector],
    ) -> int:
        hotlist_cnt = (
            hotlist_collector.enabled_source_count()
            if hasattr(hotlist_collector, "enabled_source_count")
            else 1
        )
        rss_cnt = (
            rss_collector.enabled_source_count()
            if hasattr(rss_collector, "enabled_source_count")
            else 1
        )
        return max(1, int(hotlist_cnt) + int(rss_cnt) + len(foreign_collectors))

    @staticmethod
    def _run_collector_safe(label: str, collector: BaseCollector) -> CollectionResult:
        try:
            return collector.collect()
        except Exception as exc:
            return CollectionResult(errors=[f"{label}: {exc}"])

    @staticmethod
    def _run_collector_safe_fn(label: str, fn: Callable[[], CollectionResult]) -> CollectionResult:
        try:
            return fn()
        except Exception as exc:
            return CollectionResult(errors=[f"{label}: {exc}"])

    def _persist_scored_items(
        self,
        items: List[CollectedItem],
        now: datetime,
        now_iso: str,
    ) -> int:
        if not items:
            return 0

        payloads = [
            {
                "platform_id": item.platform_id,
                "platform_name": item.platform_name,
                "domain": item.domain,
                "title": item.title,
                "title_hash": item.title_hash(),
                "url": item.url,
                "mobile_url": item.mobile_url,
                "summary": item.summary,
                "extra_metrics": item.extra_metrics,
                "rank": item.rank,
                "primary_metric": item.primary_metric,
            }
            for item in items
        ]
        persisted_rows = self._repo.bulk_upsert_news_and_history(payloads, now_iso)

        platform_entries: Dict[str, List[Tuple[int, str, List[Tuple[str, int, Optional[float]]]]]] = {}
        for item_id, platform_id, first_seen, history in persisted_rows:
            platform_entries.setdefault(platform_id, []).append((item_id, first_seen, history))

        velocity_updates: List[Tuple[int, float]] = []
        for platform_id, entries in platform_entries.items():
            if platform_id in _INTERACTION_PLATFORMS:
                raw_rates = {
                    item_id: compute_raw_interaction_rate(history, first_seen, now)
                    for item_id, first_seen, history in entries
                }
                velocity_updates.extend(normalize_platform_interaction_velocities(raw_rates).items())
            else:
                for item_id, first_seen, history in entries:
                    velocity_updates.append((item_id, compute_rank_velocity(history, first_seen, now)))

        self._repo.batch_update_velocities(velocity_updates)
        return len(items)

    def _persist_rss_items(self, items: List[CollectedItem], now_iso: str) -> int:
        if not items:
            return 0
        payloads = [
            {
                "feed_id": item.platform_id,
                "feed_name": item.platform_name,
                "domain": item.domain or "其他",
                "title": item.title,
                "url": item.url,
                "guid": item.guid,
                "author": item.author,
                "summary": item.summary,
                "published_at": item.published_at,
            }
            for item in items
        ]
        return self._repo.bulk_upsert_rss_items(payloads, now_iso)

    def _make_hotlist_collector(self, cfg: Dict[str, Any]) -> BaseCollector:
        if self._hotlist_factory is not None:
            return self._hotlist_factory(cfg)
        return NewsNowCollector(cfg)

    def _make_rss_collector(self, cfg: Dict[str, Any], extra_feeds: List[Dict[str, Any]]) -> BaseCollector:
        if self._rss_factory is not None:
            return self._rss_factory(cfg, extra_feeds)
        return RssCollector(cfg, timezone_name=self._tz_name, extra_feeds=extra_feeds)

    def _make_foreign_collectors(self, cfg: Dict[str, Any]) -> List[BaseCollector]:
        if self._foreign_factory is not None:
            return self._foreign_factory(cfg)
        return [
            HackerNewsCollector(cfg),
            HuggingFaceCollector(cfg),
            GitHubTrendingCollector(cfg),
            RedditCollector(cfg),
            self._make_youtube_collector(cfg),
        ]

    def _make_youtube_collector(self, cfg: Dict[str, Any]) -> YouTubeMetricsCollector:
        if self._youtube_factory is not None:
            return self._youtube_factory(cfg)
        return YouTubeMetricsCollector(cfg)
