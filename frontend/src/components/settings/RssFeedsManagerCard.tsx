import { useMemo, useState } from "react";
import { Code2, Pencil, Plus, Search, SlidersHorizontal, Sparkles, Trash2 } from "lucide-react";
import { AutoSaveBadge } from "@/components/settings/AutoSaveBadge";
import {
  AUTHORITATIVE_RSS_PRESETS,
  isDeprecatedFeedUrl,
  type DomainItemCfg,
  type RssFeedCfg,
  type RssPreset,
} from "@/components/settings/authoritativePresets";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { AutoSaveStatus } from "@/hooks/useAutoSave";
import { cn } from "@/lib/utils";

interface RssFeedsManagerCardProps {
  config: Record<string, unknown>;
  domains: DomainItemCfg[];
  saveStatus?: AutoSaveStatus;
  onChange: (next: Record<string, unknown>, immediate?: boolean) => void;
  onSave: () => void;
  onError: (msg: string) => void;
}

interface FeedFormValues {
  id: string;
  name: string;
  url: string;
  domain: string;
  maxAge: string;
  maxItems: string;
  enabled: boolean;
}

interface RssFeedFormProps {
  title: string;
  submitLabel: string;
  values: FeedFormValues;
  domainOptions: { id: string; label: string }[];
  saveStatus?: AutoSaveStatus;
  onSave?: () => void;
  onChange: (patch: Partial<FeedFormValues>) => void;
  onCancel: () => void;
  onSubmit: () => void;
}

