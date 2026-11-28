"""Tests for keyword matching, encrypted settings endpoints, and webhook test endpoint."""

from fastapi.testclient import TestClient

from app.services.keyword_service import match_items_by_keyword_groups


def test_keyword_matching_syntax_required_and_filters() -> None:
    raw = """
[GLOBAL_FILTER]
广告

[WORD_GROUPS]
[AI算力]
+AI
芯片
大模型
!低价
@2
"""
    items = [
        {
            "id": 1,
            "source_type": "hotlist",
            "platform_id": "zhihu",
            "platform_name": "知乎",
            "domain": "AI大模型",
            "title": "国产 AI 芯片最新突破",
            "url": "https://zhihu.com/1",
            "summary": "",
            "latest_rank": 1,
            "velocity": 10.0,
            "hot_index": None,
            "event_id": None,
            "extra_metrics": {},
            "first_seen_at": "2026-11-22T10:00:00+08:00",
            "last_seen_at": "2026-11-22T10:00:00+08:00",
        },
        {
            "id": 2,
            "source_type": "hotlist",
            "platform_id": "weibo",
            "platform_name": "微博",
            "domain": "",
            "title": "AI 芯片广告推广",
            "url": "https://weibo.com/2",
            "summary": "",
            "latest_rank": 3,
            "velocity": 5.0,
            "hot_index": None,
            "event_id": None,
            "extra_metrics": {},
            "first_seen_at": "2026-11-22T10:00:00+08:00",
            "last_seen_at": "2026-11-22T10:00:00+08:00",
        },
        {
            "id": 3,
            "source_type": "rss",
            "platform_id": "tc",
            "platform_name": "TechCrunch",
            "domain": "科技互联网",
            "title": "芯片行业动态（无必须词）",
            "url": "https://tc.com/3",
            "summary": "",
            "latest_rank": None,
            "velocity": 0.0,
            "hot_index": None,
            "event_id": None,
            "extra_metrics": {},
            "first_seen_at": "2026-11-22T10:00:00+08:00",
            "last_seen_at": "2026-11-22T10:00:00+08:00",
        },
    ]
    groups, total = match_items_by_keyword_groups(items, raw)
    assert total == 1
    assert len(groups) == 1
    assert groups[0]["display_name"] == "AI算力"
    assert groups[0]["items"][0]["id"] == 1


def test_settings_secret_masking_and_preservation_via_api(auth_client: TestClient) -> None:
    assert auth_client.get("/api/settings/nonexistent").status_code == 404

    put_resp = auth_client.put(
        "/api/settings/webhooks",
        json={
            "payload": {
                "enabled": True,
                "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/secret-123456",
                "dingtalk_webhook_url": "",
            }
        },
    )
    assert put_resp.status_code == 200
    masked_url = put_resp.json()["payload"]["feishu_webhook_url"]
    assert "***" in masked_url
    assert "secret-123456" not in masked_url

    # Re-submitting masked placeholder must preserve the stored encrypted secret.
    second_put = auth_client.put(
        "/api/settings/webhooks",
        json={
            "payload": {
                "enabled": False,
                "feishu_webhook_url": masked_url,
            }
        },
    )
    assert second_put.status_code == 200
    admin_id = auth_client.get("/api/auth/me").json()["id"]
    internal = auth_client.app.state.settings_service.get_user_internal_section(
        admin_id,
        "webhooks",
        user_role="admin",
    )
    assert internal["feishu_webhook_url"] == "https://open.feishu.cn/open-apis/bot/v2/hook/secret-123456"


def test_webhook_test_endpoint_with_fake_dispatcher(auth_client: TestClient) -> None:
    no_channel = auth_client.post("/api/webhooks/test", json={})
    assert no_channel.status_code == 400

    removed_channel = auth_client.post("/api/webhooks/test", json={"channel": "telegram"})
    assert removed_channel.status_code == 400

    auth_client.put(
        "/api/settings/webhooks",
        json={
            "payload": {
                "enabled": True,
                "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/abc987",
                "dingtalk_webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=dt1",
                "wework_webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=ww1",
                "wework_msg_type": "text",
                "generic_webhook_url": "https://example.com/hook",
                "generic_webhook_payload_template": '{"subject":"{title}","body":"{content}"}',
            }
        },
    )

    sent_calls = []

    def _fake_http_post(url: str, payload: dict):
        sent_calls.append((url, payload))
        if "feishu" in url:
            return 200, {"code": 0}
        if "dingtalk" in url or "weixin" in url:
            return 200, {"errcode": 0}
        return 200, {"ok": True}

    auth_client.app.state.webhook_service._http_post = _fake_http_post

    feishu_resp = auth_client.post("/api/webhooks/test", json={"channel": "feishu"})
    assert feishu_resp.status_code == 200
    assert feishu_resp.json()["results"] == [
        {"channel": "feishu", "success": True, "message": "sent"}
    ]
    assert sent_calls[0][0].endswith("abc987")
    assert sent_calls[0][1]["msg_type"] == "interactive"

    all_resp = auth_client.post("/api/webhooks/test", json={})
    assert all_resp.status_code == 200
    assert [r["channel"] for r in all_resp.json()["results"]] == [
        "feishu",
        "dingtalk",
        "wework",
        "generic_webhook",
    ]
    assert all(r["success"] for r in all_resp.json()["results"])
    assert sent_calls[-3][1]["msgtype"] == "markdown"
    assert sent_calls[-2][1]["msgtype"] == "text"
    assert sent_calls[-1][1]["subject"] == "通知连通性测试"
    assert "Webhook 通道配置正常" in sent_calls[-1][1]["body"]


