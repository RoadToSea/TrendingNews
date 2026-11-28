"""Tests for incremental cross-lingual clustering, multi-day trend charts, domains, and reports."""

import json
from typing import Any, AsyncIterator, Dict, List, Tuple

from fastapi.testclient import TestClient

from app.services.ai_gateway.base import LLMUpstreamError, StreamEvent


class _FakeClusterAndSummaryGateway:
    """Stub LLM gateway aligning Chinese/English titles by topic and outputting Markdown reports."""

    async def complete_json(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        extra_params: Dict[str, Any] | None = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        content = messages[-1]["content"]
        # Extract pending news items serialized in the prompt
        marker = "待归类新闻："
        idx = content.find(marker)
        assert idx != -1
        items = json.loads(content[idx + len(marker) :])
        existing_idx_start = content.find("近3天已有事件：") + len("近3天已有事件：")
        existing_idx_end = content.find("\n" + marker)
        existing = json.loads(content[existing_idx_start:existing_idx_end])
        existing_map = {e["canonical_title"]: e["event_id"] for e in existing}

        assignments = []
        for item in items:
            title_lower = item["title"].lower()
            if "chip" in title_lower or "芯片" in title_lower:
                canon = "全球AI芯片架构突破"
                domain = "AI大模型"
                eid = existing_map.get(canon)
                assignments.append(
                    {
                        "news_id": item["news_id"],
                        "event_id": eid,
                        "canonical_title": canon,
                        "domain": domain,
                        "summary": "中美平台热议新一代 AI 芯片算力发布",
                        "confidence": 0.96,
                    }
                )
            else:
                assignments.append(
                    {
                        "news_id": item["news_id"],
                        "event_id": existing_map.get("城市单日突发议题"),
                        "canonical_title": "城市单日突发议题",
                        "domain": "社会民生",
                        "summary": "单日上榜社会新闻",
                        "confidence": 0.88,
                    }
                )
        return {"assignments": assignments}, {"total_tokens": 50}

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        system_prompt: str = "",
        external_conversation_id: str = "",
        extra_params: Dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type="init", conversation_id="")
        yield StreamEvent(type="delta", text="# 热点研判报告\n\n- 核心观察：**全球AI芯片架构突破** 连续跨平台升温。")
        yield StreamEvent(type="done", usage={"total_tokens": 42})


def _seed_day_items(auth_client: TestClient, day: str, specs: List[tuple]) -> List[int]:
    repo = auth_client.app.state.news_repo
    ids: List[int] = []
    seen_at = f"{day}T12:00:00+08:00"
    for pid, pname, title, url, rank, vel in specs:
        nid, _ = repo.upsert_news_item(
            source_type="hotlist",
            platform_id=pid,
            platform_name=pname,
            domain="",
            title=title,
            title_hash=f"h-{day}-{pid}-{rank}",
            url=url,
            mobile_url="",
            summary="Sample summary",
            extra_metrics={},
            rank=rank,
            seen_at=seen_at,
        )
        repo.insert_rank_history(nid, rank, seen_at, None)
        repo.batch_update_velocities([(nid, vel)])
        ids.append(nid)
    return ids


