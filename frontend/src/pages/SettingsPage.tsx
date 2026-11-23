import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AIProvidersTab } from "@/components/settings/AIProvidersTab";
import { KeywordsWebhooksTab } from "@/components/settings/KeywordsWebhooksTab";
import { PromptsTab } from "@/components/settings/PromptsTab";
import { SourcesTab } from "@/components/settings/SourcesTab";
import { SystemScheduleTab } from "@/components/settings/SystemScheduleTab";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const VALID_TABS = new Set(["sources", "keywords", "ai", "prompts", "system"]);

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab") || "sources";
  const activeTab = VALID_TABS.has(rawTab) ? rawTab : "sources";

  const [tab, setTab] = useState(activeTab);
  const [sourcesDirty, setSourcesDirty] = useState(false);
  const [keywordsDirty, setKeywordsDirty] = useState(false);
  const [systemDirty, setSystemDirty] = useState(false);

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
        <h1 className="text-xl font-bold tracking-tight">系统配置中心</h1>
        <p className="text-sm text-muted-foreground">
          常用配置都会自动保存，无需额外操作，改动后会实时生效。
        </p>
      </div>

      <Tabs value={tab} onValueChange={handleTabChange}>
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1.5 sm:w-auto">
          <TabsTrigger value="sources" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            <span>数据源与领域</span>
            {sourcesDirty && (
              <span
                title="有未保存的数据源修改"
                aria-label="未保存"
                className="size-2 rounded-full bg-amber-500"
              />
            )}
          </TabsTrigger>
          <TabsTrigger value="keywords" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            <span>关键词与推送</span>
            {keywordsDirty && (
              <span
                title="有未保存的关键词或推送修改"
                aria-label="未保存"
                className="size-2 rounded-full bg-amber-500"
              />
            )}
          </TabsTrigger>
          <TabsTrigger value="ai" className="min-h-9 px-3 py-1.5 text-sm shrink-0">AI 模型配置</TabsTrigger>
          <TabsTrigger value="prompts" className="min-h-9 px-3 py-1.5 text-sm shrink-0">开场提示词</TabsTrigger>
          <TabsTrigger value="system" className="min-h-9 px-3 py-1.5 text-sm shrink-0">
            <span>定时与账户</span>
            {systemDirty && (
              <span
                title="有未保存的定时修改"
                aria-label="未保存"
                className="size-2 rounded-full bg-amber-500"
              />
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="sources" forceMount className="data-[state=inactive]:hidden">
          <SourcesTab onDirtyChange={setSourcesDirty} />
        </TabsContent>
        <TabsContent value="keywords" forceMount className="data-[state=inactive]:hidden">
          <KeywordsWebhooksTab onDirtyChange={setKeywordsDirty} />
        </TabsContent>
        <TabsContent value="ai" forceMount className="data-[state=inactive]:hidden">
          <AIProvidersTab isActive={tab === "ai"} />
        </TabsContent>
        <TabsContent value="prompts" forceMount className="data-[state=inactive]:hidden">
          <PromptsTab />
        </TabsContent>
        <TabsContent value="system" forceMount className="data-[state=inactive]:hidden">
          <SystemScheduleTab onDirtyChange={setSystemDirty} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
