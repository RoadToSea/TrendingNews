"""Domestic hotlist collector and NewsNow API data fetcher."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import requests

from app.services.collectors.base import CollectedItem, CollectionResult

logger = logging.getLogger(__name__)

SourceDoneCallback = Callable[[str, str, List[CollectedItem], Optional[str]], None]


class DataFetcher:
    """HTTP client fetching ranked hotlist payloads from NewsNow-compatible endpoints."""

    DEFAULT_API_URL = "https://newsnow.busiyi.world/api/s"
    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }

    def __init__(
        self,
        proxy_url: Optional[str] = None,
        api_url: Optional[str] = None,
    ) -> None:
        """Initialize the NewsNow data fetcher.

        Args:
            proxy_url: Optional HTTP/HTTPS proxy URL.
            api_url: Optional base API URL overriding `DEFAULT_API_URL`.
        """
        self.proxy_url = proxy_url
        self.api_url = api_url or self.DEFAULT_API_URL

    @staticmethod
    def _check_domain_safety(
        items: List[Dict[str, Any]],
        expected_domain: str,
    ) -> Optional[str]:
        """Verify all item URLs use HTTPS and belong to `expected_domain` or its subdomains."""
        expected = expected_domain.lower().strip()
        if not expected:
            return None

        for item in items:
            for field in ("url", "mobileUrl"):
                url = item.get(field, "")
                if not url:
                    continue
                parsed = urlparse(url)
                if parsed.scheme != "https":
                    return f"{url} (非 HTTPS 或格式异常)"
                hostname = (parsed.hostname or "").lower()
                if hostname != expected and not hostname.endswith("." + expected):
                    return f"{hostname} (来自 {url})"
        return None

    def fetch_data(
        self,
        id_info: Union[str, Tuple[str, str]],
        max_retries: int = 2,
        min_retry_wait: int = 3,
        max_retry_wait: int = 5,
    ) -> Tuple[Optional[str], str, str]:
        """Fetch raw JSON payload text for a single platform with exponential jittered retries.

        Args:
            id_info: Platform ID or `(platform_id, alias)` tuple.
            max_retries: Maximum retry attempts after initial failure.
            min_retry_wait: Minimum base wait seconds before retrying.
            max_retry_wait: Maximum base wait seconds before retrying.

        Returns:
            Tuple[Optional[str], str, str]: `(raw_text_or_none, platform_id, alias)`.
        """
        if isinstance(id_info, tuple):
            id_value, alias = id_info
        else:
            id_value, alias = id_info, id_info

        url = f"{self.api_url}?id={id_value}&latest"
        proxies = {"http": self.proxy_url, "https": self.proxy_url} if self.proxy_url else None

        retries = 0
        while retries <= max_retries:
            try:
                response = requests.get(
                    url,
                    proxies=proxies,
                    headers=self.DEFAULT_HEADERS,
                    timeout=10,
                )
                response.raise_for_status()
                data_text = response.text
                data_json = json.loads(data_text)
                status = data_json.get("status", "未知")
                if status not in ("success", "cache"):
                    raise ValueError(f"响应状态异常: {status}")
                return data_text, id_value, alias
            except Exception as exc:
                retries += 1
                if retries <= max_retries:
                    wait_time = random.uniform(min_retry_wait, max_retry_wait) + (
                        (retries - 1) * random.uniform(1, 2)
                    )
                    logger.warning("Request %s failed (%s); retrying in %.2fs", id_value, exc, wait_time)
                    time.sleep(wait_time)
                else:
                    logger.warning("Request %s failed after retries: %s", id_value, exc)
                    return None, id_value, alias

        return None, id_value, alias


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
