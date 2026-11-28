import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AdminScheduleTab } from "@/components/admin/AdminScheduleTab";
import { InviteCodesPanel } from "@/components/admin/InviteCodesPanel";
import { UsersPanel } from "@/components/admin/UsersPanel";
import { AIProvidersTab } from "@/components/settings/AIProvidersTab";
import { SourcesTab } from "@/components/settings/SourcesTab";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const VALID_TABS = new Set(["sources", "ai", "schedule", "invites", "users"]);

/** Dedicated admin dashboard governing system sources, AI models, schedule, invites, and members. */
export function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab") || "sources";
  const activeTab = VALID_TABS.has(rawTab) ? rawTab : "sources";
  const [tab, setTab] = useState(activeTab);

  useEffect(() => {
    const paramTab = searchParams.get("tab");
    if (paramTab && VALID_TABS.has(paramTab)) {
      setTab(paramTab);
    }
  }, [searchParams]);

  const handleTabChange = (nextTab: string) => {
    setTab(nextTab);
    setSearchParams({ tab: nextTab }, { replace: true });
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-bold tracking-tight">管理后台</h1>
        <p className="text-sm text-muted-foreground">
          统一管理数据源与领域分类、AI 模型配置、全站定时调度、注册邀请码与成员账号。
        </p>
      </div>

      <Tabs value={tab} onValueChange={handleTabChange}>
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1.5 sm:w-auto">
          <TabsTrigger value="sources" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            数据源与领域
          </TabsTrigger>
          <TabsTrigger value="ai" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            AI 模型配置
          </TabsTrigger>
          <TabsTrigger value="schedule" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            定时与趋势
          </TabsTrigger>
          <TabsTrigger value="invites" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            邀请码管理
          </TabsTrigger>
          <TabsTrigger value="users" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            成员账号管理
          </TabsTrigger>
        </TabsList>

        <TabsContent value="sources" forceMount className="data-[state=inactive]:hidden">
          <SourcesTab />
        </TabsContent>
        <TabsContent value="ai" forceMount className="data-[state=inactive]:hidden">
          <AIProvidersTab />
        </TabsContent>
        <TabsContent value="schedule" forceMount className="data-[state=inactive]:hidden">
          <AdminScheduleTab />
        </TabsContent>
        <TabsContent value="invites" forceMount className="data-[state=inactive]:hidden">
          <InviteCodesPanel />
        </TabsContent>
        <TabsContent value="users" forceMount className="data-[state=inactive]:hidden">
          <UsersPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
