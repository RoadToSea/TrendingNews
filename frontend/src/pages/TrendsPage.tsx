import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ExternalLink, FileText, RefreshCw, Settings, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { reportsApi, settingsApi, trendsApi } from "@/api/endpoints";
import type { DomainInfoDTO, EventDetailResponse, TrendsResponse } from "@/api/types";
import { TrendChart } from "@/components/trends/TrendChart";
import { getEventColor } from "@/components/trends/trendChartUtils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert, Skeleton } from "@/components/ui/feedback";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useAuth } from "@/context/AuthContext";
import { useCrawl } from "@/context/CrawlContext";
import { useSelection } from "@/context/SelectionContext";

export function TrendsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { addItem, setChatOpen } = useSelection();
  const { crawling, startCrawl, clusterVersion } = useCrawl();

  const [days, setDays] = useState("14");
  const [topN, setTopN] = useState("10");
  const [domain, setDomain] = useState("ALL");
  const [domains, setDomains] = useState<DomainInfoDTO[]>([]);
  const [trends, setTrends] = useState<TrendsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState("");
  const [eventDetail, setEventDetail] = useState<EventDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    settingsApi
      .getSection<{ items?: DomainInfoDTO[] }>("domains")
      .then((res) => setDomains(res.payload.items || []))
      .catch(() => {});
  }, []);

  const domainNameMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const d of domains) {
      map[d.id] = d.name;
    }
    return map;
  }, [domains]);

  const reqSeqRef = useRef(0);

  const loadTrends = useCallback(
    async (silent = false) => {
      const seq = ++reqSeqRef.current;
      if (!silent) {
        setLoading(true);
        setError("");
      }
      try {
        const res = await trendsApi.trends(
          Number(days),
          Number(topN),
          domain === "ALL" ? undefined : domain,
        );
        if (seq !== reqSeqRef.current) return;
        setTrends(res);
      } catch (err) {
        if (seq !== reqSeqRef.current) return;
        if (!silent) {
          setError(err instanceof Error ? err.message : "加载趋势图数据失败");
        }
      } finally {
        if (!silent && seq === reqSeqRef.current) {
          setLoading(false);
        }
      }
    },
    [days, topN, domain],
  );

  useEffect(() => {
    void loadTrends(false);
  }, [loadTrends]);

  useEffect(() => {
    if (clusterVersion === 0) return;
    void loadTrends(true);
  }, [clusterVersion, loadTrends]);

  const handleSelectPoint = useCallback(async (eventId: number, dateStr: string) => {
    setSelectedDate(dateStr);
    setDrawerOpen(true);
    setDetailLoading(true);
    try {
      const detail = await trendsApi.eventDetail(eventId);
      setEventDetail(detail);
    } catch {
      setEventDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleGenerateDailyReport = async (targetDate?: string) => {
    setGenerating(true);
    setError("");
    try {
      const rep = await reportsApi.generate({
        mode: "daily_overall",
        date: targetDate || trends?.dates[trends.dates.length - 1],
      });
      navigate(`/reports?id=${rep.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成每日总体报告失败");
    } finally {
      setGenerating(false);
    }
  };

  const handleGenerateEventReport = async (ev: EventDetailResponse) => {
    setGenerating(true);
    setError("");
    try {
      const rep = await reportsApi.generate({
        mode: "item_analysis",
        event_ids: [ev.id],
      });
      navigate(`/reports?id=${rep.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成事件深度报告失败");
    } finally {
      setGenerating(false);
    }
  };

  const dailyReportIdForSelected = selectedDate ? trends?.daily_reports[selectedDate] : undefined;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-bold tracking-tight">近期热点走势</h1>
          <p className="text-sm text-muted-foreground">
            横轴以今日为中心对称展开，纵轴为综合关注度；不同颜色区分各热点事件，连续上榜以折线相连，单日热点以圆点展示。
          </p>
        </div>

        <Button
          size="sm"
          onClick={() => void handleGenerateDailyReport()}
          disabled={generating || !trends || trends.series.length === 0}
        >
          <Sparkles data-icon="inline-start" />
          <span>{generating ? "生成中..." : "生成今日总体热点报告"}</span>
        </Button>
      </div>

      {error && <Alert variant="destructive">{error}</Alert>}

      <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center sm:gap-3">
        <div className="min-w-0 sm:w-32">
          <Select value={days} onValueChange={setDays}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="7">近 7 天</SelectItem>
                <SelectItem value="14">近 14 天</SelectItem>
                <SelectItem value="30">近 30 天</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        <div className="min-w-0 sm:w-36">
          <Select value={topN} onValueChange={setTopN}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="5">每日 Top 5</SelectItem>
                <SelectItem value="10">每日 Top 10</SelectItem>
                <SelectItem value="15">每日 Top 15</SelectItem>
                <SelectItem value="20">每日 Top 20</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        <div className="col-span-2 min-w-0 sm:col-span-1 sm:w-40">
          <Select value={domain} onValueChange={setDomain}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="ALL">全部领域</SelectItem>
                {domains.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    {d.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
      </div>

      <Card className="p-2.5 sm:p-4">
        {loading ? (
          <Skeleton className="h-[340px] sm:h-[460px] w-full" />
        ) : trends && trends.series.length > 0 ? (
          <TrendChart
            dates={trends.dates}
            series={trends.series}
            onSelectPoint={handleSelectPoint}
            domainNameMap={domainNameMap}
          />
        ) : (
          <div className="flex h-[280px] sm:h-[320px] flex-col items-center justify-center gap-3 px-4 text-center text-sm text-muted-foreground">
            <p className="text-base font-medium text-foreground">暂无跨天事件趋势数据</p>
            <p className="max-w-md text-sm">
              {isAdmin
                ? "请确认已在管理后台启用 AI 模型并点击「更新数据」，系统会自动整理每日热点走势。"
                : "暂无跨天事件趋势数据，请等待系统完成采集与归类。"}
            </p>
            {isAdmin && (
              <div className="flex flex-wrap justify-center gap-2 pt-1">
                <Button size="sm" onClick={() => void startCrawl(true)} disabled={crawling}>
                  <RefreshCw data-icon="inline-start" className={cn(crawling && "animate-spin")} />
                  <span>{crawling ? "更新中..." : "立即更新数据"}</span>
                </Button>
                <Button size="sm" variant="outline" onClick={() => navigate("/admin?tab=ai")}>
                  <Settings data-icon="inline-start" />
                  <span>前往管理后台</span>
                </Button>
              </div>
            )}
          </div>
        )}
      </Card>

      {trends && trends.series.length > 0 && (
        <Card className="overflow-hidden">
          <div className="border-b border-border px-4 py-3 text-sm font-semibold">
            窗口期内热点事件清单 ({trends.series.length} 个)
          </div>
          <div className="divide-y divide-border">
            {trends.series.map((s, idx) => {
              const peak = Math.max(...s.points.map((p) => p.hot_index));
              const latest = s.points[s.points.length - 1];
              const domainLabel = domainNameMap[s.domain] || s.domain;
              return (
                <div
                  key={s.event_id}
                  onClick={() => void handleSelectPoint(s.event_id, latest.date)}
                  className="flex flex-col gap-1.5 px-4 py-3 text-sm hover:bg-muted/50 cursor-pointer sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex min-w-0 flex-wrap items-center gap-1.5 sm:flex-nowrap sm:gap-2">
                    <span
                      className="size-2.5 shrink-0 rounded-full"
                      style={{ backgroundColor: getEventColor(idx) }}
                      aria-hidden="true"
                    />
                    <Badge variant={s.is_multi_day ? "default" : "secondary"} className="shrink-0">
                      {s.is_multi_day ? `跨 ${s.points.length} 天` : "单日"}
                    </Badge>
                    <Badge variant="outline" className="shrink-0">{domainLabel}</Badge>
                    <span className="truncate font-medium">{s.canonical_title}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground tabular-nums">
                    <span>最高关注度 {peak}</span>
                    <span>最近上榜 {latest.date}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{eventDetail?.canonical_title || "事件详情"}</SheetTitle>
            <SheetDescription>点击日期：{selectedDate}</SheetDescription>
          </SheetHeader>

          {detailLoading ? (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : eventDetail ? (
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">
                  {domainNameMap[eventDetail.domain] || eventDetail.domain}
                </Badge>
                <Badge variant="secondary" className="tabular-nums">
                  {eventDetail.first_seen_date} 至 {eventDetail.last_seen_date}
                </Badge>
              </div>

              {eventDetail.summary && (
                <p className="text-sm leading-relaxed text-muted-foreground">{eventDetail.summary}</p>
              )}

              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    addItem({
                      kind: "event",
                      id: eventDetail.id,
                      title: eventDetail.canonical_title,
                      platform_or_domain: domainNameMap[eventDetail.domain] || eventDetail.domain,
                      snapshot_text: eventDetail.summary,
                    });
                    setChatOpen(true);
                  }}
                >
                  发给 AI 分析
                </Button>

                {dailyReportIdForSelected ? (
                  <Button size="sm" variant="outline" asChild>
                    <Link to={`/reports?id=${dailyReportIdForSelected}`}>
                      <FileText data-icon="inline-start" />
                      <span>查看 {selectedDate} 日报</span>
                    </Link>
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={generating}
                    onClick={() => void handleGenerateDailyReport(selectedDate)}
                  >
                    生成 {selectedDate} 日报
                  </Button>
                )}

                {eventDetail.report_id ? (
                  <Button size="sm" asChild>
                    <Link to={`/reports?id=${eventDetail.report_id}`}>打开事件报告</Link>
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    disabled={generating}
                    onClick={() => void handleGenerateEventReport(eventDetail)}
                  >
                    生成事件深度报告
                  </Button>
                )}
              </div>

              <div className="flex flex-col gap-2">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  每日关注度走势
                </h4>
                <div className="divide-y divide-border rounded-md border border-border">
                  {eventDetail.metrics.map((m) => (
                    <div
                      key={m.metric_date}
                      className="flex items-center justify-between px-3 py-2 text-xs tabular-nums"
                    >
                      <span className="font-mono">{m.metric_date}</span>
                      <span>关注度 {m.hot_index}</span>
                      <span>排名 #{m.daily_rank}</span>
                      <span>{m.platform_count} 平台</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  关联各平台原始报道 ({eventDetail.items.length})
                </h4>
                <div className="flex flex-col gap-2">
                  {eventDetail.items.map((item) => (
                    <Card key={item.id} className="flex items-start justify-between gap-2 p-3 text-xs">
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-1.5">
                          <Badge variant="secondary">{item.platform_name}</Badge>
                          {item.latest_rank !== null && (
                            <span className="font-mono text-muted-foreground">#{item.latest_rank}</span>
                          )}
                        </div>
                        <span className="font-medium leading-snug">{item.title}</span>
                      </div>
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noreferrer"
                          className="shrink-0 text-primary"
                        >
                          <ExternalLink className="size-3.5" />
                        </a>
                      )}
                    </Card>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <Alert variant="destructive">无法加载事件详情</Alert>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
