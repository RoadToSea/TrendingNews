"""Shared Pydantic request, response, and DTO models for the API and service layers."""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


UserRole = Literal["admin", "user"]
InviteCodeStatus = Literal["active", "expired", "exhausted", "disabled"]


class ErrorResponse(BaseModel):
    """Uniform error response payload."""

    detail: str
    code: str


class UserDTO(BaseModel):
    """Authenticated user representation."""

    id: int
    username: str
    role: UserRole = "user"


class LoginRequest(BaseModel):
    """Credentials payload for `/api/auth/login`."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    """Account sign-up payload requiring an invite code for `/api/auth/register`."""

    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=256)
    invite_code: str = Field(min_length=4, max_length=64)


class ChangePasswordRequest(BaseModel):
    """Password update payload for `/api/auth/change-password`."""

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class LoginResponse(BaseModel):
    """Login and registration response wrapper."""

    user: UserDTO


class InviteCodeDTO(BaseModel):
    """Invite code record enriched with derived runtime status."""

    id: int
    code: str
    note: str
    max_uses: int
    used_count: int
    remaining_uses: Optional[int] = None
    expires_at: Optional[str] = None
    is_active: bool
    status: InviteCodeStatus
    created_by: Optional[int] = None
    created_by_username: Optional[str] = None
    created_at: str
    updated_at: str


class InviteCodeCreateRequest(BaseModel):
    """Admin request payload for generating a new invite code."""

    code: Optional[str] = Field(default=None, max_length=64)
    note: str = Field(default="", max_length=200)
    max_uses: int = Field(default=1, ge=0, le=10000)
    expires_in_hours: Optional[int] = Field(default=None, ge=1, le=87600)
    expires_at: Optional[str] = Field(default=None, max_length=64)


class InviteCodeUpdateRequest(BaseModel):
    """Admin patch payload for modifying quota, expiry, note, or active flag."""

    note: Optional[str] = Field(default=None, max_length=200)
    max_uses: Optional[int] = Field(default=None, ge=0, le=10000)
    expires_in_hours: Optional[int] = Field(default=None, ge=1, le=87600)
    expires_at: Optional[str] = Field(default=None, max_length=64)
    clear_expires_at: bool = False
    is_active: Optional[bool] = None


class AdminUserDTO(BaseModel):
    """Admin view of a registered user including role and invite lineage."""

    id: int
    username: str
    role: UserRole
    is_active: bool
    invited_by_code: Optional[str] = None
    last_login_at: Optional[str] = None
    created_at: str
    updated_at: str


class AdminUserUpdateRequest(BaseModel):
    """Admin patch payload for toggling active status or changing account role."""

    is_active: Optional[bool] = None
    role: Optional[UserRole] = None


class NewsItemDTO(BaseModel):
    """Unified news and RSS item returned to the frontend."""

    id: int
    source_type: Literal["hotlist", "rss"]
    platform_id: str
    platform_name: str
    domain: str
    title: str
    url: str
    summary: str = ""
    latest_rank: Optional[int] = None
    velocity: float = 0.0
    hot_index: Optional[float] = None
    event_id: Optional[int] = None
    extra_metrics: Dict[str, Union[int, float, str]] = Field(default_factory=dict)
    first_seen_at: str
    last_seen_at: str


class PlatformSummaryDTO(BaseModel):
    """Summary metadata for an active news/API platform."""

    id: str
    name: str
    count: int


class RssFeedSummaryDTO(BaseModel):
    """Summary metadata for an active RSS feed."""

    id: str
    name: str
    domain: str
    count: int


class HotlistResponse(BaseModel):
    """Response payload for `/api/hotlist`."""

    items: List[NewsItemDTO]
    platforms: List[PlatformSummaryDTO]


class RisingResponse(BaseModel):
    """Response payload for `/api/hotlist/rising`."""

    items: List[NewsItemDTO]


class RssResponse(BaseModel):
    """Response payload for `/api/rss`."""

    items: List[NewsItemDTO]
    feeds: List[RssFeedSummaryDTO]


class KeywordGroupStatDTO(BaseModel):
    """Matched items aggregated under one keyword group."""

    group_key: str
    display_name: str
    count: int
    items: List[NewsItemDTO]


class KeywordStatsResponse(BaseModel):
    """Response payload for `/api/keywords/stats`."""

    groups: List[KeywordGroupStatDTO]
    total: int


class SettingsSectionResponse(BaseModel):
    """Response payload for `/api/settings/{section}`."""

    section: str
    payload: Dict[str, Any]
    updated_at: str


class SettingsUpdateRequest(BaseModel):
    """Request payload for updating a settings section."""

    payload: Dict[str, Any]


class CrawlTriggerRequest(BaseModel):
    """Optional parameters when manually triggering a crawl job."""

    run_cluster: bool = False


class CrawlTriggerResponse(BaseModel):
    """Result summary of a synchronous or triggered crawl run."""

    job_id: str
    status: str
    hotlist_count: int = 0
    rss_count: int = 0
    foreign_api_count: int = 0
    clustered_count: int = 0
    duration_ms: int = 0
    errors: List[str] = Field(default_factory=list)


class WebhookTestRequest(BaseModel):
    """Request body for `/api/webhooks/test`."""

    channel: Optional[str] = None


class WebhookChannelResultDTO(BaseModel):
    """Send status for a single notification channel."""

    channel: str
    success: bool
    message: str


class WebhookTestResponse(BaseModel):
    """Response payload for `/api/webhooks/test`."""

    results: List[WebhookChannelResultDTO]


class DomainInfoDTO(BaseModel):
    """Domain category metadata with active event count."""

    id: str
    name: str
    description: str = ""
    event_count: int = 0


class HotEventDTO(BaseModel):
    """Clustered cross-platform hot event with daily aggregated scores."""

    id: int
    canonical_title: str
    domain: str
    summary: str
    hot_index: float
    velocity: float
    platform_count: int
    daily_rank: int
    items: List[NewsItemDTO] = Field(default_factory=list)
    report_id: Optional[int] = None


class DomainsResponse(BaseModel):
    """Response payload for `/api/domains`."""

    date: str
    domains: List[DomainInfoDTO]
    events: List[HotEventDTO]
    rss: List[NewsItemDTO]


class TrendPointDTO(BaseModel):
    """Single day point on an event's multi-day trend trajectory."""

    date: str
    hot_index: float
    daily_rank: int
    platform_count: int
    velocity: float
    is_top_n: bool
    daily_report_id: Optional[int] = None
    event_report_id: Optional[int] = None


