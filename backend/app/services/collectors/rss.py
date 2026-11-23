"""RSS and Atom feed collector wrapping legacy `trendradar.crawler.rss.RSSFetcher` concurrently."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

from trendradar.crawler.rss.fetcher import RSSFetcher
from trendradar.storage.base import RSSItem
from trendradar.utils.time import DEFAULT_TIMEZONE, is_within_days

from app.services.collectors.base import CollectedItem, CollectionResult

SourceDoneCallback = Callable[[str, str, List[CollectedItem], Optional[str]], None]


def _resolve_max_age_days(meta: Dict[str, Any], default_max_age: int) -> int:
    """Resolve effective max-age filter days for a feed, safely falling back on empty/invalid values."""
    raw = meta.get("max_age_days")
    if raw is None or raw == "" or isinstance(raw, bool):
        return default_max_age
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default_max_age
    return parsed if parsed >= 0 else default_max_age


class RssCollector:
    """Collects foreign media RSS, Google News topic RSS, and YouTube native Atom feeds concurrently."""

    def __init__(
        self,
        rss_config: Dict[str, Any],
        timezone_name: str = DEFAULT_TIMEZONE,
        extra_feeds: Optional[List[Dict[str, Any]]] = None,
        fetcher: Optional[RSSFetcher] = None,
        max_workers: int = 8,
    ) -> None:
        """Initialize concurrent RSS collector from stored settings.

        Args:
            rss_config: `rss` section dictionary from `app_settings`.
            timezone_name: Application timezone name.
            extra_feeds: Additional feed configs (such as YouTube channel Atom feeds).
            fetcher: Optional pre-built `RSSFetcher` for dependency injection in tests.
            max_workers: Maximum parallel threads fetching independent RSS feeds.
        """
        self._config = rss_config
        self._timezone = timezone_name
        self._injected_fetcher = fetcher
        self._max_workers = max(1, max_workers)

        combined_feeds = [
            f
            for f in (rss_config.get("feeds") or [])
            if isinstance(f, dict) and f.get("id") and f.get("url") and f.get("enabled", True)
        ]
        if extra_feeds:
            combined_feeds.extend(
                f
                for f in extra_feeds
                if isinstance(f, dict) and f.get("id") and f.get("url") and f.get("enabled", True)
            )
        self._feeds = combined_feeds
        self._feed_meta: Dict[str, Dict[str, Any]] = {str(f["id"]): f for f in combined_feeds}

    def enabled_source_count(self) -> int:
        """Return the number of enabled RSS/Atom feeds configured to fetch.

        Returns:
            int: Enabled feed count.
        """
        if not self._config.get("enabled", True):
            return 0
        if self._injected_fetcher is not None:
            return len(getattr(self._injected_fetcher, "feeds", []) or [])
        return len(self._feeds)

    @staticmethod
    def _build_fetcher(
        rss_config: Dict[str, Any],
        feeds: List[Dict[str, Any]],
        timezone_name: str,
    ) -> RSSFetcher:
        adapted = {
            "enabled": rss_config.get("enabled", True),
            "request_interval": 0,
            "timeout": rss_config.get("timeout_sec", 15),
            "use_proxy": rss_config.get("use_proxy", False),
            "proxy_url": rss_config.get("proxy_url", ""),
            "timezone": timezone_name,
            "freshness_filter": {
                "enabled": rss_config.get("freshness_enabled", True),
                "max_age_days": rss_config.get("max_age_days", 2),
            },
            "feeds": feeds,
        }
        return RSSFetcher.from_config(adapted)

    def collect(self, on_source_done: Optional[SourceDoneCallback] = None) -> CollectionResult:
        """Fetch all enabled RSS feeds concurrently and notify as each feed finishes.

        Args:
            on_source_done: Optional callback `(feed_id, feed_name, items, error)` triggered
                immediately when each feed finishes downloading and filtering.

        Returns:
            CollectionResult: Normalized RSS items and per-feed errors.
        """
        result = CollectionResult()
        if not self._config.get("enabled", True):
            return result

        if self._injected_fetcher is not None:
            return self._collect_from_injected_fetcher(self._injected_fetcher, on_source_done)

        if not self._feeds:
            return result

        freshness_enabled = bool(self._config.get("freshness_enabled", True))
        default_max_age = int(self._config.get("max_age_days", 2) or 0)
        ordered: List[Optional[Tuple[List[CollectedItem], Optional[str]]]] = [None] * len(self._feeds)
        workers = min(self._max_workers, len(self._feeds))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(self._fetch_single_feed, feed_dict): (idx, feed_dict)
                for idx, feed_dict in enumerate(self._feeds)
            }
            for fut in as_completed(future_map):
                idx, feed_dict = future_map[fut]
                feed_id = str(feed_dict["id"])
                feed_name = str(feed_dict.get("name") or feed_id)
                try:
                    _, entries, raw_err = fut.result()
                except Exception as exc:
                    entries, raw_err = [], str(exc)

                if raw_err:
                    err_msg = f"rss:{feed_id}: fetch failed"
                    ordered[idx] = ([], err_msg)
                    if on_source_done is not None:
                        on_source_done(feed_id, feed_name, [], err_msg)
                    continue

                filtered = self._filter_entries(entries, feed_dict, freshness_enabled, default_max_age)
                ordered[idx] = (filtered, None)
                if on_source_done is not None:
                    on_source_done(feed_id, feed_name, filtered, None)

        for entry in ordered:
            if entry is None:
                continue
            items, err_msg = entry
            if err_msg:
                result.errors.append(err_msg)
            else:
                result.items.extend(items)
        return result

    def _fetch_single_feed(self, feed_dict: Dict[str, Any]) -> Tuple[Dict[str, Any], List[RSSItem], Optional[str]]:
        # Construct one isolated RSSFetcher (and requests.Session) per worker to avoid cross-thread Session races.
        worker_fetcher = self._build_fetcher(self._config, [feed_dict], self._timezone)
        try:
            if not worker_fetcher.feeds:
                return feed_dict, [], "invalid feed config"
            entries, error = worker_fetcher.fetch_feed(worker_fetcher.feeds[0])
            return feed_dict, entries, error
        finally:
            worker_fetcher.session.close()

    def _collect_from_injected_fetcher(
        self,
        fetcher: RSSFetcher,
        on_source_done: Optional[SourceDoneCallback] = None,
    ) -> CollectionResult:
        result = CollectionResult()
        if not getattr(fetcher, "feeds", None):
            return result

        rss_data = fetcher.fetch_all()
        for failed_id in rss_data.failed_ids:
            err_msg = f"rss:{failed_id}: fetch failed"
            result.errors.append(err_msg)
            if on_source_done is not None:
                on_source_done(failed_id, rss_data.id_to_name.get(failed_id, failed_id), [], err_msg)

        freshness_enabled = bool(self._config.get("freshness_enabled", True))
        default_max_age = int(self._config.get("max_age_days", 2) or 0)
        for feed_id, entries in rss_data.items.items():
            meta = self._feed_meta.get(feed_id, {})
            filtered = self._filter_entries(entries, meta, freshness_enabled, default_max_age)
            result.items.extend(filtered)
            if on_source_done is not None:
                on_source_done(feed_id, rss_data.id_to_name.get(feed_id, feed_id), filtered, None)
        return result

    def _filter_entries(
        self,
        entries: List[RSSItem],
        meta: Dict[str, Any],
        freshness_enabled: bool,
        default_max_age: int,
    ) -> List[CollectedItem]:
        domain = str(meta.get("domain") or "其他")
        max_age_days = _resolve_max_age_days(meta, default_max_age)
        filtered: List[CollectedItem] = []

        for entry in entries:
            if freshness_enabled and max_age_days > 0 and entry.published_at:
                if not is_within_days(entry.published_at, max_age_days, self._timezone):
                    continue
            filtered.append(
                CollectedItem(
                    source_type="rss",
                    platform_id=entry.feed_id,
                    platform_name=entry.feed_name,
                    domain=domain,
                    title=entry.title,
                    url=entry.url,
                    guid=entry.guid,
                    author=entry.author,
                    summary=entry.summary,
                    published_at=entry.published_at,
                )
            )
        return filtered
