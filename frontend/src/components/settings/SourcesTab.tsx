import { useEffect, useState } from "react";
import { Globe, ShieldAlert } from "lucide-react";
import { settingsApi } from "@/api/endpoints";
import type { DomainItemCfg, PlatformSource, RssFeedCfg } from "@/components/settings/authoritativePresets";
import { DomainsManagerCard } from "@/components/settings/DomainsManagerCard";
import { ForeignSourcesManagerCard } from "@/components/settings/ForeignSourcesManagerCard";
import { PlatformsManagerCard } from "@/components/settings/PlatformsManagerCard";
import { RssFeedsManagerCard } from "@/components/settings/RssFeedsManagerCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert } from "@/components/ui/feedback";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useAutoSave } from "@/hooks/useAutoSave";

type SourceCategory = "platforms" | "foreign" | "rss" | "domains";

interface SourcesTabProps {
  onDirtyChange?: (dirty: boolean) => void;
}

export function SourcesTab({ onDirtyChange }: SourcesTabProps = {}) {
  const [category, setCategory] = useState<SourceCategory>("platforms");
  const [platformsCfg, setPlatformsCfg] = useState<Record<string, unknown>>({});
  const [foreignCfg, setForeignCfg] = useState<Record<string, unknown>>({});
  const [rssCfg, setRssCfg] = useState<Record<string, unknown>>({});
  const [domainsCfg, setDomainsCfg] = useState<Record<string, unknown>>({});
  const [loadError, setLoadError] = useState("");
  const [categoryErrors, setCategoryErrors] = useState<Record<SourceCategory, string>>({
    platforms: "",
    foreign: "",
    rss: "",
    domains: "",
  });
  const [proxyOpen, setProxyOpen] = useState(false);
  const [unifiedProxy, setUnifiedProxy] = useState("");
  const [proxyNotice, setProxyNotice] = useState("");

  const platformsAuto = useAutoSave<Record<string, unknown>>({
    delayMs: 450,
    onSave: async (payload) => {
      await settingsApi.updateSection("platforms", payload);
    },
    keepaliveFlush: (payload) => {
      settingsApi.keepaliveUpdateSection("platforms", payload);
    },
  });
  const foreignAuto = useAutoSave<Record<string, unknown>>({
    delayMs: 450,
    onSave: async (payload) => {
      await settingsApi.updateSection("foreign_sources", payload);
    },
    keepaliveFlush: (payload) => {
      settingsApi.keepaliveUpdateSection("foreign_sources", payload);
    },
  });
  const rssAuto = useAutoSave<Record<string, unknown>>({
    delayMs: 450,
    onSave: async (payload) => {
      await settingsApi.updateSection("rss", payload);
    },
    keepaliveFlush: (payload) => {
      settingsApi.keepaliveUpdateSection("rss", payload);
    },
  });
  const domainsAuto = useAutoSave<Record<string, unknown>>({
    delayMs: 450,
    onSave: async (payload) => {
      await settingsApi.updateSection("domains", payload);
    },
    keepaliveFlush: (payload) => {
      settingsApi.keepaliveUpdateSection("domains", payload);
    },
  });

  useEffect(() => {
    Promise.all([
      settingsApi.getSection("platforms"),
      settingsApi.getSection("foreign_sources"),
      settingsApi.getSection("rss"),
      settingsApi.getSection("domains"),
    ])
      .then(([p, f, r, d]) => {
        setPlatformsCfg(p.payload);
        setForeignCfg(f.payload);
        setRssCfg(r.payload);
        setDomainsCfg(d.payload);
        platformsAuto.hydrate(p.payload);
        foreignAuto.hydrate(f.payload);
        rssAuto.hydrate(r.payload);
        domainsAuto.hydrate(d.payload);
        const existingProxy =
          String(f.payload.proxy_url || r.payload.proxy_url || p.payload.proxy_url || "").trim();
        if (existingProxy) setUnifiedProxy(existingProxy);
      })
      .catch((err) => setLoadError(err instanceof Error ? err.message : "加载数据源配置失败"));
    // Run once on initial mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = {
    platforms: platformsAuto.dirty,
    foreign: foreignAuto.dirty,
    rss: rssAuto.dirty,
    domains: domainsAuto.dirty,
  };
  const anyDirty = dirty.platforms || dirty.foreign || dirty.rss || dirty.domains;

  useEffect(() => {
    onDirtyChange?.(anyDirty);
  }, [anyDirty, onDirtyChange]);

  const setCatError = (key: SourceCategory, msg: string) => {
    setCategoryErrors((prev) => ({ ...prev, [key]: msg }));
  };

  const activeAutoError =
    category === "platforms"
      ? platformsAuto.error
      : category === "foreign"
        ? foreignAuto.error
        : category === "rss"
          ? rssAuto.error
          : domainsAuto.error;

  const activeError = loadError || categoryErrors[category] || activeAutoError;

  const platformSources = (platformsCfg.sources as PlatformSource[]) || [];
  const platformEnabledCount = platformSources.filter((s) => s.enabled !== false).length;
  const rssFeeds = (rssCfg.feeds as RssFeedCfg[]) || [];
  const rssEnabledCount = rssFeeds.filter((f) => f.enabled !== false).length;
  const domains = (domainsCfg.items as DomainItemCfg[]) || [];
  const foreignEnabledCount = [
    Boolean(foreignCfg.reddit_enabled),
    Boolean(foreignCfg.youtube_enabled ?? true),
    Boolean(foreignCfg.hackernews_enabled ?? true),
    Boolean(foreignCfg.huggingface_enabled ?? true),
    Boolean(foreignCfg.github_enabled ?? true),
  ].filter(Boolean).length;

  const hasAnyProxy =
    Boolean(platformsCfg.use_proxy && String(platformsCfg.proxy_url || "").trim()) ||
    Boolean(rssCfg.use_proxy && String(rssCfg.proxy_url || "").trim()) ||
    Boolean(String(foreignCfg.proxy_url || "").trim());

  const applyUnifiedProxy = (enable: boolean) => {
    const cleanUrl = enable ? unifiedProxy.trim() : "";
    if (enable && !cleanUrl) {
      setLoadError("请先填写代理地址，例如 http://127.0.0.1:7897");
      return;
    }
    setLoadError("");
    const nextPlatforms = { ...platformsCfg, use_proxy: enable, proxy_url: cleanUrl };
    const nextRss = { ...rssCfg, use_proxy: enable, proxy_url: cleanUrl };
    const nextForeign = { ...foreignCfg, proxy_url: cleanUrl };
    setPlatformsCfg(nextPlatforms);
    setRssCfg(nextRss);
    setForeignCfg(nextForeign);
    platformsAuto.queueSave(nextPlatforms, { immediate: true });
    rssAuto.queueSave(nextRss, { immediate: true });
    foreignAuto.queueSave(nextForeign, { immediate: true });
    setProxyNotice(
      enable
        ? `已将代理 ${cleanUrl} 同步应用到国内热榜、媒体订阅和海外资讯源`
        : "已清空全部网络代理并恢复直连",
    );
  };

  const categories: { key: SourceCategory; label: string; countText: string }[] = [
    {
      key: "platforms",
      label: "国内热榜",
      countText: `${platformEnabledCount}/${platformSources.length}`,
    },
    {
      key: "foreign",
      label: "海外资讯",
      countText: `${foreignEnabledCount}/5`,
    },
    {
      key: "rss",
      label: "媒体订阅",
      countText: `${rssEnabledCount}/${rssFeeds.length}`,
    },
    {
      key: "domains",
      label: "领域分类",
      countText: `${domains.length}`,
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {activeError && <Alert variant="destructive">{activeError}</Alert>}
      {proxyNotice && <Alert variant="success">{proxyNotice}</Alert>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="数据源分类" className="flex flex-wrap gap-2">
          {categories.map((item) => {
            const active = category === item.key;
            return (
              <Button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={active}
                size="sm"
                variant={active ? "default" : "outline"}
                className="shrink-0"
                onClick={() => setCategory(item.key)}
              >
                <span>{item.label}</span>
                <span
                  className={
                    active
                      ? "rounded bg-primary-foreground/20 px-1.5 py-0.5 text-xs"
                      : "rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
                  }
                >
                  {item.countText}
                </span>
                {dirty[item.key] && <Badge variant="warning">保存中</Badge>}
              </Button>
            );
          })}
        </div>

        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setProxyOpen((v) => !v)}
          className="shrink-0"
        >
          <Globe data-icon="inline-start" />
          <span>{proxyOpen ? "收起统一代理" : hasAnyProxy ? "统一代理（已开启）" : "统一网络代理"}</span>
        </Button>
      </div>

      {proxyOpen && (
        <Card className="border-border bg-muted/20 p-4">
          <div className="flex flex-col gap-3">
            <Field>
              <FieldLabel htmlFor="unified-proxy-url">数据更新网络代理（可一键同步给三类来源）</FieldLabel>
              <FieldDescription>
                如果您在本地电脑运行并需要访问海外资讯，可填本地代理地址；部署在香港或海外云主机上通常保持直连即可。
              </FieldDescription>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  id="unified-proxy-url"
                  value={unifiedProxy}
                  onChange={(e) => setUnifiedProxy(e.target.value)}
                  placeholder="例如：http://127.0.0.1:7897"
                  className="flex-1"
                />
                <Button type="button" size="sm" onClick={() => applyUnifiedProxy(true)} className="h-10 shrink-0">
                  同步到三类数据源
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => applyUnifiedProxy(false)}
                  className="h-10 shrink-0"
                >
                  全部恢复直连
                </Button>
              </div>
            </Field>
            <div className="flex items-start gap-2 text-sm text-muted-foreground">
              <ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber-600" />
              <span>注：Antigravity CLI 的网络代理独立由服务器环境变量 TRENDRADAR_AGY_PROXY 控制，不受此处影响。</span>
            </div>
          </div>
        </Card>
      )}

      <div className={category === "platforms" ? "" : "hidden"}>
        <PlatformsManagerCard
          config={platformsCfg}
          saveStatus={platformsAuto.status}
          onChange={(next, immediate = false) => {
            setPlatformsCfg(next);
            platformsAuto.queueSave(next, { immediate });
          }}
          onSave={() => void platformsAuto.flushNow()}
          onError={(msg) => setCatError("platforms", msg)}
        />
      </div>

      <div className={category === "foreign" ? "" : "hidden"}>
        <ForeignSourcesManagerCard
          config={foreignCfg}
          saveStatus={foreignAuto.status}
          onChange={(next, immediate = false) => {
            setForeignCfg(next);
            foreignAuto.queueSave(next, { immediate });
          }}
          onKeepaliveFlush={(next) => settingsApi.keepaliveUpdateSection("foreign_sources", next)}
          onSave={() => void foreignAuto.flushNow()}
        />
      </div>

      <div className={category === "rss" ? "" : "hidden"}>
        <RssFeedsManagerCard
          config={rssCfg}
          domains={domains}
          saveStatus={rssAuto.status}
          onChange={(next, immediate = false) => {
            setRssCfg(next);
            rssAuto.queueSave(next, { immediate });
          }}
          onSave={() => void rssAuto.flushNow()}
          onError={(msg) => setCatError("rss", msg)}
        />
      </div>

      <div className={category === "domains" ? "" : "hidden"}>
        <DomainsManagerCard
          domains={domains}
          saveStatus={domainsAuto.status}
          onChange={(nextItems, immediate = false) => {
            const next = { ...domainsCfg, items: nextItems };
            setDomainsCfg(next);
            domainsAuto.queueSave(next, { immediate });
          }}
          onSave={() => void domainsAuto.flushNow()}
          onError={(msg) => setCatError("domains", msg)}
        />
      </div>
    </div>
  );
}