def test_cross_lingual_clustering_trends_and_report_modes(auth_client: TestClient) -> None:
    import asyncio

    # Without an event_cluster bound slot, clustering skips gracefully without crashing
    for slot in auth_client.get("/api/ai-providers").json():
        auth_client.put(f"/api/ai-providers/{slot['id']}", json={"role_bindings": []})

    nids_day1 = _seed_day_items(
        auth_client,
        "2026-11-20",
        [
            ("zhihu", "知乎", "国产 AI 芯片架构取得关键突破", "https://zhihu.com/chip-1", 1, 35.0),
            ("hackernews", "Hacker News", "Next-gen AI Chip architecture benchmark released", "https://hn.algolia.com/1", 2, 70.0),
            ("weibo", "微博", "某地公交线路优化调整", "https://weibo.com/bus-1", 4, 15.0),
        ],
    )
    cluster_svc = auth_client.app.state.cluster_service
    assert asyncio.run(cluster_svc.run_incremental_clustering("2026-11-20")) == 0

    # Bind OpenAI stub slot to summary_report & event_cluster
    slot = auth_client.post(
        "/api/ai-providers",
        json={
            "name": "聚类与报告槽位",
            "protocol": "openai",
            "api_key": "sk-stub",
            "model": "gpt-4o-mini",
            "role_bindings": ["summary_report", "event_cluster"],
            "is_enabled": True,
        },
    ).json()
    assert slot["id"] > 0
    auth_client.app.state.gateway_service._adapter_factory = lambda s, k: _FakeClusterAndSummaryGateway()

    # Cluster Day 1 -> 2026-11-20 (cross-lingual zhihu + hn merge into 1 event, weibo single-day event)
    assert asyncio.run(cluster_svc.run_incremental_clustering("2026-11-20")) == 3

    # Cluster Day 2 -> 2026-11-21 (same AI chip story persists across platforms -> same event_id)
    _seed_day_items(
        auth_client,
        "2026-11-21",
        [
            ("baidu", "百度热搜", "AI芯片架构实测引发行业热议", "https://baidu.com/chip-2", 1, 40.0),
        ],
    )
    assert asyncio.run(cluster_svc.run_incremental_clustering("2026-11-21")) == 1

    # Cluster Day 3 -> 2026-11-22 (continues a 3rd day + seed one RSS item)
    _seed_day_items(
        auth_client,
        "2026-11-22",
        [
            ("bilibili", "B站", "AI 芯片架构深度评测视频登顶", "https://bili.com/chip-3", 2, 28.0),
        ],
    )
    assert asyncio.run(cluster_svc.run_incremental_clustering("2026-11-22")) == 1

    # Generate reports in all 3 AI modes
    r_daily = auth_client.post(
        "/api/reports/generate",
        json={"mode": "daily_overall", "date": "2026-11-22"},
    )
    assert r_daily.status_code == 200
    daily_id = r_daily.json()["id"]

    r_domain = auth_client.post(
        "/api/reports/generate",
        json={"mode": "domain_trend", "date": "2026-11-22", "domain": "AI大模型"},
    )
    assert r_domain.status_code == 200
    assert r_domain.json()["report_type"] == "domain_trend"

    r_item = auth_client.post(
        "/api/reports/generate",
        json={"mode": "item_analysis", "news_ids": [nids_day1[0]]},
    )
    assert r_item.status_code == 200
    assert r_item.json()["report_type"] == "item_analysis"

    # Manual report save + list/get/delete
    r_manual = auth_client.post(
        "/api/reports",
        json={
            "title": "手动记录报告",
            "report_type": "daily_overall",
            "report_date": "2026-11-19",
            "domain": "AI大模型",
            "content_md": "人工补充研判",
        },
    )
    assert r_manual.status_code == 200
    manual_id = r_manual.json()["id"]
    assert auth_client.get("/api/reports").json()["total"] == 4
    assert auth_client.get(f"/api/reports/{manual_id}").status_code == 200
    assert auth_client.delete(f"/api/reports/{manual_id}").status_code == 200
    assert auth_client.get(f"/api/reports/{manual_id}").status_code == 404

    # Verify /api/domains
    dom_resp = auth_client.get("/api/domains", params={"date": "2026-11-20", "domain": "AI大模型"})
    assert dom_resp.status_code == 200
    dom_data = dom_resp.json()
    assert len(dom_data["events"]) == 1
    chip_event = dom_data["events"][0]
    assert chip_event["canonical_title"] == "全球AI芯片架构突破"
    assert chip_event["platform_count"] == 2
    assert len(chip_event["items"]) == 4  # across 3 days

    # Verify /api/trends connects multi-day event and keeps single-day event unlinked
    trends = auth_client.get("/api/trends", params={"days": 7, "top_n": 10}).json()
    assert trends["daily_reports"]["2026-11-22"] == daily_id
    series_by_title = {s["canonical_title"]: s for s in trends["series"]}
    assert series_by_title["全球AI芯片架构突破"]["is_multi_day"] is True
    assert len(series_by_title["全球AI芯片架构突破"]["points"]) == 3
    assert series_by_title["全球AI芯片架构突破"]["points"][-1]["daily_report_id"] == daily_id
    assert series_by_title["城市单日突发议题"]["is_multi_day"] is False
    assert len(series_by_title["城市单日突发议题"]["points"]) == 1

    # Verify /api/events/{id}
    detail = auth_client.get(f"/api/events/{chip_event['id']}")
    assert detail.status_code == 200
    assert len(detail.json()["metrics"]) == 3
    assert auth_client.get("/api/events/999999").status_code == 404


