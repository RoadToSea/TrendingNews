"""Native 4-channel webhook notification service with per-user incremental delivery."""

from datetime import datetime, timedelta
import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import zoneinfo

import requests

from app.models import WebhookChannelResultDTO
from app.repositories.news_repo import NewsRepository
from app.repositories.settings_repo import SettingsRepository
from app.services.keyword_service import match_items_by_keyword_groups
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

_SUPPORTED_CHANNELS = ("feishu", "dingtalk", "wework", "generic_webhook")

_CHANNEL_URL_KEYS: Dict[str, str] = {
    "feishu": "feishu_webhook_url",
    "dingtalk": "dingtalk_webhook_url",
    "wework": "wework_webhook_url",
    "generic_webhook": "generic_webhook_url",
}

_CHANNEL_MAX_BYTES: Dict[str, int] = {
    "feishu": 29000,
    "dingtalk": 20000,
    "wework": 4000,
    "generic_webhook": 4000,
}

HttpPostFunc = Callable[[str, Dict[str, Any]], Tuple[int, Any]]


class WebhookConfigError(Exception):
    """Raised when webhook channel selection or configuration is invalid."""


def _default_http_post(url: str, payload: Dict[str, Any]) -> Tuple[int, Any]:
    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body


def _strip_markdown(text: str) -> str:
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    return cleaned.replace("**", "").replace("__", "")


def _format_summary_markdown(
    report_type: str,
    groups: List[Dict[str, Any]],
    now: datetime,
) -> str:
    lines = [f"**{report_type}** ({now.strftime('%Y-%m-%d %H:%M')})", ""]
    for grp in groups:
        lines.append(f"**{grp['display_name']}** ({grp['count']})")
        for idx, entry in enumerate(grp["items"], start=1):
            title = str(entry.get("title") or "").strip()
            source = str(entry.get("platform_name") or "").strip()
            url = str(entry.get("url") or "").strip()
            seen = str(entry.get("last_seen_at") or "")[11:16]
            title_part = f"[{title}]({url})" if url else title
            meta_parts = [part for part in (source, seen) if part]
            suffix = f" ({' · '.join(meta_parts)})" if meta_parts else ""
            lines.append(f"{idx}. {title_part}{suffix}")
        lines.append("")
    return "\n".join(lines).strip()


def _split_utf8_batches(text: str, max_bytes: int) -> List[str]:
    if not text:
        return [""]
    # Reserve space for the "[第 i/n 批]" prefix added when output spans multiple batches.
    budget = max(256, max_bytes - 64)
    if len(text.encode("utf-8")) <= budget:
        return [text]

    batches: List[str] = []
    current_lines: List[str] = []
    current_bytes = 0

    for line in text.splitlines():
        line_bytes = len((line + "\n").encode("utf-8"))
        if line_bytes > budget:
            if current_lines:
                batches.append("\n".join(current_lines))
                current_lines = []
                current_bytes = 0
            batches.extend(_chunk_long_line(line, budget))
            continue

        if current_lines and current_bytes + line_bytes > budget:
            batches.append("\n".join(current_lines))
            current_lines = [line]
            current_bytes = line_bytes
        else:
            current_lines.append(line)
            current_bytes += line_bytes

    if current_lines:
        batches.append("\n".join(current_lines))

    total = len(batches)
    if total <= 1:
        return batches
    return [f"[第 {idx}/{total} 批]\n{chunk}" for idx, chunk in enumerate(batches, start=1)]


def _chunk_long_line(line: str, budget: int) -> List[str]:
    chunks: List[str] = []
    buf: List[str] = []
    used = 0
    for ch in line:
        ch_bytes = len(ch.encode("utf-8"))
        if buf and used + ch_bytes > budget:
            chunks.append("".join(buf))
            buf = [ch]
            used = ch_bytes
        else:
            buf.append(ch)
            used += ch_bytes
    if buf:
        chunks.append("".join(buf))
    return chunks


