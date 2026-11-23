import { useState } from "react";
import { Plus, SlidersHorizontal, Sparkles, Trash2 } from "lucide-react";
import { AutoSaveBadge } from "@/components/settings/AutoSaveBadge";
import { AUTHORITATIVE_PLATFORM_PRESETS, type PlatformSource } from "@/components/settings/authoritativePresets";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import type { AutoSaveStatus } from "@/hooks/useAutoSave";

interface PlatformsManagerCardProps {
  config: Record<string, unknown>;
  saveStatus?: AutoSaveStatus;
  onChange: (next: Record<string, unknown>, immediate?: boolean) => void;
  onSave: () => void;
  onError: (msg: string) => void;
}

export function PlatformsManagerCard({
  config,
  saveStatus = "idle",
  onChange,
  onSave,
  onError,
}: PlatformsManagerCardProps) {
  const [presetOpen, setPresetOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [customId, setCustomId] = useState("");
  const [customName, setCustomName] = useState("");
  const [customDomain, setCustomDomain] = useState("");

  const sources = (config.sources as PlatformSource[]) || [];
  const existingIds = new Set(sources.map((s) => s.id));
  const enabledCount = sources.filter((s) => s.enabled !== false).length;

  const updateSources = (nextSources: PlatformSource[], immediate = true) => {
    onChange({ ...config, sources: nextSources }, immediate);
  };

  const handleAddPreset = (id: string, name: string) => {
    if (existingIds.has(id)) return;
    updateSources([...sources, { id, name, enabled: true }], true);
  };

  const handleAddAllPresets = () => {
    const missing = AUTHORITATIVE_PLATFORM_PRESETS.filter((p) => !existingIds.has(p.id)).map((p) => ({
      id: p.id,
      name: p.name,
      enabled: true,
    }));
    if (missing.length > 0) {
      updateSources([...sources, ...missing], true);
    }
  };

  const handleAddCustom = () => {
    const id = customId.trim();
    const name = customName.trim();
    if (!id || !name) {
      onError("请填写平台 ID 与显示名称");
      return;
    }
    if (existingIds.has(id)) {
      onError(`平台 ID "${id}" 已存在`);
      return;
    }
    onError("");
    const entry: PlatformSource = { id, name, enabled: true };
    if (customDomain.trim()) {
      entry.expected_domain = customDomain.trim();
    }
    updateSources([...sources, entry], true);
    setCustomId("");
    setCustomName("");
    setCustomDomain("");
  };

  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-semibold">国内热门榜单</h3>
          <Badge variant="outline">
            已启用 {enabledCount} / 共 {sources.length}
          </Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <AutoSaveBadge status={saveStatus} onFlush={onSave} />
          <Button size="sm" variant="outline" onClick={() => setPresetOpen((v) => !v)}>
            <Sparkles data-icon="inline-start" />
            <span>{presetOpen ? "收起预设" : "权威媒体预设"}</span>
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setAdvancedOpen((v) => !v)}>
            <SlidersHorizontal data-icon="inline-start" />
            <span>{advancedOpen ? "收起高级选项" : "高级连接与自定义"}</span>
          </Button>
        </div>
      </div>

      <FieldGroup>
        <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/15 px-3.5 py-2.5">
          <span className="text-sm font-medium">启用国内热榜更新</span>
          <Switch
            checked={Boolean(config.enabled ?? true)}
            onCheckedChange={(v) => onChange({ ...config, enabled: v }, true)}
          />
        </div>

        {presetOpen && (
          <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/30 p-3.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold">已验证权威 NewsNow 平台源</span>
                <span className="text-sm text-muted-foreground">添加后将自动保存到数据库</span>
              </div>
              <Button size="sm" variant="secondary" onClick={handleAddAllPresets}>
                一键添加全部权威平台
              </Button>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {AUTHORITATIVE_PLATFORM_PRESETS.map((preset) => {
                const added = existingIds.has(preset.id);
                return (
                  <div
                    key={preset.id}
                    className="flex items-start justify-between gap-2 rounded-md border border-border bg-card p-3"
                  >
                    <div className="flex min-w-0 flex-col gap-0.5">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-sm font-semibold">{preset.name}</span>
                        <span className="font-mono text-xs text-muted-foreground">{preset.id}</span>
                      </div>
                      <p className="text-xs sm:text-sm leading-snug text-muted-foreground">{preset.description}</p>
                    </div>
                    <Button
                      size="sm"
                      variant={added ? "outline" : "default"}
                      disabled={added}
                      onClick={() => handleAddPreset(preset.id, preset.name)}
                    >
                      {added ? "已添加" : "+ 添加"}
                    </Button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {sources.map((src, idx) => (
            <div
              key={src.id}
              className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2.5"
            >
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-sm font-medium">{src.name}</span>
                <span className="truncate font-mono text-xs text-muted-foreground">{src.id}</span>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <Switch
                  aria-label={`开关平台 ${src.name}`}
                  checked={src.enabled !== false}
                  onCheckedChange={(checked) => {
                    updateSources(
                      sources.map((item, i) => (i === idx ? { ...item, enabled: checked } : item)),
                      true,
                    );
                  }}
                />
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="size-9 text-muted-foreground hover:text-destructive"
                  aria-label={`删除平台 ${src.name}`}
                  onClick={() => {
                    if (!window.confirm(`确定删除平台「${src.name}」吗？`)) return;
                    updateSources(sources.filter((_, i) => i !== idx), true);
                  }}
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>

        {advancedOpen && (
          <div className="flex flex-col gap-4 rounded-lg border border-border bg-muted/20 p-4">
            <Field>
              <FieldLabel>NewsNow API URL</FieldLabel>
              <FieldDescription>默认保持官方聚合地址即可，仅自建镜像时修改</FieldDescription>
              <Input
                value={String(config.api_url || "")}
                onChange={(e) => onChange({ ...config, api_url: e.target.value }, false)}
                placeholder="https://newsnow.busiyi.world/api/s"
              />
            </Field>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2.5">
                <span className="text-sm font-medium">启用国内热榜代理</span>
                <Switch
                  checked={Boolean(config.use_proxy ?? false)}
                  onCheckedChange={(v) => onChange({ ...config, use_proxy: v }, true)}
                />
              </div>
              <Field>
                <FieldLabel>热榜代理 URL（可选）</FieldLabel>
                <Input
                  value={String(config.proxy_url || "")}
                  onChange={(e) => {
                    const val = e.target.value;
                    onChange({ ...config, proxy_url: val, use_proxy: Boolean(val.trim()) }, false);
                  }}
                  placeholder="http://127.0.0.1:7897"
                />
              </Field>
            </div>

            <div className="flex flex-col gap-3 rounded-md border border-dashed border-border bg-card p-4">
              <span className="text-sm font-semibold text-foreground">添加自定义 NewsNow 平台</span>
              <div className="grid gap-3 sm:grid-cols-4">
                <Input
                  value={customId}
                  onChange={(e) => setCustomId(e.target.value)}
                  placeholder="平台 ID（如 zhihu）"
                />
                <Input
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  placeholder="显示名称（如 知乎）"
                />
                <Input
                  value={customDomain}
                  onChange={(e) => setCustomDomain(e.target.value)}
                  placeholder="域名校验(可选，如 zhihu.com)"
                />
                <Button type="button" variant="outline" onClick={handleAddCustom} className="h-10">
                  <Plus data-icon="inline-start" />
                  <span>添加平台</span>
                </Button>
              </div>
            </div>
          </div>
        )}
      </FieldGroup>
    </Card>
  );
}