function RssFeedForm({
  title,
  submitLabel,
  values,
  domainOptions,
  saveStatus = "idle",
  onSave,
  onChange,
  onCancel,
  onSubmit,
}: RssFeedFormProps) {
  return (
    <div className="flex flex-col gap-5">
      <span className="text-base font-semibold text-foreground">{title}</span>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel>名称 *</FieldLabel>
          <Input
            value={values.name}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="例如：国家统计局 · 最新发布"
          />
        </Field>
        <Field>
          <FieldLabel>唯一 ID（可留空自动生成）</FieldLabel>
          <Input
            value={values.id}
            onChange={(e) => onChange({ id: e.target.value })}
            placeholder="留空则按名称自动生成"
          />
        </Field>
        <Field className="sm:col-span-2">
          <FieldLabel>订阅 URL *</FieldLabel>
          <Input
            value={values.url}
            onChange={(e) => onChange({ url: e.target.value })}
            placeholder="https://example.com/rss.xml"
          />
        </Field>
        <Field>
          <FieldLabel>所属领域</FieldLabel>
          <Select value={values.domain} onValueChange={(v) => onChange({ domain: v })}>
            <SelectTrigger>
              <SelectValue placeholder="选择领域" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {domainOptions.map((dom) => (
                  <SelectItem key={dom.id} value={dom.id}>
                    {dom.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field>
            <FieldLabel>保留天数（空=全局）</FieldLabel>
            <Input
              type="text"
              inputMode="numeric"
              value={values.maxAge}
              onChange={(e) => onChange({ maxAge: e.target.value.replace(/[^\d]/g, "") })}
              placeholder="0=不限"
            />
          </Field>
          <Field>
            <FieldLabel>条目上限（0=不限）</FieldLabel>
            <Input
              type="text"
              inputMode="numeric"
              value={values.maxItems}
              onChange={(e) => onChange({ maxItems: e.target.value.replace(/[^\d]/g, "") })}
            />
          </Field>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <div className="flex flex-wrap items-center gap-3">
          <Switch checked={values.enabled} onCheckedChange={(v) => onChange({ enabled: v })} />
          <span className="text-sm font-medium">启用此订阅</span>
          <AutoSaveBadge status={saveStatus} onFlush={onSave} />
        </div>
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="outline" onClick={onCancel}>
            取消
          </Button>
          <Button type="button" size="sm" onClick={onSubmit}>
            {submitLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

function generateFeedSlug(name: string, url: string, existingIds: Set<string>): string {
  let base = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (!base) {
    try {
      const host = new URL(url).hostname.replace(/^www\./, "").replace(/[^a-z0-9]+/g, "-");
      base = host || "rss-feed";
    } catch {
      base = "rss-feed";
    }
  }
  let candidate = base.slice(0, 32);
  let seq = 2;
  while (existingIds.has(candidate)) {
    candidate = `${base.slice(0, 26)}-${seq}`;
    seq += 1;
  }
  return candidate;
}

export function RssFeedsManagerCard({
  config,
  domains,
  saveStatus = "idle",
  onChange,
  onSave,
  onError,
}: RssFeedsManagerCardProps) {
  const [globalOpen, setGlobalOpen] = useState(false);
  const [presetOpen, setPresetOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [domainFilter, setDomainFilter] = useState("ALL");
  const [jsonOpen, setJsonOpen] = useState(false);
  const [jsonDraft, setJsonDraft] = useState("");

  const [formValues, setFormValues] = useState<FeedFormValues>({
    id: "",
    name: "",
    url: "",
    domain: "宏观政策",
    maxAge: "",
    maxItems: "0",
    enabled: true,
  });

  const feeds = useMemo(() => (config.feeds as RssFeedCfg[]) || [], [config.feeds]);
  const existingIds = useMemo(() => new Set(feeds.map((f) => f.id)), [feeds]);
  const existingUrls = useMemo(() => new Set(feeds.map((f) => f.url.trim())), [feeds]);
  const enabledCount = feeds.filter((f) => f.enabled !== false).length;

  const domainNameMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const d of domains) {
      if (d.id) {
        map[d.id] = d.name || d.id;
      }
    }
    return map;
  }, [domains]);

  const domainOptions = useMemo(() => {
    const seen = new Set<string>();
    const opts: { id: string; label: string }[] = [];
    for (const d of domains) {
      if (d.id && !seen.has(d.id)) {
        seen.add(d.id);
        opts.push({ id: d.id, label: d.name || d.id });
      }
    }
    for (const f of feeds) {
      if (f.domain && !seen.has(f.domain)) {
        seen.add(f.domain);
        opts.push({ id: f.domain, label: domainNameMap[f.domain] || f.domain });
      }
    }
    if (!seen.has("其他")) opts.push({ id: "其他", label: domainNameMap["其他"] || "其他" });
    return opts;
  }, [domains, feeds, domainNameMap]);

  const filterDomains = useMemo(() => {
    const present = Array.from(new Set(feeds.map((f) => f.domain || "其他")));
    return ["ALL", ...present];
  }, [feeds]);

  const visibleFeeds = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return feeds
      .map((feed, idx) => ({ feed, idx }))
      .filter(({ feed }) => {
        if (domainFilter !== "ALL" && (feed.domain || "其他") !== domainFilter) return false;
        if (!q) return true;
        return (
          feed.name.toLowerCase().includes(q) ||
          feed.url.toLowerCase().includes(q) ||
          feed.id.toLowerCase().includes(q)
        );
      });
  }, [feeds, domainFilter, searchQuery]);

  const updateFeeds = (nextFeeds: RssFeedCfg[], immediate = true) => {
    onChange({ ...config, feeds: nextFeeds }, immediate);
  };

  const patchForm = (patch: Partial<FeedFormValues>) => {
    setFormValues((prev) => ({ ...prev, ...patch }));
  };

  const openCreateForm = () => {
    onError("");
    setEditingIdx(null);
    setFormValues({
      id: "",
      name: "",
      url: "",
      domain: domainOptions[0]?.id || "宏观政策",
      maxAge: "",
      maxItems: "0",
      enabled: true,
    });
    setCreateOpen((v) => !v);
  };

  const toggleEditForm = (feed: RssFeedCfg, idx: number) => {
    onError("");
    setCreateOpen(false);
    if (editingIdx === idx) {
      setEditingIdx(null);
      return;
    }
    setEditingIdx(idx);
    setFormValues({
      id: feed.id,
      name: feed.name,
      url: feed.url,
      domain: feed.domain || "其他",
      maxAge: feed.max_age_days === undefined || feed.max_age_days === null ? "" : String(feed.max_age_days),
      maxItems: String(feed.max_items ?? 0),
      enabled: feed.enabled !== false,
    });
  };

  const handleSubmitForm = (targetIdx: number | null) => {
    const cleanName = formValues.name.trim();
    const cleanUrl = formValues.url.trim();
    if (!cleanName || !cleanUrl) {
      onError("请填写 RSS 名称和订阅 URL");
      return;
    }
    if (!/^https?:\/\//i.test(cleanUrl)) {
      onError("RSS 订阅地址必须以 http:// 或 https:// 开头");
      return;
    }

    const otherIds = new Set(feeds.filter((_, i) => i !== targetIdx).map((f) => f.id));
    const resolvedId = formValues.id.trim() || generateFeedSlug(cleanName, cleanUrl, otherIds);
    if (otherIds.has(resolvedId)) {
      onError(`RSS 唯一 ID "${resolvedId}" 已存在`);
      return;
    }

    const nextItem: RssFeedCfg = {
      id: resolvedId,
      name: cleanName,
      url: cleanUrl,
      domain: formValues.domain || "其他",
      enabled: formValues.enabled,
    };
    const ageTrim = formValues.maxAge.trim();
    if (ageTrim !== "") {
      const parsedAge = Number.parseInt(ageTrim, 10);
      if (Number.isNaN(parsedAge) || parsedAge < 0) {
        onError("保留天数必须为非负整数（0 表示不限）");
        return;
      }
      nextItem.max_age_days = parsedAge;
    }
    const itemsTrim = formValues.maxItems.trim();
    if (itemsTrim !== "") {
      const parsedItems = Number.parseInt(itemsTrim, 10);
      if (!Number.isNaN(parsedItems) && parsedItems > 0) {
        nextItem.max_items = parsedItems;
      }
    }

    onError("");
    if (targetIdx === null) {
      updateFeeds([nextItem, ...feeds], true);
      setCreateOpen(false);
    } else {
      updateFeeds(feeds.map((item, i) => (i === targetIdx ? nextItem : item)), true);
      setEditingIdx(null);
    }
  };

  const handleDeleteFeed = (feed: RssFeedCfg, idx: number) => {
    if (!window.confirm(`确定删除 RSS 订阅「${feed.name}」吗？`)) return;
    updateFeeds(feeds.filter((_, i) => i !== idx), true);
    if (editingIdx === idx) {
      setEditingIdx(null);
    } else if (editingIdx !== null && idx < editingIdx) {
      setEditingIdx(editingIdx - 1);
    }
  };

  const addPresetFeed = (preset: RssPreset) => {
    if (existingIds.has(preset.id) || existingUrls.has(preset.url)) return;
    updateFeeds(
      [
        ...feeds,
        {
          id: preset.id,
          name: preset.name,
          url: preset.url,
          domain: preset.domain,
          enabled: true,
          max_age_days: preset.max_age_days,
          max_items: preset.max_items,
        },
      ],
      true,
    );
  };

  const addAllDirectPresets = () => {
    const additions = AUTHORITATIVE_RSS_PRESETS.filter(
      (p) => !p.needsProxy && !existingIds.has(p.id) && !existingUrls.has(p.url),
    ).map((p) => ({
      id: p.id,
      name: p.name,
      url: p.url,
      domain: p.domain,
      enabled: true,
      max_age_days: p.max_age_days,
      max_items: p.max_items,
    }));
    if (additions.length > 0) {
      updateFeeds([...feeds, ...additions], true);
    }
  };

  const toggleJsonTool = () => {
    if (!jsonOpen) {
      setJsonDraft(JSON.stringify(feeds, null, 2));
    }
    setJsonOpen((v) => !v);
  };

  const applyJsonImport = () => {
    try {
      const parsed = JSON.parse(jsonDraft);
      if (!Array.isArray(parsed)) {
        onError("JSON 必须是订阅对象数组");
        return;
      }
      onError("");
      updateFeeds(parsed as RssFeedCfg[], true);
      setEditingIdx(null);
      setJsonOpen(false);
    } catch {
      onError("RSS JSON 格式无效，请检查语法");
    }
  };

  const presetGroups: { key: RssPreset["category"]; title: string }[] = [
    { key: "domestic_direct", title: "国内直连官方 RSS（免代理）" },
    { key: "official_proxy", title: "新华社 / 国家部委定向聚合（需海外或开启 RSS 代理）" },
    { key: "international_proxy", title: "国际权威媒体（需海外或开启 RSS 代理）" },
  ];

  const rssUseProxy = Boolean(config.use_proxy ?? false);

  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-semibold">媒体与官方订阅 (RSS)</h3>
          <Badge variant="outline">
            已启用 {enabledCount} / 共 {feeds.length}
          </Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <AutoSaveBadge status={saveStatus} onFlush={onSave} />
          <Button size="sm" variant="outline" onClick={() => setPresetOpen((v) => !v)}>
            <Sparkles data-icon="inline-start" />
            <span>{presetOpen ? "收起预设" : "权威媒体预设"}</span>
          </Button>
          <Button size="sm" variant="outline" onClick={openCreateForm}>
            <Plus data-icon="inline-start" />
            <span>{createOpen ? "取消新增" : "新增订阅"}</span>
          </Button>
        </div>
      </div>

      <FieldGroup>
        <div className="flex flex-col gap-3 rounded-md border border-border bg-muted/20 p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2.5">
              <Switch
                aria-label="启用 RSS 抓取"
                checked={Boolean(config.enabled ?? true)}
                onCheckedChange={(v) => onChange({ ...config, enabled: v }, true)}
              />
              <span className="text-sm font-medium">启用媒体订阅更新</span>
              <Badge variant="outline">保留 {Number(config.max_age_days ?? 2)} 天</Badge>
              <Badge variant={rssUseProxy ? "warning" : "outline"}>
                {rssUseProxy ? "已开启代理" : "直连"}
              </Badge>
            </div>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setGlobalOpen((v) => !v)}
            >
              <SlidersHorizontal data-icon="inline-start" />
              <span>{globalOpen ? "收起全局参数" : "全局参数与代理"}</span>
            </Button>
          </div>

          {globalOpen && (
            <div className="grid gap-3 border-t border-border pt-3 sm:grid-cols-2 lg:grid-cols-3">
              <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2.5">
                <span className="text-sm font-medium">启用新鲜度过滤</span>
                <Switch
                  checked={Boolean(config.freshness_enabled ?? true)}
                  onCheckedChange={(v) => onChange({ ...config, freshness_enabled: v }, true)}
                />
              </div>
              <Field>
                <FieldLabel>默认保留天数</FieldLabel>
                <Input
                  type="text"
                  inputMode="numeric"
                  value={String(config.max_age_days ?? 2)}
                  onChange={(e) => {
                    const cleaned = e.target.value.replace(/[^\d]/g, "");
                    onChange({ ...config, max_age_days: cleaned ? Number.parseInt(cleaned, 10) : 0 }, false);
                  }}
                />
              </Field>
              <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2.5">
                <span className="text-sm font-medium">启用 RSS 代理</span>
                <Switch
                  checked={rssUseProxy}
                  onCheckedChange={(v) => onChange({ ...config, use_proxy: v }, true)}
                />
              </div>
              <Field className="sm:col-span-2 lg:col-span-3">
                <FieldLabel>RSS 代理 URL（填写非空地址会自动启用代理）</FieldLabel>
                <Input
                  value={String(config.proxy_url || "")}
                  onChange={(e) => {
                    const val = e.target.value;
                    onChange({ ...config, proxy_url: val, use_proxy: Boolean(val.trim()) }, false);
                  }}
                  placeholder="http://127.0.0.1:7897（香港服务器直连可留空）"
                />
              </Field>
            </div>
          )}
        </div>

        {presetOpen && (
          <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/30 p-3.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold">权威媒体官方 RSS 与定向源预设（均已实测可用）</span>
                <span className="text-sm text-muted-foreground">加入列表后将自动保存到数据库</span>
              </div>
              <Button size="sm" variant="secondary" onClick={addAllDirectPresets}>
                一键加入全部直连源
              </Button>
            </div>

            {presetGroups.map((grp) => {
              const items = AUTHORITATIVE_RSS_PRESETS.filter((p) => p.category === grp.key);
              return (
                <div key={grp.key} className="flex flex-col gap-2">
                  <span className="text-sm font-semibold text-foreground">{grp.title}</span>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {items.map((preset) => {
                      const added = existingIds.has(preset.id) || existingUrls.has(preset.url);
                      return (
                        <div
                          key={preset.id}
                          className="flex items-start justify-between gap-2 rounded-md border border-border bg-card p-3"
                        >
                          <div className="flex min-w-0 flex-col gap-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-sm font-semibold">{preset.name}</span>
                              <Badge variant="outline">
                                {domainNameMap[preset.domain || "其他"] || preset.domain || "其他"}
                              </Badge>
                              <Badge variant={preset.needsProxy ? "warning" : "success"}>
                                {preset.needsProxy ? "需代理" : "直连"}
                              </Badge>
                            </div>
                            <p className="text-xs sm:text-sm leading-snug text-muted-foreground">{preset.note}</p>
                          </div>
                          <Button
                            size="sm"
                            variant={added ? "outline" : "default"}
                            disabled={added}
                            onClick={() => addPresetFeed(preset)}
                          >
                            {added ? "已添加" : "+ 添加"}
                          </Button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {createOpen && (
          <div className="rounded-lg border border-primary/40 bg-muted/30 p-4 sm:p-5">
            <RssFeedForm
              title="新增 RSS 订阅"
              submitLabel="确认添加"
              values={formValues}
              domainOptions={domainOptions}
              saveStatus={saveStatus}
              onSave={onSave}
              onChange={patchForm}
              onCancel={() => setCreateOpen(false)}
              onSubmit={() => handleSubmitForm(null)}
            />
          </div>
        )}

        <div className="flex flex-col gap-2.5">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative flex-1 sm:max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-3 size-4 text-muted-foreground" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索订阅名称、ID 或 URL..."
                className="pl-8"
              />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {filterDomains.map((dom) => (
                <Button
                  key={dom}
                  type="button"
                  size="sm"
                  variant={domainFilter === dom ? "default" : "outline"}
                  className="shrink-0"
                  onClick={() => setDomainFilter(dom)}
                >
                  {dom === "ALL" ? "全部领域" : domainNameMap[dom] || dom}
                </Button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-2.5">
            {visibleFeeds.length === 0 ? (
              <div className="rounded-md border border-dashed border-border p-5 text-center text-sm text-muted-foreground">
                暂无匹配的 RSS 订阅项
              </div>
            ) : (
              visibleFeeds.map(({ feed, idx }) => {
                const deprecatedMsg = isDeprecatedFeedUrl(feed.url);
                const isEditing = editingIdx === idx;
                const domainLabel = domainNameMap[feed.domain || "其他"] || feed.domain || "其他";
                return (
                  <div
                    key={`${feed.id}-${idx}`}
                    data-feed-id={feed.id}
                    className={cn(
                      "rounded-md border bg-card transition-colors",
                      isEditing ? "border-primary/60 ring-1 ring-primary/20" : "border-border",
                    )}
                  >
                    <div className="flex flex-col gap-2 p-3.5 sm:flex-row sm:items-center sm:justify-between">
                      <button
                        type="button"
                        aria-expanded={isEditing}
                        onClick={() => toggleEditForm(feed, idx)}
                        className="flex min-w-0 flex-1 flex-col gap-1 text-left cursor-pointer"
                      >
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-sm sm:text-base font-medium">{feed.name}</span>
                          <Badge variant="outline">{domainLabel}</Badge>
                          <span className="font-mono text-xs text-muted-foreground">{feed.id}</span>
                          {feed.max_age_days !== undefined && feed.max_age_days !== null && (
                            <Badge variant="secondary">
                              {feed.max_age_days === 0 ? "不限天数" : `保留 ${feed.max_age_days} 天`}
                            </Badge>
                          )}
                          {feed.max_items ? <Badge variant="secondary">上限 {feed.max_items} 条</Badge> : null}
                          {deprecatedMsg && <Badge variant="destructive">{deprecatedMsg}</Badge>}
                        </div>
                        <span className="break-all font-mono text-xs sm:text-sm text-muted-foreground">{feed.url}</span>
                      </button>

                      <div className="flex shrink-0 items-center justify-end gap-1.5">
                        <Switch
                          aria-label={`开关订阅 ${feed.name}`}
                          checked={feed.enabled !== false}
                          onCheckedChange={(checked) => {
                            updateFeeds(
                              feeds.map((item, i) => (i === idx ? { ...item, enabled: checked } : item)),
                              true,
                            );
                          }}
                        />
                        <Button
                          type="button"
                          size="icon"
                          variant={isEditing ? "secondary" : "ghost"}
                          className="size-9"
                          aria-label={`编辑 RSS ${feed.name}`}
                          aria-expanded={isEditing}
                          onClick={() => toggleEditForm(feed, idx)}
                        >
                          <Pencil className="size-4" />
                        </Button>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="size-9 text-muted-foreground hover:text-destructive"
                          aria-label={`删除 RSS ${feed.name}`}
                          onClick={() => handleDeleteFeed(feed, idx)}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      </div>
                    </div>

                    {isEditing && (
                      <div className="border-t border-border bg-muted/20 p-4 sm:p-5" data-inline-edit-for={feed.id}>
                        <RssFeedForm
                          title={`编辑订阅：${feed.name}`}
                          submitLabel="确认更新"
                          values={formValues}
                          domainOptions={domainOptions}
                          saveStatus={saveStatus}
                          onSave={onSave}
                          onChange={patchForm}
                          onCancel={() => setEditingIdx(null)}
                          onSubmit={() => handleSubmitForm(idx)}
                        />
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="flex flex-col gap-2 border-t border-border pt-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <FieldDescription>编辑、增删或导入预设后将自动保存到数据库。</FieldDescription>
            <Button type="button" size="sm" variant="ghost" onClick={toggleJsonTool}>
              <Code2 data-icon="inline-start" />
              <span>{jsonOpen ? "收起 JSON" : "JSON 批量导入/导出"}</span>
            </Button>
          </div>
          {jsonOpen && (
            <div className="flex flex-col gap-2">
              <Textarea
                value={jsonDraft}
                onChange={(e) => setJsonDraft(e.target.value)}
                className="min-h-40 font-mono text-sm"
              />
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="outline" onClick={() => setJsonOpen(false)}>
                  关闭
                </Button>
                <Button size="sm" onClick={applyJsonImport}>
                  应用到列表
                </Button>
              </div>
            </div>
          )}
        </div>
      </FieldGroup>
    </Card>
  );
}
