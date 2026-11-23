import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowLeft, ExternalLink, Plus, Sparkles, Trash2 } from "lucide-react";
import { feedApi, reportsApi, settingsApi } from "@/api/endpoints";
import type { DomainInfoDTO, KeywordGroupStatDTO, ReportDTO, ReportType } from "@/api/types";
import { SelectableCard } from "@/components/selectable/SelectableCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Alert, Skeleton } from "@/components/ui/feedback";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { MarkdownView } from "@/components/ui/markdown-view";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ResizableSplitPane } from "@/components/ui/resizable-split-pane";
import { cn, formatShortTime } from "@/lib/utils";

const REPORT_TYPE_LABEL: Record<ReportType, string> = {
  daily_overall: "每日总体",
  domain_trend: "领域趋势",
  item_analysis: "新闻/事件深析",
  chat_generated: "对话生成",
};

export function ReportsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialId = Number(searchParams.get("id") || 0) || null;

  const [tab, setTab] = useState("archive");
  const [mobileView, setMobileView] = useState<"list" | "detail">(initialId ? "detail" : "list");
  const [typeFilter, setTypeFilter] = useState("ALL");
  const [dateFilter, setDateFilter] = useState("");
  const [reports, setReports] = useState<ReportDTO[]>([]);
  const [activeReport, setActiveReport] = useState<ReportDTO | null>(null);
  const [loadingReports, setLoadingReports] = useState(true);
  const [error, setError] = useState("");

  const [kwGroups, setKwGroups] = useState<KeywordGroupStatDTO[]>([]);
  const [kwTotal, setKwTotal] = useState(0);
  const [kwHours, setKwHours] = useState("24");
  const [kwLoading, setKwLoading] = useState(false);

  const [domains, setDomains] = useState<DomainInfoDTO[]>([]);
  const [genOpen, setGenOpen] = useState(false);
  const [genMode, setGenMode] = useState<"daily_overall" | "domain_trend">("daily_overall");
  const [genDomain, setGenDomain] = useState("AI大模型");
  const [genDate, setGenDate] = useState("");
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState("");

  useEffect(() => {
    settingsApi
      .getSection<{ items?: DomainInfoDTO[] }>("domains")
      .then((res) => {
        const list = res.payload.items || [];
        setDomains(list);
        if (list.length > 0) {
          setGenDomain((prev) => (list.some((d) => d.id === prev) ? prev : list[0].id));
        }
      })
      .catch(() => {});
  }, []);

  const loadReports = useCallback(async () => {
    setLoadingReports(true);
    setError("");
    try {
      const res = await reportsApi.list({
        report_type: typeFilter === "ALL" ? undefined : typeFilter,
        date: dateFilter || undefined,
        page: 1,
        page_size: 50,
      });
      setReports(res.items);
      if (initialId) {
        const hit = res.items.find((r) => r.id === initialId);
        if (hit) {
          setActiveReport(hit);
        } else {
          const single = await reportsApi.get(initialId).catch(() => null);
          if (single) setActiveReport(single);
        }
      } else if (res.items.length > 0 && !activeReport) {
        setActiveReport(res.items[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载报告归档失败");
    } finally {
      setLoadingReports(false);
    }
  }, [typeFilter, dateFilter, initialId]);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  const loadKeywords = useCallback(async () => {
    setKwLoading(true);
    try {
      const res = await feedApi.keywordsStats(Number(kwHours));
      setKwGroups(res.groups);
      setKwTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载关键词统计失败");
    } finally {
      setKwLoading(false);
    }
  }, [kwHours]);

  useEffect(() => {
    if (tab === "keywords") {
      void loadKeywords();
    }
  }, [tab, loadKeywords]);

  const handleSelectReport = (rep: ReportDTO) => {
    setActiveReport(rep);
    setSearchParams({ id: String(rep.id) });
    setMobileView("detail");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleDeleteReport = async (repId: number) => {
    if (!window.confirm("确定删除当前选中的报告吗？")) return;
    try {
      await reportsApi.delete(repId);
      const next = reports.filter((r) => r.id !== repId);
      setReports(next);
      if (activeReport?.id === repId) {
        setActiveReport(next[0] || null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除报告失败");
    }
  };

  const handleGenerate = async () => {
    setGenerating(true);
    setGenError("");
    try {
      const rep = await reportsApi.generate({
        mode: genMode,
        date: genDate || undefined,
        domain: genMode === "domain_trend" ? genDomain.trim() : undefined,
      });
      setGenOpen(false);
      setReports((prev) => [rep, ...prev]);
      handleSelectReport(rep);
    } catch (err) {
      setGenError(err instanceof Error ? err.message : "生成报告失败");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-bold tracking-tight">报告归档与关键词分析</h1>
          <p className="text-sm text-muted-foreground">
            统一管理每日总体、领域趋势、新闻深析及对话沉淀报告，并查看词组规则实时命中情况。
          </p>
        </div>

        <Button
          size="sm"
          onClick={() => {
            setGenError("");
            setGenOpen(true);
          }}
        >
          <Plus data-icon="inline-start" />
          <span>AI 生成报告</span>
        </Button>
      </div>

      {error && <Alert variant="destructive">{error}</Alert>}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="archive">报告归档 ({reports.length})</TabsTrigger>
          <TabsTrigger value="keywords">关键词词组分析</TabsTrigger>
        </TabsList>

        <TabsContent value="archive" className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center sm:gap-3">
            <div className="min-w-0 sm:w-40">
              <Select value={typeFilter} onValueChange={setTypeFilter}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="ALL">全部类型</SelectItem>
                    <SelectItem value="daily_overall">每日总体</SelectItem>
                    <SelectItem value="domain_trend">领域趋势</SelectItem>
                    <SelectItem value="item_analysis">新闻/事件深析</SelectItem>
                    <SelectItem value="chat_generated">对话生成</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            <Input
              type="date"
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value)}
              className="min-w-0 sm:w-44"
            />
          </div>

          {loadingReports ? (
            <div className="flex flex-col gap-4 lg:flex-row">
              <Skeleton className="h-96 w-full lg:w-[260px] lg:shrink-0" />
              <Skeleton className="h-96 w-full lg:flex-1" />
            </div>
          ) : (
            <ResizableSplitPane
              defaultLeftWidth={260}
              minLeftWidth={190}
              maxLeftWidth={460}
              maxLeftRatio={0.45}
              storageKey="trendradar:reports-sidebar-width"
              handleLabel="左右拖动调节报告列表宽度"
              leftClassName={cn(mobileView === "detail" && "hidden lg:block")}
              rightClassName={cn(mobileView === "list" && "hidden lg:block")}
              left={
                <Card className="flex max-h-[680px] flex-col divide-y divide-border overflow-y-auto">
                  {reports.length === 0 ? (
                    <div className="p-8 text-center text-sm text-muted-foreground">暂无归档报告</div>
                  ) : (
                    reports.map((rep) => (
                      <div
                        key={rep.id}
                        onClick={() => handleSelectReport(rep)}
                        className={cn(
                          "flex flex-col gap-1.5 p-3 transition-colors cursor-pointer",
                          activeReport?.id === rep.id ? "bg-accent/60" : "hover:bg-muted/50",
                        )}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 text-xs">
                          <div className="flex min-w-0 flex-wrap items-center gap-1">
                            <Badge variant="default">{REPORT_TYPE_LABEL[rep.report_type]}</Badge>
                            {rep.domain && <Badge variant="outline">{rep.domain}</Badge>}
                          </div>
                          <span className="shrink-0 font-mono text-muted-foreground tabular-nums">
                            {rep.report_date}
                          </span>
                        </div>
                        <p className="line-clamp-2 text-sm font-semibold leading-snug">{rep.title}</p>
                      </div>
                    ))
                  )}
                </Card>
              }
              right={
                <Card className="p-4 sm:p-6">
                  <div className="mb-3 lg:hidden">
                    <Button size="sm" variant="outline" onClick={() => setMobileView("list")}>
                      <ArrowLeft data-icon="inline-start" />
                      <span>返回报告列表</span>
                    </Button>
                  </div>

                  {activeReport ? (
                    <div className="flex flex-col gap-4">
                      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-4">
                        <div className="flex flex-col gap-1.5">
                          <div className="flex flex-wrap items-center gap-1.5 text-xs">
                            <Badge variant="default">{REPORT_TYPE_LABEL[activeReport.report_type]}</Badge>
                            {activeReport.domain && <Badge variant="outline">{activeReport.domain}</Badge>}
                            {activeReport.provider_name && (
                              <Badge variant="secondary">{activeReport.provider_name}</Badge>
                            )}
                            <span className="font-mono text-muted-foreground">
                              {formatShortTime(activeReport.created_at)}
                            </span>
                          </div>
                          <h2 className="text-lg font-bold">{activeReport.title}</h2>
                        </div>

                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => void handleDeleteReport(activeReport.id)}
                          title="删除报告"
                        >
                          <Trash2 data-icon="inline-start" />
                          <span>删除</span>
                        </Button>
                      </div>

                      <MarkdownView content={activeReport.content_md} />
                    </div>
                  ) : (
                    <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
                      选择左侧一篇报告查看正文
                    </div>
                  )}
                </Card>
              }
            />
          )}
        </TabsContent>

        <TabsContent value="keywords" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-sm text-muted-foreground">
              近 {kwHours} 小时共命中 <strong className="tabular-nums text-foreground">{kwTotal}</strong> 条热点（规则可在配置中心调整）
            </span>
            <div className="w-36 shrink-0 min-w-[116px]">
              <Select value={kwHours} onValueChange={setKwHours}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="12">近 12 小时</SelectItem>
                    <SelectItem value="24">近 24 小时</SelectItem>
                    <SelectItem value="48">近 48 小时</SelectItem>
                    <SelectItem value="72">近 72 小时</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
          </div>

          {kwLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : kwGroups.length === 0 ? (
            <Card className="p-8 text-center text-sm text-muted-foreground">
              当前时间窗口暂无命中关键词规则的新闻。
            </Card>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {kwGroups.map((grp) => (
                <Card key={grp.group_key} className="flex min-w-0 flex-col gap-3 overflow-hidden p-4">
                  <div className="flex min-w-0 items-center justify-between gap-2 border-b border-border pb-2">
                    <h3 className="min-w-0 truncate font-semibold">{grp.display_name}</h3>
                    <Badge variant="default" className="shrink-0 tabular-nums">
                      {grp.count} 条命中
                    </Badge>
                  </div>
                  <div className="flex min-w-0 flex-col gap-2">
                    {grp.items.map((item) => (
                      <SelectableCard
                        key={`${item.source_type}-${item.id}`}
                        item={{
                          kind: item.source_type === "rss" ? "rss" : "news",
                          id: item.id,
                          title: item.title,
                          platform_or_domain: item.platform_name,
                          url: item.url,
                        }}
                      >
                        <div className="flex min-w-0 items-center justify-between gap-2 rounded-md border border-border/70 px-2.5 py-2 text-xs sm:text-sm">
                          <div className="flex min-w-0 flex-1 items-center gap-2 pr-12">
                            <Badge variant="secondary" className="shrink-0">
                              {item.platform_name}
                            </Badge>
                            <span className="min-w-0 truncate">{item.title}</span>
                          </div>
                          {item.url && (
                            <a href={item.url} target="_blank" rel="noreferrer" className="shrink-0 text-primary">
                              <ExternalLink className="size-3.5" />
                            </a>
                          )}
                        </div>
                      </SelectableCard>
                    ))}
                  </div>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      <Dialog
        open={genOpen}
        onOpenChange={(open) => {
          setGenOpen(open);
          if (!open) setGenError("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>AI 生成热点分析报告</DialogTitle>
            <DialogDescription>
              使用当前启用的 AI 模型整理热点并生成简洁易读的分析报告，自动保存在本页。
            </DialogDescription>
          </DialogHeader>

          {genError && <Alert variant="destructive">{genError}</Alert>}

          <FieldGroup>
            <Field>
              <FieldLabel>报告类型</FieldLabel>
              <Select
                value={genMode}
                onValueChange={(v) => setGenMode(v as "daily_overall" | "domain_trend")}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="daily_overall">每日总体热点趋势</SelectItem>
                    <SelectItem value="domain_trend">指定领域趋势分析</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>

            {genMode === "domain_trend" && (
              <Field>
                <FieldLabel>选择领域</FieldLabel>
                {domains.length > 0 ? (
                  <Select value={genDomain} onValueChange={setGenDomain}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择一个领域" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {domains.map((d) => (
                          <SelectItem key={d.id} value={d.id}>
                            {d.name}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    id="gen-domain"
                    value={genDomain}
                    onChange={(e) => setGenDomain(e.target.value)}
                    placeholder="例如：AI大模型"
                  />
                )}
              </Field>
            )}

            <Field>
              <FieldLabel htmlFor="gen-date">目标日期（留空取最新日期）</FieldLabel>
              <Input
                id="gen-date"
                type="date"
                value={genDate}
                onChange={(e) => setGenDate(e.target.value)}
              />
            </Field>

            <DialogFooter>
              <Button variant="outline" onClick={() => setGenOpen(false)} disabled={generating}>
                取消
              </Button>
              <Button onClick={handleGenerate} disabled={generating}>
                <Sparkles data-icon="inline-start" />
                <span>{generating ? "生成中..." : "开始生成"}</span>
              </Button>
            </DialogFooter>
          </FieldGroup>
        </DialogContent>
      </Dialog>
    </div>
  );
}
