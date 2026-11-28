"""Tests for domestic hotlist, RSS, foreign open API collectors, and CrawlService."""

import json
from pathlib import Path
from typing import Any, Dict, List

import httpx

from app.config import Settings
from app.repositories.db import Database
from app.repositories.news_repo import NewsRepository
from app.repositories.settings_repo import SettingsRepository
from app.security import SecretCipher
from app.services.collectors.base import CollectedItem, CollectionResult
from app.services.collectors.foreign_apis import (
    GitHubTrendingCollector,
    HackerNewsCollector,
    HuggingFaceCollector,
    RedditCollector,
    YouTubeMetricsCollector,
)
from app.services.collectors.newsnow import NewsNowCollector
from app.services.collectors.rss import RssCollector
from app.services.collectors.rss_parser import RSSData, RSSItem
from app.services.crawl_service import CrawlService
from app.services.settings_service import SettingsService


class _FakeDataFetcher:
    def fetch_data(self, id_info):
        sid = id_info[0] if isinstance(id_info, tuple) else id_info
        if sid == "bad-domain":
            payload = {
                "status": "success",
                "items": [{"title": "Hijacked", "url": "https://evil.example.com/1"}],
            }
            return json.dumps(payload), sid, sid
        payload = {
            "status": "success",
            "items": [
                {
                    "title": "国产算力芯片新突破",
                    "url": "https://www.zhihu.com/question/999",
                    "mobileUrl": "https://m.zhihu.com/question/999",
                    "extra": {"info": "420万热度", "hover": "摘要内容"},
                }
            ],
        }
        return json.dumps(payload), sid, sid

    @staticmethod
    def _check_domain_safety(items, expected_domain):
        from app.services.collectors.newsnow import DataFetcher
        return DataFetcher._check_domain_safety(items, expected_domain)


class _FakeRSSFetcher:
    feeds = ["dummy"]

    def fetch_all(self) -> RSSData:
        return RSSData(
            date="2026-11-22",
            crawl_time="22:00",
            items={
                "yt-UC123": [
                    RSSItem(
                        title="AI Agents Explained",
                        feed_id="yt-UC123",
                        feed_name="TechChannel",
                        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                        guid="yt:video:dQw4w9WgXcQ",
                        published_at="",
                        summary="Deep dive into agents.",
                    )
                ]
            },
            id_to_name={"yt-UC123": "TechChannel"},
            failed_ids=[],
        )


def test_newsnow_collector_preserves_extra_and_blocks_unsafe_domain() -> None:
    collector = NewsNowCollector(
        platforms_config={
            "enabled": True,
            "request_interval_ms": 0,
            "sources": [
                {"id": "zhihu", "name": "知乎", "expected_domain": "zhihu.com"},
                {"id": "bad-domain", "name": "坏源", "expected_domain": "baidu.com"},
            ],
        },
        fetcher=_FakeDataFetcher(),
    )
    res = collector.collect()
    assert len(res.items) == 1
    assert res.items[0].title == "国产算力芯片新突破"
    assert res.items[0].extra_metrics["info"] == "420万热度"
    assert res.items[0].summary == "摘要内容"
    assert len(res.errors) == 1
    assert "domain safety rejected" in res.errors[0]