def test_cluster_error_surfaces_in_last_error_and_crawl_summary(auth_client: TestClient) -> None:
    import asyncio
    from datetime import datetime
    import zoneinfo

    from app.models import CrawlTriggerResponse

    for slot in auth_client.get("/api/ai-providers").json():
        auth_client.put(f"/api/ai-providers/{slot['id']}", json={"role_bindings": []})

    today = datetime.now(zoneinfo.ZoneInfo("Asia/Shanghai")).date().isoformat()
    _seed_day_items(
        auth_client,
        today,
        [("zhihu", "知乎", "未聚类测试话题", "https://zhihu.com/unlinked-err", 1, 20.0)],
    )
    cluster_svc = auth_client.app.state.cluster_service
    assert asyncio.run(cluster_svc.run_incremental_clustering(today)) == 0
    assert cluster_svc.last_error is not None and "event_cluster" in cluster_svc.last_error

    class _FailingClusterGateway:
        async def complete_json(self, *args, **kwargs):
            raise LLMUpstreamError("upstream 502 bad gateway")

    auth_client.post(
        "/api/ai-providers",
        json={
            "name": "失败聚类槽位",
            "protocol": "openai",
            "api_key": "sk-stub",
            "model": "gpt-4o-mini",
            "role_bindings": ["event_cluster"],
            "is_enabled": True,
        },
    )
    auth_client.app.state.gateway_service._adapter_factory = lambda s, k: _FailingClusterGateway()

    class _StubCrawlSvc:
        def run_once(self):
            return CrawlTriggerResponse(
                job_id="job-cluster-err",
                status="completed",
                hotlist_count=1,
                rss_count=0,
                foreign_api_count=0,
                errors=[],
            )

    auth_client.app.state.crawl_service = _StubCrawlSvc()
    trig = auth_client.post("/api/jobs/crawl/trigger", json={"run_cluster": True})
    assert trig.status_code == 200
    body = trig.json()
    assert body["status"] == "partial"
    assert any("upstream 502 bad gateway" in err for err in body["errors"])


def test_report_prompts_exclude_internal_ids_and_forbid_tables(auth_client: TestClient) -> None:
    captured_prompts: List[Dict[str, str]] = []

    class _CapturingGateway:
        async def complete_json(self, *args, **kwargs):
            return {"assignments": []}, {"total_tokens": 1}

        async def stream_chat(self, messages, model, *, system_prompt="", **kwargs):
            captured_prompts.append(
                {
                    "system": system_prompt,
                    "user": messages[-1]["content"],
                }
            )
            yield StreamEvent(type="init", conversation_id="")
            yield StreamEvent(type="delta", text="# 测试简报\n\n核心结论清晰明确。")
            yield StreamEvent(type="done", usage={"total_tokens": 12})

    for slot in auth_client.get("/api/ai-providers").json():
        auth_client.put(f"/api/ai-providers/{slot['id']}", json={"role_bindings": []})

    auth_client.post(
        "/api/ai-providers",
        json={
            "name": "简报测试槽位",
            "protocol": "openai",
            "api_key": "sk-stub",
            "model": "gpt-4o-mini",
            "role_bindings": ["summary_report", "event_cluster"],
            "is_enabled": True,
        },
    )
    auth_client.app.state.gateway_service._adapter_factory = lambda s, k: _CapturingGateway()

    nid = _seed_day_items(
        auth_client,
        "2026-11-24",
        [("zhihu", "知乎", "新一代开源编译器发布", "https://zhihu.com/compiler", 1, 55.0)],
    )[0]
    ev_repo = auth_client.app.state.event_repo
    eid = ev_repo.create_event(
        canonical_title="新一代开源编译器发布",
        domain="科技互联网",
        summary="开发者社区热议开源编译器性能提升",
        seen_date="2026-11-24",
        now_iso="2026-11-24T12:00:00+08:00",
    )
    ev_repo.link_item(event_id=eid, source_type="hotlist", item_id=nid, confidence=0.95, now_iso="2026-11-24T12:00:00+08:00")
    ev_repo.replace_daily_metrics(
        "2026-11-24",
        [
            {
                "event_id": eid,
                "hot_index": 77.7,
                "velocity": 55.0,
                "platform_count": 3,
                "mention_count": 1,
                "daily_rank": 1,
                "is_top_n": True,
            }
        ],
        "2026-11-24T12:00:00+08:00",
    )

    assert auth_client.post("/api/reports/generate", json={"mode": "daily_overall", "date": "2026-11-24"}).status_code == 200
    assert auth_client.post("/api/reports/generate", json={"mode": "domain_trend", "date": "2026-11-24", "domain": "科技互联网"}).status_code == 200
    assert auth_client.post("/api/reports/generate", json={"mode": "item_analysis", "news_ids": [nid], "event_ids": [eid]}).status_code == 200

    assert len(captured_prompts) == 3
    for idx, cap in enumerate(captured_prompts):
        assert "严禁使用 Markdown 表格" in cap["system"], f"prompt {idx} missing no-table rule"
        assert "event_id" in cap["system"], f"prompt {idx} system should forbid event_id"
        for forbidden in ("event_id", "news_id", "hot_index", "title_hash", "77.7", "platform_count"):
            assert forbidden not in cap["user"], f"user prompt {idx} leaked internal token: {forbidden}"
        assert "新一代开源编译器发布" in cap["user"]