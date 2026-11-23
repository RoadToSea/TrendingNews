import { apiRequest, apiUrl } from "@/api/client";
import type {
  AIProviderModelsResponse,
  AIProviderProbePayload,
  AIProviderProtocol,
  AIProviderRole,
  AIProviderSlotDTO,
  AIProviderTestResponse,
  AdminUserDTO,
  AdminUserUpdatePayload,
  ChatMessagesResponse,
  ChatSessionDTO,
  CrawlTriggerResponse,
  DomainsResponse,
  EventDetailResponse,
  HotlistResponse,
  InviteCodeCreatePayload,
  InviteCodeDTO,
  InviteCodeUpdatePayload,
  KeywordStatsResponse,
  PromptTemplateDTO,
  ReportDTO,
  ReportListResponse,
  ReportType,
  RisingResponse,
  RssResponse,
  SettingsSectionResponse,
  TrendsResponse,
  UserDTO,
  WebhookChannelResultDTO,
} from "@/api/types";

export const authApi = {
  login: (username: string, password: string) =>
    apiRequest<{ user: UserDTO }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  register: (username: string, password: string, invite_code: string) =>
    apiRequest<{ user: UserDTO }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, password, invite_code }),
    }),
  logout: () => apiRequest<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  me: () => apiRequest<UserDTO>("/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    apiRequest<{ ok: boolean }>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),
};

