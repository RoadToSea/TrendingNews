import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ChevronDown, ChevronRight, ExternalLink, FileText, RefreshCw, Settings, Sparkles } from "lucide-react";
import { reportsApi, trendsApi } from "@/api/endpoints";
import type { DomainsResponse, HotEventDTO } from "@/api/types";
import { SelectableCard } from "@/components/selectable/SelectableCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert, Skeleton } from "@/components/ui/feedback";
import { useCrawl } from "@/context/CrawlContext";
import { useSelection } from "@/context/SelectionContext";
import { cn } from "@/lib/utils";

export function DomainsPage() {
  const navigate = useNavigate();
  const { setChatOpen, addItem } = useSelection();
  const { crawling, startCrawl, rssVersion, clusterVersion } = useCrawl();

  const [activeDomain, setActiveDomain] = useState<string>("");
  const [dateFilter, setDateFilter] = useState<string>("");
  const [data, setData] = useState<DomainsResponse | null>(null);
  const [expandedIds, setExpandedIds] = useState<Record<number, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const reqSeqRef = useRef(0);

  const loadDomains = useCallback(
    async (silent = false) => {
      const seq = ++reqSeqRef.current;
      if (!silent) {
        setLoading(true);
        setError("");
      }
      try {
        const res = await trendsApi.domains(dateFilter || undefined, activeDomain || undefined);
        if (seq !== reqSeqRef.current) return;
        setData(res);
      } catch (err) {
        if (seq !== reqSeqRef.current) return;
        if (!silent) {
          setError(err instanceof Error ? err.message : "加载领域聚合数据失败");
        }
      } finally {
        if (!silent && seq === reqSeqRef.current) {
          setLoading(false);
        }
      }
    },
    [dateFilter, activeDomain],
  );

  useEffect(() => {
    void loadDomains(false);
  }, [loadDomains]);

  useEffect(() => {
    if (rssVersion === 0 && clusterVersion === 0) return;
    const timer = window.setTimeout(() => {
      void loadDomains(true);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [rssVersion, clusterVersion, loadDomains]);

  const handleGenerateDomainReport = async () => {
    if (!activeDomain) return;
    setGenerating(true);
    setError("");
    try {
      const rep = await reportsApi.generate({
        mode: "domain_trend",
        date: data?.date,
        domain: activeDomain,
      });
      navigate(`/reports?id=${rep.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成领域报告失败");
    } finally {
      setGenerating(false);
    }
  };

  const toggleExpand = (eventId: number) => {
    setExpandedIds((prev) => ({ ...prev, [eventId]: !prev[eventId] }));
  };

  const domainNameMap: Record<string, string> = {};
  for (const dom of data?.domains || []) {
    if (dom.id) {
      domainNameMap[dom.id] = dom.name || dom.id;
    }
  }

  const renderEventCard = (ev: HotEventDTO) => {
    const expanded = !!expandedIds[ev.id];
    const eventDomainLabel = domainNameMap[ev.domain] || ev.domain;
    return (
      <SelectableCard
        key={ev.id}
        item={{
          kind: "event",
          id: ev.id,
          title: ev.canonical_title,
          platform_or_domain: eventDomainLabel,
          metric_label: `火热指数 ${ev.hot_index} | 覆盖 ${ev.platform_count} 平台`,
          snapshot_text: ev.summary,
        }}
      >
        <Card className="flex min-w-0 flex-col gap-3 overflow-hidden p-4">
          <div className="flex flex-wrap items-start justify-between gap-2 pr-12">
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <Badge variant="default" className="tabular-nums font-mono">
                指数 {ev.hot_index}
              </Badge>
              <Badge variant="secondary">第 #{ev.daily_rank} 名</Badge>
              <Badge variant="outline">{eventDomainLabel}</Badge>
              <Badge variant="outline" className="tabular-nums">
                {ev.platform_count} 平台覆盖
              </Badge>
            </div>
            {ev.report_id && (
              <Link
                to={`/reports?id=${ev.report_id}`}
                className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                <FileText className="size-3.5" />
                <span>关联报告</span>
              </Link>
            )}
          </div>

          <h3 className="text-base font-semibold leading-snug text-foreground break-words">{ev.canonical_title}</h3>
          {ev.summary && <p className="text-sm leading-relaxed text-muted-foreground break-words">{ev.summary}</p>}

          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <button
              type="button"
              onClick={() => toggleExpand(ev.id)}
              className="inline-flex min-h-9 items-center gap-1 rounded-md px-2 -ml-2 text-xs sm:text-sm font-medium text-foreground hover:bg-muted hover:text-primary cursor-pointer"
            >
              {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
              <span>展开同源报道 ({ev.items.length} 条)</span>
            </button>

            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                addItem({
                  kind: "event",
                  id: ev.id,
                  title: ev.canonical_title,
                  platform_or_domain: eventDomainLabel,
                  metric_label: `火热指数 ${ev.hot_index}`,
                  snapshot_text: ev.summary,
                });
                setChatOpen(true);
              }}
            >
              问 AI
            </Button>
          </div>

          {expanded && ev.items.length > 0 && (
            <div className="flex flex-col gap-1.5 border-t border-border pt-2.5">
              {ev.items.map((item) => (
                <div key={item.id} className="flex items-center justify-between gap-2 text-xs">
                  <div className="flex min-w-0 items-center gap-2">
                    <Badge variant="secondary" className="shrink-0">
                      {item.platform_name}
                    </Badge>
                    <span className="truncate text-foreground">{item.title}</span>
                  </div>
                  {item.url && (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      className="shrink-0 text-primary hover:underline"
                    >
                      <ExternalLink className="size-3.5" />
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      </SelectableCard>
    );
  };

  const hasDomainData = Boolean(data && (data.events.length > 0 || data.rss.length > 0));
  const selectedDomainInfo = data?.domains.find((d) => d.id === activeDomain);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-bold tracking-tight">分领域热点汇总</h1>
          <p className="text-sm text-muted-foreground">
            系统自动将国内外关于同一事件的多条报道归类合并，当前查看日期：{data?.date || "..."}。
          </p>
        </div>

        <div className="flex w-full sm:w-auto flex-wrap items-center gap-2">
          <input
            type="date"
            value={dateFilter}
            onChange={(e) => setDateFilter(e.target.value)}
            className="h-9 rounded-md border border-input bg-card px-3 text-base sm:text-sm"
          />
          <Button
            size="sm"
            onClick={handleGenerateDomainReport}
            disabled={generating || !hasDomainData || !activeDomain}
            className="flex-1 sm:flex-none"
          >
            <Sparkles data-icon="inline-start" />
            <span className="truncate">
              {generating
                ? "生成中..."
                : activeDomain
                  ? `生成「${selectedDomainInfo?.name || activeDomain}」趋势报告`
                  : "请先在下方选择具体领域"}
            </span>
          </Button>
        </div>
      </div>

      {error && <Alert variant="destructive">{error}</Alert>}

      {data && (
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => setActiveDomain("")}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs sm:text-sm font-medium transition-colors cursor-pointer",
              activeDomain === ""
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-muted-foreground hover:text-foreground",
            )}
          >
            全部领域
          </button>
          {data.domains.map((dom) => (
            <button
              key={dom.id}
              type="button"
              onClick={() => setActiveDomain(dom.id)}
              className={cn(
                "shrink-0 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs sm:text-sm font-medium transition-colors tabular-nums cursor-pointer",
                activeDomain === dom.id
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:text-foreground",
              )}
            >
              {dom.name} ({dom.event_count})
            </button>
          ))}
        </div>
      )}

      {loading && !data ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="flex flex-col gap-3 lg:col-span-2">
            <Skeleton className="h-36 w-full" />
            <Skeleton className="h-36 w-full" />
          </div>
          <Skeleton className="h-72 w-full" />
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="flex min-w-0 flex-col gap-3 lg:col-span-2">
            <h2 className="text-sm font-semibold text-muted-foreground">热点事件汇总</h2>
            {data && data.events.length > 0 ? (
              data.events.map(renderEventCard)
            ) : (
              <Card className="flex flex-col items-center gap-3 p-8 text-center text-sm text-muted-foreground">
                <p className="text-base font-medium text-foreground">当日暂无已归类事件</p>
                <p className="max-w-md text-sm">
                  请确认已在配置中心启用 AI 模型并点击一次「更新数据」，系统会自动把同一事件的多条报道归并展示。
                </p>
                <div className="flex flex-wrap justify-center gap-2 pt-1">
                  <Button size="sm" onClick={() => void startCrawl(true)} disabled={crawling}>
                    <RefreshCw data-icon="inline-start" className={cn(crawling && "animate-spin")} />
                    <span>{crawling ? "更新中..." : "立即更新数据"}</span>
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => navigate("/settings?tab=ai")}>
                    <Settings data-icon="inline-start" />
                    <span>前往配置中心</span>
                  </Button>
                </div>
              </Card>
            )}
          </div>

          <div className="flex min-w-0 flex-col gap-3">
            <h2 className="text-sm font-semibold text-muted-foreground">相关媒体订阅</h2>
            {data && data.rss.length > 0 ? (
              <div className="flex min-w-0 flex-col gap-2.5">
                {data.rss.slice(0, 20).map((rss) => {
                  const rssDomainLabel = domainNameMap[rss.domain] || rss.domain;
                  return (
                    <SelectableCard
                      key={`rss-${rss.id}`}
                      item={{
                        kind: "rss",
                        id: rss.id,
                        title: rss.title,
                        platform_or_domain: rss.platform_name,
                        url: rss.url,
                        metric_label: rssDomainLabel,
                        snapshot_text: rss.summary,
                      }}
                    >
                      <Card className="flex min-w-0 flex-col gap-1.5 overflow-hidden p-3">
                        <div className="flex flex-wrap items-center gap-1.5 pr-12 text-xs">
                          <Badge variant="secondary">{rss.platform_name}</Badge>
                          <Badge variant="outline">{rssDomainLabel}</Badge>
                        </div>
                        <a
                          href={rss.url}
                          target="_blank"
                          rel="noreferrer"
                          className="min-w-0 text-xs sm:text-sm font-medium leading-snug [overflow-wrap:anywhere] hover:text-primary"
                        >
                          {rss.title}
                        </a>
                      </Card>
                    </SelectableCard>
                  );
                })}
              </div>
            ) : (
              <Card className="p-6 text-center text-sm text-muted-foreground">暂无相关媒体订阅内容</Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