class TrendSeriesDTO(BaseModel):
    """Series representing one event across one or more dates."""

    event_id: int
    canonical_title: str
    domain: str
    is_multi_day: bool
    points: List[TrendPointDTO]


class TrendsResponse(BaseModel):
    """Response payload for `/api/trends`."""

    dates: List[str]
    series: List[TrendSeriesDTO]
    daily_reports: Dict[str, int] = Field(default_factory=dict)


class EventMetricHistoryDTO(BaseModel):
    """Daily metric history entry for an event detail drawer."""

    metric_date: str
    hot_index: float
    daily_rank: int
    platform_count: int
    velocity: float
    is_top_n: bool


class EventDetailResponse(BaseModel):
    """Detailed view for `/api/events/{event_id}`."""

    id: int
    canonical_title: str
    domain: str
    summary: str
    first_seen_date: str
    last_seen_date: str
    items: List[NewsItemDTO]
    metrics: List[EventMetricHistoryDTO]
    report_id: Optional[int] = None


ReportType = Literal["daily_overall", "domain_trend", "item_analysis", "chat_generated"]


class ReportDTO(BaseModel):
    """Persisted Markdown report returned by `/api/reports*`."""

    id: int
    report_type: ReportType
    report_date: str
    domain: str = ""
    title: str
    content_md: str
    related_event_ids: List[int] = Field(default_factory=list)
    related_news_ids: List[int] = Field(default_factory=list)
    source_session_id: Optional[int] = None
    provider_name: Optional[str] = None
    created_at: str


class ReportListResponse(BaseModel):
    """Paginated response payload for `/api/reports`."""

    items: List[ReportDTO]
    total: int


class ReportCreateRequest(BaseModel):
    """Manual report creation payload for `POST /api/reports`."""

    title: str = Field(min_length=1, max_length=200)
    report_type: ReportType
    report_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    domain: str = ""
    content_md: str = Field(min_length=1)
    related_event_ids: List[int] = Field(default_factory=list)
    related_news_ids: List[int] = Field(default_factory=list)


class ReportGenerateRequest(BaseModel):
    """Request payload for AI report generation via `/api/reports/generate`."""

    mode: Literal["daily_overall", "domain_trend", "item_analysis"]
    date: Optional[str] = None
    domain: Optional[str] = None
    news_ids: List[int] = Field(default_factory=list)
    event_ids: List[int] = Field(default_factory=list)
    provider_slot_id: Optional[int] = None


AIProviderProtocol = Literal["openai", "anthropic", "gemini"]
AIProviderRole = Literal["chat_default", "summary_report", "event_cluster"]