export const adminApi = {
  listInviteCodes: () => apiRequest<InviteCodeDTO[]>("/admin/invite-codes"),
  createInviteCode: (payload: InviteCodeCreatePayload) =>
    apiRequest<InviteCodeDTO>("/admin/invite-codes", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateInviteCode: (id: number, payload: InviteCodeUpdatePayload) =>
    apiRequest<InviteCodeDTO>(`/admin/invite-codes/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteInviteCode: (id: number) =>
    apiRequest<{ ok: boolean }>(`/admin/invite-codes/${id}`, { method: "DELETE" }),
  listUsers: () => apiRequest<AdminUserDTO[]>("/admin/users"),
  updateUser: (id: number, payload: AdminUserUpdatePayload) =>
    apiRequest<AdminUserDTO>(`/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
};

export const feedApi = {
  hotlist: (params?: { platform_id?: string; q?: string; hours?: number; limit?: number }) => {
    const sp = new URLSearchParams();
    if (params?.platform_id) sp.set("platform_id", params.platform_id);
    if (params?.q) sp.set("q", params.q);
    if (params?.hours) sp.set("hours", String(params.hours));
    if (params?.limit) sp.set("limit", String(params.limit));
    const qs = sp.toString();
    return apiRequest<HotlistResponse>(`/hotlist${qs ? `?${qs}` : ""}`);
  },
  rising: (hours = 6, limit = 50) =>
    apiRequest<RisingResponse>(`/hotlist/rising?hours=${hours}&limit=${limit}`),
  rss: (params?: { feed_id?: string; domain?: string; days?: number; limit?: number }) => {
    const sp = new URLSearchParams();
    if (params?.feed_id) sp.set("feed_id", params.feed_id);
    if (params?.domain) sp.set("domain", params.domain);
    if (params?.days) sp.set("days", String(params.days));
    if (params?.limit) sp.set("limit", String(params.limit));
    const qs = sp.toString();
    return apiRequest<RssResponse>(`/rss${qs ? `?${qs}` : ""}`);
  },
  keywordsStats: (hours = 24) =>
    apiRequest<KeywordStatsResponse>(`/keywords/stats?hours=${hours}`),
};

export const trendsApi = {
  domains: (date?: string, domain?: string) => {
    const sp = new URLSearchParams();
    if (date) sp.set("date", date);
    if (domain) sp.set("domain", domain);
    const qs = sp.toString();
    return apiRequest<DomainsResponse>(`/domains${qs ? `?${qs}` : ""}`);
  },
  trends: (days = 14, top_n?: number, domain?: string) => {
    const sp = new URLSearchParams();
    sp.set("days", String(days));
    if (top_n) sp.set("top_n", String(top_n));
    if (domain) sp.set("domain", domain);
    return apiRequest<TrendsResponse>(`/trends?${sp.toString()}`);
  },
  eventDetail: (eventId: number) =>
    apiRequest<EventDetailResponse>(`/events/${eventId}`),
};

export const reportsApi = {
  list: (params?: {
    report_type?: string;
    domain?: string;
    date?: string;
    page?: number;
    page_size?: number;
  }) => {
    const sp = new URLSearchParams();
    if (params?.report_type) sp.set("report_type", params.report_type);
    if (params?.domain) sp.set("domain", params.domain);
    if (params?.date) sp.set("date", params.date);
    if (params?.page) sp.set("page", String(params.page));
    if (params?.page_size) sp.set("page_size", String(params.page_size));
    const qs = sp.toString();
    return apiRequest<ReportListResponse>(`/reports${qs ? `?${qs}` : ""}`);
  },
  get: (id: number) => apiRequest<ReportDTO>(`/reports/${id}`),
  create: (body: {
    title: string;
    report_type: ReportType;
    report_date: string;
    domain?: string;
    content_md: string;
    related_event_ids?: number[];
    related_news_ids?: number[];
  }) =>
    apiRequest<ReportDTO>("/reports", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  delete: (id: number) => apiRequest<{ ok: boolean }>(`/reports/${id}`, { method: "DELETE" }),
  generate: (body: {
    mode: "daily_overall" | "domain_trend" | "item_analysis";
    date?: string;
    domain?: string;
    news_ids?: number[];
    event_ids?: number[];
    provider_slot_id?: number;
  }) =>
    apiRequest<ReportDTO>("/reports/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export const aiConfigApi = {
  listProviders: () => apiRequest<AIProviderSlotDTO[]>("/ai-providers"),
  createProvider: (body: {
    name: string;
    protocol: AIProviderProtocol;
    base_url: string;
    api_key: string;
    model: string;
    extra_params: Record<string, unknown>;
    role_bindings: AIProviderRole[];
    is_enabled: boolean;
  }) =>
    apiRequest<AIProviderSlotDTO>("/ai-providers", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateProvider: (
    id: number,
    body: {
      name?: string;
      protocol?: AIProviderProtocol;
      base_url?: string;
      api_key?: string;
      clear_api_key?: boolean;
      model?: string;
      extra_params?: Record<string, unknown>;
      role_bindings?: AIProviderRole[];
      is_enabled?: boolean;
    },
  ) =>
    apiRequest<AIProviderSlotDTO>(`/ai-providers/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteProvider: (id: number) =>
    apiRequest<{ ok: boolean }>(`/ai-providers/${id}`, { method: "DELETE" }),
  testProvider: (id: number) =>
    apiRequest<AIProviderTestResponse>(`/ai-providers/${id}/test`, { method: "POST" }),
  testDraft: (body: AIProviderProbePayload) =>
    apiRequest<AIProviderTestResponse>("/ai-providers/test", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  fetchModels: (body: AIProviderProbePayload) =>
    apiRequest<AIProviderModelsResponse>("/ai-providers/models", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  activateProvider: (id: number) =>
    apiRequest<AIProviderSlotDTO>(`/ai-providers/${id}/activate`, { method: "POST" }),
  listPrompts: () => apiRequest<PromptTemplateDTO[]>("/prompts"),
  createPrompt: (body: {
    name: string;
    content: string;
    is_default: boolean;
    is_enabled: boolean;
  }) =>
    apiRequest<PromptTemplateDTO>("/prompts", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updatePrompt: (
    id: number,
    body: {
      name?: string;
      content?: string;
      is_default?: boolean;
      is_enabled?: boolean;
    },
  ) =>
    apiRequest<PromptTemplateDTO>(`/prompts/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deletePrompt: (id: number) =>
    apiRequest<{ ok: boolean }>(`/prompts/${id}`, { method: "DELETE" }),
};

export const chatApi = {
  listSessions: () => apiRequest<ChatSessionDTO[]>("/chat/sessions"),
  createSession: (body?: {
    title?: string;
    provider_slot_id?: number | null;
    prompt_template_id?: number | null;
  }) =>
    apiRequest<ChatSessionDTO>("/chat/sessions", {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),
  deleteSession: (id: number) =>
    apiRequest<{ ok: boolean }>(`/chat/sessions/${id}`, { method: "DELETE" }),
  getMessages: (id: number) => apiRequest<ChatMessagesResponse>(`/chat/sessions/${id}/messages`),
  saveReport: (
    id: number,
    body: {
      title?: string;
      report_date?: string;
      domain?: string;
      message_ids?: number[];
      auto_summarize?: boolean;
      provider_slot_id?: number;
    },
  ) =>
    apiRequest<ReportDTO>(`/chat/sessions/${id}/save-report`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export const settingsApi = {
  getSection: <T = Record<string, unknown>>(section: string) =>
    apiRequest<SettingsSectionResponse<T>>(`/settings/${section}`),
  updateSection: <T = Record<string, unknown>>(section: string, payload: T) =>
    apiRequest<SettingsSectionResponse<T>>(`/settings/${section}`, {
      method: "PUT",
      body: JSON.stringify({ payload }),
    }),
  keepaliveUpdateSection: (section: string, payload: Record<string, unknown>) => {
    void fetch(apiUrl(`/settings/${section}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ payload }),
      credentials: "include",
      keepalive: true,
    }).catch(() => {});
  },
  testWebhook: (channel?: string) =>
    apiRequest<{ results: WebhookChannelResultDTO[] }>("/webhooks/test", {
      method: "POST",
      body: JSON.stringify({ channel: channel || null }),
    }),
  triggerCrawl: (run_cluster = true) =>
    apiRequest<CrawlTriggerResponse>("/jobs/crawl/trigger", {
      method: "POST",
      body: JSON.stringify({ run_cluster }),
    }),
};
