"""Domestic hotlist collector adapter wrapping legacy `trendradar.crawler.DataFetcher`."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from trendradar.crawler.fetcher import DataFetcher

from app.services.collectors.base import CollectedItem, CollectionResult

SourceDoneCallback = Callable[[str, str, List[CollectedItem], Optional[str]], None]


class NewsNowCollector:
    """Collects ranked hotlist items concurrently from NewsNow-compatible `/api/s` endpoints."""

    def __init__(
        self,
        platforms_config: Dict[str, Any],
        fetcher: Optional[DataFetcher] = None,
        max_workers: int = 4,
    ) -> None:
        """Initialize the NewsNow hotlist collector.

        Args:
            platforms_config: Decrypted `platforms` section from `app_settings`.
            fetcher: Optional pre-built `DataFetcher` instance for dependency injection.
            max_workers: Bounded concurrent worker count to speed up crawling politely.
        """
        self._config = platforms_config
        proxy_url = str(platforms_config.get("proxy_url", "") or "") if platforms_config.get("use_proxy") else None
        api_url = str(platforms_config.get("api_url", "") or "") or None
        self._fetcher = fetcher or DataFetcher(proxy_url=proxy_url, api_url=api_url)
        self._max_workers = max(1, max_workers)

    def _enabled_sources(self) -> List[Dict[str, Any]]:
        if not self._config.get("enabled", True):
            return []
        return [
            s
            for s in (self._config.get("sources") or [])
            if isinstance(s, dict) and s.get("enabled", True) and str(s.get("id", "")).strip()
        ]

    def enabled_source_count(self) -> int:
        """Return the number of enabled valid domestic hotlist sources.

        Returns:
            int: Active platform count.
        """
        return len(self._enabled_sources())

    def collect(self, on_source_done: Optional[SourceDoneCallback] = None) -> CollectionResult:
        """Fetch all enabled domestic hotlist platforms concurrently and notify per source.

        Args:
            on_source_done: Optional callback `(source_id, source_name, items, error)` invoked
                immediately as each platform finishes fetching.

        Returns:
            CollectionResult: Normalized hotlist items and per-platform error messages.
        """
        result = CollectionResult()
        sources = self._enabled_sources()
        if not sources:
            return result

        ordered: List[Optional[Tuple[List[CollectedItem], Optional[str]]]] = [None] * len(sources)
        workers = min(self._max_workers, len(sources))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(self._fetch_single_source, source): (idx, source)
                for idx, source in enumerate(sources)
            }
            for fut in as_completed(future_map):
                idx, source = future_map[fut]
                sid = str(source.get("id", "")).strip()
                sname = str(source.get("name") or sid)
                try:
                    items, error = fut.result()
                except Exception as exc:
                    items, error = [], f"hotlist:{sid}: {exc}"
                ordered[idx] = (items, error)
                if on_source_done is not None:
                    on_source_done(sid, sname, items, error)

        for entry in ordered:
            if entry is None:
                continue
            items, error = entry
            if error:
                result.errors.append(error)
            result.items.extend(items)
        return result

    def _fetch_single_source(
        self,
        source: Dict[str, Any],
    ) -> Tuple[List[CollectedItem], Optional[str]]:
        source_id = str(source.get("id", "")).strip()
        source_name = str(source.get("name") or source_id)
        expected_domain = str(source.get("expected_domain") or "").strip()

        raw_text, _, _ = self._fetcher.fetch_data((source_id, source_name))
        if not raw_text:
            return [], f"hotlist:{source_id}: fetch failed"

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            return [], f"hotlist:{source_id}: invalid JSON ({exc})"

        raw_items = payload.get("items") or []
        if expected_domain:
            bad_reason = self._fetcher._check_domain_safety(raw_items, expected_domain)
            if bad_reason:
                return [], f"hotlist:{source_id}: domain safety rejected ({bad_reason})"

        return self._convert_items(source_id, source_name, raw_items), None

    @staticmethod
    def _convert_items(
        source_id: str,
        source_name: str,
        raw_items: List[Dict[str, Any]],
    ) -> List[CollectedItem]:
        collected: List[CollectedItem] = []
        for rank, item in enumerate(raw_items, start=1):
            title = item.get("title")
            if title is None or isinstance(title, float) or not str(title).strip():
                continue
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            extra_metrics: Dict[str, Any] = {}
            if extra.get("info"):
                extra_metrics["info"] = str(extra["info"])
            summary = str(extra.get("hover") or "").strip()
            collected.append(
                CollectedItem(
                    source_type="hotlist",
                    platform_id=source_id,
                    platform_name=source_name,
                    title=str(title).strip(),
                    url=str(item.get("url") or ""),
                    mobile_url=str(item.get("mobileUrl") or ""),
                    rank=rank,
                    summary=summary,
                    extra_metrics=extra_metrics,
                )
            )
        return collected
