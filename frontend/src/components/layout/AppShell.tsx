import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  ChevronDown,
  ChevronUp,
  FileText,
  Flame,
  Layers,
  LogOut,
  RefreshCw,
  Settings,
  ShieldCheck,
} from "lucide-react";
import { FloatingChatWidget } from "@/components/chat/FloatingChatWidget";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";
import { useCrawl } from "@/context/CrawlContext";
import { cn } from "@/lib/utils";

const BASE_NAV_ITEMS = [
  { to: "/platforms", label: "平台热点", shortLabel: "热点", icon: Flame },
  { to: "/domains", label: "领域聚合", shortLabel: "领域", icon: Layers },
  { to: "/trends", label: "趋势图谱", shortLabel: "趋势", icon: Activity },
  { to: "/reports", label: "报告与词频", shortLabel: "报告", icon: FileText },
  { to: "/settings", label: "配置中心", shortLabel: "配置", icon: Settings },
];

const ADMIN_NAV_ITEM = {
  to: "/admin",
  label: "管理后台",
  shortLabel: "管理",
  icon: ShieldCheck,
};

export function AppShell() {
  const { user, logout } = useAuth();
  const {
    crawling,
    completedSources,
    totalSources,
    recentSources,
    notice,
    crawlErrors,
    error,
    startCrawl,
    clearNotice,
  } = useCrawl();
  const navigate = useNavigate();
  const location = useLocation();
  const isConfigRoute =
    location.pathname.startsWith("/settings") || location.pathname.startsWith("/admin");
  const canCrawl = user?.role === "admin" && !isConfigRoute;

  const [detailsOpen, setDetailsOpen] = useState(false);

  const navItems = user?.role === "admin" ? [...BASE_NAV_ITEMS, ADMIN_NAV_ITEM] : BASE_NAV_ITEMS;

  useEffect(() => {
    if (crawlErrors.length === 0) setDetailsOpen(false);
  }, [crawlErrors.length]);

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const progressPct =
    totalSources > 0 ? Math.min(100, Math.round((completedSources / totalSources) * 100)) : 8;

  return (
    <div className="min-h-[100dvh] flex flex-col bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-2 px-3 py-2 sm:px-6 md:py-2.5">
          <div className="flex min-w-0 items-center gap-5">
            <NavLink to="/platforms" className="flex shrink-0 items-center gap-2 font-bold tracking-tight text-foreground">
              <span className="inline-flex size-7 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
                TR
              </span>
              <span className="text-sm sm:text-base">TrendRadar</span>
            </NavLink>

            <nav className="hidden md:flex flex-wrap items-center gap-1">
              {navItems.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) =>
                    cn(
                      "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )
                  }
                >
                  <Icon className="size-4" />
                  <span>{label}</span>
                </NavLink>
              ))}
            </nav>
          </div>

          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            {canCrawl && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => void startCrawl(true)}
                disabled={crawling}
                className="px-2.5 sm:px-3"
              >
                <RefreshCw data-icon="inline-start" className={cn(crawling && "animate-spin")} />
                <span className="tabular-nums">
                  {crawling ? (
                    `${completedSources}/${totalSources || "..."}`
                  ) : (
                    <>
                      更新<span className="hidden sm:inline">数据</span>
                    </>
                  )}
                </span>
              </Button>
            )}

            <div className="flex items-center gap-1.5 pl-0.5 text-xs text-muted-foreground sm:pl-1.5">
              <span className="hidden sm:inline max-w-[110px] truncate text-sm font-medium text-foreground/85">
                {user?.username}
              </span>
              <Button
                size="sm"
                variant="ghost"
                className="h-9 px-2.5 text-sm text-foreground/80"
                onClick={handleLogout}
                title="退出登录"
                aria-label="退出登录"
              >
                <LogOut data-icon="inline-start" />
                <span>退出</span>
              </Button>
            </div>
          </div>
        </div>

        {crawling && (
          <div className="border-t border-border bg-muted/40 px-3 py-2 text-xs sm:px-6">
            <div className="mx-auto flex max-w-7xl flex-col gap-1.5">
              <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between">
                <span className="font-medium text-foreground tabular-nums">
                  正在更新热点（{completedSources} / {totalSources || "..."} 个来源）
                </span>
                <div className="flex flex-nowrap items-center gap-1.5 overflow-x-auto no-scrollbar sm:flex-wrap">
                  {recentSources.map((src) => (
                    <Badge
                      key={`${src.source_kind}-${src.source_id}-${src.completed_sources}`}
                      variant={src.error ? "warning" : "success"}
                      className="shrink-0 whitespace-nowrap text-xs tabular-nums"
                    >
                      {src.source_name} {src.error ? "失败" : `+${src.count}`}
                    </Badge>
                  ))}
                </div>
              </div>
              <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-primary transition-all duration-300"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            </div>
          </div>
        )}

        {(notice || error) && (
          <div
            className={cn(
              "border-t px-3 py-2 text-xs sm:text-sm sm:px-6",
              error ? "border-red-200 bg-red-50 text-red-800" : "border-border bg-muted/60 text-foreground",
            )}
          >
            <div className="mx-auto flex max-w-7xl flex-col gap-1.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="line-clamp-2">{error || notice}</span>
                <div className="flex shrink-0 items-center gap-3">
                  {!error && crawlErrors.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setDetailsOpen((v) => !v)}
                      className="inline-flex items-center gap-1 font-medium text-amber-700 hover:underline cursor-pointer"
                    >
                      <span>查看失败详情 ({crawlErrors.length})</span>
                      {detailsOpen ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
                    </button>
                  )}
                  <button type="button" onClick={clearNotice} className="shrink-0 underline cursor-pointer">
                    关闭
                  </button>
                </div>
              </div>
              {detailsOpen && crawlErrors.length > 0 && (
                <ul className="max-h-36 list-disc overflow-y-auto rounded border border-amber-200 bg-amber-50/90 py-1.5 pl-6 pr-3 text-xs text-amber-900">
                  {crawlErrors.map((msg, idx) => (
                    <li key={idx} className="leading-relaxed">{msg}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-3 py-4 pb-32 sm:px-6 md:py-6 md:pb-24">
        <Outlet />
      </main>

      <nav
        aria-label="移动端主导航"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 backdrop-blur md:hidden pb-[env(safe-area-inset-bottom)]"
      >
        <div className={cn("grid", user?.role === "admin" ? "grid-cols-6" : "grid-cols-5")}>
          {navItems.map(({ to, shortLabel, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex min-h-14 flex-col items-center justify-center gap-1 text-xs font-medium transition-colors",
                  isActive ? "text-primary" : "text-muted-foreground hover:text-foreground",
                )
              }
            >
              <Icon className="size-5" />
              <span>{shortLabel}</span>
            </NavLink>
          ))}
        </div>
      </nav>

      <FloatingChatWidget />
    </div>
  );
}
