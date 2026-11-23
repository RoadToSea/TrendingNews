"""First-run bootstrap service seeding admin user, settings, and default prompt templates."""

from datetime import datetime
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import zoneinfo

import yaml

from app.config import Settings
from app.repositories.chat_repo import ChatRepository
from app.repositories.db import Database
from app.repositories.settings_repo import SettingsRepository
from app.repositories.user_repo import UserRepository
from app.security import SecretCipher, generate_random_password, hash_password

logger = logging.getLogger(__name__)

_DEFAULT_CHAT_PROMPT = (
    "你是 TrendRadar 热点研判助手。请基于用户提供的热点新闻、媒体订阅与趋势脉络，"
    "采用结论先行、连贯清晰的简体中文叙述展开分析，注重多信源交叉印证与平台舆论温差；"
    "禁止在正文中暴露系统内部编号或参数名，尽量避免堆砌复杂表格，未提供的数据不要编造。"
)

_DEFAULT_DOMAINS: List[Dict[str, str]] = [
    {"id": "AI大模型", "name": "AI大模型", "description": "人工智能、大模型、芯片算力、开源生态"},
    {"id": "科技互联网", "name": "科技互联网", "description": "软硬件产品、消费电子、开发者生态"},
    {"id": "财经金融", "name": "财经金融", "description": "资本市场、宏观经济、财报与投融资"},
    {"id": "宏观政策", "name": "宏观政策", "description": "产业政策、监管法规、公共治理"},
    {"id": "国际地缘", "name": "国际地缘", "description": "国际政治、外交关系、全球突发事件"},
    {"id": "社会民生", "name": "社会民生", "description": "社会热点、消费民生、职场教育"},
    {"id": "其他", "name": "其他", "description": "未归入以上类别的热点信息"},
]

_DEFAULT_AUTHORITATIVE_PLATFORMS: List[Dict[str, Any]] = [
    {"id": "cankaoxiaoxi", "name": "参考消息", "enabled": True},
    {"id": "zaobao", "name": "联合早报", "enabled": True},
    {"id": "cls-telegraph", "name": "财联社电报", "enabled": True},
]

_DEFAULT_AUTHORITATIVE_RSS: List[Dict[str, Any]] = [
    {
        "id": "stats-zxfb",
        "name": "国家统计局 · 最新发布",
        "url": "https://www.stats.gov.cn/sj/zxfb/rss.xml",
        "domain": "宏观政策",
        "enabled": True,
        "max_age_days": 30,
        "max_items": 25,
    },
    {
        "id": "stats-sjjd",
        "name": "国家统计局 · 数据解读",
        "url": "https://www.stats.gov.cn/sj/sjjd/rss.xml",
        "domain": "宏观政策",
        "enabled": True,
        "max_age_days": 30,
        "max_items": 25,
    },
    {
        "id": "chinanews-import",
        "name": "中国新闻网 · 要闻导读",
        "url": "https://www.chinanews.com.cn/rss/importnews.xml",
        "domain": "宏观政策",
        "enabled": True,
        "max_age_days": 3,
        "max_items": 30,
    },
    {
        "id": "chinanews-china",
        "name": "中国新闻网 · 时政新闻",
        "url": "https://www.chinanews.com.cn/rss/china.xml",
        "domain": "宏观政策",
        "enabled": True,
        "max_age_days": 3,
        "max_items": 30,
    },
    {
        "id": "chinanews-finance",
        "name": "中国新闻网 · 财经新闻",
        "url": "https://www.chinanews.com.cn/rss/finance.xml",
        "domain": "财经金融",
        "enabled": True,
        "max_age_days": 3,
        "max_items": 30,
    },
    {
        "id": "chinanews-world",
        "name": "中国新闻网 · 国际新闻",
        "url": "https://www.chinanews.com.cn/rss/world.xml",
        "domain": "国际地缘",
        "enabled": True,
        "max_age_days": 3,
        "max_items": 30,
    },
    {
        "id": "jiemian",
        "name": "界面新闻",
        "url": "https://a.jiemian.com/index.php?m=article&a=rss",
        "domain": "财经金融",
        "enabled": True,
        "max_age_days": 3,
        "max_items": 30,
    },
    {
        "id": "gnews-xinhua",
        "name": "新华社 · news.cn (Google News 定向)",
        "url": "https://news.google.com/rss/search?q=site:news.cn+when:3d&hl=zh-CN&gl=CN&ceid=CN:zh",
        "domain": "宏观政策",
        "enabled": True,
        "max_age_days": 3,
        "max_items": 30,
    },
    {
        "id": "gnews-gov",
        "name": "中国政府网 · 国务院政策 (Google News 定向)",
        "url": "https://news.google.com/rss/search?q=site:gov.cn+when:7d&hl=zh-CN&gl=CN&ceid=CN:zh",
        "domain": "宏观政策",
        "enabled": True,
        "max_age_days": 14,
        "max_items": 25,
    },
    {
        "id": "ft-home",
        "name": "Financial Times 金融时报",
        "url": "https://www.ft.com/rss/home",
        "domain": "财经金融",
        "enabled": True,
        "max_age_days": 3,
        "max_items": 20,
    },
    {
        "id": "nature-news",
        "name": "Nature 自然期刊",
        "url": "https://www.nature.com/nature.rss",
        "domain": "科技互联网",
        "enabled": True,
        "max_age_days": 7,
        "max_items": 25,
    },
]

