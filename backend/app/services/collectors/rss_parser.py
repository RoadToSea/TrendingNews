"""Standalone RSS/Atom/JSON-Feed parser, fetcher, and timezone helpers."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import html
import json
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import zoneinfo

import feedparser
import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Asia/Shanghai"


def _resolve_zone(timezone_name: str) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(timezone_name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown timezone '%s', falling back to %s", timezone_name, DEFAULT_TIMEZONE)
        return zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)


def get_configured_time(timezone_name: str = DEFAULT_TIMEZONE) -> datetime:
    """Return current timezone-aware datetime for the configured timezone.

    Args:
        timezone_name: IANA timezone name (defaults to `Asia/Shanghai`).

    Returns:
        datetime: Current timezone-aware datetime.
    """
    return datetime.now(_resolve_zone(timezone_name))


def _parse_iso_time(iso_time: str) -> datetime:
    dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def is_within_days(
    iso_time: str,
    max_days: int,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> bool:
    """Check whether an ISO timestamp falls within `max_days` of current time.

    Args:
        iso_time: ISO-8601 timestamp string.
        max_days: Maximum age in days; `<= 0` disables filtering.
        timezone_name: Target IANA timezone name.

    Returns:
        bool: True when within limit, empty, disabled, or unparseable.
    """
    if not iso_time or max_days <= 0:
        return True
    try:
        dt = _parse_iso_time(iso_time)
        now = get_configured_time(timezone_name)
        return ((now - dt).total_seconds() / 86400.0) <= max_days
    except Exception:
        return True


@dataclass
class ParsedRSSItem:
    """Parsed feed entry normalized before attaching feed metadata."""

    title: str
    url: str
    published_at: Optional[str] = None
    summary: Optional[str] = None
    author: Optional[str] = None
    guid: Optional[str] = None


@dataclass
class RSSItem:
    """Normalized RSS/Atom article entry."""

    title: str
    feed_id: str
    feed_name: str = ""
    url: str = ""
    guid: str = ""
    published_at: str = ""
    summary: str = ""
    author: str = ""
    crawl_time: str = ""
    first_time: str = ""
    last_time: str = ""
    count: int = 1


@dataclass
class RSSData:
    """Batch collection output grouped by feed ID."""

    date: str
    crawl_time: str
    items: Dict[str, List[RSSItem]]
    id_to_name: Dict[str, str] = field(default_factory=dict)
    failed_ids: List[str] = field(default_factory=list)


@dataclass
class RSSFeedConfig:
    """Configuration for a single RSS/Atom/JSON feed source."""

    id: str
    name: str
    url: str
    max_items: int = 0
    enabled: bool = True
    max_age_days: Optional[int] = None


class RSSParser:
    """Parser supporting RSS 2.0, Atom, and JSON Feed 1.1 documents."""

    def __init__(self, max_summary_length: int = 500) -> None:
        """Initialize the feed parser.

        Args:
            max_summary_length: Maximum character length retained for cleaned summaries.
        """
        self.max_summary_length = max_summary_length

    def parse(self, content: str, feed_url: str = "") -> List[ParsedRSSItem]:
        """Parse raw XML or JSON feed text into normalized items.

        Args:
            content: Raw response text.
            feed_url: Source feed URL used in error context.

        Returns:
            List[ParsedRSSItem]: Parsed feed items.

        Raises:
            ValueError: When XML or JSON feed parsing fails with no entries.
        """
        if self._is_json_feed(content):
            return self._parse_json_feed(content, feed_url)

        feed = feedparser.parse(content)
        if feed.bozo and not feed.entries:
            raise ValueError(f"RSS 解析失败 ({feed_url}): {feed.bozo_exception}")

        items: List[ParsedRSSItem] = []
        for entry in feed.entries:
            parsed = self._parse_entry(entry)
            if parsed is not None:
                items.append(parsed)
        return items

    @staticmethod
    def _is_json_feed(content: str) -> bool:
        stripped = content.strip()
        if not stripped.startswith("{"):
            return False
        try:
            data = json.loads(stripped)
            return "jsonfeed.org" in str(data.get("version", ""))
        except (json.JSONDecodeError, TypeError):
            return False

    def _parse_json_feed(self, content: str, feed_url: str = "") -> List[ParsedRSSItem]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON Feed 解析失败 ({feed_url}): {exc}") from exc

        items: List[ParsedRSSItem] = []
        for item_data in data.get("items", []) or []:
            parsed = self._parse_json_feed_item(item_data)
            if parsed is not None:
                items.append(parsed)
        return items

    def _parse_json_feed_item(self, item_data: Dict[str, Any]) -> Optional[ParsedRSSItem]:
        url = str(item_data.get("url") or item_data.get("external_url") or "")
        title = str(item_data.get("title") or "")
        if not title:
            content_text = str(item_data.get("content_text") or "")
            if content_text:
                title = content_text[:20] + ("..." if len(content_text) > 20 else "")
        title = self._clean_text(title) or url
        if not title:
            return None

        date_str = item_data.get("date_published") or item_data.get("date_modified")
        published_at = self._parse_iso_date(str(date_str)) if date_str else None
        summary = self._truncate_summary(
            item_data.get("summary")
            or item_data.get("content_text")
            or item_data.get("content_html")
            or ""
        )
        authors = item_data.get("authors") or []
        names = [a.get("name", "") for a in authors if isinstance(a, dict) and a.get("name")]
        author = ", ".join(names) if names else None
        guid = str(item_data.get("id") or url)
        return ParsedRSSItem(
            title=title,
            url=url,
            published_at=published_at,
            summary=summary,
            author=author,
            guid=guid,
        )

    @staticmethod
    def _parse_iso_date(date_str: str) -> Optional[str]:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).isoformat()
        except (ValueError, TypeError):
            return None

    def _parse_entry(self, entry: Any) -> Optional[ParsedRSSItem]:
        title = self._clean_text(str(entry.get("title", "")))
        url = self._extract_entry_url(entry)
        if not title:
            title = self._fallback_entry_title(entry, url)
        if not title:
            return None

        guid_raw = entry.get("id") or (
            entry.get("guid", {}).get("value") if isinstance(entry.get("guid"), dict) else None
        )
        return ParsedRSSItem(
            title=title,
            url=url,
            published_at=self._parse_date(entry),
            summary=self._parse_summary(entry),
            author=self._parse_author(entry),
            guid=str(guid_raw or url),
        )

    @staticmethod
    def _extract_entry_url(entry: Any) -> str:
        url = str(entry.get("link", "") or "")
        if url:
            return url
        links = entry.get("links") or []
        for link in links:
            if link.get("rel") == "alternate" or str(link.get("type", "")).startswith("text/html"):
                return str(link.get("href", "") or "")
        return str(links[0].get("href", "") or "") if links else ""

    def _fallback_entry_title(self, entry: Any, url: str) -> str:
        raw_summary = entry.get("summary") or entry.get("description") or ""
        if not raw_summary:
            content = entry.get("content")
            if content and isinstance(content, list):
                raw_summary = content[0].get("value", "")
        if raw_summary:
            cleaned = self._clean_text(str(raw_summary))
            return cleaned[:20] + "..." if len(cleaned) > 20 else cleaned
        return url

    @staticmethod
    def _clean_text(text: str) -> str:
        if not text:
            return ""
        cleaned = html.unescape(text)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _truncate_summary(self, raw_text: str) -> Optional[str]:
        if not raw_text:
            return None
        cleaned = self._clean_text(str(raw_text))
        if not cleaned:
            return None
        if len(cleaned) > self.max_summary_length:
            return cleaned[: self.max_summary_length] + "..."
        return cleaned

    @staticmethod
    def _parse_date(entry: Any) -> Optional[str]:
        date_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if date_struct:
            try:
                return datetime(*date_struct[:6]).isoformat()
            except (ValueError, TypeError):
                pass
        date_str = entry.get("published") or entry.get("updated")
        if date_str:
            for parser_fn in (
                parsedate_to_datetime,
                lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
            ):
                try:
                    return parser_fn(str(date_str)).isoformat()
                except (ValueError, TypeError):
                    pass
        return None

    def _parse_summary(self, entry: Any) -> Optional[str]:
        raw = entry.get("summary") or entry.get("description") or ""
        if not raw:
            content = entry.get("content")
            if content and isinstance(content, list):
                raw = content[0].get("value", "")
        return self._truncate_summary(str(raw))

    def _parse_author(self, entry: Any) -> Optional[str]:
        author = entry.get("author") or entry.get("dc_creator")
        if author:
            return self._clean_text(str(author))
        authors = entry.get("authors") or []
        names = [a.get("name", "") for a in authors if isinstance(a, dict) and a.get("name")]
        return ", ".join(names) if names else None


class RSSFetcher:
    """HTTP RSS/Atom/JSON-Feed fetcher using `requests.Session`."""

    def __init__(
        self,
        feeds: List[RSSFeedConfig],
        request_interval: int = 2000,
        timeout: int = 15,
        use_proxy: bool = False,
        proxy_url: str = "",
        timezone: str = DEFAULT_TIMEZONE,
        freshness_enabled: bool = True,
        default_max_age_days: int = 3,
    ) -> None:
        """Initialize the RSS fetcher.

        Args:
            feeds: Configured feeds list (only enabled entries are retained).
            request_interval: Delay between sequential feeds in milliseconds.
            timeout: HTTP request timeout in seconds.
            use_proxy: Whether to route requests through `proxy_url`.
            proxy_url: HTTP/HTTPS proxy URL.
            timezone: IANA timezone name for crawl timestamps.
            freshness_enabled: Retained for config compatibility.
            default_max_age_days: Default freshness limit in days.
        """
        self.feeds = [f for f in feeds if f.enabled]
        self.request_interval = request_interval
        self.timeout = timeout
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url
        self.timezone = timezone
        self.freshness_enabled = freshness_enabled
        self.default_max_age_days = default_max_age_days
        self.parser = RSSParser()
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "TrendRadar/2.0 RSS Reader",
                "Accept": (
                    "application/feed+json, application/json, application/rss+xml, "
                    "application/atom+xml, application/xml, text/xml, */*"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        if self.use_proxy and self.proxy_url:
            session.proxies = {"http": self.proxy_url, "https": self.proxy_url}
        return session

    def fetch_feed(self, feed: RSSFeedConfig) -> Tuple[List[RSSItem], Optional[str]]:
        """Fetch and parse a single RSS feed with a single retry on transient errors.

        Args:
            feed: Target feed configuration.

        Returns:
            Tuple[List[RSSItem], Optional[str]]: `(items, error_message_or_none)`.
        """
        try:
            response = self._get_with_retry(feed.url)
            parsed_items = self.parser.parse(response.text, feed.url)
            if feed.max_items > 0:
                parsed_items = parsed_items[: feed.max_items]

            crawl_time = get_configured_time(self.timezone).strftime("%H:%M")
            items = [
                RSSItem(
                    title=parsed.title,
                    feed_id=feed.id,
                    feed_name=feed.name,
                    url=parsed.url,
                    guid=parsed.guid or "",
                    published_at=parsed.published_at or "",
                    summary=parsed.summary or "",
                    author=parsed.author or "",
                    crawl_time=crawl_time,
                    first_time=crawl_time,
                    last_time=crawl_time,
                    count=1,
                )
                for parsed in parsed_items
            ]
            return items, None
        except requests.Timeout:
            return [], f"请求超时 ({self.timeout}s)"
        except requests.RequestException as exc:
            return [], f"请求失败: {exc}"
        except ValueError as exc:
            return [], f"解析失败: {exc}"
        except Exception as exc:
            return [], f"未知错误: {exc}"

    def _get_with_retry(self, url: str) -> requests.Response:
        for attempt in range(2):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                err_resp = exc.response
                retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError)) and not isinstance(
                    exc, requests.exceptions.SSLError
                )
                if isinstance(exc, requests.HTTPError):
                    retryable = err_resp is not None and err_resp.status_code in {408, 500, 502, 503, 504}
                if (
                    not retryable
                    or attempt == 1
                    or (err_resp is not None and "Retry-After" in err_resp.headers)
                ):
                    raise
        raise RuntimeError("Unreachable retry state")

    def fetch_all(self) -> RSSData:
        """Fetch all enabled feeds sequentially."""
        all_items: Dict[str, List[RSSItem]] = {}
        id_to_name: Dict[str, str] = {}
        failed_ids: List[str] = []
        now = get_configured_time(self.timezone)

        for idx, feed in enumerate(self.feeds):
            if idx > 0 and self.request_interval > 0:
                interval = self.request_interval / 1000.0
                time.sleep(max(0.0, interval + random.uniform(-0.2, 0.2) * interval))
            items, error = self.fetch_feed(feed)
            id_to_name[feed.id] = feed.name
            if error:
                failed_ids.append(feed.id)
            else:
                all_items[feed.id] = items

        return RSSData(
            date=now.strftime("%Y-%m-%d"),
            crawl_time=now.strftime("%H:%M"),
            items=all_items,
            id_to_name=id_to_name,
            failed_ids=failed_ids,
        )

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "RSSFetcher":
        """Build an `RSSFetcher` from a settings dictionary."""
        freshness_config = config.get("freshness_filter", {}) or {}
        freshness_enabled = bool(freshness_config.get("enabled", True))
        default_max_age_days = int(freshness_config.get("max_age_days", 3) or 0)

        feeds: List[RSSFeedConfig] = []
        for feed_cfg in config.get("feeds", []) or []:
            max_age_days = _parse_feed_max_age(feed_cfg.get("max_age_days"))
            feed = RSSFeedConfig(
                id=str(feed_cfg.get("id", "")),
                name=str(feed_cfg.get("name", "")),
                url=str(feed_cfg.get("url", "")),
                max_items=int(feed_cfg.get("max_items", 0) or 0),
                enabled=bool(feed_cfg.get("enabled", True)),
                max_age_days=max_age_days,
            )
            if feed.id and feed.url:
                feeds.append(feed)

        return cls(
            feeds=feeds,
            request_interval=int(config.get("request_interval", 2000) or 0),
            timeout=int(config.get("timeout", 15) or 15),
            use_proxy=bool(config.get("use_proxy", False)),
            proxy_url=str(config.get("proxy_url", "") or ""),
            timezone=str(config.get("timezone", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE),
            freshness_enabled=freshness_enabled,
            default_max_age_days=default_max_age_days,
        )


def _parse_feed_max_age(raw: Any) -> Optional[int]:
    if raw is None or raw == "" or isinstance(raw, bool):
        return None
    try:
        parsed = int(raw)
        return parsed if parsed >= 0 else None
    except (TypeError, ValueError):
        return None
