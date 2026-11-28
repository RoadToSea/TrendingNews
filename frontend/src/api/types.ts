export type UserRole = "admin" | "user";

export interface UserDTO {
  id: number;
  username: string;
  role: UserRole;
}

export type InviteCodeStatus = "active" | "expired" | "exhausted" | "disabled";

export interface InviteCodeDTO {
  id: number;
  code: string;
  note: string;
  max_uses: number;
  used_count: number;
  remaining_uses: number | null;
  expires_at: string | null;
  is_active: boolean;
  status: InviteCodeStatus;
  created_by: number | null;
  created_by_username: string | null;
  created_at: string;
  updated_at: string;
}

export interface InviteCodeCreatePayload {
  code?: string;
  note?: string;
  max_uses: number;
  expires_in_hours?: number;
  expires_at?: string;
}

export interface InviteCodeUpdatePayload {
  note?: string;
  max_uses?: number;
  expires_in_hours?: number;
  expires_at?: string;
  clear_expires_at?: boolean;
  is_active?: boolean;
}

export interface AdminUserDTO {
  id: number;
  username: string;
  role: UserRole;
  is_active: boolean;
  invited_by_code: string | null;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminUserUpdatePayload {
  is_active?: boolean;
  role?: UserRole;
}

export interface NewsItemDTO {
  id: number;
  source_type: "hotlist" | "rss";
  platform_id: string;
  platform_name: string;
  domain: string;
  title: string;
  url: string;
  summary: string;
  latest_rank: number | null;
  velocity: number;
  hot_index: number | null;
  event_id: number | null;
  extra_metrics: Record<string, number | string>;
  first_seen_at: string;
  last_seen_at: string;
}

export interface PlatformSummaryDTO {
  id: string;
  name: string;
  count: number;
}

export interface RssFeedSummaryDTO {
  id: string;
  name: string;
  domain: string;
  count: number;
}

export interface HotlistResponse {
  items: NewsItemDTO[];
  platforms: PlatformSummaryDTO[];
}

export interface RisingResponse {
  items: NewsItemDTO[];
}

export interface RssResponse {
  items: NewsItemDTO[];
  feeds: RssFeedSummaryDTO[];
}

export interface KeywordGroupStatDTO {
  group_key: string;
  display_name: string;
  count: number;
  items: NewsItemDTO[];
}

export interface KeywordStatsResponse {
  groups: KeywordGroupStatDTO[];
  total: number;
}

export interface DomainInfoDTO {
  id: string;
  name: string;
  description: string;
  event_count: number;
}

export interface HotEventDTO {
  id: number;
  canonical_title: string;
  domain: string;
  summary: string;
  hot_index: number;
  velocity: number;
  platform_count: number;
  daily_rank: number;
  items: NewsItemDTO[];
  report_id: number | null;
}

export interface DomainsResponse {
  date: string;
  domains: DomainInfoDTO[];
  events: HotEventDTO[];
  rss: NewsItemDTO[];
}

export interface TrendPointDTO {
  date: string;
  hot_index: number;
  daily_rank: number;
  platform_count: number;
  velocity: number;
  is_top_n: boolean;
  daily_report_id: number | null;
  event_report_id: number | null;
}

export interface TrendSeriesDTO {
  event_id: number;
  canonical_title: string;
  domain: string;
  is_multi_day: boolean;
  points: TrendPointDTO[];
}

export interface TrendsResponse {
  dates: string[];
  series: TrendSeriesDTO[];
  daily_reports: Record<string, number>;
}

export interface EventMetricHistoryDTO {
  metric_date: string;
  hot_index: number;
  daily_rank: number;
  platform_count: number;
  velocity: number;
  is_top_n: boolean;
}

export interface EventDetailResponse {
  id: number;
  canonical_title: string;
  domain: string;
  summary: string;
  first_seen_date: string;
  last_seen_date: string;
  items: NewsItemDTO[];
  metrics: EventMetricHistoryDTO[];
  report_id: number | null;
}

export type ReportType = "daily_overall" | "domain_trend" | "item_analysis" | "chat_generated";

export interface ReportDTO {
  id: number;
  report_type: ReportType;
  report_date: string;
  domain: string;
  title: string;
  content_md: string;
  related_event_ids: number[];
  related_news_ids: number[];
  source_session_id: number | null;
  provider_name: string | null;
  created_at: string;
}

export interface ReportListResponse {
  items: ReportDTO[];
  total: number;
}

export type AIProviderProtocol = "openai" | "anthropic" | "gemini";
export type AIProviderRole = "chat_default" | "summary_report" | "event_cluster";

export interface AIProviderSlotDTO {
  id: number;
  name: string;
  protocol: AIProviderProtocol;
  base_url: string;
  has_api_key: boolean;
  api_key_masked: string;
  model: string;
  extra_params: Record<string, unknown>;
  role_bindings: AIProviderRole[];
  is_enabled: boolean;
}

export interface AIProviderTestResponse {
  ok: boolean;
  latency_ms: number;
  message: string;
  model: string;
}

export interface AIProviderProbePayload {
  protocol: AIProviderProtocol;
  base_url: string;
  api_key: string;
  model: string;
  extra_params?: Record<string, unknown>;
  slot_id?: number;
}

export interface AIProviderModelsResponse {
  models: string[];
  message: string;
}

export interface PromptTemplateDTO {
  id: number;
  name: string;
  category: string;
  content: string;
  is_default: boolean;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ChatContextItem {
  kind: "news" | "rss" | "event" | "report";
  id: number;
  title: string;
  platform_or_domain: string;
  url?: string;
  metric_label?: string;
  snapshot_text?: string;
}

export interface ChatSessionDTO {
  id: number;
  title: string;
  provider_slot_id: number | null;
  external_conversation_id: string;
  prompt_template_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessageDTO {
  id: number;
  session_id: number;
  role: "system" | "user" | "assistant";
  content: string;
  context_items: ChatContextItem[];
  usage: Record<string, unknown>;
  created_at: string;
}

export interface ChatMessagesResponse {
  session: ChatSessionDTO;
  messages: ChatMessageDTO[];
}

export interface SettingsSectionResponse<T = Record<string, unknown>> {
  section: string;
  payload: T;
  updated_at: string;
}

export interface CrawlTriggerResponse {
  job_id: string;
  status: string;
  hotlist_count: number;
  rss_count: number;
  foreign_api_count: number;
  clustered_count: number;
  duration_ms?: number;
  errors: string[];
}

export interface CrawlStartEvent {
  completed_sources: number;
  total_sources: number;
}

export interface CrawlSourceDoneEvent {
  source_kind: "hotlist" | "rss" | "foreign_api";
  source_id: string;
  source_name: string;
  count: number;
  completed_sources: number;
  total_sources: number;
  error: string | null;
}

export interface CrawlClusterDoneEvent {
  clustered_count: number;
}

export interface WebhookChannelResultDTO {
  channel: string;
  success: boolean;
  message: string;
}
