import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Plus, RefreshCw, Trash2, Zap } from "lucide-react";
import { aiConfigApi } from "@/api/endpoints";
import type { AIProviderProtocol, AIProviderSlotDTO } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert } from "@/components/ui/feedback";
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
import { cn } from "@/lib/utils";

const DEFAULT_PROTOCOL_URLS: Record<AIProviderProtocol, string> = {
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com",
  antigravity: "",
};

const ANTIGRAVITY_FALLBACK_MODELS: string[] = [
  "gemini-3.8-flash-medium",
  "gemini-3.8-flash-high",
  "gemini-3.8-flash-low",
  "gemini-4-neon-medium",
  "gemini-4-neon-high",
  "gemini-4-neon-xhigh",
  "gemini-4-carbon-medium",
  "gemini-4-carbon-high",
  "claude-sonnet-4-6",
  "claude-opus-4-6-thinking",
  "gpt-oss-120b-medium",
];

function mergeUniqueModels(...lists: (string | string[] | undefined)[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of lists) {
    if (!item) continue;
    const arr = Array.isArray(item) ? item : [item];
    for (const raw of arr) {
      const m = raw.trim();
      if (m && !seen.has(m)) {
        seen.add(m);
        out.push(m);
      }
    }
  }
  return out;
}

function isSlotFullyActive(slot: AIProviderSlotDTO): boolean {
  return (
    slot.is_enabled &&
    slot.role_bindings.includes("chat_default") &&
    slot.role_bindings.includes("summary_report") &&
    slot.role_bindings.includes("event_cluster")
  );
}

function requiresExplicitApiKey(protocol: AIProviderProtocol, url: string): boolean {
  if (protocol === "antigravity") return false;
  const trimmed = url.trim().toLowerCase();
  if (!trimmed) return true;
  return trimmed.includes("api.openai.com") || trimmed.includes("api.anthropic.com");
}

interface AIProvidersTabProps {
  isActive?: boolean;
}

