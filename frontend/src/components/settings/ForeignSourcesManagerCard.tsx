import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Plus, SlidersHorizontal, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

type ForeignKey = "reddit" | "youtube" | "hackernews" | "huggingface" | "github";

interface ForeignSourcesManagerCardProps {
  config: Record<string, unknown>;
  onChange: (next: Record<string, unknown>, immediate?: boolean) => void;
  onKeepaliveFlush?: (next: Record<string, unknown>) => void;
}

export function normalizeYoutubeChannels(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const entry of raw) {
    let val = "";
    if (typeof entry === "string") {
      val = entry.trim();
    } else if (entry && typeof entry === "object") {
      const obj = entry as Record<string, unknown>;
      val = String(obj.channel_id || obj.url || obj.handle || "").trim();
    }
    if (val && !seen.has(val)) {
      seen.add(val);
      out.push(val);
    }
  }
  return out;
}

interface ForeignChipEditorProps {
  label: string;
  description: string;
  items: string[];
  placeholder: string;
  addButtonText: string;
  onChange: (next: string[], immediate?: boolean) => void;
  onUnloadCommit?: (next: string[]) => void;
}

function mergeChipTokens(rawDraft: string, items: string[]): string[] | null {
  const tokens = rawDraft
    .split(/[,，\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (tokens.length === 0) return null;
  const seen = new Set(items);
  const next = [...items];
  for (const token of tokens) {
    if (!seen.has(token)) {
      seen.add(token);
      next.push(token);
    }
  }
  return next;
}

function ForeignChipEditor({
  label,
  description,
  items,
  placeholder,
  addButtonText,
  onChange,
  onUnloadCommit,
}: ForeignChipEditorProps) {
  const [draft, setDraft] = useState("");
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const onUnloadCommitRef = useRef(onUnloadCommit);
  onUnloadCommitRef.current = onUnloadCommit;

  useEffect(() => {
    const handleUnload = () => {
      const merged = mergeChipTokens(draftRef.current, itemsRef.current);
      if (merged) {
        onUnloadCommitRef.current?.(merged);
      }
    };
    window.addEventListener("beforeunload", handleUnload);
    return () => window.removeEventListener("beforeunload", handleUnload);
  }, []);

  const commitDraft = () => {
    const next = mergeChipTokens(draft, items);
    if (!next) return;
    setDraft("");
    draftRef.current = "";
    onChange(next, true);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <span className="text-base sm:text-[15px] font-semibold leading-snug text-foreground">{label}</span>
        <span className="text-sm leading-relaxed text-muted-foreground">{description}</span>
      </div>

      {items.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {items.map((item, idx) => (
            <Badge key={`${item}-${idx}`} variant="outline" className="max-w-full gap-1.5 px-3 py-1.5 text-sm font-normal">
              <span className="truncate">{item}</span>
              <button
                type="button"
                aria-label={`移除 ${item}`}
                onClick={() => onChange(items.filter((_, i) => i !== idx), true)}
                className="ml-0.5 inline-flex size-6 items-center justify-center rounded-full hover:bg-foreground/10 cursor-pointer"
              >
                <X className="size-3.5" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitDraft}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commitDraft();
            }
          }}
          placeholder={placeholder}
          className="flex-1"
        />
        <Button
          type="button"
          variant="outline"
          onMouseDown={(e) => e.preventDefault()}
          onClick={commitDraft}
          className="h-10 shrink-0 px-4"
        >
          <Plus data-icon="inline-start" />
          <span>{addButtonText}</span>
        </Button>
      </div>
      <span className="text-xs sm:text-sm text-muted-foreground">
        多个条目可用逗号隔开；按回车、点右侧按钮或离开输入框都会自动加入。
      </span>
    </div>
  );
}

export function ForeignSourcesManagerCard({
  config,
  onChange,
  onKeepaliveFlush,
}: ForeignSourcesManagerCardProps) {
  const [expandedKey, setExpandedKey] = useState<ForeignKey | null>(null);
  const [proxyOpen, setProxyOpen] = useState(false);
  const [redditUaOpen, setRedditUaOpen] = useState(false);

  const configRef = useRef(config);
  configRef.current = config;
  const onKeepaliveFlushRef = useRef(onKeepaliveFlush);
  onKeepaliveFlushRef.current = onKeepaliveFlush;

  const toggleExpand = (key: ForeignKey) => {
    setExpandedKey((prev) => (prev === key ? null : key));
  };

  const subreddits = Array.isArray(config.reddit_subreddits)
    ? (config.reddit_subreddits as unknown[]).map((s) => String(s || "").trim()).filter(Boolean)
    : [];
  const ytChannels = normalizeYoutubeChannels(config.youtube_channels);

  const redditEnabled = Boolean(config.reddit_enabled);
  const youtubeEnabled = Boolean(config.youtube_enabled ?? true);
  const hnEnabled = Boolean(config.hackernews_enabled ?? true);
  const hfEnabled = Boolean(config.huggingface_enabled ?? true);
  const ghEnabled = Boolean(config.github_enabled ?? true);
  const enabledCount = [redditEnabled, youtubeEnabled, hnEnabled, hfEnabled, ghEnabled].filter(Boolean).length;
  const proxyConfigured = Boolean(String(config.proxy_url || "").trim());

  const rows: {
    key: ForeignKey;
    title: string;
    enabled: boolean;
    enabledField: string;
    summary: string;
    renderDetail: () => JSX.Element;
  }[] = [
    {
      key: "reddit",
      title: "Reddit 公开板块（留作后续代理扩展）",
      enabled: redditEnabled,
      enabledField: "reddit_enabled",
      summary:
        subreddits.length > 0
          ? `已配置 ${subreddits.length} 个版块 · 最低 ${Number(config.reddit_min_ups ?? 100)} 赞`
          : "点击展开配置订阅版块与门槛",
      renderDetail: () => (
        <div className="flex flex-col gap-4">
          <ForeignChipEditor
            label="订阅版块或网址"
            description="支持版块名、r/name 或完整 Reddit 网址；无需复杂账号授权（如直连受限，可在后续配置代理）"
            items={subreddits}
            placeholder="例如：LocalLLaMA 或 https://www.reddit.com/r/technology"
            addButtonText="添加版块"
            onChange={(nextSubs, immediate) =>
              onChange({ ...config, reddit_subreddits: nextSubs }, immediate)
            }
            onUnloadCommit={(nextSubs) =>
              onKeepaliveFlushRef.current?.({
                ...configRef.current,
                reddit_subreddits: nextSubs,
              })
            }
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field>
              <FieldLabel>最低点赞门槛 (Hot)</FieldLabel>
              <Input
                type="text"
                inputMode="numeric"
                value={String(config.reddit_min_ups ?? 100)}
                onChange={(e) => {
                  const cleaned = e.target.value.replace(/[^\d]/g, "");
                  onChange(
                    { ...config, reddit_min_ups: cleaned ? Number.parseInt(cleaned, 10) : 0 },
                    false,
                  );
                }}
              />
            </Field>
          </div>
          <div>
            <Button type="button" size="sm" variant="ghost" onClick={() => setRedditUaOpen((v) => !v)}>
              <SlidersHorizontal data-icon="inline-start" />
              <span>{redditUaOpen ? "收起高级请求头" : "高级请求头设置（可选）"}</span>
            </Button>
          </div>
          {redditUaOpen && (
            <Field>
              <FieldLabel>自定义 User-Agent（可选）</FieldLabel>
              <Input
                value={String(config.reddit_user_agent || "")}
                onChange={(e) => onChange({ ...config, reddit_user_agent: e.target.value }, false)}
                placeholder="TrendRadar/1.0 (personal self-hosted reader)"
              />
            </Field>
          )}
        </div>
      ),
    },
    {
      key: "youtube",
      title: "YouTube 频道直抓",
      enabled: youtubeEnabled,
      enabledField: "youtube_enabled",
      summary:
        ytChannels.length > 0
          ? `已配置 ${ytChannels.length} 个频道 · 免申请密钥`
          : "未添加频道，点击展开添加频道网址或 @频道名",
      renderDetail: () => (
        <ForeignChipEditor
          label="订阅频道"
          description="自动读取公开频道最新视频与简介，无需申请 Google API Key"
          items={ytChannels}
          placeholder="支持 @OpenAI、https://www.youtube.com/@TwoMinutePapers 或 UC..."
          addButtonText="添加频道"
          onChange={(nextChannels, immediate) =>
            onChange({ ...config, youtube_channels: nextChannels }, immediate)
          }
          onUnloadCommit={(nextChannels) =>
            onKeepaliveFlushRef.current?.({
              ...configRef.current,
              youtube_channels: nextChannels,
            })
          }
        />
      ),
    },
    {
      key: "hackernews",
      title: "Hacker News 科技热榜",
      enabled: hnEnabled,
      enabledField: "hackernews_enabled",
      summary: `最低 ${Number(config.hackernews_min_score ?? 80)} 分 · 最多 ${Number(config.hackernews_limit ?? 25)} 条`,
      renderDetail: () => (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field>
            <FieldLabel>最低分数门槛</FieldLabel>
            <Input
              type="text"
              inputMode="numeric"
              value={String(config.hackernews_min_score ?? 80)}
              onChange={(e) => {
                const cleaned = e.target.value.replace(/[^\d]/g, "");
                onChange(
                  { ...config, hackernews_min_score: cleaned ? Number.parseInt(cleaned, 10) : 0 },
                  false,
                );
              }}
            />
          </Field>
          <Field>
            <FieldLabel>抓取条数上限</FieldLabel>
            <Input
              type="text"
              inputMode="numeric"
              value={String(config.hackernews_limit ?? 25)}
              onChange={(e) => {
                const cleaned = e.target.value.replace(/[^\d]/g, "");
                onChange(
                  { ...config, hackernews_limit: Math.max(1, Number.parseInt(cleaned || "1", 10)) },
                  false,
                );
              }}
            />
          </Field>
        </div>
      ),
    },
    {
      key: "huggingface",
      title: "Hugging Face 每日论文与模型",
      enabled: hfEnabled,
      enabledField: "huggingface_enabled",
      summary: `每次最多抓取 ${Number(config.huggingface_limit ?? 20)} 条（论文 + 热门模型）`,
      renderDetail: () => (
        <Field className="sm:max-w-xs">
          <FieldLabel>抓取条数上限（论文与模型平分）</FieldLabel>
          <Input
            type="text"
            inputMode="numeric"
            value={String(config.huggingface_limit ?? 20)}
            onChange={(e) => {
              const cleaned = e.target.value.replace(/[^\d]/g, "");
              onChange(
                { ...config, huggingface_limit: Math.max(2, Number.parseInt(cleaned || "2", 10)) },
                false,
              );
            }}
          />
        </Field>
      ),
    },
    {
      key: "github",
      title: "GitHub Trending 开源热榜",
      enabled: ghEnabled,
      enabledField: "github_enabled",
      summary: `最低 ${Number(config.github_min_stars ?? 50)} Stars · 最多 ${Number(config.github_limit ?? 20)} 条 · ${String(config.github_token || "").trim() ? "已填 Token" : "匿名模式"}`,
      renderDetail: () => (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field>
            <FieldLabel>近 7 天最低 Star 数</FieldLabel>
            <Input
              type="text"
              inputMode="numeric"
              value={String(config.github_min_stars ?? 50)}
              onChange={(e) => {
                const cleaned = e.target.value.replace(/[^\d]/g, "");
                onChange(
                  { ...config, github_min_stars: cleaned ? Number.parseInt(cleaned, 10) : 0 },
                  false,
                );
              }}
            />
          </Field>
          <Field>
            <FieldLabel>抓取条数上限</FieldLabel>
            <Input
              type="text"
              inputMode="numeric"
              value={String(config.github_limit ?? 20)}
              onChange={(e) => {
                const cleaned = e.target.value.replace(/[^\d]/g, "");
                onChange(
                  { ...config, github_limit: Math.max(1, Number.parseInt(cleaned || "1", 10)) },
                  false,
                );
              }}
            />
          </Field>
          <Field>
            <FieldLabel>GitHub Token（可选提额）</FieldLabel>
            <Input
              type="password"
              value={String(config.github_token || "")}
              onChange={(e) => onChange({ ...config, github_token: e.target.value }, false)}
              placeholder="留空则使用匿名请求限额"
            />
          </Field>
        </div>
      ),
    },
  ];

  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold">海外资讯平台（无需繁琐授权）</h3>
            <Badge variant="outline">
              已启用 {enabledCount} / 共 {rows.length}
            </Badge>
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">
            点击任一平台即可展开其专属参数与订阅列表，未展开项保持折叠以减少视觉干扰
          </p>
        </div>
      </div>

      <FieldGroup>
        <div className="flex flex-col gap-2.5">
          {rows.map((row) => {
            const isOpen = expandedKey === row.key;
            return (
              <div
                key={row.key}
                className={cn(
                  "rounded-md border bg-card transition-colors",
                  isOpen ? "border-primary/60 ring-1 ring-primary/20" : "border-border",
                )}
              >
                <div className="flex flex-wrap items-center justify-between gap-2.5 p-3.5">
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    onClick={() => toggleExpand(row.key)}
                    className="flex min-w-0 flex-1 flex-col gap-1 text-left cursor-pointer"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-base font-medium">{row.title}</span>
                      <Badge variant={row.enabled ? "success" : "secondary"}>
                        {row.enabled ? "已启用" : "已停用"}
                      </Badge>
                    </div>
                    <span className="text-sm leading-snug text-muted-foreground break-words sm:truncate">
                      {row.summary}
                    </span>
                  </button>

                  <div className="flex shrink-0 items-center gap-2">
                    <Switch
                      aria-label={`开关 ${row.title}`}
                      checked={row.enabled}
                      onCheckedChange={(v) => onChange({ ...config, [row.enabledField]: v }, true)}
                    />
                    <Button
                      type="button"
                      size="sm"
                      variant={isOpen ? "secondary" : "outline"}
                      aria-expanded={isOpen}
                      aria-label={`${isOpen ? "收起" : "配置"} ${row.title}`}
                      onClick={() => toggleExpand(row.key)}
                    >
                      {isOpen ? (
                        <>
                          <ChevronUp data-icon="inline-start" />
                          <span>收起</span>
                        </>
                      ) : (
                        <>
                          <ChevronDown data-icon="inline-start" />
                          <span>配置</span>
                        </>
                      )}
                    </Button>
                  </div>
                </div>

                {isOpen && (
                  <div className="border-t border-border bg-muted/20 p-4 sm:p-5">{row.renderDetail()}</div>
                )}
              </div>
            );
          })}
        </div>

        <div className="flex flex-col gap-2 border-t border-border pt-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <FieldDescription>上述 5 个海外源共用同一个可选出口代理。</FieldDescription>
              <Badge variant={proxyConfigured ? "warning" : "outline"}>
                {proxyConfigured ? "已配置代理" : "直连"}
              </Badge>
            </div>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setProxyOpen((v) => !v)}
            >
              <SlidersHorizontal data-icon="inline-start" />
              <span>{proxyOpen ? "收起代理设置" : "海外网络代理设置"}</span>
            </Button>
          </div>
          {proxyOpen && (
            <Field>
              <FieldLabel>海外源可选代理 URL</FieldLabel>
              <Input
                value={String(config.proxy_url || "")}
                onChange={(e) => onChange({ ...config, proxy_url: e.target.value }, false)}
                placeholder="例如：http://127.0.0.1:7897（香港服务器直连可留空）"
              />
            </Field>
          )}
        </div>
      </FieldGroup>
    </Card>
  );
}
