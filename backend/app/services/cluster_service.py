"""Incremental cross-lingual LLM event clustering and daily hot-index computation."""

from datetime import datetime, timedelta
import json
import logging
from typing import Any, Dict, List, Optional, Set
import zoneinfo

from app.repositories.event_repo import EventRepository
from app.repositories.news_repo import NewsRepository
from app.services.ai_gateway.base import LLMGatewayError
from app.services.ai_gateway.gateway_service import AIGatewayService
from app.services.scoring_service import compute_event_hot_index
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

_DEFAULT_WEIGHTS = {"coverage": 0.35, "rank": 0.35, "persistence": 0.20, "velocity": 0.10}


class ClusterService:
    """Assigns unlinked hotlist news items to standardized cross-lingual Chinese hot events."""

    def __init__(
        self,
        event_repo: EventRepository,
        news_repo: NewsRepository,
        settings_service: SettingsService,
        gateway_service: AIGatewayService,
        timezone_name: str,
    ) -> None:
        """Initialize the clustering coordinator.

        Args:
            event_repo: Event/metric persistence repository.
            news_repo: News repository for assigning inferred domain tags.
            settings_service: Settings provider for domains and trend weights.
            gateway_service: AI gateway supplying the `event_cluster` model slot.
            timezone_name: Application timezone name.
        """
        self._events = event_repo
        self._news = news_repo
        self._settings = settings_service
        self._gateway = gateway_service
        self._tz = zoneinfo.ZoneInfo(timezone_name)
        self.last_error: Optional[str] = None

    def _now(self) -> datetime:
        return datetime.now(self._tz)

    async def run_incremental_clustering(
        self,
        metric_date: Optional[str] = None,
        batch_limit: int = 50,
    ) -> int:
        """Cluster newly collected items with LLM when bound and refresh daily event metrics.

        Args:
            metric_date: Optional target `YYYY-MM-DD` date; defaults to current date.
            batch_limit: Maximum unlinked items clustered per LLM call.

        Returns:
            int: Number of items linked to event clusters in this run.
        """
        self.last_error = None
        now = self._now()
        target_date = metric_date or now.date().isoformat()
        now_iso = now.isoformat(timespec="seconds")
        anchor_dt = (
            datetime.fromisoformat(f"{target_date}T23:59:59").replace(tzinfo=self._tz)
            if metric_date
            else now
        )
        since_iso = (anchor_dt - timedelta(hours=48)).isoformat(timespec="seconds")

        unlinked = self._events.list_unlinked_news_items(since_iso=since_iso, limit=batch_limit)
        linked_count = 0

        if unlinked:
            linked_count = await self._cluster_batch_with_llm(unlinked, target_date, anchor_dt, now_iso)

        self.recompute_daily_metrics(target_date, now_iso=now_iso)
        return linked_count

    async def _cluster_batch_with_llm(
        self,
        unlinked: List[Dict[str, Any]],
        target_date: str,
        now: datetime,
        now_iso: str,
    ) -> int:
        slot = self._gateway.find_slot_by_role("event_cluster")
        if slot is None:
            self.last_error = "事件自动归类已跳过：当前未启用支持事件归类 (event_cluster) 的 AI 模型配置"
            logger.info("Skipping LLM clustering: no enabled slot bound to 'event_cluster'")
            return 0

        since_3d = (now.date() - timedelta(days=3)).isoformat()
        recent_events = self._events.list_recent_events(since_date=since_3d)
        domains_cfg = self._settings.get_internal_section("domains")
        domain_items = domains_cfg.get("items") or []
        valid_domains = [str(d["id"]) for d in domain_items if isinstance(d, dict) and d.get("id")] or ["其他"]

        prompt = self._build_clustering_prompt(unlinked, recent_events, domain_items)
        try:
            adapter = self._gateway.build_adapter(slot)
            parsed, _ = await adapter.complete_json(
                messages=[{"role": "user", "content": prompt}],
                model=str(slot["model"]),
                system_prompt=(
                    "你是一个跨语言热点事件聚类引擎。请将同一事件的中英文与跨平台报道归并到同一事件簇，"
                    "全部输出合法 JSON 对象。"
                ),
                extra_params=dict(slot.get("extra_params") or {}),
            )
        except LLMGatewayError as exc:
            self.last_error = f"事件自动归类失败：{exc.message}"
            logger.warning("Incremental event clustering failed gracefully: %s", exc.message)
            return 0

        return self._apply_assignments(
            assignments=parsed.get("assignments") or [],
            unlinked=unlinked,
            recent_events=recent_events,
            valid_domains=set(valid_domains),
            default_date=target_date,
            now_iso=now_iso,
        )

    @staticmethod
    def _build_clustering_prompt(
        unlinked: List[Dict[str, Any]],
        recent_events: List[Dict[str, Any]],
        domain_items: List[Dict[str, Any]],
    ) -> str:
        news_payload = [
            {
                "news_id": int(item["id"]),
                "platform": str(item["platform_name"]),
                "title": str(item["title"]),
                "summary": str(item.get("raw_summary") or "")[:160],
                "date": str(item.get("last_seen_at") or "")[:10],
            }
            for item in unlinked
        ]
        events_payload = [
            {
                "event_id": int(ev["id"]),
                "canonical_title": str(ev["canonical_title"]),
                "domain": str(ev["domain"]),
                "last_seen_date": str(ev["last_seen_date"]),
            }
            for ev in recent_events[:60]
        ]
        domains_payload = [
            {"id": d.get("id"), "description": d.get("description", "")}
            for d in domain_items
            if isinstance(d, dict)
        ]

        return (
            "请为以下待归类新闻分配热点事件簇。\n"
            "规则：\n"
            "1. 若新闻与“近3天已有事件”属于同一现实事件（含中英文同源报道），请复用该 `event_id`。\n"
            "2. 若属于本批次的新事件，请将 `event_id` 设为 `null`；若多条新闻同属一个新事件，"
            "请为它们赋予完全一致的中文 `canonical_title` 和 `domain`，系统会自动合并到同一个新事件。\n"
            "3. `canonical_title`（<=28字）与 `summary`（<=80字）必须统一使用简体中文。\n"
            "4. `domain` 必须从可选领域 ID 中选择其一。\n"
            "5. 严格返回 JSON 对象：`{\"assignments\": [{\"news_id\": int, \"event_id\": int|null, "
            "\"canonical_title\": str, \"domain\": str, \"summary\": str, \"confidence\": float}]}`。\n\n"
            f"可选领域：{json.dumps(domains_payload, ensure_ascii=False)}\n"
            f"近3天已有事件：{json.dumps(events_payload, ensure_ascii=False)}\n"
            f"待归类新闻：{json.dumps(news_payload, ensure_ascii=False)}"
        )

    def _apply_assignments(
        self,
        *,
        assignments: List[Any],
        unlinked: List[Dict[str, Any]],
        recent_events: List[Dict[str, Any]],
        valid_domains: Set[str],
        default_date: str,
        now_iso: str,
    ) -> int:
        news_map = {int(item["id"]): item for item in unlinked}
        existing_ids = {int(ev["id"]) for ev in recent_events}
        created_by_title: Dict[str, int] = {}
        linked = 0

        for entry in assignments:
            if not isinstance(entry, dict):
                continue
            news_id = entry.get("news_id")
            if not isinstance(news_id, int) or news_id not in news_map:
                continue
            item = news_map[news_id]
            seen_date = str(item.get("last_seen_at") or "")[:10] or default_date
            domain = str(entry.get("domain") or "其他").strip()
            if domain not in valid_domains:
                domain = "其他"
            title_zh = str(entry.get("canonical_title") or item["title"]).strip()[:120]
            summary_zh = str(entry.get("summary") or "").strip()[:300]
            conf = float(entry.get("confidence", 0.9) or 0.9)

            raw_eid = entry.get("event_id")
            if isinstance(raw_eid, int) and raw_eid in existing_ids:
                event_id = raw_eid
                self._events.update_event_seen(
                    event_id=event_id,
                    last_seen_date=seen_date,
                    summary=summary_zh,
                    domain=domain,
                    now_iso=now_iso,
                )
            else:
                norm_key = title_zh.lower()
                if norm_key in created_by_title:
                    event_id = created_by_title[norm_key]
                    self._events.update_event_seen(
                        event_id=event_id,
                        last_seen_date=seen_date,
                        summary=summary_zh,
                        domain=domain,
                        now_iso=now_iso,
                    )
                else:
                    event_id = self._events.create_event(
                        canonical_title=title_zh or str(item["title"]),
                        domain=domain,
                        summary=summary_zh,
                        seen_date=seen_date,
                        now_iso=now_iso,
                    )
                    created_by_title[norm_key] = event_id

            self._events.link_item(
                event_id=event_id,
                source_type="hotlist",
                item_id=news_id,
                confidence=max(0.0, min(1.0, conf)),
                now_iso=now_iso,
            )
            self._news.update_news_item_domain(news_id, domain)
            linked += 1
        return linked

    def recompute_daily_metrics(
        self,
        metric_date: str,
        *,
        now_iso: Optional[str] = None,
    ) -> int:
        """Recompute composite `[0, 100]` `hot_index`, ranks, and `is_top_n` for `metric_date`.

        Args:
            metric_date: Date formatted as `YYYY-MM-DD`.
            now_iso: Optional update timestamp override.

        Returns:
            int: Number of daily event metrics written.
        """
        obs_rows = self._events.list_event_daily_observations(metric_date)
        if not obs_rows:
            return 0

        platforms_cfg = self._settings.get_internal_section("platforms")
        foreign_cfg = self._settings.get_internal_section("foreign_sources")
        trends_cfg = self._settings.get_internal_section("trends")
        total_platforms = self._count_configured_platforms(platforms_cfg, foreign_cfg)
        total_batches = self._events.count_daily_crawl_batches(metric_date)
        top_n = max(1, int(trends_cfg.get("daily_top_n", 10) or 10))
        weights = dict(trends_cfg.get("weights") or _DEFAULT_WEIGHTS)

        grouped: Dict[int, Dict[str, Any]] = {}
        for row in obs_rows:
            eid = int(row["event_id"])
            bucket = grouped.setdefault(
                eid,
                {"platforms": {}, "batches": set(), "mentions": 0, "max_vel": 0.0},
            )
            pid = str(row["platform_id"])
            rank = int(row["best_rank"])
            if pid not in bucket["platforms"] or rank < bucket["platforms"][pid]:
                bucket["platforms"][pid] = rank
            bucket["mentions"] += 1
            bucket["max_vel"] = max(bucket["max_vel"], float(row["velocity"] or 0.0))
            raw_batches = str(row.get("batch_keys") or "")
            if raw_batches:
                bucket["batches"].update(b for b in raw_batches.split(",") if b)

        scored: List[Dict[str, Any]] = []
        for eid, stats in grouped.items():
            best_ranks = list(stats["platforms"].values())
            mention_batches = max(1, len(stats["batches"]))
            hot_idx = compute_event_hot_index(
                platform_count=len(stats["platforms"]),
                total_enabled_platforms=total_platforms,
                best_ranks=best_ranks,
                mention_batches=mention_batches,
                total_daily_batches=total_batches,
                max_velocity=stats["max_vel"],
                weights=weights,
            )
            scored.append(
                {
                    "event_id": eid,
                    "hot_index": hot_idx,
                    "velocity": round(stats["max_vel"], 2),
                    "platform_count": len(stats["platforms"]),
                    "mention_count": stats["mentions"],
                }
            )

        scored.sort(key=lambda item: (-item["hot_index"], -item["velocity"], item["event_id"]))
        for idx, item in enumerate(scored, start=1):
            item["daily_rank"] = idx
            item["is_top_n"] = idx <= top_n

        ts = now_iso or self._now().isoformat(timespec="seconds")
        self._events.replace_daily_metrics(metric_date, scored, ts)
        return len(scored)

    @staticmethod
    def _count_configured_platforms(platforms_cfg: Dict[str, Any], foreign_cfg: Dict[str, Any]) -> int:
        count = 0
        if platforms_cfg.get("enabled", True):
            sources = platforms_cfg.get("sources") or []
            count += len([s for s in sources if isinstance(s, dict) and s.get("enabled", True)])
        for key in ("hackernews_enabled", "huggingface_enabled", "github_enabled", "reddit_enabled"):
            if foreign_cfg.get(key):
                count += 1
        if foreign_cfg.get("youtube_channels"):
            count += 1
        return max(1, count)