def test_foreign_api_collectors_with_mock_transport() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "topstories.json" in url:
            return httpx.Response(200, json=[101, 102])
        if "/item/101.json" in url:
            return httpx.Response(
                200,
                json={"id": 101, "title": "Show HN: SQLite Sync", "score": 250, "descendants": 44},
            )
        if "/item/102.json" in url:
            return httpx.Response(200, json={"id": 102, "title": "Low score", "score": 5})
        if "daily_papers" in url:
            return httpx.Response(
                200,
                json=[{"paper": {"id": "2611.0001", "title": "Paper X", "upvotes": 95, "summary": "S"}}],
            )
        if "huggingface.co/api/models" in url:
            return httpx.Response(200, json=[{"id": "org/model-a", "likes": 320, "downloads": 9000}])
        if "api.github.com/search/repositories" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "full_name": "acme/radar",
                            "html_url": "https://github.com/acme/radar",
                            "stargazers_count": 640,
                            "forks_count": 50,
                            "description": "Fast radar",
                            "language": "Python",
                        }
                    ]
                },
            )
        if "reddit.com/r/LocalLLaMA/" in url and ".json" in url:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "title": "New 32B quant release",
                                    "permalink": "/r/LocalLLaMA/comments/abc/new_32b/",
                                    "ups": 420,
                                    "num_comments": 65,
                                    "selftext": "Benchmarks inside",
                                }
                            }
                        ]
                    }
                },
            )
        if "googleapis.com/youtube/v3/videos" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "dQw4w9WgXcQ",
                            "statistics": {"viewCount": "185000", "likeCount": "9200", "commentCount": "410"},
                        }
                    ]
                },
            )
        return httpx.Response(404)

    mock_client = httpx.Client(transport=httpx.MockTransport(_handler))
    cfg: Dict[str, Any] = {
        "hackernews_enabled": True,
        "hackernews_min_score": 80,
        "hackernews_limit": 10,
        "huggingface_enabled": True,
        "huggingface_limit": 4,
        "github_enabled": True,
        "github_min_stars": 50,
        "github_limit": 10,
        "reddit_enabled": True,
        "reddit_subreddits": ["https://www.reddit.com/r/LocalLLaMA/"],
        "reddit_min_ups": 100,
        "youtube_api_key": "yt-key",
    }

    hn = HackerNewsCollector(cfg, client=mock_client).collect()
    assert len(hn.items) == 1
    assert hn.items[0].primary_metric == 250.0

    hf = HuggingFaceCollector(cfg, client=mock_client).collect()
    assert len(hf.items) == 2

    gh = GitHubTrendingCollector(cfg, client=mock_client).collect()
    assert len(gh.items) == 1
    assert gh.items[0].extra_metrics["stars"] == 640

    rd = RedditCollector(cfg, client=mock_client).collect()
    assert len(rd.items) == 1
    assert rd.items[0].extra_metrics["ups"] == 420

    rss_res = RssCollector({"enabled": True}, fetcher=_FakeRSSFetcher()).collect()
    assert len(rss_res.items) == 1
    yt = YouTubeMetricsCollector(cfg, client=mock_client).collect_from_rss_items(rss_res.items)
    assert len(yt.items) == 1
    assert yt.items[0].primary_metric == 185000.0


def test_crawl_service_persists_all_sources_and_computes_velocities(tmp_path: Path) -> None:
    db = Database(tmp_path / "crawl.db")
    db.init_schema()
    news_repo = NewsRepository(db)
    settings_repo = SettingsRepository(db)
    cipher = SecretCipher("crawl-secret")
    settings_svc = SettingsService(settings_repo, cipher, "Asia/Shanghai")
    for sec in ("platforms", "rss", "foreign_sources", "schedule"):
        settings_repo.upsert_section(sec, {"enabled": True}, "2026-11-22T00:00:00+08:00")

    class _StubCollector:
        def __init__(self, items: List[CollectedItem]):
            self._items = items

        def collect(self) -> CollectionResult:
            return CollectionResult(items=self._items, errors=[])

    crawl = CrawlService(
        settings_service=settings_svc,
        news_repo=news_repo,
        timezone_name="Asia/Shanghai",
        hotlist_collector_factory=lambda _: _StubCollector(
            [
                CollectedItem(
                    source_type="hotlist",
                    platform_id="weibo",
                    platform_name="微博",
                    title="突发科技突破",
                    url="https://weibo.com/1",
                    rank=2,
                )
            ]
        ),
        rss_collector_factory=lambda _, __: _StubCollector(
            [
                CollectedItem(
                    source_type="rss",
                    platform_id="bbc-world",
                    platform_name="BBC World",
                    domain="国际地缘",
                    title="Global Summit Opens",
                    url="https://bbc.com/news/1",
                )
            ]
        ),
        foreign_collectors_factory=lambda _: [
            _StubCollector(
                [
                    CollectedItem(
                        source_type="hotlist",
                        platform_id="hackernews",
                        platform_name="Hacker News",
                        domain="科技互联网",
                        title="Open Weights Model",
                        url="https://news.ycombinator.com/item?id=1",
                        rank=1,
                        primary_metric=320.0,
                        extra_metrics={"score": 320, "comments": 80},
                    )
                ]
            )
        ],
    )

    summary = crawl.run_once()
    assert summary.status == "completed"
    assert summary.hotlist_count == 1
    assert summary.rss_count == 1
    assert summary.foreign_api_count == 1

    hotlist = news_repo.list_hotlist()
    assert len(hotlist) == 2
    rising = news_repo.list_rising(since_iso="2020-01-01T00:00:00")
    assert len(rising) == 2
    rss_items = news_repo.list_rss()
    assert len(rss_items) == 1


