export interface PlatformSource {
  id: string;
  name: string;
  enabled?: boolean;
  expected_domain?: string;
}

export interface RssFeedCfg {
  id: string;
  name: string;
  url: string;
  domain?: string;
  enabled?: boolean;
  max_age_days?: number;
  max_items?: number;
}

export interface DomainItemCfg {
  id: string;
  name: string;
  description: string;
}

export interface PlatformPreset {
  id: string;
  name: string;
  description: string;
}

export interface RssPreset extends RssFeedCfg {
  category: "domestic_direct" | "official_proxy" | "international_proxy";
  needsProxy: boolean;
  note: string;
}

export const AUTHORITATIVE_PLATFORM_PRESETS: PlatformPreset[] = [
  { id: "cankaoxiaoxi", name: "参考消息", description: "新华社主管主办，国际时政与深度报道" },
  { id: "zaobao", name: "联合早报", description: "华语权威时政财经新闻媒体" },
  { id: "cls-telegraph", name: "财联社电报", description: "A股及全球宏观金融 7x24 实时快讯" },
  { id: "cls-depth", name: "财联社深度", description: "资本市场与产业经济深度报道" },
  { id: "wallstreetcn-quick", name: "华尔街见闻快讯", description: "全球市场宏观与财经实时动态" },
  { id: "jin10", name: "金十数据", description: "外汇、大宗商品与央行政策快讯" },
  { id: "kaopu", name: "靠谱新闻", description: "精选科技与产业资讯聚合" },
  { id: "solidot", name: "Solidot 奇客", description: "开源软件、互联网技术与科学动态" },
  { id: "gelonghui", name: "格隆汇", description: "港美股与宏观财经要闻" },
];

