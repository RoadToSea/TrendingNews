import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AccountTab } from "@/components/settings/AccountTab";
import { ChatSessionsTab } from "@/components/settings/ChatSessionsTab";
import { KeywordsTab } from "@/components/settings/KeywordsTab";
import { PromptsTab } from "@/components/settings/PromptsTab";
import { WebhooksTab } from "@/components/settings/WebhooksTab";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const VALID_TABS = new Set(["keywords", "webhooks", "sessions", "prompts", "account"]);

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab") || "keywords";
  const activeTab = VALID_TABS.has(rawTab) ? rawTab : "keywords";

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
        <h1 className="text-xl font-bold tracking-tight">个人配置中心</h1>
        <p className="text-sm text-muted-foreground">
          管理您的关注话题、个人增量消息推送、历史会话、开场提示词与登录密码。
        </p>
      </div>

      <Tabs value={tab} onValueChange={handleTabChange}>
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1.5 sm:w-auto">
          <TabsTrigger value="keywords" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            关注话题
          </TabsTrigger>
          <TabsTrigger value="webhooks" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            消息推送
          </TabsTrigger>
          <TabsTrigger value="sessions" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            会话管理
          </TabsTrigger>
          <TabsTrigger value="prompts" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            开场提示词
          </TabsTrigger>
          <TabsTrigger value="account" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            账户设置
          </TabsTrigger>
        </TabsList>

        <TabsContent value="keywords" forceMount className="data-[state=inactive]:hidden">
          <KeywordsTab />
        </TabsContent>
        <TabsContent value="webhooks" forceMount className="data-[state=inactive]:hidden">
          <WebhooksTab />
        </TabsContent>
        <TabsContent value="sessions" forceMount className="data-[state=inactive]:hidden">
          <ChatSessionsTab />
        </TabsContent>
        <TabsContent value="prompts" forceMount className="data-[state=inactive]:hidden">
          <PromptsTab />
        </TabsContent>
        <TabsContent value="account" forceMount className="data-[state=inactive]:hidden">
          <AccountTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
