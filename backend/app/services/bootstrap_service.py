"""First-run bootstrap service seeding admin user, settings, and default prompt templates."""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional
import zoneinfo

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

_DEFAULT_DOMESTIC_PLATFORMS: List[Dict[str, Any]] = [
    {"id": "toutiao", "name": "今日头条", "expected_domain": "toutiao.com"},
    {"id": "baidu", "name": "百度热搜", "expected_domain": "baidu.com"},
    {"id": "wallstreetcn-hot", "name": "华尔街见闻", "expected_domain": "wallstreetcn.com"},
    {"id": "thepaper", "name": "澎湃新闻", "expected_domain": "thepaper.cn"},
    {"id": "bilibili-hot-search", "name": "bilibili 热搜", "expected_domain": "bilibili.com"},
    {"id": "cls-hot", "name": "财联社热门", "expected_domain": "cls.cn"},
    {"id": "ifeng", "name": "凤凰网", "expected_domain": "ifeng.com"},
    {"id": "tieba", "name": "贴吧", "expected_domain": "baidu.com"},
    {"id": "weibo", "name": "微博", "expected_domain": "weibo.com"},
    {"id": "douyin", "name": "抖音", "expected_domain": "douyin.com"},
    {"id": "zhihu", "name": "知乎", "expected_domain": "zhihu.com"},
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
        "id": "hacker-news",
        "name": "Hacker News",
        "url": "https://hnrss.org/frontpage",
        "domain": "科技互联网",
        "enabled": True,
        "max_age_days": 2,
    },
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

_DEFAULT_KEYWORDS_TEXT = """[GLOBAL_FILTER]
震惊

[WORD_GROUPS]
/胖东来|于东来/ => 胖东来

/深度求索|幻方量化|梁文锋|\\bDeepSeek\\b/ => DeepSeek

/华为|任正非|余承东|鸿蒙|海思|昇腾|鲲鹏|\\bHUAWEI\\b|\\bHarmonyOS\\b|\\bHiSilicon\\b/ => 华为

/比亚迪|王传福|方程豹|腾势|仰望|弗迪|刀片电池|云辇|\\bBYD\\b|\\bDenza\\b|\\bYangwang\\b/ => 比亚迪

/大疆|汪滔|灵眸|如影|\\bDJI\\b|\\bRoboMaster\\b|\\bMavic\\b|\\bZenmuse\\b/ => 大疆

/宇树|王兴兴|\\bUnitree\\b/ => 宇树机器人

/智元|灵犀|稚晖君|彭志辉|AgiBot/ => 智元机器人

/众擎|EngineAI|赵同阳/ => 众擎机器人

/黑神话|冯骥/ => 黑神话悟空

/影之刃零|梁其伟/ => 影之刃零

/三体|流浪地球|刘慈欣|郭帆/ => 三体/流浪地球

申奥

/京东|刘强东|\\bJD\\b|\\bJingdong\\b/ => 京东

/字节|张一鸣|梁汝波|抖音|\\bByteDance\\b|\\bTikTok\\b|\\bDouyin\\b|\\bLark\\b|\\bCapCut\\b/ => 字节跳动

/腾讯|鹅厂|马化腾|微信|QQ|天美|阅文集团|微众银行|\\bTencent\\b|\\bPony Ma\\b|\\bWeChat\\b|\\bLightSpeed\\b|\\bWeBank\\b/ => 腾讯

/qwen|minimax|glm/ => 国产开源模型

/特斯拉|马斯克|\\bTesla\\b|\\bElon Musk\\b|\\bCybertruck\\b|\\bModel 3\\b|\\bModel Y\\b|\\bModel S\\b|\\bModel X\\b|\\bFSD\\b/ => 特斯拉

/英伟达|黄仁勋|\\bNVIDIA\\b|\\bGeForce\\b|\\bRTX\\b|\\bCUDA\\b|\\bJensen Huang\\b/ => 英伟达

/苏姿丰|锐龙|霄龙|\\bAMD\\b|\\bRyzen\\b|\\bEPYC\\b|\\bRadeon\\b|\\bLisa Su\\b/ => AMD

/微软|\\bMicrosoft\\b|\\bWindows\\b|\\bAzure\\b|\\bSatya Nadella\\b|\\bCopilot\\b/ => 微软

/谷歌|皮查伊|安卓|油管|\\bGoogle\\b|\\bAlphabet\\b|\\bAndroid\\b|\\bChrome\\b|\\bYouTube\\b|\\bGemini\\b|\\bDeepMind\\b|\\bWaymo\\b/ => 谷歌

/库克|\\biPhone\\b|\\biPad\\b|\\bMacBook\\b|\\biOS\\b|\\bVision Pro\\b|\\bAirPods\\b|\\bApple\\b|\\bTim Cook\\b/ => 苹果

/\\bOpenAI\\b|\\bChatGPT\\b|\\bSora\\b|\\bDALL-E\\b|\\bSam Altman\\b|\\bGreg Brockman\\b/ => OpenAI

/\\bAnthropic\\b|\\bClaude\\b|\\bDario Amodei\\b/ => Claude

[中国]
国产
中国

[东亚]
日本
朝鲜
韩国

[北美]
美国
加拿大

[西欧]
法国
英国

/俄罗斯|俄国/ => 俄罗斯

印度

[AI 相关]
/(?<![a-zA-Z])ai(?![a-zA-Z])/
人工智能

[芯片]
芯片
光刻机
半导体

/水电|雅鲁藏布江/ => 水电

/光伏|太阳能/ => 光伏

核能

能源

/自动驾驶|无人驾驶|智驾/ => 自动驾驶

机器人

/机械狗|四足/ => 机器狗

具身智能

/月球|登月|火星|宇宙|飞船|航天|空间站|卫星/ => 航天

量子

脑机

基因

生产力"""


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

    def _build_default_sections(self) -> Dict[str, Dict[str, Any]]:
        platform_sources = [dict(item) for item in _DEFAULT_DOMESTIC_PLATFORMS]
        rss_feeds = [dict(item) for item in (*_DEFAULT_AUTHORITATIVE_RSS, *_DEFAULT_FOREIGN_RSS)]

        webhooks_payload = {
            "enabled": False,
            "feishu_webhook_url": "",
            "dingtalk_webhook_url": "",
            "wework_webhook_url": "",
            "wework_msg_type": "markdown",
            "generic_webhook_url": "",
            "generic_webhook_payload_template": "",
        }

        return {
            "platforms": {
                "enabled": True,
                "api_url": "",
                "request_interval_ms": 200,
                "use_proxy": False,
                "proxy_url": "",
                "sources": platform_sources,
            },
            "rss": {
                "enabled": True,
                "request_interval_ms": 500,
                "timeout_sec": 15,
                "use_proxy": False,
                "proxy_url": "",
                "freshness_enabled": True,
                "max_age_days": 2,
                "feeds": rss_feeds,
            },
            "keywords": {
                "raw_text": _DEFAULT_KEYWORDS_TEXT,
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