_DEFAULT_FOREIGN_RSS: List[Dict[str, Any]] = [
    {
        "id": "gnews-world",
        "name": "Google News World",
        "url": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
        "domain": "国际地缘",
        "enabled": True,
        "max_age_days": 2,
    },
    {
        "id": "gnews-tech",
        "name": "Google News Technology",
        "url": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
        "domain": "科技互联网",
        "enabled": True,
        "max_age_days": 2,
    },
    {
        "id": "gnews-business",
        "name": "Google News Business",
        "url": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
        "domain": "财经金融",
        "enabled": True,
        "max_age_days": 2,
    },
    {
        "id": "bbc-world",
        "name": "BBC World News",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "domain": "国际地缘",
        "enabled": True,
        "max_age_days": 2,
    },
    {
        "id": "guardian-world",
        "name": "The Guardian World",
        "url": "https://www.theguardian.com/world/rss",
        "domain": "国际地缘",
        "enabled": True,
        "max_age_days": 2,
    },
    {
        "id": "techcrunch",
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "domain": "科技互联网",
        "enabled": True,
        "max_age_days": 2,
    },
    {
        "id": "theverge",
        "name": "The Verge",
        "url": "https://www.theverge.com/rss/index.xml",
        "domain": "科技互联网",
        "enabled": True,
        "max_age_days": 2,
    },
    {
        "id": "arstechnica",
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "domain": "科技互联网",
        "enabled": True,
        "max_age_days": 2,
    },
]

_SECRET_WEBHOOK_FIELDS = (
    "feishu_webhook_url",
    "dingtalk_webhook_url",
    "wework_webhook_url",
    "telegram_bot_token",
    "email_password",
    "ntfy_token",
    "bark_url",
    "slack_webhook_url",
    "generic_webhook_url",
)


