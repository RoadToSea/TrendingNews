"""Official & public keyless collectors for international rising communities (HN, HF, GitHub, Reddit, YouTube)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET

import httpx

from app.services.collectors.base import CollectedItem, CollectionResult

_YT_VIDEO_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_CHANNEL_ID_PATTERN = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


def extract_youtube_video_id(url: str) -> Optional[str]:
    """Extract an 11-character YouTube video ID from standard watch or short URLs.

    Args:
        url: Video URL string.

    Returns:
        Optional[str]: Extracted video ID, or None if URL does not match YouTube patterns.
    """
    if not url:
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "youtube.com" in host:
        vid = (parse_qs(parsed.query).get("v") or [""])[0]
        return vid if _YT_VIDEO_PATTERN.match(vid) else None
    if "youtu.be" in host:
        vid = parsed.path.strip("/").split("/")[0]
        return vid if _YT_VIDEO_PATTERN.match(vid) else None
    return None


def _build_httpx_client(
    config: Dict[str, Any],
    *,
    timeout: float = 15.0,
    limits: Optional[httpx.Limits] = None,
) -> httpx.Client:
    kwargs: Dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
    proxy_url = str(config.get("proxy_url") or "").strip()
    if proxy_url:
        kwargs["proxy"] = proxy_url
    if limits is not None:
        kwargs["limits"] = limits
    return httpx.Client(**kwargs)


class HackerNewsCollector:
    """Collects top stories concurrently with real score and comment counts from Firebase HN API."""

    BASE_URL = "https://hacker-news.firebaseio.com/v0"

    def __init__(
        self,
        config: Dict[str, Any],
        client: Optional[httpx.Client] = None,
        max_workers: int = 10,
    ) -> None:
        """Initialize Hacker News collector.

        Args:
            config: `foreign_sources` configuration dictionary.
            client: Optional injected `httpx.Client` for testing.
            max_workers: Maximum concurrent item requests.
        """
        self._config = config
        self._client = client
        self._max_workers = max(1, max_workers)

    def collect(self) -> CollectionResult:
        """Fetch top HN stories concurrently while preserving `topstories` ranking order.

        Returns:
            CollectionResult: Collected HN items and any HTTP error messages.
        """
        result = CollectionResult()
        if not self._config.get("hackernews_enabled", True):
            return result

        limit = max(1, int(self._config.get("hackernews_limit", 25) or 25))
        min_score = int(self._config.get("hackernews_min_score", 80) or 0)

        try:
            with self._get_client() as client:
                ids_resp = client.get(f"{self.BASE_URL}/topstories.json")
                ids_resp.raise_for_status()
                story_ids = [int(sid) for sid in (ids_resp.json() or [])[: limit * 2]]
                if not story_ids:
                    return result

                workers = min(self._max_workers, len(story_ids))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    fetched = list(pool.map(lambda sid: self._fetch_story(client, sid), story_ids))

                rank = 0
                for sid, item in zip(story_ids, fetched):
                    if rank >= limit:
                        break
                    if item is None or item.get("score", 0) < min_score:
                        continue
                    title = str(item.get("title") or "").strip()
                    if not title:
                        continue
                    rank += 1
                    score = int(item.get("score", 0))
                    comments = int(item.get("descendants", 0))
                    url = str(item.get("url") or f"https://news.ycombinator.com/item?id={sid}")
                    result.items.append(
                        CollectedItem(
                            source_type="hotlist",
                            platform_id="hackernews",
                            platform_name="Hacker News",
                            domain="科技互联网",
                            title=title,
                            url=url,
                            rank=rank,
                            primary_metric=float(score),
                            extra_metrics={"score": score, "comments": comments},
                        )
                    )
        except Exception as exc:
            result.errors.append(f"foreign:hackernews: {exc}")
        return result

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return _NoCloseClient(self._client)
        limits = httpx.Limits(max_connections=16, max_keepalive_connections=12)
        return _build_httpx_client(self._config, limits=limits)

    def _fetch_story(self, client: httpx.Client, story_id: int) -> Optional[Dict[str, Any]]:
        try:
            resp = client.get(f"{self.BASE_URL}/item/{story_id}.json")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None


class HuggingFaceCollector:
    """Collects daily papers and trending models concurrently from Hugging Face public APIs."""

    PAPERS_URL = "https://huggingface.co/api/daily_papers"
    MODELS_URL = "https://huggingface.co/api/models"

    def __init__(
        self,
        config: Dict[str, Any],
        client: Optional[httpx.Client] = None,
    ) -> None:
        """Initialize Hugging Face collector.

        Args:
            config: `foreign_sources` configuration dictionary.
            client: Optional injected `httpx.Client` for testing.
        """
        self._config = config
        self._client = client

    def collect(self) -> CollectionResult:
        """Fetch trending Hugging Face daily papers and models in parallel.

        Returns:
            CollectionResult: Normalized items and non-fatal error messages.
        """
        result = CollectionResult()
        if not self._config.get("huggingface_enabled", True):
            return result

        limit = max(1, int(self._config.get("huggingface_limit", 20) or 20))
        half = max(1, limit // 2)
        model_limit = limit - half

        with self._get_client() as client:
            with ThreadPoolExecutor(max_workers=2) as pool:
                papers_fut = pool.submit(self._fetch_papers, client, half)
                models_fut = pool.submit(self._fetch_models, client, model_limit)
                paper_items, paper_err = papers_fut.result()
                model_items, model_err = models_fut.result()

        if paper_err:
            result.errors.append(paper_err)
        if model_err:
            result.errors.append(model_err)

        offset = len(paper_items)
        for idx, item in enumerate(model_items, start=1):
            item.rank = offset + idx
        result.items.extend(paper_items)
        result.items.extend(model_items)
        return result

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return _NoCloseClient(self._client)
        return _build_httpx_client(self._config)

    def _fetch_papers(
        self,
        client: httpx.Client,
        limit: int,
    ) -> Tuple[List[CollectedItem], Optional[str]]:
        items: List[CollectedItem] = []
        try:
            resp = client.get(self.PAPERS_URL, params={"limit": limit})
            resp.raise_for_status()
            for rank, row in enumerate((resp.json() or [])[:limit], start=1):
                paper = row.get("paper") if isinstance(row.get("paper"), dict) else row
                paper_id = str(paper.get("id") or "")
                title = str(row.get("title") or paper.get("title") or "").strip()
                if not title or not paper_id:
                    continue
                upvotes = int(paper.get("upvotes") or row.get("upvotes") or 0)
                summary = str(paper.get("summary") or "").strip()
                items.append(
                    CollectedItem(
                        source_type="hotlist",
                        platform_id="huggingface",
                        platform_name="Hugging Face",
                        domain="AI大模型",
                        title=f"[Paper] {title}",
                        url=f"https://huggingface.co/papers/{paper_id}",
                        rank=rank,
                        summary=summary[:500],
                        primary_metric=float(upvotes),
                        extra_metrics={"upvotes": upvotes},
                    )
                )
            return items, None
        except Exception as exc:
            return items, f"foreign:huggingface_papers: {exc}"

    def _fetch_models(
        self,
        client: httpx.Client,
        limit: int,
    ) -> Tuple[List[CollectedItem], Optional[str]]:
        if limit <= 0:
            return [], None
        items: List[CollectedItem] = []
        try:
            resp = client.get(
                self.MODELS_URL,
                params={"sort": "likes7d", "direction": -1, "limit": limit},
            )
            resp.raise_for_status()
            for idx, row in enumerate((resp.json() or [])[:limit], start=1):
                model_id = str(row.get("id") or "").strip()
                if not model_id:
                    continue
                likes = int(row.get("likes") or 0)
                downloads = int(row.get("downloads") or 0)
                items.append(
                    CollectedItem(
                        source_type="hotlist",
                        platform_id="huggingface",
                        platform_name="Hugging Face",
                        domain="AI大模型",
                        title=f"[Model] {model_id}",
                        url=f"https://huggingface.co/{model_id}",
                        rank=idx,
                        primary_metric=float(likes),
                        extra_metrics={"likes": likes, "downloads": downloads},
                    )
                )
            return items, None
        except Exception as exc:
            return items, f"foreign:huggingface_models: {exc}"


class GitHubTrendingCollector:
    """Collects fast-growing repositories from the official GitHub Search API."""

    SEARCH_URL = "https://api.github.com/search/repositories"

    def __init__(
        self,
        config: Dict[str, Any],
        client: Optional[httpx.Client] = None,
    ) -> None:
        """Initialize GitHub Search trending collector.

        Args:
            config: Decrypted `foreign_sources` configuration dictionary.
            client: Optional injected `httpx.Client` for testing.
        """
        self._config = config
        self._client = client

    def collect(self) -> CollectionResult:
        """Fetch recently created repositories with rapid star growth.

        Returns:
            CollectionResult: Collected repositories and any API errors.
        """
        result = CollectionResult()
        if not self._config.get("github_enabled", True):
            return result

        limit = max(1, int(self._config.get("github_limit", 20) or 20))
        min_stars = int(self._config.get("github_min_stars", 50) or 0)
        since_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "TrendRadar/1.0"}
        token = str(self._config.get("github_token") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            with self._get_client() as client:
                resp = client.get(
                    self.SEARCH_URL,
                    headers=headers,
                    params={
                        "q": f"created:>{since_date} stars:>={min_stars}",
                        "sort": "stars",
                        "order": "desc",
                        "per_page": limit,
                    },
                )
                resp.raise_for_status()
                items = (resp.json() or {}).get("items") or []
                for rank, repo in enumerate(items[:limit], start=1):
                    full_name = str(repo.get("full_name") or "").strip()
                    if not full_name:
                        continue
                    stars = int(repo.get("stargazers_count") or 0)
                    forks = int(repo.get("forks_count") or 0)
                    desc = str(repo.get("description") or "").strip()
                    lang = str(repo.get("language") or "")
                    result.items.append(
                        CollectedItem(
                            source_type="hotlist",
                            platform_id="github",
                            platform_name="GitHub Trending",
                            domain="科技互联网",
                            title=f"{full_name}: {desc}" if desc else full_name,
                            url=str(repo.get("html_url") or f"https://github.com/{full_name}"),
                            rank=rank,
                            summary=desc,
                            primary_metric=float(stars),
                            extra_metrics={"stars": stars, "forks": forks, "language": lang},
                        )
                    )
        except Exception as exc:
            result.errors.append(f"foreign:github: {exc}")
        return result

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return _NoCloseClient(self._client)
        return _build_httpx_client(self._config)


class RedditCollector:
    """Collects rising and hot posts from public subreddit `.json` endpoints without OAuth."""

    BASE_URL = "https://www.reddit.com"

    def __init__(
        self,
        config: Dict[str, Any],
        client: Optional[httpx.Client] = None,
        max_workers: int = 2,
    ) -> None:
        """Initialize keyless Reddit `.json` collector.

        Args:
            config: `foreign_sources` configuration dictionary.
            client: Optional injected `httpx.Client` for testing.
            max_workers: Bounded concurrent request workers (kept gentle to avoid 429).
        """
        self._config = config
        self._client = client
        self._max_workers = max(1, max_workers)

    @staticmethod
    def normalize_subreddit(raw: str) -> str:
        """Extract clean subreddit name from raw token, `r/name`, or full Reddit URL.

        Args:
            raw: Subreddit name or full URL string.

        Returns:
            str: Clean subreddit identifier without `r/` prefix.
        """
        val = str(raw or "").strip().rstrip("/")
        if not val:
            return ""
        if "reddit.com/" in val:
            match = re.search(r"/r/([A-Za-z0-9_]+)", val)
            return match.group(1) if match else ""
        return re.sub(r"^/?r/", "", val)

    def collect(self) -> CollectionResult:
        """Fetch public `.json` listings for configured subreddits concurrently without OAuth.

        Returns:
            CollectionResult: Collected Reddit posts and error diagnostics.
        """
        result = CollectionResult()
        if not self._config.get("reddit_enabled", False):
            return result

        subreddits = [
            name
            for raw in (self._config.get("reddit_subreddits") or [])
            if (name := self.normalize_subreddit(str(raw)))
        ]
        if not subreddits:
            return result

        user_agent = str(
            self._config.get("reddit_user_agent") or "TrendRadar/1.0 (personal self-hosted reader)"
        )
        min_ups = int(self._config.get("reddit_min_ups", 100) or 0)
        headers = {"User-Agent": user_agent, "Accept": "application/json"}

        try:
            with self._get_client() as client:
                tasks = [(sub, mode) for sub in subreddits for mode in ("rising", "hot")]
                workers = min(self._max_workers, len(tasks))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    pages = list(
                        pool.map(
                            lambda task: self._fetch_feed_json(client, headers, task[0], task[1], min_ups),
                            tasks,
                        )
                    )

                seen_urls: set[str] = set()
                rank = 0
                for page_items, page_err in pages:
                    if page_err:
                        result.errors.append(page_err)
                        continue
                    for item in page_items:
                        if item.url in seen_urls:
                            continue
                        seen_urls.add(item.url)
                        rank += 1
                        item.rank = rank
                        result.items.append(item)
        except Exception as exc:
            result.errors.append(f"foreign:reddit: {exc}")
        return result

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return _NoCloseClient(self._client)
        limits = httpx.Limits(max_connections=6, max_keepalive_connections=4)
        return _build_httpx_client(self._config, limits=limits)

    def _fetch_feed_json(
        self,
        client: httpx.Client,
        headers: Dict[str, str],
        subreddit: str,
        feed_mode: str,
        min_ups: int,
    ) -> Tuple[List[CollectedItem], Optional[str]]:
        collected: List[CollectedItem] = []
        try:
            resp = client.get(
                f"{self.BASE_URL}/r/{subreddit}/{feed_mode}.json",
                headers=headers,
                params={"limit": 15, "raw_json": 1},
            )
            resp.raise_for_status()
            children = ((resp.json() or {}).get("data") or {}).get("children") or []
            for child in children:
                post = child.get("data") or {}
                ups = int(post.get("ups") or 0)
                if feed_mode == "hot" and ups < min_ups:
                    continue
                permalink = str(post.get("permalink") or "")
                post_url = f"https://www.reddit.com{permalink}" if permalink else str(post.get("url") or "")
                title = str(post.get("title") or "").strip()
                if not title or not post_url:
                    continue
                comments = int(post.get("num_comments") or 0)
                collected.append(
                    CollectedItem(
                        source_type="hotlist",
                        platform_id="reddit",
                        platform_name="Reddit",
                        domain="",
                        title=f"[r/{subreddit}] {title}",
                        url=post_url,
                        rank=0,
                        summary=str(post.get("selftext") or "")[:400],
                        primary_metric=float(ups),
                        extra_metrics={"ups": ups, "comments": comments, "subreddit": subreddit},
                    )
                )
            return collected, None
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            hint = "（可在海外源配置代理 URL）" if code in (403, 429) else ""
            return [], f"foreign:reddit:{subreddit}/{feed_mode}: HTTP {code}{hint}"
        except Exception as exc:
            return [], f"foreign:reddit:{subreddit}/{feed_mode}: {exc}"


class YouTubeMetricsCollector:
    """Direct keyless YouTube collector parsing public Atom feeds (`feeds/videos.xml`) and `@handle` pages."""

    FEED_URL = "https://www.youtube.com/feeds/videos.xml"
    VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

    def __init__(
        self,
        config: Dict[str, Any],
        client: Optional[httpx.Client] = None,
        max_workers: int = 4,
    ) -> None:
        """Initialize keyless YouTube direct collector.

        Args:
            config: `foreign_sources` configuration dictionary.
            client: Optional injected `httpx.Client` for testing.
            max_workers: Concurrent channel feed fetch limit.
        """
        self._config = config
        self._client = client
        self._max_workers = max(1, max_workers)

    def collect(self) -> CollectionResult:
        """Fetch latest videos directly from configured YouTube channels without any API key.

        Returns:
            CollectionResult: Video items with views/likes extracted from YouTube Atom XML.
        """
        result = CollectionResult()
        if not self._config.get("youtube_enabled", True):
            return result

        specs = self._parse_channel_specs()
        if not specs:
            return result

        raw_videos: List[Tuple[int, int, CollectedItem]] = []
        with self._get_client() as client:
            workers = min(self._max_workers, len(specs))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                per_channel = list(pool.map(lambda sp: self._collect_single_channel(client, sp), specs))

        for items, err in per_channel:
            if err:
                result.errors.append(err)
            for views, likes, item in items:
                raw_videos.append((views, likes, item))

        raw_videos.sort(key=lambda entry: entry[0], reverse=True)
        for rank, (_, _, item) in enumerate(raw_videos, start=1):
            item.rank = rank
            result.items.append(item)
        return result

    def _parse_channel_specs(self) -> List[Tuple[str, str, str]]:
        specs: List[Tuple[str, str, str]] = []
        for entry in self._config.get("youtube_channels") or []:
            if isinstance(entry, str):
                ref = entry.strip()
                if ref:
                    specs.append((ref, ref, "科技互联网"))
            elif isinstance(entry, dict) and entry.get("enabled", True):
                ref = str(entry.get("channel_id") or entry.get("url") or entry.get("handle") or "").strip()
                if ref:
                    name = str(entry.get("name") or ref)
                    domain = str(entry.get("domain") or "科技互联网")
                    specs.append((ref, name, domain))
        return specs

    def _collect_single_channel(
        self,
        client: httpx.Client,
        spec: Tuple[str, str, str],
    ) -> Tuple[List[Tuple[int, int, CollectedItem]], Optional[str]]:
        ref, fallback_name, domain = spec
        try:
            channel_id = self._resolve_channel_id(client, ref)
            if not channel_id:
                return [], f"foreign:youtube:{ref}: 无法解析频道 UC ID"
            resp = client.get(
                self.FEED_URL,
                params={"channel_id": channel_id},
                headers={"User-Agent": "TrendRadar/1.0"},
            )
            resp.raise_for_status()
            parsed = self._parse_atom_feed(resp.text, fallback_name, domain)
            return parsed, None
        except Exception as exc:
            return [], f"foreign:youtube:{ref}: {exc}"

    @staticmethod
    def _resolve_channel_id(client: httpx.Client, ref: str) -> Optional[str]:
        cleaned = ref.strip().rstrip("/")
        if _YT_CHANNEL_ID_PATTERN.match(cleaned):
            return cleaned
        m_path = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})", cleaned)
        if m_path:
            return m_path.group(1)

        page_url = cleaned if cleaned.startswith("http") else f"https://www.youtube.com/{cleaned.lstrip('/')}"
        resp = client.get(page_url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"})
        resp.raise_for_status()
        for pat in (
            r'"channelId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"',
            r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"',
            r'https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})',
        ):
            hit = re.search(pat, resp.text)
            if hit:
                return hit.group(1)
        return None

    @staticmethod
    def _parse_atom_feed(
        xml_text: str,
        fallback_name: str,
        domain: str,
    ) -> List[Tuple[int, int, CollectedItem]]:
        root = ET.fromstring(xml_text)
        feed_title = (root.findtext("atom:title", default="", namespaces=_ATOM_NS) or "").strip() or fallback_name
        results: List[Tuple[int, int, CollectedItem]] = []

        for entry in root.findall("atom:entry", _ATOM_NS)[:15]:
            title = (entry.findtext("atom:title", default="", namespaces=_ATOM_NS) or "").strip()
            link_el = entry.find("atom:link", _ATOM_NS)
            video_url = str(link_el.attrib.get("href") or "") if link_el is not None else ""
            if not title or not video_url:
                continue

            author_name = (
                entry.findtext("atom:author/atom:name", default="", namespaces=_ATOM_NS) or feed_title
            ).strip()
            published = (entry.findtext("atom:published", default="", namespaces=_ATOM_NS) or "").strip()
            desc = (
                entry.findtext("media:group/media:description", default="", namespaces=_ATOM_NS) or ""
            ).strip()

            stats_el = entry.find("media:group/media:community/media:statistics", _ATOM_NS)
            rating_el = entry.find("media:group/media:community/media:starRating", _ATOM_NS)
            views = int(stats_el.attrib.get("views", 0)) if stats_el is not None else 0
            likes = int(rating_el.attrib.get("count", 0)) if rating_el is not None else 0

            results.append(
                (
                    views,
                    likes,
                    CollectedItem(
                        source_type="hotlist",
                        platform_id="youtube",
                        platform_name="YouTube",
                        domain=domain,
                        title=f"[{author_name}] {title}",
                        url=video_url,
                        rank=0,
                        summary=desc[:400],
                        published_at=published,
                        primary_metric=float(views),
                        extra_metrics={"views": views, "likes": likes, "channel": author_name},
                    ),
                )
            )
        return results

    def build_channel_rss_feeds(self) -> List[Dict[str, Any]]:
        """Build Atom RSS feed definitions for dict-formatted channels with explicit `UC...` IDs."""
        feeds: List[Dict[str, Any]] = []
        for ch in self._config.get("youtube_channels") or []:
            if not isinstance(ch, dict) or not ch.get("enabled", True):
                continue
            channel_id = str(ch.get("channel_id") or "").strip()
            if not _YT_CHANNEL_ID_PATTERN.match(channel_id):
                continue
            feeds.append(
                {
                    "id": f"yt-{channel_id}",
                    "name": str(ch.get("name") or channel_id),
                    "url": f"{self.FEED_URL}?channel_id={channel_id}",
                    "domain": str(ch.get("domain") or "科技互联网"),
                    "enabled": True,
                    "max_age_days": int(ch.get("max_age_days", 7)),
                }
            )
        return feeds

    def collect_from_rss_items(self, rss_items: List[CollectedItem]) -> CollectionResult:
        """Enrich YouTube RSS videos via Data API v3 when `youtube_api_key` is optionally configured."""
        result = CollectionResult()
        api_key = str(self._config.get("youtube_api_key") or "").strip()
        if not api_key:
            return result

        video_entries: List[tuple[str, CollectedItem]] = []
        for item in rss_items:
            vid = extract_youtube_video_id(item.url)
            if vid:
                video_entries.append((vid, item))
        if not video_entries:
            return result

        stats_map = self._fetch_video_statistics(api_key, [v for v, _ in video_entries[:50]], result)
        ranked = []
        for vid, src in video_entries:
            stat = stats_map.get(vid)
            if not stat:
                continue
            views = int(stat.get("viewCount") or 0)
            likes = int(stat.get("likeCount") or 0)
            comments = int(stat.get("commentCount") or 0)
            ranked.append((views, likes, comments, src))

        ranked.sort(key=lambda entry: entry[0], reverse=True)
        for rank, (views, likes, comments, src) in enumerate(ranked, start=1):
            result.items.append(
                CollectedItem(
                    source_type="hotlist",
                    platform_id="youtube",
                    platform_name="YouTube",
                    domain=src.domain or "科技互联网",
                    title=f"[{src.platform_name}] {src.title}",
                    url=src.url,
                    rank=rank,
                    summary=src.summary[:400],
                    primary_metric=float(views),
                    extra_metrics={"views": views, "likes": likes, "comments": comments},
                )
            )
        return result

    def _fetch_video_statistics(
        self,
        api_key: str,
        video_ids: List[str],
        result: CollectionResult,
    ) -> Dict[str, Dict[str, Any]]:
        try:
            with self._get_client() as client:
                resp = client.get(
                    self.VIDEOS_URL,
                    params={
                        "part": "statistics",
                        "id": ",".join(video_ids),
                        "key": api_key,
                    },
                )
                resp.raise_for_status()
                items = (resp.json() or {}).get("items") or []
                return {str(it["id"]): (it.get("statistics") or {}) for it in items if it.get("id")}
        except Exception as exc:
            result.errors.append(f"foreign:youtube: {exc}")
            return {}

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return _NoCloseClient(self._client)
        return _build_httpx_client(self._config)


YouTubeDirectCollector = YouTubeMetricsCollector


class _NoCloseClient:
    """Context wrapper keeping an injected `httpx.Client` open across calls in tests."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def __enter__(self) -> httpx.Client:
        return self._client

    def __exit__(self, exc_type, exc, tb) -> None:
        return None
