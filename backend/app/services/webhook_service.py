"""Webhook notification adapter bridging DB settings/items to legacy `NotificationDispatcher`."""

from datetime import datetime, timedelta
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import zoneinfo

from trendradar.notification import NotificationDispatcher, split_content_into_batches

from app.models import WebhookChannelResultDTO
from app.repositories.news_repo import NewsRepository
from app.services.keyword_service import match_items_by_keyword_groups
from app.services.settings_service import SettingsService

_SUPPORTED_CHANNELS = (
    "feishu",
    "dingtalk",
    "wework",
    "telegram",
    "email",
    "ntfy",
    "bark",
    "slack",
    "generic_webhook",
)


class WebhookConfigError(Exception):
    """Raised when webhook channel selection or configuration is invalid."""


class WebhookService:
    """Adapter sending test pings and scheduled summaries across 9 legacy notification channels."""

    def __init__(
        self,
        settings_service: SettingsService,
        news_repo: NewsRepository,
        timezone_name: str,
        dispatcher_factory: Optional[Callable[[Dict[str, Any], Callable, Callable], Any]] = None,
    ) -> None:
        """Initialize the webhook adapter service.

        Args:
            settings_service: Settings service supplying decrypted webhook secrets.
            news_repo: Repository reading recent items for scheduled keyword summary pushes.
            timezone_name: Application timezone name.
            dispatcher_factory: Optional factory override for unit testing.
        """
        self._settings = settings_service
        self._news_repo = news_repo
        self._tz_name = timezone_name
        self._tz = zoneinfo.ZoneInfo(timezone_name)
        self._dispatcher_factory = dispatcher_factory

    def _now(self) -> datetime:
        return datetime.now(self._tz)

    def _build_legacy_config(
        self,
        webhooks_cfg: Dict[str, Any],
        target_channel: Optional[str] = None,
    ) -> Dict[str, Any]:
        if target_channel is not None and target_channel not in _SUPPORTED_CHANNELS:
            raise WebhookConfigError(f"Unsupported webhook channel: {target_channel}")

        def _val(ch: str, key: str, default: str = "") -> str:
            if target_channel is not None and target_channel != ch:
                return ""
            return str(webhooks_cfg.get(key) or default)

        return {
            "TIMEZONE": self._tz_name,
            "MAX_ACCOUNTS_PER_CHANNEL": 3,
            "MESSAGE_BATCH_SIZE": 4000,
            "DINGTALK_BATCH_SIZE": 20000,
            "FEISHU_BATCH_SIZE": 29000,
            "BARK_BATCH_SIZE": 3600,
            "SLACK_BATCH_SIZE": 4000,
            "BATCH_SEND_INTERVAL": 1.0,
            "FEISHU_MESSAGE_SEPARATOR": "---",
            "DISPLAY": {
                "REGION_ORDER": ["hotlist", "rss"],
                "REGIONS": {
                    "HOTLIST": True,
                    "NEW_ITEMS": False,
                    "RSS": True,
                    "STANDALONE": False,
                    "AI_ANALYSIS": False,
                },
            },
            "WEB_SEARCH": {"NOTIFICATION_SHOW_SNIPPET": False},
            "FEISHU_WEBHOOK_URL": _val("feishu", "feishu_webhook_url"),
            "DINGTALK_WEBHOOK_URL": _val("dingtalk", "dingtalk_webhook_url"),
            "WEWORK_WEBHOOK_URL": _val("wework", "wework_webhook_url"),
            "WEWORK_MSG_TYPE": str(webhooks_cfg.get("wework_msg_type") or "markdown"),
            "TELEGRAM_BOT_TOKEN": _val("telegram", "telegram_bot_token"),
            "TELEGRAM_CHAT_ID": _val("telegram", "telegram_chat_id"),
            "EMAIL_FROM": _val("email", "email_from"),
            "EMAIL_PASSWORD": _val("email", "email_password"),
            "EMAIL_TO": _val("email", "email_to"),
            "EMAIL_SMTP_SERVER": _val("email", "email_smtp_server"),
            "EMAIL_SMTP_PORT": _val("email", "email_smtp_port"),
            "NTFY_SERVER_URL": _val("ntfy", "ntfy_server_url", "https://ntfy.sh"),
            "NTFY_TOPIC": _val("ntfy", "ntfy_topic"),
            "NTFY_TOKEN": _val("ntfy", "ntfy_token"),
            "BARK_URL": _val("bark", "bark_url"),
            "SLACK_WEBHOOK_URL": _val("slack", "slack_webhook_url"),
            "GENERIC_WEBHOOK_URL": _val("generic_webhook", "generic_webhook_url"),
            "GENERIC_WEBHOOK_TEMPLATE": _val(
                "generic_webhook", "generic_webhook_payload_template"
            ),
        }

    def _split_batches(
        self,
        report_data: Dict[str, Any],
        format_type: str,
        update_info: Optional[Dict[str, Any]] = None,
        max_bytes: Optional[int] = None,
        mode: str = "daily",
        rss_items: Optional[list] = None,
        rss_new_items: Optional[list] = None,
        ai_content: Optional[str] = None,
        standalone_data: Optional[Dict[str, Any]] = None,
        ai_stats: Optional[Dict[str, Any]] = None,
        report_type: str = "热点分析报告",
        **_: Any,
    ) -> List[str]:
        return split_content_into_batches(
            report_data=report_data,
            format_type=format_type,
            update_info=update_info,
            max_bytes=max_bytes,
            mode=mode,
            feishu_separator="---",
            region_order=["hotlist", "rss"],
            get_time_func=self._now,
            rss_items=rss_items,
            rss_new_items=rss_new_items,
            timezone=self._tz_name,
            display_mode="keyword",
            ai_content=ai_content,
            standalone_data=standalone_data,
            ai_stats=ai_stats,
            report_type=report_type,
            show_new_section=False,
        )

    def _make_dispatcher(self, legacy_cfg: Dict[str, Any]) -> Any:
        if self._dispatcher_factory is not None:
            return self._dispatcher_factory(legacy_cfg, self._now, self._split_batches)
        return NotificationDispatcher(
            config=legacy_cfg,
            get_time_func=self._now,
            split_content_func=self._split_batches,
            translator=None,
        )

    def send_test(self, channel: Optional[str] = None) -> List[WebhookChannelResultDTO]:
        """Send a connectivity test message to one channel or all configured channels.

        Args:
            channel: Optional specific channel key (`feishu`, `dingtalk`, etc.).

        Returns:
            List[WebhookChannelResultDTO]: Per-channel delivery status.

        Raises:
            WebhookConfigError: If `channel` is invalid or no configured channel is found.
        """
        webhooks_cfg = self._settings.get_internal_section("webhooks")
        legacy_cfg = self._build_legacy_config(webhooks_cfg, target_channel=channel)

        now = self._now()
        report_data = {
            "stats": [
                {
                    "word": "连通性测试",
                    "count": 1,
                    "titles": [
                        {
                            "title": f"TrendRadar 通知测试 ({now.strftime('%Y-%m-%d %H:%M:%S')})",
                            "source_name": "TrendRadar",
                            "url": "",
                            "mobile_url": "",
                            "ranks": [1],
                            "rank_threshold": 10,
                            "count": 1,
                            "is_new": True,
                            "time_display": now.strftime("%H:%M"),
                            "matched_keyword": "连通性测试",
                        }
                    ],
                }
            ],
            "failed_ids": [],
            "new_titles": [],
            "id_to_name": {},
        }

        dispatcher = self._make_dispatcher(legacy_cfg)
        with tempfile.TemporaryDirectory() as tmp_dir:
            html_file = Path(tmp_dir) / "webhook_test.html"
            html_file.write_text(
                f"<html><body><h3>TrendRadar 通知连通性测试 ({now.isoformat()})</h3></body></html>",
                encoding="utf-8",
            )
            results = dispatcher.dispatch_all(
                report_data=report_data,
                report_type="通知连通性测试",
                mode="daily",
                html_file_path=str(html_file),
                skip_translation=True,
            )

        if not results:
            raise WebhookConfigError("No configured notification channel matched")

        return [
            WebhookChannelResultDTO(
                channel=ch,
                success=bool(ok),
                message="sent" if ok else "delivery failed",
            )
            for ch, ok in results.items()
        ]

    def push_latest_summary(self) -> List[WebhookChannelResultDTO]:
        """Push keyword-matched recent items across enabled webhook channels.

        Returns:
            List[WebhookChannelResultDTO]: Delivery results per configured channel.
        """
        webhooks_cfg = self._settings.get_internal_section("webhooks")
        if not webhooks_cfg.get("enabled", False):
            return []

        kw_cfg = self._settings.get_internal_section("keywords")
        since_iso = (self._now() - timedelta(hours=24)).isoformat(timespec="seconds")
        items = self._news_repo.get_items_for_keywords(
            since_iso=since_iso,
            include_rss=bool(kw_cfg.get("include_rss", True)),
        )
        groups, _ = match_items_by_keyword_groups(items, str(kw_cfg.get("raw_text") or ""))
        if not groups:
            return []

        stats = []
        for grp in groups:
            titles = []
            for entry in grp["items"]:
                titles.append(
                    {
                        "title": entry["title"],
                        "source_name": entry["platform_name"],
                        "url": entry["url"],
                        "mobile_url": "",
                        "ranks": [entry["latest_rank"]] if entry["latest_rank"] else [1],
                        "rank_threshold": 10,
                        "count": 1,
                        "is_new": False,
                        "time_display": entry["last_seen_at"][11:16],
                        "matched_keyword": grp["display_name"],
                    }
                )
            stats.append({"word": grp["display_name"], "count": len(titles), "titles": titles})

        legacy_cfg = self._build_legacy_config(webhooks_cfg)
        dispatcher = self._make_dispatcher(legacy_cfg)
        results = dispatcher.dispatch_all(
            report_data={"stats": stats, "failed_ids": [], "new_titles": [], "id_to_name": {}},
            report_type="热点关键词汇总",
            mode="daily",
            skip_translation=True,
        )
        return [
            WebhookChannelResultDTO(
                channel=ch,
                success=bool(ok),
                message="sent" if ok else "delivery failed",
            )
            for ch, ok in results.items()
        ]
