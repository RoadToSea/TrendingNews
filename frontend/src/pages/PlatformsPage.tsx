import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowUpRight, ExternalLink, Search, Settings, Sparkles } from "lucide-react";
import { feedApi, reportsApi } from "@/api/endpoints";
import type { NewsItemDTO, PlatformSummaryDTO, RssFeedSummaryDTO } from "@/api/types";
import { SelectableCard } from "@/components/selectable/SelectableCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert, Skeleton } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/context/AuthContext";
import { useCrawl } from "@/context/CrawlContext";
import { useSelection } from "@/context/SelectionContext";
import { cn, formatMetricLabel, formatShortTime } from "@/lib/utils";

export function PlatformsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { selectedItems, setChatOpen } = useSelection();
  const { crawling, hotlistVersion, rssVersion, startCrawl } = useCrawl();

  const [tab, setTab] = useState("hotlist");
  const [hotItems, setHotItems] = useState<NewsItemDTO[]>([]);
  const [platforms, setPlatforms] = useState<PlatformSummaryDTO[]>([]);
  const [selectedPlatform, setSelectedPlatform] = useState<string>("");
  const [query, setQuery] = useState("");
  const [risingItems, setRisingItems] = useState<NewsItemDTO[]>([]);
  const [rssItems, setRssItems] = useState<NewsItemDTO[]>([]);
  const [feeds, setFeeds] = useState<RssFeedSummaryDTO[]>([]);
  const [selectedFeed, setSelectedFeed] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [analyzing, setAnalyzing] = useState(false);

  const reqSeqRef = useRef(0);

  const loadData = useCallback(
    async (silent = false) => {
      const seq = ++reqSeqRef.current;
      if (!silent) setLoading(true);
      if (!silent) setError("");

      try {
        if (tab === "hotlist") {
          const res = await feedApi.hotlist({
            platform_id: selectedPlatform || undefined,
            q: query.trim() || undefined,
            limit: selectedPlatform ? 150 : 250,
          });
          if (seq !== reqSeqRef.current) return;
          setHotItems(res.items);
          setPlatforms(res.platforms);
        } else if (tab === "rising") {
          const res = await feedApi.rising(24, 80);
          if (seq !== reqSeqRef.current) return;
          setRisingItems(res.items);
        } else {
          const res = await feedApi.rss({
            feed_id: selectedFeed || undefined,
            days: 3,
            limit: 150,
          });
          if (seq !== reqSeqRef.current) return;
          setRssItems(res.items);
          setFeeds(res.feeds);
        }
      } catch (err) {
        if (seq !== reqSeqRef.current) return;
        if (!silent) {
          setError(err instanceof Error ? err.message : "加载热点数据失败");
        }
      } finally {
        if (!silent && seq === reqSeqRef.current) {
          setLoading(false);
        }
      }
    },
    [tab, selectedPlatform, selectedFeed, query],
  );

  useEffect(() => {
    void loadData(false);
  }, [loadData]);

  // Incrementally refresh without flashing skeletons as each hotlist or foreign API source lands.
  useEffect(() => {
    if (hotlistVersion === 0 || (tab !== "hotlist" && tab !== "rising")) return;
    const timer = window.setTimeout(() => {
      void loadData(true);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [hotlistVersion, tab, loadData]);

  // Incrementally refresh RSS list without flicker as each feed finishes.
  useEffect(() => {
    if (rssVersion === 0 || tab !== "rss") return;
    const timer = window.setTimeout(() => {
      void loadData(true);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [rssVersion, tab, loadData]);

  const handleAnalyzeSelected = async () => {
    const newsIds = selectedItems.filter((i) => i.kind === "news").map((i) => i.id);
    if (newsIds.length === 0) {
      setChatOpen(true);
      return;
    }
    setAnalyzing(true);
    setError("");
    try {
      const report = await reportsApi.generate({
        mode: "item_analysis",
        news_ids: newsIds,
      });
      navigate(`/reports?id=${report.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成组合新闻分析失败");
    } finally {
      setAnalyzing(false);
    }
  };

  const renderNewsList = (items: NewsItemDTO[], showVelocityFocus = false) => {
    if (loading && items.length === 0) {
      return (
        <div className="grid gap-3 md:grid-cols-2">
          {Array.from({ length: 6 }).map((_, idx) => (
            <Skeleton key={idx} className="h-28 w-full" />
          ))}
        </div>
      );
    }

    if (items.length === 0) {
      if (crawling) {
        return (
          <Card className="flex flex-col items-center justify-center gap-2 p-10 text-center">
            <p className="text-base font-medium text-foreground">正在更新最新热点</p>
            <p className="text-sm text-muted-foreground">
              各个来源更新完成后会逐一显示在本页，无需等待全部完成。
            </p>
          </Card>
        );
      }
      return (
        <Card className="flex flex-col items-center justify-center gap-3 p-10 text-center">
          <p className="text-base font-semibold text-foreground">暂无满足条件的热点新闻</p>
          <p className="max-w-md text-sm text-muted-foreground">
            {isAdmin
              ? "点击顶部「更新数据」或下方按钮即可获取最新热点，也可先到管理后台调整数据源。"
              : "暂未采集到满足条件的热点新闻，可在配置中心调整您的关注话题规则。"}
          </p>
          <div className="flex flex-wrap justify-center gap-2 pt-1">
            {isAdmin ? (
              <>
                <Button size="sm" onClick={() => void startCrawl(true)}>
                  立即更新数据
                </Button>
                <Button size="sm" variant="outline" onClick={() => navigate("/admin")}>
                  <Settings data-icon="inline-start" />
                  <span>前往管理后台</span>
                </Button>
              </>
            ) : (
              <Button size="sm" variant="outline" onClick={() => navigate("/settings")}>
                <Settings data-icon="inline-start" />
                <span>前往配置中心</span>
              </Button>
            )}
          </div>
        </Card>
      );
    }

    return (
      <div className="grid gap-3 md:grid-cols-2">
        {items.map((item) => {
          const metricStr = formatMetricLabel(item.extra_metrics);
          return (
            <SelectableCard
              key={`${item.source_type}-${item.id}`}
              item={{
                kind: item.source_type === "rss" ? "rss" : "news",
                id: item.id,
                title: item.title,
                platform_or_domain: item.platform_name,
                url: item.url,
                metric_label:
                  item.latest_rank !== null
                    ? `排名 #${item.latest_rank} | 增速 ${item.velocity}`
                    : item.domain,
                snapshot_text: item.summary,
              }}
            >
              <Card className="flex h-full min-w-0 flex-col justify-between gap-3 overflow-hidden p-4">
                <div className="flex min-w-0 flex-col gap-2">
                  <div className="flex flex-wrap items-center gap-1.5 pr-12 text-xs">
                    {item.latest_rank !== null && (
                      <Badge variant="default" className="tabular-nums font-mono">
                        #{item.latest_rank}
                      </Badge>
                    )}
                    <Badge variant="secondary">{item.platform_name}</Badge>
                    {item.domain && <Badge variant="outline">{item.domain}</Badge>}
                    {(showVelocityFocus || item.velocity > 0) && item.source_type === "hotlist" && (
                      <Badge variant={item.velocity >= 20 ? "warning" : "success"} className="tabular-nums">
                        <ArrowUpRight className="size-3" />
                        <span>+{item.velocity}</span>
                      </Badge>
                    )}
                  </div>

                  <a
                    href={item.url || "#"}
                    target="_blank"
                    rel="noreferrer"
                    className="group flex min-w-0 items-start justify-between gap-2 text-sm sm:text-base font-semibold leading-snug text-foreground hover:text-primary"
                  >
                    <span className="min-w-0 break-words">{item.title}</span>
                    {item.url && (
                      <ExternalLink className="mt-0.5 size-3.5 shrink-0 text-muted-foreground group-hover:text-primary" />
                    )}
                  </a>

                  {item.summary && (
                    <p className="line-clamp-2 break-words text-xs sm:text-sm leading-relaxed text-muted-foreground">
                      {item.summary}
                    </p>
                  )}
                </div>

                <div className="flex min-w-0 items-center justify-between gap-2 text-xs text-muted-foreground tabular-nums">
                  <span className="min-w-0 truncate font-mono">{metricStr || "常规排行条目"}</span>
                  <span className="shrink-0">{formatShortTime(item.last_seen_at)}</span>
                </div>
              </Card>
            </SelectableCard>
          );
        })}
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-bold tracking-tight">全平台热点榜单</h1>
          <p className="text-sm text-muted-foreground">
            汇总国内热榜、海外科技社区及权威媒体订阅，支持快速筛选与 AI 研判。
          </p>
        </div>

        {selectedItems.length > 0 && (
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => setChatOpen(true)}>
              带入 AI 对话 ({selectedItems.length})
            </Button>
            <Button size="sm" onClick={handleAnalyzeSelected} disabled={analyzing}>
              <Sparkles data-icon="inline-start" />
              <span>{analyzing ? "正在分析..." : "生成选中条目深度报告"}</span>
            </Button>
          </div>
        )}
      </div>

      {error && <Alert variant="destructive">{error}</Alert>}

      <Tabs value={tab} onValueChange={setTab}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <TabsList className="w-full justify-start overflow-x-auto no-scrollbar sm:w-auto">
            <TabsTrigger value="hotlist" className="shrink-0">实时热榜</TabsTrigger>
            <TabsTrigger value="rising" className="shrink-0">飙升榜</TabsTrigger>
            <TabsTrigger value="rss" className="shrink-0">媒体订阅</TabsTrigger>
          </TabsList>

          {tab === "hotlist" && (
            <div className="relative w-full sm:w-72">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="筛选标题关键词..."
                className="pl-8"
              />
            </div>
          )}
        </div>

        <TabsContent value="hotlist" className="flex flex-col gap-4">
          {platforms.length > 0 && (
            <div className="-mx-3 flex flex-nowrap gap-1.5 overflow-x-auto no-scrollbar px-3 pb-1 sm:mx-0 sm:flex-wrap sm:px-0 sm:pb-0">
              <button
                type="button"
                onClick={() => setSelectedPlatform("")}
                className={cn(
                  "shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium transition-colors cursor-pointer",
                  selectedPlatform === ""
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card text-muted-foreground hover:text-foreground",
                )}
              >
                全部平台
              </button>
              {platforms.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setSelectedPlatform(p.id)}
                  className={cn(
                    "shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium transition-colors tabular-nums cursor-pointer",
                    selectedPlatform === p.id
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  {p.name} ({p.count})
                </button>
              ))}
            </div>
          )}
          {renderNewsList(hotItems)}
        </TabsContent>

        <TabsContent value="rising">{renderNewsList(risingItems, true)}</TabsContent>

        <TabsContent value="rss" className="flex flex-col gap-4">
          {feeds.length > 0 && (
            <div className="-mx-3 flex flex-nowrap gap-1.5 overflow-x-auto no-scrollbar px-3 pb-1 sm:mx-0 sm:flex-wrap sm:px-0 sm:pb-0">
              <button
                type="button"
                onClick={() => setSelectedFeed("")}
                className={cn(
                  "shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium transition-colors cursor-pointer",
                  selectedFeed === ""
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card text-muted-foreground hover:text-foreground",
                )}
              >
                全部订阅源
              </button>
              {feeds.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setSelectedFeed(f.id)}
                  className={cn(
                    "shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium transition-colors tabular-nums cursor-pointer",
                    selectedFeed === f.id
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  {f.name} ({f.count})
                </button>
              ))}
            </div>
          )}
          {renderNewsList(rssItems)}
        </TabsContent>
      </Tabs>
    </div>
  );
}
