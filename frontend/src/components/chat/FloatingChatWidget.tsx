import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import {
  FilePlus2,
  Loader2,
  Maximize2,
  MessageSquare,
  Minimize2,
  MousePointerClick,
  Plus,
  Send,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { streamChatSSE } from "@/api/client";
import { aiConfigApi, chatApi } from "@/api/endpoints";
import type {
  AIProviderSlotDTO,
  ChatMessageDTO,
  ChatSessionDTO,
  PromptTemplateDTO,
} from "@/api/types";
import { SaveReportDialog } from "@/components/chat/SaveReportDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/feedback";
import { Textarea } from "@/components/ui/input";
import { MarkdownView } from "@/components/ui/markdown-view";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSelection } from "@/context/SelectionContext";
import { cn } from "@/lib/utils";

export function FloatingChatWidget() {
  const {
    chatOpen,
    setChatOpen,
    isPicking,
    togglePicking,
    selectedItems,
    removeItem,
    clearItems,
  } = useSelection();
  const location = useLocation();
  const isSettingsPage = location.pathname.startsWith("/settings");

  const [wideMode, setWideMode] = useState(false);
  const [sessions, setSessions] = useState<ChatSessionDTO[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessageDTO[]>([]);
  const [providers, setProviders] = useState<AIProviderSlotDTO[]>([]);
  const [prompts, setPrompts] = useState<PromptTemplateDTO[]>([]);
  const [slotId, setSlotId] = useState<string>("");
  const [promptId, setPromptId] = useState<string>("");
  const [input, setInput] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [sending, setSending] = useState(false);
  const [waitSeconds, setWaitSeconds] = useState(0);
  const [error, setError] = useState("");
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const scrollEndRef = useRef<HTMLDivElement | null>(null);

  const defaultProviderId = (() => {
    const def =
      providers.find((p) => p.role_bindings.includes("chat_default")) ?? providers[0];
    return def ? String(def.id) : "";
  })();

  const defaultPromptId = (() => {
    const def = prompts.find((t) => t.is_default) ?? prompts[0];
    return def ? String(def.id) : "";
  })();

  const loadMetadata = async () => {
    try {
      const [sessList, provList, tplList] = await Promise.all([
        chatApi.listSessions(),
        aiConfigApi.listProviders(),
        aiConfigApi.listPrompts(),
      ]);
      setSessions(sessList);
      const enabledProviders = provList.filter((p) => p.is_enabled);
      const enabledPrompts = tplList.filter((t) => t.is_enabled);
      setProviders(enabledProviders);
      setPrompts(enabledPrompts);

      const defaultSlot =
        enabledProviders.find((p) => p.role_bindings.includes("chat_default")) ?? enabledProviders[0];
      if (defaultSlot && !slotId) setSlotId(String(defaultSlot.id));

      const defaultTpl = enabledPrompts.find((t) => t.is_default) ?? enabledPrompts[0];
      if (defaultTpl && !promptId) setPromptId(String(defaultTpl.id));

      if (sessList.length > 0 && activeSessionId === null) {
        setActiveSessionId(sessList[0].id);
      }
    } catch {
      // Ignore transient init errors until drawer opens
    }
  };

  useEffect(() => {
    if (chatOpen) {
      void loadMetadata();
    }
  }, [chatOpen]);

  useEffect(() => {
    if (!chatOpen || activeSessionId === null) return;
    let cancelled = false;
    chatApi
      .getMessages(activeSessionId)
      .then((res) => {
        if (cancelled) return;
        setMessages(res.messages);
        if (res.session.provider_slot_id) {
          setSlotId(String(res.session.provider_slot_id));
        } else if (defaultProviderId) {
          setSlotId(defaultProviderId);
        }
        if (res.session.prompt_template_id) {
          setPromptId(String(res.session.prompt_template_id));
        } else if (defaultPromptId) {
          setPromptId(defaultPromptId);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载对话历史失败");
      });
    return () => {
      cancelled = true;
    };
  }, [chatOpen, activeSessionId, defaultProviderId, defaultPromptId]);

  useEffect(() => {
    if (!sending || streamingText) {
      setWaitSeconds(0);
      return;
    }
    const timer = window.setInterval(() => {
      setWaitSeconds((s) => s + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [sending, streamingText]);

  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText, waitSeconds]);

  const handleNewSession = async () => {
    setError("");
    try {
      const created = await chatApi.createSession({
        title: "新对话",
        provider_slot_id: slotId ? Number(slotId) : null,
        prompt_template_id: promptId ? Number(promptId) : null,
      });
      setSessions((prev) => [created, ...prev]);
      setActiveSessionId(created.id);
      setMessages([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建会话失败");
    }
  };

  const handleDeleteSession = async () => {
    if (activeSessionId === null) return;
    if (!window.confirm("确定删除当前对话记录吗？")) return;
    try {
      await chatApi.deleteSession(activeSessionId);
      const remaining = sessions.filter((s) => s.id !== activeSessionId);
      setSessions(remaining);
      setActiveSessionId(remaining.length > 0 ? remaining[0].id : null);
      setMessages([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除会话失败");
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setError("");
    setSending(true);
    setStreamingText("");

    let targetId = activeSessionId;
    try {
      if (targetId === null) {
        const created = await chatApi.createSession({
          title: text.slice(0, 32),
          provider_slot_id: slotId ? Number(slotId) : null,
          prompt_template_id: promptId ? Number(promptId) : null,
        });
        setSessions((prev) => [created, ...prev]);
        setActiveSessionId(created.id);
        targetId = created.id;
      }

      const attached = [...selectedItems];
      const optimisticMsg: ChatMessageDTO = {
        id: Date.now(),
        session_id: targetId,
        role: "user",
        content: text,
        context_items: attached,
        usage: {},
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimisticMsg]);
      setInput("");

      const controller = new AbortController();
      abortRef.current = controller;

      let assembled = "";
      await streamChatSSE(
        targetId,
        {
          content: text,
          context_items: attached,
          provider_slot_id: slotId ? Number(slotId) : undefined,
          prompt_template_id: promptId ? Number(promptId) : undefined,
        },
        {
          onDelta: (delta) => {
            assembled += delta;
            setStreamingText(assembled);
          },
          onDone: async () => {
            setStreamingText("");
            if (targetId !== null) {
              const refreshed = await chatApi.getMessages(targetId);
              setMessages(refreshed.messages);
              setSessions((prev) =>
                prev.map((s) => (s.id === refreshed.session.id ? refreshed.session : s)),
              );
            }
          },
          onError: (msg) => {
            setError(msg);
          },
        },
        controller.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(err instanceof Error ? err.message : "发送失败");
      }
    } finally {
      abortRef.current = null;
      setSending(false);
    }
  };

  const activeSession = sessions.find((s) => s.id === activeSessionId);

  if (!chatOpen) {
    if (isSettingsPage) return null;
    return (
      <div className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom))] right-3.5 z-40 flex items-center gap-2 md:bottom-5 md:right-5">
        {isPicking && (
          <Button
            size="lg"
            variant="outline"
            onClick={togglePicking}
            className="h-11 rounded-full border-destructive/50 bg-card px-3.5 sm:px-4 text-sm font-medium text-destructive shadow-lg hover:bg-destructive/10"
          >
            <X data-icon="inline-start" />
            <span>退出选择模式</span>
          </Button>
        )}
        <Button
          size="lg"
          onClick={() => setChatOpen(true)}
          className="h-11 rounded-full px-4 shadow-lg"
        >
          <MessageSquare data-icon="inline-start" />
          <span className="hidden sm:inline">AI 研判助手</span>
          <span className="sm:hidden">AI 助手</span>
          {selectedItems.length > 0 && (
            <Badge className="ml-1 bg-card text-primary">{selectedItems.length}</Badge>
          )}
        </Button>
      </div>
    );
  }

  return (
    <>
      <div
        className={cn(
          "fixed inset-0 z-50 flex h-[100dvh] w-full flex-col overflow-hidden bg-card transition-all pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] md:z-40 md:inset-auto md:bottom-4 md:right-4 md:rounded-xl md:border md:border-border md:shadow-2xl md:pt-0 md:pb-0",
          wideMode
            ? "md:h-[82dvh] md:w-[min(740px,calc(100vw-2rem))]"
            : "md:h-[min(640px,82dvh)] md:w-[min(450px,calc(100vw-2rem))]",
        )}
      >
        <div className="flex items-center justify-between gap-2 border-b border-border bg-muted/40 px-3 py-2.5 sm:px-3.5">
          <div className="flex min-w-0 flex-1 items-center gap-1.5 sm:gap-2">
            <Select
              value={activeSessionId !== null ? String(activeSessionId) : ""}
              onValueChange={(val) => setActiveSessionId(Number(val))}
            >
              <SelectTrigger className="h-9 min-w-0 flex-1 text-sm md:max-w-[200px]">
                <SelectValue placeholder="新建或选择会话" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {sessions.map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>
                      {s.title}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button
              size="icon"
              variant="outline"
              className="size-9 shrink-0"
              onClick={handleNewSession}
              aria-label="新建对话"
              title="新建对话"
            >
              <Plus className="size-4" />
            </Button>
            {activeSessionId !== null && (
              <Button
                size="icon"
                variant="ghost"
                className="size-9 shrink-0 text-muted-foreground hover:text-destructive"
                onClick={handleDeleteSession}
                aria-label="删除当前对话"
                title="删除当前对话"
              >
                <Trash2 className="size-4" />
              </Button>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-1">
            <Button
              size="sm"
              variant="outline"
              disabled={activeSessionId === null || messages.length === 0}
              onClick={() => setSaveDialogOpen(true)}
              className="h-9 px-2.5 sm:px-3"
            >
              <FilePlus2 data-icon="inline-start" />
              <span>存报告</span>
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="hidden size-9 md:inline-flex"
              onClick={() => setWideMode((prev) => !prev)}
              aria-label={wideMode ? "收窄窗口" : "加宽窗口"}
              title={wideMode ? "紧凑模式" : "宽屏模式"}
            >
              {wideMode ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-9 px-2.5 text-sm"
              onClick={() => setChatOpen(false)}
              aria-label="关闭对话窗口"
            >
              <X data-icon="inline-start" />
              <span>关闭</span>
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 border-b border-border bg-background/60 px-3 py-2">
          <Select value={slotId} onValueChange={setSlotId}>
            <SelectTrigger className="h-9 text-sm">
              <SelectValue placeholder="选择 AI 模型" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {providers.map((p) => (
                  <SelectItem key={p.id} value={String(p.id)}>
                    {p.name} ({p.model})
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>

          <Select value={promptId} onValueChange={setPromptId}>
            <SelectTrigger className="h-9 text-sm">
              <SelectValue placeholder="开场提示词模板" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {prompts.map((tpl) => (
                  <SelectItem key={tpl.id} value={String(tpl.id)}>
                    {tpl.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-2 border-b border-border bg-card px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <Button
              size="sm"
              variant={isPicking && !isSettingsPage ? "secondary" : "outline"}
              onClick={() => {
                if (isSettingsPage) {
                  setError("当前位于配置中心，请先切换到「热点」或「领域」页面再选择新闻卡片。");
                  return;
                }
                setError("");
                if (isPicking) {
                  togglePicking();
                } else {
                  togglePicking();
                  setChatOpen(false);
                }
              }}
              className={cn(isPicking && !isSettingsPage && "text-destructive border-destructive/40")}
            >
              {isPicking && !isSettingsPage ? (
                <X data-icon="inline-start" />
              ) : (
                <MousePointerClick data-icon="inline-start" />
              )}
              <span>{isPicking && !isSettingsPage ? "退出选择模式" : "选择页面新闻"}</span>
            </Button>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>已附带 {selectedItems.length} 项</span>
              {selectedItems.length > 0 && (
                <button
                  type="button"
                  onClick={clearItems}
                  className="text-primary hover:underline cursor-pointer"
                >
                  清空
                </button>
              )}
            </div>
          </div>

          {selectedItems.length > 0 && (
            <div className="flex max-h-20 flex-wrap gap-1.5 overflow-y-auto">
              {selectedItems.map((item) => (
                <Badge key={`${item.kind}-${item.id}`} variant="default" className="max-w-[210px] pr-1">
                  <span className="truncate">{item.title}</span>
                  <button
                    type="button"
                    onClick={() => removeItem(item.kind, item.id)}
                    className="ml-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full hover:bg-primary/20 cursor-pointer"
                    aria-label="移除上下文"
                  >
                    <X className="size-3" />
                  </button>
                </Badge>
              ))}
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-3.5 py-3">
          {error && (
            <Alert variant="destructive" className="mb-3">
              {error}
            </Alert>
          )}
          {messages.length === 0 && !streamingText && !sending && (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
              <p className="text-base font-medium text-foreground">开启热点研判对话</p>
              <p className="max-w-xs text-sm leading-relaxed">
                点击上方「选择页面新闻」在热点或领域页勾选文章，或直接输入问题，分析结果可一键存为报告。
              </p>
            </div>
          )}

          <div className="flex flex-col gap-3">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  "flex flex-col gap-1.5 rounded-lg px-3 py-2.5 text-sm",
                  msg.role === "user"
                    ? "ml-3 sm:ml-6 bg-accent text-foreground"
                    : "mr-1 sm:mr-4 border border-border bg-background/60",
                )}
              >
                <div className="text-xs font-medium text-muted-foreground">
                  {msg.role === "user" ? "你" : "AI 助手"}
                </div>
                {msg.context_items.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {msg.context_items.map((ctx) => (
                      <Badge key={`${ctx.kind}-${ctx.id}`} variant="outline" className="max-w-full text-xs">
                        [{ctx.platform_or_domain}] {ctx.title}
                      </Badge>
                    ))}
                  </div>
                )}
                {msg.role === "user" ? (
                  <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                ) : (
                  <MarkdownView content={msg.content} />
                )}
              </div>
            ))}

            {sending && !streamingText && (
              <div className="mr-1 sm:mr-4 flex flex-col gap-1.5 rounded-lg border border-primary/30 bg-background/80 px-3 py-2.5 text-sm">
                <div className="flex items-center gap-2 text-xs font-medium text-primary">
                  <Loader2 className="size-3.5 animate-spin" />
                  <span>AI 正在连接并思考中...（已等待 {waitSeconds}s）</span>
                </div>
                {waitSeconds >= 8 && (
                  <span className="text-xs text-muted-foreground">
                    若等待时间较长，可在配置中心的「AI 模型配置」测试接口联通状态。
                  </span>
                )}
              </div>
            )}

            {streamingText && (
              <div className="mr-1 sm:mr-4 flex flex-col gap-1.5 rounded-lg border border-primary/30 bg-background/80 px-3 py-2.5 text-sm">
                <div className="text-xs font-medium text-primary">AI 正在生成...</div>
                <MarkdownView content={streamingText} />
              </div>
            )}
            <div ref={scrollEndRef} />
          </div>
        </div>

        <div className="border-t border-border bg-muted/20 p-3">
          <div className="flex items-end gap-2">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void handleSend();
                }
              }}
              placeholder="输入分析问题（Enter 发送，Shift+Enter 换行）"
              className="min-h-11 max-h-32 resize-none"
            />
            {sending ? (
              <Button
                variant="destructive"
                size="icon"
                className="size-10 shrink-0"
                onClick={() => abortRef.current?.abort()}
                aria-label="停止生成"
                title="停止生成"
              >
                <Square className="size-4" />
              </Button>
            ) : (
              <Button
                size="icon"
                className="size-10 shrink-0"
                onClick={() => void handleSend()}
                disabled={!input.trim()}
                aria-label="发送"
                title="发送"
              >
                <Send className="size-4" />
              </Button>
            )}
          </div>
        </div>
      </div>

      <SaveReportDialog
        open={saveDialogOpen}
        onOpenChange={setSaveDialogOpen}
        sessionId={activeSessionId}
        defaultTitle={activeSession?.title || ""}
        providerSlotId={slotId ? Number(slotId) : undefined}
      />
    </>
  );
}