class AIProviderSlotDTO(BaseModel):
    """Public representation of an AI provider slot (never contains plaintext secrets)."""

    id: int
    name: str
    protocol: AIProviderProtocol
    base_url: str
    has_api_key: bool
    api_key_masked: str
    model: str
    extra_params: Dict[str, Any] = Field(default_factory=dict)
    role_bindings: List[AIProviderRole] = Field(default_factory=list)
    is_enabled: bool


class AIProviderCreateRequest(BaseModel):
    """Payload to create a new AI provider slot."""

    name: str = Field(min_length=1, max_length=80)
    protocol: AIProviderProtocol
    base_url: str = ""
    api_key: str = ""
    model: str = Field(min_length=1, max_length=160)
    extra_params: Dict[str, Any] = Field(default_factory=dict)
    role_bindings: List[AIProviderRole] = Field(default_factory=list)
    is_enabled: bool = True


class AIProviderUpdateRequest(BaseModel):
    """Payload to update an existing AI provider slot."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    protocol: Optional[AIProviderProtocol] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    model: Optional[str] = Field(default=None, min_length=1, max_length=160)
    extra_params: Optional[Dict[str, Any]] = None
    role_bindings: Optional[List[AIProviderRole]] = None
    is_enabled: Optional[bool] = None


class AIProviderTestResponse(BaseModel):
    """Connectivity test result for `/api/ai-providers/{id}/test` and `/api/ai-providers/test`."""

    ok: bool
    latency_ms: int
    message: str
    model: str


class AIProviderProbeRequest(BaseModel):
    """Unsaved draft or existing provider configuration used to test connectivity or list models."""

    protocol: AIProviderProtocol
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    extra_params: Dict[str, Any] = Field(default_factory=dict)
    slot_id: Optional[int] = None


class AIProviderModelsResponse(BaseModel):
    """Response payload listing discoverable models for an AI provider configuration."""

    models: List[str] = Field(default_factory=list)
    message: str = ""


class PromptTemplateDTO(BaseModel):
    """Opening system prompt template record."""

    id: int
    name: str
    category: str
    content: str
    is_default: bool
    is_enabled: bool
    created_at: str
    updated_at: str


class PromptTemplateCreateRequest(BaseModel):
    """Request body for creating a prompt template."""

    name: str = Field(min_length=1, max_length=80)
    category: str = "chat_system"
    content: str = Field(min_length=1)
    is_default: bool = False
    is_enabled: bool = True


class PromptTemplateUpdateRequest(BaseModel):
    """Request body for updating a prompt template."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    content: Optional[str] = Field(default=None, min_length=1)
    is_default: Optional[bool] = None
    is_enabled: Optional[bool] = None


class ChatContextItem(BaseModel):
    """Structured reference card attached via global Picker Mode or detail drawer."""

    kind: Literal["news", "rss", "event", "report"]
    id: int
    title: str
    platform_or_domain: str
    url: Optional[str] = None
    metric_label: Optional[str] = None
    snapshot_text: Optional[str] = None


class ChatSessionDTO(BaseModel):
    """Persistent AI chat session metadata."""

    id: int
    title: str
    provider_slot_id: Optional[int] = None
    external_conversation_id: str = ""
    prompt_template_id: Optional[int] = None
    created_at: str
    updated_at: str


class ChatSessionCreateRequest(BaseModel):
    """Payload for creating a chat session."""

    title: str = Field(default="新对话", min_length=1, max_length=120)
    provider_slot_id: Optional[int] = None
    prompt_template_id: Optional[int] = None


class ChatMessageDTO(BaseModel):
    """Persisted chat turn including attached context chips."""

    id: int
    session_id: int
    role: Literal["system", "user", "assistant"]
    content: str
    context_items: List[ChatContextItem] = Field(default_factory=list)
    usage: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ChatMessagesResponse(BaseModel):
    """Response payload for `/api/chat/sessions/{id}/messages`."""

    session: ChatSessionDTO
    messages: List[ChatMessageDTO]


class ChatStreamRequest(BaseModel):
    """Request body for SSE streaming chat turn."""

    content: str = Field(min_length=1)
    context_items: List[ChatContextItem] = Field(default_factory=list)
    provider_slot_id: Optional[int] = None
    prompt_template_id: Optional[int] = None


class SaveChatReportRequest(BaseModel):
    """Request payload for saving a chat conversation as a persisted report."""

    title: Optional[str] = None
    report_date: Optional[str] = None
    domain: str = ""
    message_ids: Optional[List[int]] = None
    auto_summarize: bool = True
    provider_slot_id: Optional[int] = None