def test_hotlist_rising_rss_keywords_and_crawl_api(auth_client: TestClient) -> None:
    # Seed keyword rules and run mocked crawl via API
    auth_client.put(
        "/api/settings/keywords",
        json={"payload": {"raw_text": "AI\n芯片", "include_rss": True}},
    )

    class _StubCrawl:
        def run_once(self):
            from app.models import CrawlTriggerResponse
            return CrawlTriggerResponse(
                job_id="job123",
                status="completed",
                hotlist_count=1,
                rss_count=1,
                foreign_api_count=0,
                errors=[],
            )

    auth_client.app.state.crawl_service = _StubCrawl()
    trig = auth_client.post("/api/jobs/crawl/trigger", json={"run_cluster": False})
    assert trig.status_code == 200
    assert trig.json()["job_id"] == "job123"

    # Insert sample items directly via repo to test query endpoints
    repo = auth_client.app.state.news_repo
    nid, _ = repo.upsert_news_item(
        source_type="hotlist",
        platform_id="zhihu",
        platform_name="知乎",
        domain="AI大模型",
        title="AI 芯片全链条解析",
        title_hash="hash-ai",
        url="https://zhihu.com/q/1",
        mobile_url="",
        summary="",
        extra_metrics={},
        rank=1,
        seen_at="2099-01-01T12:00:00+08:00",
    )
    repo.batch_update_velocities([(nid, 45.0)])
    repo.upsert_rss_item(
        feed_id="bbc-world",
        feed_name="BBC World",
        domain="国际地缘",
        title="World News Digest",
        url="https://bbc.com/1",
        guid="g1",
        author="",
        summary="Summary",
        published_at="2099-01-01T11:00:00+08:00",
        seen_at="2099-01-01T12:00:00+08:00",
    )

    assert len(auth_client.get("/api/hotlist").json()["items"]) == 1
    assert len(auth_client.get("/api/hotlist/rising").json()["items"]) == 1
    assert len(auth_client.get("/api/rss").json()["items"]) == 1
    kw_resp = auth_client.get("/api/keywords/stats")
    assert kw_resp.status_code == 200
    assert kw_resp.json()["total"] == 1


def test_keyword_group_scoped_excludes_do_not_block_other_groups() -> None:
    raw = """
[GLOBAL_FILTER]
广告

[WORD_GROUPS]
[苹果公司]
苹果
!水果

[农产品]
水果
"""
    items = [
        {
            "id": 10,
            "source_type": "hotlist",
            "platform_id": "zhihu",
            "platform_name": "知乎",
            "domain": "其他",
            "title": "苹果水果涨价",
            "url": "https://zhihu.com/10",
            "summary": "",
        },
        {
            "id": 11,
            "source_type": "hotlist",
            "platform_id": "weibo",
            "platform_name": "微博",
            "domain": "其他",
            "title": "水果广告推广",
            "url": "https://weibo.com/11",
            "summary": "",
        },
    ]
    groups, total = match_items_by_keyword_groups(items, raw)
    assert total == 1
    assert len(groups) == 1
    assert groups[0]["display_name"] == "农产品"
    assert [it["id"] for it in groups[0]["items"]] == [10]


def test_schedule_update_hot_reschedules_running_scheduler(tmp_path) -> None:
    from datetime import timedelta
    from app.config import Settings
    from app.main import create_app

    cfg = Settings(
        app_base_path="/",
        db_path=tmp_path / "sched_test.db",
        secret_key="sched-secret-key",
        admin_user="admin",
        admin_pass="StrongPass123!",
        timezone="Asia/Shanghai",
        enable_scheduler=True,
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        login_resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "StrongPass123!"},
        )
        assert login_resp.status_code == 200
        scheduler = client.app.state.scheduler
        assert scheduler is not None and scheduler.running
        initial_crawl = scheduler.get_job("crawl_job")
        assert initial_crawl is not None
        assert initial_crawl.trigger.interval == timedelta(minutes=30)

        upd = client.put(
            "/api/settings/schedule",
            json={
                "payload": {
                    "crawl_interval_minutes": 15,
                    "daily_report_time": "08:30",
                    "retention_days": 30,
                    "push_on_crawl": False,
                }
            },
        )
        assert upd.status_code == 200
        updated_crawl = scheduler.get_job("crawl_job")
        updated_daily = scheduler.get_job("daily_report_job")
        assert updated_crawl is not None
        assert updated_crawl.trigger.interval == timedelta(minutes=15)
        assert updated_daily is not None
        cron_fields = {f.name: str(f) for f in updated_daily.trigger.fields}
        assert cron_fields["hour"] == "8"
        assert cron_fields["minute"] == "30"