export const AUTHORITATIVE_RSS_PRESETS: RssPreset[] = [
  {
    id: "stats-zxfb",
    name: "国家统计局 · 最新发布",
    url: "https://www.stats.gov.cn/sj/zxfb/rss.xml",
    domain: "宏观政策",
    enabled: true,
    max_age_days: 30,
    max_items: 25,
    category: "domestic_direct",
    needsProxy: false,
    note: "国家统计局官网月度/季度经济统计公报（免代理直连）",
  },
  {
    id: "stats-sjjd",
    name: "国家统计局 · 数据解读",
    url: "https://www.stats.gov.cn/sj/sjjd/rss.xml",
    domain: "宏观政策",
    enabled: true,
    max_age_days: 30,
    max_items: 25,
    category: "domestic_direct",
    needsProxy: false,
    note: "官方经济运行解读与新闻发布会实录（免代理直连）",
  },
  {
    id: "chinanews-import",
    name: "中国新闻网 · 要闻导读",
    url: "https://www.chinanews.com.cn/rss/importnews.xml",
    domain: "宏观政策",
    enabled: true,
    max_age_days: 3,
    max_items: 30,
    category: "domestic_direct",
    needsProxy: false,
    note: "中新社重点时政要闻官方 XML（免代理直连）",
  },
  {
    id: "chinanews-china",
    name: "中国新闻网 · 时政新闻",
    url: "https://www.chinanews.com.cn/rss/china.xml",
    domain: "宏观政策",
    enabled: true,
    max_age_days: 3,
    max_items: 30,
    category: "domestic_direct",
    needsProxy: false,
    note: "国内时政、政策与公共治理新闻（免代理直连）",
  },
  {
    id: "chinanews-finance",
    name: "中国新闻网 · 财经新闻",
    url: "https://www.chinanews.com.cn/rss/finance.xml",
    domain: "财经金融",
    enabled: true,
    max_age_days: 3,
    max_items: 30,
    category: "domestic_direct",
    needsProxy: false,
    note: "国内宏观经济、金融与产业财经（免代理直连）",
  },
  {
    id: "chinanews-world",
    name: "中国新闻网 · 国际新闻",
    url: "https://www.chinanews.com.cn/rss/world.xml",
    domain: "国际地缘",
    enabled: true,
    max_age_days: 3,
    max_items: 30,
    category: "domestic_direct",
    needsProxy: false,
    note: "国际外交与全球热点新闻（免代理直连）",
  },
  {
    id: "jiemian",
    name: "界面新闻",
    url: "https://a.jiemian.com/index.php?m=article&a=rss",
    domain: "财经金融",
    enabled: true,
    max_age_days: 3,
    max_items: 30,
    category: "domestic_direct",
    needsProxy: false,
    note: "国内主流商业财经原创媒体官方 RSS（免代理直连）",
  },
  {
    id: "gnews-xinhua",
    name: "新华社 · news.cn (Google News 定向)",
    url: "https://news.google.com/rss/search?q=site:news.cn+when:3d&hl=zh-CN&gl=CN&ceid=CN:zh",
    domain: "宏观政策",
    enabled: true,
    max_age_days: 3,
    max_items: 30,
    category: "official_proxy",
    needsProxy: true,
    note: "新华网原 XML 已停更，通过 Google News 定向跟踪近 3 天更新（需代理/海外服务器）",
  },
  {
    id: "gnews-gov",
    name: "中国政府网 · 国务院政策 (Google News 定向)",
    url: "https://news.google.com/rss/search?q=site:gov.cn+when:7d&hl=zh-CN&gl=CN&ceid=CN:zh",
    domain: "宏观政策",
    enabled: true,
    max_age_days: 14,
    max_items: 25,
    category: "official_proxy",
    needsProxy: true,
    note: "gov.cn 未提供原生 XML，通过 Google News 定向跟踪近 7 天政策（需代理/海外服务器）",
  },
  {
    id: "gnews-ndrc",
    name: "国家发改委 · ndrc.gov.cn (Google News 定向)",
    url: "https://news.google.com/rss/search?q=site:ndrc.gov.cn+when:14d&hl=zh-CN&gl=CN&ceid=CN:zh",
    domain: "宏观政策",
    enabled: true,
    max_age_days: 30,
    max_items: 25,
    category: "official_proxy",
    needsProxy: true,
    note: "定向追踪发改委近 14 天产业与宏观调控政策（需代理/海外服务器）",
  },
  {
    id: "gnews-reuters",
    name: "Reuters 路透社",
    url: "https://news.google.com/rss/search?q=site:reuters.com+when:2d&hl=en-US&gl=US&ceid=US:en",
    domain: "国际地缘",
    enabled: true,
    max_age_days: 2,
    max_items: 30,
    category: "international_proxy",
    needsProxy: true,
    note: "全球财经与地缘新闻通讯社（需代理/海外服务器）",
  },
  {
    id: "ft-home",
    name: "Financial Times 金融时报",
    url: "https://www.ft.com/rss/home",
    domain: "财经金融",
    enabled: true,
    max_age_days: 3,
    max_items: 20,
    category: "international_proxy",
    needsProxy: true,
    note: "全球金融市场与商业头条官方 RSS（需代理/海外服务器）",
  },
  {
    id: "economist-finance",
    name: "The Economist 经济学人 · 财经",
    url: "https://www.economist.com/finance-and-economics/rss.xml",
    domain: "财经金融",
    enabled: true,
    max_age_days: 7,
    max_items: 25,
    category: "international_proxy",
    needsProxy: true,
    note: "全球宏观经济与金融深度评论（需代理/海外服务器）",
  },
  {
    id: "nature-news",
    name: "Nature 自然期刊",
    url: "https://www.nature.com/nature.rss",
    domain: "科技互联网",
    enabled: true,
    max_age_days: 7,
    max_items: 25,
    category: "international_proxy",
    needsProxy: true,
    note: "权威科学期刊研究与前沿科技动态（需代理/海外服务器）",
  },
];

export function isDeprecatedFeedUrl(url: string): string | null {
  const lower = url.toLowerCase();
  if (lower.includes("finance.yahoo.com/news/rssindex")) {
    return "该历史接口已失效 (404)，建议删除";
  }
  if (/xinhuanet\.com\/(politics|world|finance)\/news_/i.test(url) || /xinhuanet\.com\/english\/rss\//i.test(url)) {
    return "新华网历史 XML 已停更，建议改用新华社定向源";
  }
  if (/people\.com\.cn\/rss\//i.test(url)) {
    return "人民网历史 RSS 已停更，建议改用其他权威源";
  }
  return null;
}