class BootstrapService:
    """Seeds database schema, initial admin user, default config sections, and prompt templates."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        user_repo: UserRepository,
        settings_repo: SettingsRepository,
        chat_repo: ChatRepository,
        cipher: SecretCipher,
    ) -> None:
        """Initialize bootstrap service dependencies.

        Args:
            settings: Application settings.
            db: Database coordinator.
            user_repo: User repository.
            settings_repo: Settings repository.
            chat_repo: Chat/prompt repository.
            cipher: Cipher used to encrypt any legacy webhook secrets imported on first boot.
        """
        self._settings = settings
        self._db = db
        self._user_repo = user_repo
        self._settings_repo = settings_repo
        self._chat_repo = chat_repo
        self._cipher = cipher
        self._tz = zoneinfo.ZoneInfo(settings.timezone)

    def _now_iso(self) -> str:
        return datetime.now(self._tz).isoformat(timespec="seconds")

    def run(self) -> Optional[str]:
        """Initialize schema and seed missing defaults idempotently.

        Returns:
            Optional[str]: Generated random admin password if auto-generated, otherwise None.
        """
        self._db.init_schema()
        now_iso = self._now_iso()
        generated_password = self._seed_admin_user(now_iso)
        defaults = self._build_default_sections()
        self._settings_repo.ensure_defaults(defaults, now_iso)
        self._chat_repo.ensure_default_prompt_template(
            name="默认热点研判助手",
            content=_DEFAULT_CHAT_PROMPT,
            now_iso=now_iso,
        )
        self._chat_repo.ensure_default_antigravity_provider(now_iso)
        return generated_password

    def _seed_admin_user(self, now_iso: str) -> Optional[str]:
        if self._user_repo.count() > 0:
            return None
        password = self._settings.admin_pass.strip()
        generated: Optional[str] = None
        if not password:
            password = generate_random_password(16)
            generated = password
            logger.warning(
                "Generated initial admin password for user '%s': %s (change it immediately after login)",
                self._settings.admin_user,
                password,
            )
        self._user_repo.create(
            username=self._settings.admin_user,
            password_hash=hash_password(password),
            now_iso=now_iso,
            role="admin",
        )
        return generated

    def _load_legacy_yaml(self) -> Dict[str, Any]:
        config_path = self._settings.resolved_legacy_root() / "config" / "config.yaml"
        if not config_path.is_file():
            return {}
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Failed to parse legacy config.yaml: %s", exc)
            return {}

    def _load_legacy_keywords_text(self) -> str:
        kw_path = self._settings.resolved_legacy_root() / "config" / "frequency_words.txt"
        if not kw_path.is_file():
            return ""
        try:
            return kw_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to read legacy frequency_words.txt: %s", exc)
            return ""

    def _build_default_sections(self) -> Dict[str, Dict[str, Any]]:
        legacy = self._load_legacy_yaml()
        platforms_raw = legacy.get("platforms", {}) or {}
        rss_raw = legacy.get("rss", {}) or {}
        adv = legacy.get("advanced", {}) or {}
        adv_crawler = adv.get("crawler", {}) or {}
        adv_rss = adv.get("rss", {}) or {}
        notif_raw = legacy.get("notification", {}) or {}
        channels = notif_raw.get("channels", {}) or {}

        platform_sources = list(platforms_raw.get("sources", []) or [])
        existing_platform_ids = {s.get("id") for s in platform_sources if isinstance(s, dict)}
        for default_platform in _DEFAULT_AUTHORITATIVE_PLATFORMS:
            if default_platform["id"] not in existing_platform_ids:
                platform_sources.append(dict(default_platform))

        rss_feeds = [
            dict(f)
            for f in (rss_raw.get("feeds", []) or [])
            if isinstance(f, dict)
            and f.get("id") != "yahoo-finance"
            and "finance.yahoo.com/news/rssindex" not in str(f.get("url", ""))
        ]
        existing_feed_ids = {f.get("id") for f in rss_feeds}
        for default_feed in (*_DEFAULT_AUTHORITATIVE_RSS, *_DEFAULT_FOREIGN_RSS):
            if default_feed["id"] not in existing_feed_ids:
                rss_feeds.append(dict(default_feed))
                existing_feed_ids.add(default_feed["id"])

        webhooks_payload = {
            "enabled": bool(notif_raw.get("enabled", False)),
            "feishu_webhook_url": str((channels.get("feishu") or {}).get("webhook_url", "")),
            "dingtalk_webhook_url": str((channels.get("dingtalk") or {}).get("webhook_url", "")),
            "wework_webhook_url": str((channels.get("wework") or {}).get("webhook_url", "")),
            "wework_msg_type": str((channels.get("wework") or {}).get("msg_type", "markdown")),
            "telegram_bot_token": str((channels.get("telegram") or {}).get("bot_token", "")),
            "telegram_chat_id": str((channels.get("telegram") or {}).get("chat_id", "")),
            "email_from": str((channels.get("email") or {}).get("from", "")),
            "email_password": str((channels.get("email") or {}).get("password", "")),
            "email_to": str((channels.get("email") or {}).get("to", "")),
            "email_smtp_server": str((channels.get("email") or {}).get("smtp_server", "")),
            "email_smtp_port": str((channels.get("email") or {}).get("smtp_port", "")),
            "ntfy_server_url": str((channels.get("ntfy") or {}).get("server_url", "https://ntfy.sh")),
            "ntfy_topic": str((channels.get("ntfy") or {}).get("topic", "")),
            "ntfy_token": str((channels.get("ntfy") or {}).get("token", "")),
            "bark_url": str((channels.get("bark") or {}).get("url", "")),
            "slack_webhook_url": str((channels.get("slack") or {}).get("webhook_url", "")),
            "generic_webhook_url": str((channels.get("generic_webhook") or {}).get("webhook_url", "")),
            "generic_webhook_payload_template": str(
                (channels.get("generic_webhook") or {}).get("payload_template", "")
            ),
        }
        for key in _SECRET_WEBHOOK_FIELDS:
            val = webhooks_payload[key].strip()
            webhooks_payload[key] = f"enc:{self._cipher.encrypt(val)}" if val else ""

        return {
            "platforms": {
                "enabled": bool(platforms_raw.get("enabled", True)),
                "api_url": str(platforms_raw.get("api_url", "")),
                "request_interval_ms": int(adv_crawler.get("request_interval", 200)),
                "use_proxy": bool(adv_crawler.get("use_proxy", False)),
                "proxy_url": str(adv_crawler.get("default_proxy", "")),
                "sources": platform_sources,
            },
            "rss": {
                "enabled": bool(rss_raw.get("enabled", True)),
                "request_interval_ms": int(adv_rss.get("request_interval", 500)),
                "timeout_sec": int(adv_rss.get("timeout", 15)),
                "use_proxy": bool(adv_rss.get("use_proxy", False)),
                "proxy_url": str(adv_rss.get("proxy_url", "")),
                "freshness_enabled": bool((rss_raw.get("freshness_filter") or {}).get("enabled", True)),
                "max_age_days": int((rss_raw.get("freshness_filter") or {}).get("max_age_days", 2)),
                "feeds": rss_feeds,
            },
            "keywords": {
                "raw_text": self._load_legacy_keywords_text(),
                "include_rss": True,
            },
            "domains": {
                "items": _DEFAULT_DOMAINS,
            },
            "webhooks": webhooks_payload,
            "schedule": {
                "crawl_interval_minutes": 30,
                "daily_report_time": "22:00",
                "retention_days": 30,
                "push_on_crawl": False,
            },
            "trends": {
                "daily_top_n": 10,
                "default_days": 14,
                "weights": {
                    "coverage": 0.35,
                    "rank": 0.35,
                    "persistence": 0.20,
                    "velocity": 0.10,
                },
            },
            "foreign_sources": {
                "proxy_url": "",
                "hackernews_enabled": True,
                "hackernews_min_score": 80,
                "hackernews_limit": 25,
                "huggingface_enabled": True,
                "huggingface_limit": 20,
                "github_enabled": True,
                "github_token": "",
                "github_min_stars": 50,
                "github_limit": 20,
                "reddit_enabled": False,
                "reddit_user_agent": "TrendRadar/1.0 (personal self-hosted reader)",
                "reddit_subreddits": ["MachineLearning", "LocalLLaMA", "technology", "worldnews", "stocks"],
                "reddit_min_ups": 100,
                "youtube_enabled": True,
                "youtube_channels": [],
            },
        }
