import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { InviteCodesPanel } from "@/components/admin/InviteCodesPanel";
import { UsersPanel } from "@/components/admin/UsersPanel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const VALID_TABS = new Set(["invites", "users"]);

/** Dedicated admin dashboard for issuing invite codes and governing member accounts. */
export function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab") || "invites";
  const activeTab = VALID_TABS.has(rawTab) ? rawTab : "invites";
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
          签发并控制注册邀请码的有效次数与过期时间，同时管理已注册成员账号状态。
        </p>
      </div>

      <Tabs value={tab} onValueChange={handleTabChange}>
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1.5 sm:w-auto">
          <TabsTrigger value="invites" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            邀请码管理
          </TabsTrigger>
          <TabsTrigger value="users" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            成员账号管理
          </TabsTrigger>
        </TabsList>

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