def _build_channel_payload(
    channel: str,
    url: str,
    report_type: str,
    content: str,
    webhooks_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    if channel == "feishu":
        if "www.feishu.cn" in url:
            return {"msg_type": "text", "content": {"text": content}}
        return {
            "msg_type": "interactive",
            "card": {
                "schema": "2.0",
                "body": {"elements": [{"tag": "markdown", "content": content}]},
            },
        }
    if channel == "dingtalk":
        return {
            "msgtype": "markdown",
            "markdown": {"title": f"TrendRadar - {report_type}", "text": content},
        }
    if channel == "wework":
        msg_type = str(webhooks_cfg.get("wework_msg_type") or "markdown").lower()
        if msg_type == "text":
            return {"msgtype": "text", "text": {"content": _strip_markdown(content)}}
        return {"msgtype": "markdown", "markdown": {"content": content}}

    template = str(webhooks_cfg.get("generic_webhook_payload_template") or "").strip()
    if template:
        json_content = json.dumps(content, ensure_ascii=False)[1:-1]
        json_title = json.dumps(report_type, ensure_ascii=False)[1:-1]
        rendered = template.replace("{content}", json_content).replace("{title}", json_title)
        try:
            parsed = json.loads(rendered)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            logger.warning("Invalid generic webhook template JSON (%s); using default payload", exc)
    return {"title": report_type, "content": content}


def _is_delivery_ok(channel: str, status_code: int, body: Any) -> bool:
    if channel == "feishu":
        return status_code == 200 and isinstance(body, dict) and (
            body.get("StatusCode") == 0 or body.get("code") == 0
        )
    if channel in ("dingtalk", "wework"):
        return status_code == 200 and isinstance(body, dict) and body.get("errcode") == 0
    return 200 <= status_code < 300


class WebhookService:
    """Native webhook service sending test pings and per-user incremental keyword summaries."""

    def __init__(
        self,
        settings_service: SettingsService,
        settings_repo: SettingsRepository,
        news_repo: NewsRepository,
        timezone_name: str,
        http_post: Optional[HttpPostFunc] = None,
    ) -> None:
        """Initialize the webhook service.

        Args:
            settings_service: Settings service supplying per-user decrypted webhooks/keywords.
            settings_repo: Settings repository persisting delivery deduplication markers.
            news_repo: Repository reading recent items for scheduled keyword summary pushes.
            timezone_name: Application IANA timezone name.
            http_post: Optional HTTP POST callable `(url, payload) -> (status_code, body)` for tests.
        """
        self._settings = settings_service
        self._settings_repo = settings_repo
        self._news_repo = news_repo
        self._tz = zoneinfo.ZoneInfo(timezone_name)
        self._http_post: HttpPostFunc = http_post or _default_http_post

    def _now(self) -> datetime:
        return datetime.now(self._tz)

    def _send_to_channel(
        self,
        channel: str,
        raw_urls: str,
        webhooks_cfg: Dict[str, Any],
        report_type: str,
        content: str,
    ) -> bool:
        urls = [item.strip() for item in raw_urls.split(";") if item.strip()]
        if not urls:
            return False

        batches = _split_utf8_batches(content, _CHANNEL_MAX_BYTES[channel])
        all_ok = True
        for url in urls:
            for idx, batch in enumerate(batches):
                payload = _build_channel_payload(channel, url, report_type, batch, webhooks_cfg)
                try:
                    status_code, body = self._http_post(url, payload)
                except Exception as exc:
                    logger.warning("Webhook %s delivery error: %s", channel, exc)
                    all_ok = False
                    break
                if not _is_delivery_ok(channel, status_code, body):
                    logger.warning("Webhook %s rejected (status=%s)", channel, status_code)
                    all_ok = False
                    break
                if idx + 1 < len(batches):
                    time.sleep(1.0)
        return all_ok

    def _dispatch(
        self,
        webhooks_cfg: Dict[str, Any],
        report_type: str,
        content: str,
        target_channel: Optional[str] = None,
    ) -> List[WebhookChannelResultDTO]:
        if target_channel is not None and target_channel not in _SUPPORTED_CHANNELS:
            raise WebhookConfigError(f"Unsupported webhook channel: {target_channel}")

        channels = (target_channel,) if target_channel is not None else _SUPPORTED_CHANNELS
        results: List[WebhookChannelResultDTO] = []
        for channel in channels:
            raw_url = str(webhooks_cfg.get(_CHANNEL_URL_KEYS[channel]) or "").strip()
            if not raw_url:
                continue
            ok = self._send_to_channel(channel, raw_url, webhooks_cfg, report_type, content)
            results.append(
                WebhookChannelResultDTO(
                    channel=channel,
                    success=ok,
                    message="sent" if ok else "delivery failed",
                )
            )
        return results

    def send_test(
        self,
        user_id: int,
        channel: Optional[str] = None,
        *,
        user_role: str = "user",
    ) -> List[WebhookChannelResultDTO]:
        """Send a connectivity test message to the calling user's configured channels.

        Args:
            user_id: Authenticated user ID.
            channel: Optional channel key (`feishu`, `dingtalk`, `wework`, `generic_webhook`).
            user_role: Authenticated user role.

        Returns:
            List[WebhookChannelResultDTO]: Per-channel delivery status.

        Raises:
            WebhookConfigError: If `channel` is invalid or no configured channel is found.
        """
        webhooks_cfg = self._settings.get_user_internal_section(
            user_id,
            "webhooks",
            user_role=user_role,
        )
        now = self._now()
        content = (
            f"**TrendRadar 通知连通性测试**\n"
            f"- 时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- 状态：Webhook 通道配置正常"
        )
        results = self._dispatch(
            webhooks_cfg,
            report_type="通知连通性测试",
            content=content,
            target_channel=channel,
        )
        if not results:
            raise WebhookConfigError("No configured notification channel matched")
        return results

    def push_incremental_for_all_users(self) -> Dict[int, List[WebhookChannelResultDTO]]:
        """Fan out newly matched items per active user with independent deduplication.

        Returns:
            Dict[int, List[WebhookChannelResultDTO]]: Delivery results keyed by `user_id`.
        """
        user_configs = self._settings.list_active_user_webhooks()
        enabled_users = [
            (uid, cfg)
            for uid, cfg in user_configs
            if cfg.get("enabled", False)
            and any(str(cfg.get(_CHANNEL_URL_KEYS[ch]) or "").strip() for ch in _SUPPORTED_CHANNELS)
        ]
        if not enabled_users:
            return {}

        now = self._now()
        now_iso = now.isoformat(timespec="seconds")
        since_iso = (now - timedelta(hours=24)).isoformat(timespec="seconds")
        all_items = self._news_repo.get_items_for_keywords(since_iso=since_iso, include_rss=True)
        hotlist_items = [item for item in all_items if item.get("source_type") != "rss"]
        if not all_items:
            return {}

        deliveries: Dict[int, List[WebhookChannelResultDTO]] = {}
        for uid, webhooks_cfg in enabled_users:
            try:
                results = self._push_for_single_user(
                    uid,
                    webhooks_cfg,
                    all_items=all_items,
                    hotlist_items=hotlist_items,
                    now=now,
                    now_iso=now_iso,
                )
                if results:
                    deliveries[uid] = results
            except Exception:
                logger.exception("Incremental webhook delivery failed for user_id=%s", uid)

        cutoff_iso = (now - timedelta(days=7)).isoformat(timespec="seconds")
        self._settings_repo.prune_old_deliveries(cutoff_iso)
        return deliveries

    def _push_for_single_user(
        self,
        user_id: int,
        webhooks_cfg: Dict[str, Any],
        *,
        all_items: List[Dict[str, Any]],
        hotlist_items: List[Dict[str, Any]],
        now: datetime,
        now_iso: str,
    ) -> List[WebhookChannelResultDTO]:
        kw_cfg = self._settings.get_user_internal_section(user_id, "keywords")
        raw_text = str(kw_cfg.get("raw_text") or "")
        if not raw_text.strip():
            return []

        source_pool = all_items if bool(kw_cfg.get("include_rss", True)) else hotlist_items
        groups, _ = match_items_by_keyword_groups(source_pool, raw_text)
        if not groups:
            return []

        delivered = self._settings_repo.get_delivered_keys(user_id)
        fresh_groups: List[Dict[str, Any]] = []
        fresh_keys: List[Tuple[str, int]] = []
        for grp in groups:
            fresh_items = [
                entry
                for entry in grp["items"]
                if (str(entry.get("source_type") or "hotlist"), int(entry["id"])) not in delivered
            ]
            if not fresh_items:
                continue
            fresh_groups.append(
                {
                    "group_key": grp["group_key"],
                    "display_name": grp["display_name"],
                    "count": len(fresh_items),
                    "items": fresh_items,
                }
            )
            for entry in fresh_items:
                fresh_keys.append((str(entry.get("source_type") or "hotlist"), int(entry["id"])))

        if not fresh_groups:
            return []

        content = _format_summary_markdown("热点关键词增量推送", fresh_groups, now)
        results = self._dispatch(webhooks_cfg, report_type="热点关键词增量推送", content=content)
        if any(r.success for r in results):
            unique_keys = list(dict.fromkeys(fresh_keys))
            self._settings_repo.record_deliveries(user_id, unique_keys, now_iso)
        return results