def test_concurrent_crawl_runs_collectors_in_parallel_and_blocks_overlap(tmp_path: Path) -> None:
    import threading
    import time
    import pytest
    from app.services.crawl_service import CrawlAlreadyRunningError

    db = Database(tmp_path / "parallel_crawl.db")
    db.init_schema()
    news_repo = NewsRepository(db)
    settings_repo = SettingsRepository(db)
    cipher = SecretCipher("parallel-secret")
    settings_svc = SettingsService(settings_repo, cipher, "Asia/Shanghai")
    for sec in ("platforms", "rss", "foreign_sources", "schedule"):
        settings_repo.upsert_section(sec, {"enabled": True}, "2026-11-23T00:00:00+08:00")

    started_event = threading.Event()

    class _SlowCollector:
        def __init__(self, delay_sec: float, platform_id: str, signal_first: bool = False):
            self._delay = delay_sec
            self._pid = platform_id
            self._signal_first = signal_first

        def collect(self) -> CollectionResult:
            if self._signal_first:
                started_event.set()
            time.sleep(self._delay)
            return CollectionResult(
                items=[
                    CollectedItem(
                        source_type="hotlist",
                        platform_id=self._pid,
                        platform_name=self._pid,
                        title=f"Item {self._pid}",
                        url=f"https://example.com/{self._pid}",
                        rank=1,
                    )
                ],
                errors=[],
            )

    # 4 independent collectors each sleeping 0.15s would take >=0.60s serially; parallel finishes well under 0.45s.
    crawl = CrawlService(
        settings_service=settings_svc,
        news_repo=news_repo,
        timezone_name="Asia/Shanghai",
        hotlist_collector_factory=lambda _: _SlowCollector(0.15, "weibo", signal_first=True),
        rss_collector_factory=lambda _, __: _SlowCollector(0.15, "rss-1"),
        foreign_collectors_factory=lambda _: [
            _SlowCollector(0.15, "hackernews"),
            _SlowCollector(0.15, "github"),
        ],
    )

    result_box: List[Any] = []
    overlap_error: List[Exception] = []

    def _run_first() -> None:
        result_box.append(crawl.run_once())

    t0 = time.monotonic()
    worker = threading.Thread(target=_run_first)
    worker.start()
    assert started_event.wait(timeout=2.0)
    try:
        crawl.run_once()
    except CrawlAlreadyRunningError as exc:
        overlap_error.append(exc)
    worker.join(timeout=3.0)
    elapsed = time.monotonic() - t0

    assert len(overlap_error) == 1
    assert len(result_box) == 1
    assert elapsed < 0.45
    assert result_box[0].hotlist_count == 1
    assert result_box[0].foreign_api_count == 2
    assert result_box[0].duration_ms >= 100


def test_hackernews_preserves_topstories_order_when_fetched_concurrently() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "topstories.json" in url:
            return httpx.Response(200, json=[301, 302, 303])
        if "/item/301.json" in url:
            return httpx.Response(200, json={"id": 301, "title": "First HN", "score": 120})
        if "/item/302.json" in url:
            return httpx.Response(200, json={"id": 302, "title": "Second HN", "score": 450})
        if "/item/303.json" in url:
            return httpx.Response(200, json={"id": 303, "title": "Third HN", "score": 200})
        return httpx.Response(404)

    mock_client = httpx.Client(transport=httpx.MockTransport(_handler))
    res = HackerNewsCollector({"hackernews_enabled": True, "hackernews_min_score": 80, "hackernews_limit": 3}, client=mock_client).collect()
    assert [it.title for it in res.items] == ["First HN", "Second HN", "Third HN"]
    assert [it.rank for it in res.items] == [1, 2, 3]