def test_rbac_and_per_user_incremental_webhook_push(auth_client: TestClient) -> None:
    # Create an invite code so a standard member can register
    invite_resp = auth_client.post("/api/admin/invite-codes", json={"max_uses": 5})
    assert invite_resp.status_code == 200
    invite_code = invite_resp.json()["code"]

    # Configure admin's personal keywords and webhook
    auth_client.put(
        "/api/settings/keywords",
        json={"payload": {"raw_text": "芯片", "include_rss": True}},
    )
    auth_client.put(
        "/api/settings/webhooks",
        json={
            "payload": {
                "enabled": True,
                "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/admin-hook",
            }
        },
    )

    # Seed recent items (both matchable topics)
    repo = auth_client.app.state.news_repo
    from datetime import datetime
    import zoneinfo

    now_iso = datetime.now(zoneinfo.ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    repo.upsert_news_item(
        source_type="hotlist",
        platform_id="zhihu",
        platform_name="知乎",
        domain="AI大模型",
        title="国产芯片架构迎来突破",
        title_hash="h-chip-1",
        url="https://zhihu.com/chip-1",
        mobile_url="",
        summary="",
        extra_metrics={},
        rank=1,
        seen_at=now_iso,
    )
    repo.upsert_news_item(
        source_type="hotlist",
        platform_id="weibo",
        platform_name="微博",
        domain="财经金融",
        title="新能源汽车季度销量新高",
        title_hash="h-ev-1",
        url="https://weibo.com/ev-1",
        mobile_url="",
        summary="",
        extra_metrics={},
        rank=2,
        seen_at=now_iso,
    )

    # Register a standard user in an isolated TestClient
    with TestClient(auth_client.app) as member_client:
        reg = member_client.post(
            "/api/auth/register",
            json={"username": "member_alice", "password": "MemberPass123!", "invite_code": invite_code},
        )
        assert reg.status_code == 200

        # Non-admin blocked from admin settings, crawl, and AI providers
        assert member_client.get("/api/settings/platforms").status_code == 403
        assert member_client.put("/api/settings/domains", json={"payload": {"items": []}}).status_code == 403
        assert member_client.get("/api/settings/schedule").status_code == 403
        assert member_client.post("/api/jobs/crawl/trigger", json={"run_cluster": False}).status_code == 403
        assert member_client.get("/api/ai-providers").status_code == 403

        # Non-admin can read domains and manage own keywords/webhooks
        assert member_client.get("/api/settings/domains").status_code == 200
        assert (
            member_client.put(
                "/api/settings/keywords",
                json={"payload": {"raw_text": "新能源汽车", "include_rss": False}},
            ).status_code
            == 200
        )
        assert (
            member_client.put(
                "/api/settings/webhooks",
                json={
                    "payload": {
                        "enabled": True,
                        "dingtalk_webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=alice",
                    }
                },
            ).status_code
            == 200
        )
        kw_stats = member_client.get("/api/keywords/stats").json()
        assert kw_stats["total"] == 1
        assert kw_stats["groups"][0]["items"][0]["title"] == "新能源汽车季度销量新高"

    # Incremental multi-user push: each user gets only their own matched items
    sent_payloads = []

    def _fake_post(url: str, payload: dict):
        sent_payloads.append((url, payload))
        if "feishu" in url:
            return 200, {"code": 0}
        return 200, {"errcode": 0}

    wh_svc = auth_client.app.state.webhook_service
    wh_svc._http_post = _fake_post

    first_run = wh_svc.push_incremental_for_all_users()
    assert len(first_run) == 2
    assert len(sent_payloads) == 2
    admin_call = next(p for u, p in sent_payloads if "admin-hook" in u)
    alice_call = next(p for u, p in sent_payloads if "alice" in u)
    assert "国产芯片架构迎来突破" in admin_call["card"]["body"]["elements"][0]["content"]
    assert "新能源汽车" not in admin_call["card"]["body"]["elements"][0]["content"]
    assert "新能源汽车季度销量新高" in alice_call["markdown"]["text"]
    assert "芯片" not in alice_call["markdown"]["text"]

    # Second run without new items must deduplicate and send nothing
    second_run = wh_svc.push_incremental_for_all_users()
    assert second_run == {}
    assert len(sent_payloads) == 2