export function AIProvidersTab({ isActive = true }: AIProvidersTabProps = {}) {
  const [slots, setSlots] = useState<AIProviderSlotDTO[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [testingId, setTestingId] = useState<number | null>(null);
  const [switchingModelId, setSwitchingModelId] = useState<number | null>(null);

  const [agyModels, setAgyModels] = useState<string[]>(ANTIGRAVITY_FALLBACK_MODELS);
  const [loadingAgyModels, setLoadingAgyModels] = useState(false);
  const fetchedAgyOnceRef = useRef(false);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<AIProviderSlotDTO | null>(null);
  const [name, setName] = useState("");
  const [protocol, setProtocol] = useState<AIProviderProtocol>("openai");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [extraJson, setExtraJson] = useState("{}");
  const [enabled, setEnabled] = useState(true);

  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [probingDraft, setProbingDraft] = useState(false);
  const [draftStatus, setDraftStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const refreshAgyModels = useCallback(async (silent = false) => {
    setLoadingAgyModels(true);
    if (!silent) {
      setError("");
      setNotice("");
    }
    try {
      const res = await aiConfigApi.fetchModels({
        protocol: "antigravity",
        base_url: "",
        api_key: "",
        model: "",
        extra_params: {},
      });
      if (res.models.length > 0) {
        setAgyModels(mergeUniqueModels(res.models, ANTIGRAVITY_FALLBACK_MODELS));
        if (!silent) {
          setNotice(`已从 Antigravity CLI 同步 ${res.models.length} 个可用模型`);
        }
      } else if (!silent) {
        setNotice("Antigravity CLI 未返回模型列表，已保留内置常用模型选项");
      }
    } catch (err) {
      if (!silent) {
        setError(err instanceof Error ? err.message : "刷新 Antigravity 模型列表失败");
      }
    } finally {
      setLoadingAgyModels(false);
    }
  }, []);

  const loadSlots = useCallback(async () => {
    try {
      const data = await aiConfigApi.listProviders();
      setSlots(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 AI 配置失败");
    }
  }, []);

  useEffect(() => {
    void loadSlots();
  }, [loadSlots]);

  useEffect(() => {
    if (!isActive || fetchedAgyOnceRef.current) return;
    if (slots.some((s) => s.protocol === "antigravity")) {
      fetchedAgyOnceRef.current = true;
      void refreshAgyModels(true);
    }
  }, [isActive, slots, refreshAgyModels]);

  const openCreate = () => {
    setEditing(null);
    setName("");
    setProtocol("openai");
    setBaseUrl(DEFAULT_PROTOCOL_URLS.openai);
    setApiKey("");
    setModel("");
    setExtraJson("{}");
    setEnabled(true);
    setAvailableModels([]);
    setDraftStatus(null);
    setFormOpen(true);
  };

  const openEdit = (slot: AIProviderSlotDTO) => {
    setEditing(slot);
    setName(slot.name);
    setProtocol(slot.protocol);
    setBaseUrl(slot.base_url);
    setApiKey(slot.api_key_masked || "");
    setModel(slot.model);
    setExtraJson(JSON.stringify(slot.extra_params || {}, null, 2));
    setEnabled(slot.is_enabled);
    setAvailableModels([]);
    setDraftStatus(null);
    setFormOpen(true);
  };

  const parseExtra = (): Record<string, unknown> | null => {
    try {
      return extraJson.trim() ? (JSON.parse(extraJson) as Record<string, unknown>) : {};
    } catch {
      setDraftStatus({ ok: false, text: "额外参数必须是合法 JSON 对象" });
      return null;
    }
  };

  const handleTestDraft = async () => {
    const parsedExtra = parseExtra();
    if (!parsedExtra) return;
    if (requiresExplicitApiKey(protocol, baseUrl) && !apiKey.trim() && !editing?.has_api_key) {
      setDraftStatus({ ok: false, text: "请先填写访问令牌 (API Key)" });
      return;
    }
    setProbingDraft(true);
    setDraftStatus(null);
    try {
      const res = await aiConfigApi.testDraft({
        protocol,
        base_url: baseUrl.trim(),
        api_key: apiKey,
        model: model.trim(),
        extra_params: parsedExtra,
        slot_id: editing?.id,
      });
      setDraftStatus({
        ok: res.ok,
        text: res.ok
          ? `连通成功（${res.latency_ms}ms · ${res.message}）`
          : `连通失败：${res.message}`,
      });
    } catch (err) {
      setDraftStatus({
        ok: false,
        text: err instanceof Error ? err.message : "测试联通请求异常",
      });
    } finally {
      setProbingDraft(false);
    }
  };

  const handleFetchModels = async () => {
    const parsedExtra = parseExtra();
    if (!parsedExtra) return;
    if (requiresExplicitApiKey(protocol, baseUrl) && !apiKey.trim() && !editing?.has_api_key) {
      setDraftStatus({ ok: false, text: "请先填写访问令牌 (API Key)" });
      return;
    }
    setFetchingModels(true);
    setDraftStatus(null);
    try {
      const res = await aiConfigApi.fetchModels({
        protocol,
        base_url: baseUrl.trim(),
        api_key: apiKey,
        model: model.trim(),
        extra_params: parsedExtra,
        slot_id: editing?.id,
      });
      setAvailableModels(res.models);
      if (protocol === "antigravity" && res.models.length > 0) {
        setAgyModels(mergeUniqueModels(res.models, ANTIGRAVITY_FALLBACK_MODELS));
      }
      if (res.models.length > 0 && !model.trim()) {
        setModel(res.models[0]);
      }
      setDraftStatus({ ok: true, text: res.message });
    } catch (err) {
      setDraftStatus({
        ok: false,
        text: err instanceof Error ? err.message : "获取模型列表失败",
      });
    } finally {
      setFetchingModels(false);
    }
  };

  const handleSave = async (activateAfterSave: boolean) => {
    const parsedExtra = parseExtra();
    if (!parsedExtra) return;
    if (!name.trim() || !model.trim()) {
      setDraftStatus({ ok: false, text: "请先填写配置名称并选择或输入模型 ID" });
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");
    try {
      let saved: AIProviderSlotDTO;
      if (editing) {
        saved = await aiConfigApi.updateProvider(editing.id, {
          name: name.trim(),
          protocol,
          base_url: baseUrl.trim(),
          api_key: apiKey,
          model: model.trim(),
          extra_params: parsedExtra,
          is_enabled: activateAfterSave ? true : enabled,
        });
      } else {
        saved = await aiConfigApi.createProvider({
          name: name.trim(),
          protocol,
          base_url: baseUrl.trim(),
          api_key: apiKey,
          model: model.trim(),
          extra_params: parsedExtra,
          role_bindings: [],
          is_enabled: activateAfterSave ? true : enabled,
        });
      }

      if (activateAfterSave) {
        saved = await aiConfigApi.activateProvider(saved.id);
        setNotice(`已保存并切换当前 AI 为：${saved.name} (${saved.model})`);
      } else {
        setNotice(`配置「${saved.name}」已保存`);
      }

      setFormOpen(false);
      await loadSlots();
    } catch (err) {
      setDraftStatus({
        ok: false,
        text: err instanceof Error ? err.message : "保存 AI 配置失败",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleInlineModelChange = async (slot: AIProviderSlotDTO, nextModel: string) => {
    const cleanModel = nextModel.trim();
    if (!cleanModel || cleanModel === slot.model) return;
    setSwitchingModelId(slot.id);
    setError("");
    setNotice("");
    try {
      await aiConfigApi.updateProvider(slot.id, { model: cleanModel });
      setNotice(`已切换「${slot.name}」使用模型为：${cleanModel}`);
      await loadSlots();
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换模型失败");
    } finally {
      setSwitchingModelId(null);
    }
  };

  const handleActivate = async (slot: AIProviderSlotDTO) => {
    setError("");
    setNotice("");
    try {
      await aiConfigApi.activateProvider(slot.id);
      setNotice(`已启用「${slot.name} (${slot.model})」用于对话、报告与热点自动归类`);
      await loadSlots();
    } catch (err) {
      setError(err instanceof Error ? err.message : "激活失败");
    }
  };

  const handleTestSaved = async (slotId: number) => {
    setTestingId(slotId);
    setError("");
    setNotice("");
    try {
      const res = await aiConfigApi.testProvider(slotId);
      if (res.ok) {
        setNotice(`连通测试成功：${res.model} (${res.latency_ms}ms)`);
      } else {
        setError(`连通测试失败 (${res.model})：${res.message}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "连通测试异常");
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async (slot: AIProviderSlotDTO) => {
    if (!window.confirm(`确定删除 AI 配置「${slot.name}」吗？`)) return;
    try {
      await aiConfigApi.deleteProvider(slot.id);
      await loadSlots();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  };

  const activeSlot =
    slots.find((s) => s.is_enabled && s.role_bindings.includes("chat_default")) ??
    slots.find((s) => s.is_enabled) ??
    null;
  const activeFullyBound = activeSlot ? isSlotFullyActive(activeSlot) : false;

  const formSelectableModels =
    protocol === "antigravity"
      ? mergeUniqueModels(availableModels, agyModels, model)
      : mergeUniqueModels(availableModels);

  const testingAgySlot = testingId !== null && slots.find((s) => s.id === testingId)?.protocol === "antigravity";

  return (
    <div className="flex flex-col gap-5">
      {error && <Alert variant="destructive">{error}</Alert>}
      {notice && <Alert variant="success">{notice}</Alert>}
      {(testingAgySlot || (probingDraft && protocol === "antigravity")) && (
        <Alert>Antigravity CLI 首次探测通常需 10–20 秒，请耐心等待...</Alert>
      )}

      <Card className="p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold">当前使用的 AI 配置</h3>
              {activeSlot && activeFullyBound && <Badge variant="default">对话 · 报告 · 自动归类已启用</Badge>}
              {activeSlot && !activeFullyBound && (
                <Badge variant="warning">未完整激活（缺自动归类/报告），请点击下方“激活全功能”</Badge>
              )}
            </div>
            {activeSlot ? (
              <p className="font-mono text-sm text-muted-foreground">
                {activeSlot.name} · {activeSlot.protocol} · {activeSlot.model}
                {activeSlot.base_url ? ` · ${activeSlot.base_url}` : ""}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">尚未启用任何 AI 配置，请先新增并测试联通。</p>
            )}
          </div>
          <Button size="sm" onClick={openCreate}>
            <Plus data-icon="inline-start" />
            <span>新增 AI 配置</span>
          </Button>
        </div>
      </Card>

      {formOpen && (
        <Card className="border-primary/40 p-4 sm:p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-base font-semibold">
                {editing ? `编辑配置：${editing.name}` : "配置 AI 访问接口"}
              </h3>
              <p className="text-sm text-muted-foreground">
                选择协议、填写必要凭据后可直接测试联通或切换使用模型。
              </p>
            </div>
            <Button size="sm" variant="ghost" onClick={() => setFormOpen(false)}>
              收起
            </Button>
          </div>

          <FieldGroup>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="ai-name">配置名称 (Name)</FieldLabel>
                <Input
                  id="ai-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例如：中转站 / DeepSeek / Antigravity"
                />
              </Field>
              <Field>
                <FieldLabel>接口协议</FieldLabel>
                <Select
                  value={protocol}
                  onValueChange={(v) => {
                    const next = v as AIProviderProtocol;
                    setProtocol(next);
                    setAvailableModels([]);
                    const trimmed = baseUrl.trim();
                    const isDefaultOrEmpty =
                      !trimmed || Object.values(DEFAULT_PROTOCOL_URLS).includes(trimmed);
                    if (isDefaultOrEmpty) {
                      setBaseUrl(DEFAULT_PROTOCOL_URLS[next]);
                    }
                    if (next === "antigravity") {
                      if (!model.trim()) setModel(agyModels[0] || "gemini-3.8-flash-medium");
                      if (!fetchedAgyOnceRef.current) {
                        fetchedAgyOnceRef.current = true;
                        void refreshAgyModels(true);
                      }
                    } else if (
                      agyModels.includes(model.trim()) ||
                      ANTIGRAVITY_FALLBACK_MODELS.includes(model.trim())
                    ) {
                      setModel("");
                    }
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value="openai">OpenAI 兼容</SelectItem>
                      <SelectItem value="anthropic">Anthropic Messages</SelectItem>
                      <SelectItem value="antigravity">Antigravity CLI</SelectItem>
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
            </div>

            {protocol !== "antigravity" && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor="ai-url">API 地址 (URL)</FieldLabel>
                  <Input
                    id="ai-url"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="https://your-relay.example.com/v1"
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="ai-token">访问令牌 (Token / API Key)</FieldLabel>
                  <Input
                    id="ai-token"
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={editing?.has_api_key ? "保留原掩码即维持现有 Token" : "sk-..."}
                  />
                </Field>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button size="sm" variant="outline" onClick={handleTestDraft} disabled={probingDraft}>
                <Zap data-icon="inline-start" />
                <span>{probingDraft ? "测试中..." : "测试是否联通"}</span>
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleFetchModels}
                disabled={fetchingModels}
              >
                <RefreshCw data-icon="inline-start" className={cn(fetchingModels && "animate-spin")} />
                <span>{fetchingModels ? "获取中..." : "获取可选模型"}</span>
              </Button>
            </div>

            {draftStatus && (
              <Alert variant={draftStatus.ok ? "success" : "destructive"}>{draftStatus.text}</Alert>
            )}

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {formSelectableModels.length > 0 && (
                <Field>
                  <FieldLabel>从可选列表中选择模型 ({formSelectableModels.length})</FieldLabel>
                  <Select
                    value={formSelectableModels.includes(model) ? model : ""}
                    onValueChange={setModel}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="选择一个可选模型" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {formSelectableModels.map((m) => (
                          <SelectItem key={m} value={m}>
                            {m}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </Field>
              )}
              <Field className={formSelectableModels.length === 0 ? "sm:col-span-2" : ""}>
                <FieldLabel htmlFor="ai-model">设置使用模型 (Model ID)</FieldLabel>
                <Input
                  id="ai-model"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="可从列表选择，或手动输入模型 ID"
                />
              </Field>
            </div>

            <Field>
              <FieldLabel htmlFor="ai-extra">额外参数 JSON（可选）</FieldLabel>
              <Textarea
                id="ai-extra"
                value={extraJson}
                onChange={(e) => setExtraJson(e.target.value)}
                className="min-h-14 font-mono text-sm"
              />
              <FieldDescription>可填 temperature、max_tokens、extra_headers 等</FieldDescription>
            </Field>

            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">启用该配置</span>
              <Switch checked={enabled} onCheckedChange={setEnabled} />
            </div>

            <div className="flex flex-wrap justify-end gap-2 pt-2">
              <Button variant="outline" size="sm" onClick={() => setFormOpen(false)}>
                取消
              </Button>
              <Button variant="outline" size="sm" onClick={() => void handleSave(false)} disabled={saving}>
                保存配置
              </Button>
              <Button size="sm" onClick={() => void handleSave(true)} disabled={saving}>
                {saving ? "保存中..." : "保存并设为当前使用"}
              </Button>
            </div>
          </FieldGroup>
        </Card>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {slots.map((slot) => {
          const isChatDefault = slot.is_enabled && slot.role_bindings.includes("chat_default");
          const isFullyActive = isSlotFullyActive(slot);
          const cardAgyOptions =
            slot.protocol === "antigravity" ? mergeUniqueModels([slot.model], agyModels) : [];

          return (
            <Card
              key={slot.id}
              data-provider-id={slot.id}
              className={cn(
                "flex flex-col justify-between gap-3 p-4",
                isChatDefault && "border-primary/60 bg-accent/20",
              )}
            >
              <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{slot.name}</span>
                    <Badge variant="outline">{slot.protocol}</Badge>
                    {isFullyActive && (
                      <Badge variant="default">
                        <CheckCircle2 className="size-3" />
                        <span>当前使用</span>
                      </Badge>
                    )}
                    {isChatDefault && !isFullyActive && (
                      <Badge variant="warning">未完整激活（缺自动归类/报告）</Badge>
                    )}
                    {!slot.is_enabled && <Badge variant="destructive">已禁用</Badge>}
                  </div>
                </div>

                {slot.protocol === "antigravity" && (
                  <div className="flex flex-col gap-1.5 pt-1">
                    <span className="text-sm font-medium text-foreground">快速切换 Antigravity 模型</span>
                    <div className="flex items-center gap-1.5">
                      <Select
                        value={slot.model}
                        disabled={switchingModelId === slot.id}
                        onValueChange={(nextModel) => void handleInlineModelChange(slot, nextModel)}
                      >
                        <SelectTrigger aria-label={`切换 ${slot.name} 模型`} className="min-w-0 flex-1">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectGroup>
                            {cardAgyOptions.map((m) => (
                              <SelectItem key={m} value={m}>
                                {m}
                              </SelectItem>
                            ))}
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                      <Button
                        type="button"
                        size="icon"
                        variant="outline"
                        className="size-10"
                        disabled={loadingAgyModels}
                        title="刷新 Antigravity 可选模型"
                        aria-label="刷新 Antigravity 可选模型"
                        onClick={() => void refreshAgyModels(false)}
                      >
                        <RefreshCw className={cn("size-4", loadingAgyModels && "animate-spin")} />
                      </Button>
                    </div>
                  </div>
                )}

                <div className="flex flex-col gap-1 font-mono text-xs sm:text-sm text-muted-foreground">
                  <span>Model: {slot.model}</span>
                  {slot.base_url && <span className="truncate">URL: {slot.base_url}</span>}
                  <span>
                    Token: {slot.has_api_key ? slot.api_key_masked : "无（使用本机 Antigravity 登录态）"}
                  </span>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3">
                {!isChatDefault && (
                  <Button size="sm" onClick={() => void handleActivate(slot)}>
                    设为当前使用
                  </Button>
                )}
                {isChatDefault && !isFullyActive && (
                  <Button size="sm" onClick={() => void handleActivate(slot)}>
                    激活全功能
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={testingId === slot.id}
                  onClick={() => void handleTestSaved(slot.id)}
                >
                  <Zap data-icon="inline-start" />
                  <span>{testingId === slot.id ? "测试中..." : "测试联通"}</span>
                </Button>
                <Button size="sm" variant="outline" onClick={() => openEdit(slot)}>
                  编辑
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="size-9 text-muted-foreground hover:text-destructive"
                  onClick={() => void handleDelete(slot)}
                  aria-label={`删除配置 ${slot.name}`}
                  title="删除配置"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