def test_progressive_crawl_persists_fast_source_before_slow_source_finishes(tmp_path: Path) -> None:
    import threading
    import time

    db = Database(tmp_path / "progressive_crawl.db")
    db.init_schema()
    news_repo = NewsRepository(db)
    settings_repo = SettingsRepository(db)
    cipher = SecretCipher("prog-secret")
    settings_svc = SettingsService(settings_repo, cipher, "Asia/Shanghai")
    for sec in ("platforms", "rss", "foreign_sources", "schedule"):
        settings_repo.upsert_section(sec, {"enabled": True}, "2026-11-23T00:00:00+08:00")

    fast_persisted_before_slow_finished = False
    slow_release = threading.Event()
    fast_event_seen = threading.Event()

    class _ProgressiveHotlistCollector:
        def enabled_source_count(self) -> int:
            return 2

        def collect(self, on_source_done=None):
            fast_item = CollectedItem(
                source_type="hotlist",
                platform_id="zhihu",
                platform_name="知乎",
                title="Fast Source News",
                url="https://zhihu.com/fast/1",
                rank=1,
            )
            if on_source_done is not None:
                on_source_done("zhihu", "知乎", [fast_item], None)

            # Block the slow platform until test verifies the fast platform already hit SQLite.
            slow_release.wait(timeout=3.0)
            slow_item = CollectedItem(
                source_type="hotlist",
                platform_id="weibo",
                platform_name="微博",
                title="Slow Source News",
                url="https://weibo.com/slow/1",
                rank=1,
            )
            if on_source_done is not None:
                on_source_done("weibo", "微博", [slow_item], None)
            return CollectionResult(items=[fast_item, slow_item], errors=[])

    class _EmptyRss:
        def enabled_source_count(self) -> int:
            return 0

        def collect(self, on_source_done=None):
            return CollectionResult()

    events_seen = []

    def _on_progress(ev):
        events_seen.append(ev)
        if ev.stage == "source_done" and ev.source_id == "zhihu":
            fast_event_seen.set()

    crawl = CrawlService(
        settings_service=settings_svc,
        news_repo=news_repo,
        timezone_name="Asia/Shanghai",
        hotlist_collector_factory=lambda _: _ProgressiveHotlistCollector(),
        rss_collector_factory=lambda _, __: _EmptyRss(),
        foreign_collectors_factory=lambda _: [],
    )

    result_box: List[Any] = []
    worker = threading.Thread(target=lambda: result_box.append(crawl.run_once(on_progress=_on_progress)))
    worker.start()

    assert fast_event_seen.wait(timeout=2.0)
    # Query DB right after fast source event, while slow source is still blocked.
    mid_items = news_repo.list_hotlist()
    fast_persisted_before_slow_finished = len(mid_items) == 1 and mid_items[0]["platform_id"] == "zhihu"

    slow_release.set()
    worker.join(timeout=3.0)

    assert fast_persisted_before_slow_finished is True
    assert len(news_repo.list_hotlist()) == 2
    assert any(ev.stage == "source_done" and ev.source_id == "zhihu" for ev in events_seen)
    assert any(ev.stage == "source_done" and ev.source_id == "weibo" for ev in events_seen)
    assert result_box[0].hotlist_count == 2


def test_crawl_stream_sse_endpoint_emits_progressive_events(auth_client) -> None:
    from app.services.crawl_service import CrawlProgressEvent

    class _StreamStubCrawl:
        is_running = False

        def run_once(self, on_progress=None):
            from app.models import CrawlTriggerResponse

            if on_progress is not None:
                on_progress(CrawlProgressEvent(stage="start", completed_sources=0, total_sources=2))
                on_progress(
                    CrawlProgressEvent(
                        stage="source_done",
                        source_kind="hotlist",
                        source_id="zhihu",
                        source_name="知乎",
                        count=5,
                        completed_sources=1,
                        total_sources=2,
                    )
                )
            return CrawlTriggerResponse(
                job_id="stream123",
                status="completed",
                hotlist_count=5,
                rss_count=0,
                foreign_api_count=0,
                duration_ms=42,
                errors=[],
            )

    auth_client.app.state.crawl_service = _StreamStubCrawl()
    with auth_client.stream("POST", "/api/jobs/crawl/stream", json={"run_cluster": False}) as resp:
        assert resp.status_code == 200
        assert resp.headers.get("x-accel-buffering") == "no"
        raw = "".join(resp.iter_text())

    assert "event: start" in raw
    assert "event: source_done" in raw
    assert "知乎" in raw
    assert "event: done" in raw
    assert "stream123" in raw


