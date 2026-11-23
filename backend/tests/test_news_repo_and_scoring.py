"""Tests for NewsRepository deduplication and velocity/hot-index scoring."""

from datetime import datetime, timedelta
from pathlib import Path
import zoneinfo

from app.repositories.db import Database
from app.repositories.news_repo import NewsRepository
from app.services.scoring_service import (
    compute_event_hot_index,
    compute_rank_velocity,
    compute_raw_interaction_rate,
    normalize_platform_interaction_velocities,
)


def test_news_repo_deduplication_and_trajectories(tmp_path: Path) -> None:
    db = Database(tmp_path / "repo.db")
    db.init_schema()
    repo = NewsRepository(db)

    id1, first1 = repo.upsert_news_item(
        source_type="hotlist",
        platform_id="zhihu",
        platform_name="知乎",
        domain="",
        title="AI 新模型发布",
        title_hash="h1",
        url="https://www.zhihu.com/question/123",
        mobile_url="",
        summary="",
        extra_metrics={"info": "100万热度"},
        rank=10,
        seen_at="2026-11-22T10:00:00+08:00",
    )
    id2, first2 = repo.upsert_news_item(
        source_type="hotlist",
        platform_id="zhihu",
        platform_name="知乎",
        domain="AI大模型",
        title="AI 新模型发布（更新）",
        title_hash="h2",
        url="https://www.zhihu.com/question/123",
        mobile_url="",
        summary="补充摘要",
        extra_metrics={"info": "300万热度"},
        rank=2,
        seen_at="2026-11-22T11:00:00+08:00",
    )
    assert id1 == id2
    assert first2 == first1

    repo.insert_rank_history(id1, 10, "2026-11-22T10:00:00+08:00")
    repo.insert_rank_history(id1, 2, "2026-11-22T11:00:00+08:00")
    history = repo.get_recent_rank_history(id1)
    assert [(r[1], r[0]) for r in history] == [
        (10, "2026-11-22T10:00:00+08:00"),
        (2, "2026-11-22T11:00:00+08:00"),
    ]

    # Empty URL falls back to title_hash deduplication
    no_url_1, _ = repo.upsert_news_item(
        source_type="hotlist",
        platform_id="weibo",
        platform_name="微博",
        domain="",
        title="无链接热搜",
        title_hash="same-hash",
        url="",
        mobile_url="",
        summary="",
        extra_metrics={},
        rank=5,
        seen_at="2026-11-22T10:00:00+08:00",
    )
    no_url_2, _ = repo.upsert_news_item(
        source_type="hotlist",
        platform_id="weibo",
        platform_name="微博",
        domain="",
        title="无链接热搜",
        title_hash="same-hash",
        url="",
        mobile_url="",
        summary="",
        extra_metrics={},
        rank=3,
        seen_at="2026-11-22T11:00:00+08:00",
    )
    assert no_url_1 == no_url_2


def test_rank_velocity_climb_and_debut_bonus() -> None:
    tz = zoneinfo.ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 11, 22, 12, 0, tzinfo=tz)
    first_seen = (now - timedelta(minutes=60)).isoformat(timespec="seconds")
    history = [
        ((now - timedelta(minutes=60)).isoformat(timespec="seconds"), 18, None),
        (now.isoformat(timespec="seconds"), 2, None),
    ]
    # Rank score climbed from (51-18)=33 to (51-2)=49 over 1.0h (+16/h) + debut (16-2)*2.5 (+35)
    vel = compute_rank_velocity(history, first_seen, now)
    assert vel == 51.0


def test_interaction_rate_normalization_and_hot_index() -> None:
    tz = zoneinfo.ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 11, 22, 12, 0, tzinfo=tz)
    t0 = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    t1 = now.isoformat(timespec="seconds")

    rate_low = compute_raw_interaction_rate([(t0, 5, 100.0), (t1, 4, 150.0)], t0, now)
    rate_high = compute_raw_interaction_rate([(t0, 2, 100.0), (t1, 1, 5100.0)], t0, now)
    assert rate_low == 50.0
    assert rate_high == 5000.0

    norm = normalize_platform_interaction_velocities({1: rate_low, 2: rate_high})
    assert 0.0 < norm[1] < norm[2] == 100.0

    hot_idx = compute_event_hot_index(
        platform_count=4,
        total_enabled_platforms=8,
        best_ranks=[1, 2, 3, 5],
        mention_batches=6,
        total_daily_batches=8,
        max_velocity=35.0,
    )
    assert 70.0 <= hot_idx <= 100.0
