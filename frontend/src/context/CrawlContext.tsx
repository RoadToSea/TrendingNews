import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import { streamCrawlSSE } from "@/api/client";
import type { CrawlSourceDoneEvent } from "@/api/types";

interface CrawlContextValue {
  crawling: boolean;
  completedSources: number;
  totalSources: number;
  recentSources: CrawlSourceDoneEvent[];
  notice: string;
  crawlErrors: string[];
  error: string;
  hotlistVersion: number;
  rssVersion: number;
  clusterVersion: number;
  startCrawl: (runCluster?: boolean) => Promise<void>;
  clearNotice: () => void;
}

const CrawlContext = createContext<CrawlContextValue | null>(null);

export function CrawlProvider({ children }: { children: React.ReactNode }) {
  const [crawling, setCrawling] = useState(false);
  const [completedSources, setCompletedSources] = useState(0);
  const [totalSources, setTotalSources] = useState(0);
  const [recentSources, setRecentSources] = useState<CrawlSourceDoneEvent[]>([]);
  const [notice, setNotice] = useState("");
  const [crawlErrors, setCrawlErrors] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [hotlistVersion, setHotlistVersion] = useState(0);
  const [rssVersion, setRssVersion] = useState(0);
  const [clusterVersion, setClusterVersion] = useState(0);
  const activeRef = useRef(false);

  const clearNotice = useCallback(() => {
    setNotice("");
    setCrawlErrors([]);
    setError("");
  }, []);

  const startCrawl = useCallback(async (runCluster = true) => {
    if (activeRef.current) return;
    activeRef.current = true;
    setCrawling(true);
    setError("");
    setNotice("");
    setCrawlErrors([]);
    setCompletedSources(0);
    setTotalSources(0);
    setRecentSources([]);

    try {
      await streamCrawlSSE(runCluster, {
        onStart: (ev) => {
          setCompletedSources(ev.completed_sources);
          setTotalSources(ev.total_sources);
        },
        onSourceDone: (ev) => {
          setCompletedSources(ev.completed_sources);
          setTotalSources(ev.total_sources);
          setRecentSources((prev) => [ev, ...prev].slice(0, 6));
          if (ev.count > 0) {
            if (ev.source_kind === "rss") {
              setRssVersion((v) => v + 1);
            } else {
              setHotlistVersion((v) => v + 1);
            }
          }
        },
        onClusterDone: () => {
          setClusterVersion((v) => v + 1);
        },
        onDone: (res) => {
          setHotlistVersion((v) => v + 1);
          setRssVersion((v) => v + 1);
          setClusterVersion((v) => v + 1);
          const errs = Array.isArray(res.errors) ? res.errors.filter(Boolean) : [];
          setCrawlErrors(errs);
          const secLabel = res.duration_ms ? `（耗时 ${(res.duration_ms / 1000).toFixed(1)}s）` : "";
          const warnLabel = errs.length > 0 ? `（含 ${errs.length} 项警告/失败）` : "";
          setNotice(
            `数据已更新${secLabel}：国内热榜 ${res.hotlist_count}、海外资讯 ${res.foreign_api_count}、媒体订阅 ${res.rss_count}、归类事件 ${res.clustered_count}${warnLabel}`,
          );
        },
        onError: (msg) => {
          setError(msg);
        },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新数据失败");
    } finally {
      activeRef.current = false;
      setCrawling(false);
    }
  }, []);

  return (
    <CrawlContext.Provider
      value={{
        crawling,
        completedSources,
        totalSources,
        recentSources,
        notice,
        crawlErrors,
        error,
        hotlistVersion,
        rssVersion,
        clusterVersion,
        startCrawl,
        clearNotice,
      }}
    >
      {children}
    </CrawlContext.Provider>
  );
}

export function useCrawl() {
  const ctx = useContext(CrawlContext);
  if (!ctx) throw new Error("useCrawl must be used inside CrawlProvider");
  return ctx;
}