def test_keyless_youtube_direct_handle_and_atom_xml_stats() -> None:
    cid = "UCxzC4g_1234567890123456"
    atom_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
  <title>OpenAI</title>
  <entry>
    <title>Introducing Reasoning Models</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abcDEF12345"/>
    <author><name>OpenAI</name></author>
    <published>2026-11-23T01:00:00+00:00</published>
    <media:group>
      <media:description>Deep dive into reasoning.</media:description>
      <media:community>
        <media:starRating count="12345" average="4.9"/>
        <media:statistics views="543210"/>
      </media:community>
    </media:group>
  </entry>
</feed>
"""

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "youtube.com/@OpenAI" in url:
            return httpx.Response(200, text=f'<html><script>{{"channelId":"{cid}"}}</script></html>')
        if "youtube.com/feeds/videos.xml" in url and cid in url:
            return httpx.Response(200, text=atom_xml)
        return httpx.Response(404)

    mock_client = httpx.Client(transport=httpx.MockTransport(_handler))
    res = YouTubeMetricsCollector(
        {"youtube_enabled": True, "youtube_channels": ["@OpenAI"]},
        client=mock_client,
    ).collect()
    assert len(res.errors) == 0
    assert len(res.items) == 1
    assert res.items[0].platform_id == "youtube"
    assert res.items[0].title == "[OpenAI] Introducing Reasoning Models"
    assert res.items[0].primary_metric == 543210.0
    assert res.items[0].extra_metrics["views"] == 543210
    assert res.items[0].extra_metrics["likes"] == 12345


def test_rss_collector_per_feed_max_age_days_edge_cases() -> None:
    from datetime import datetime, timedelta
    import zoneinfo

    tz = zoneinfo.ZoneInfo("Asia/Shanghai")
    old_iso = (datetime.now(tz) - timedelta(days=10)).isoformat(timespec="seconds")

    class _EdgeRSSFetcher:
        feeds = [
            {"id": "feed-empty", "name": "Empty MaxAge"},
            {"id": "feed-none", "name": "None MaxAge"},
            {"id": "feed-zero", "name": "Zero MaxAge"},
            {"id": "feed-30", "name": "Official 30d"},
        ]

        def fetch_all(self) -> RSSData:
            return RSSData(
                date="2026-11-23",
                crawl_time="14:00",
                items={
                    "feed-empty": [
                        RSSItem(title="Empty age item", feed_id="feed-empty", feed_name="Empty", url="https://e.com/1", published_at=old_iso)
                    ],
                    "feed-none": [
                        RSSItem(title="None age item", feed_id="feed-none", feed_name="None", url="https://n.com/1", published_at=old_iso)
                    ],
                    "feed-zero": [
                        RSSItem(title="Unlimited age item", feed_id="feed-zero", feed_name="Zero", url="https://z.com/1", published_at=old_iso)
                    ],
                    "feed-30": [
                        RSSItem(title="Official 10d bulletin", feed_id="feed-30", feed_name="Official", url="https://o.com/1", published_at=old_iso)
                    ],
                },
                id_to_name={
                    "feed-empty": "Empty MaxAge",
                    "feed-none": "None MaxAge",
                    "feed-zero": "Zero MaxAge",
                    "feed-30": "Official 30d",
                },
                failed_ids=[],
            )

    cfg: Dict[str, Any] = {
        "enabled": True,
        "freshness_enabled": True,
        "max_age_days": 2,
        "feeds": [
            {"id": "feed-empty", "name": "Empty MaxAge", "url": "https://e.com/rss", "domain": "宏观政策", "max_age_days": ""},
            {"id": "feed-none", "name": "None MaxAge", "url": "https://n.com/rss", "domain": "宏观政策", "max_age_days": None},
            {"id": "feed-zero", "name": "Zero MaxAge", "url": "https://z.com/rss", "domain": "宏观政策", "max_age_days": 0},
            {"id": "feed-30", "name": "Official 30d", "url": "https://o.com/rss", "domain": "宏观政策", "max_age_days": 30},
        ],
    }
    res = RssCollector(cfg, timezone_name="Asia/Shanghai", fetcher=_EdgeRSSFetcher()).collect()
    assert res.errors == []
    kept_ids = {item.platform_id for item in res.items}
    assert kept_ids == {"feed-zero", "feed-30"}
