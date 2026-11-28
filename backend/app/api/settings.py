"""Settings CRUD, webhook test, and manual/streaming crawl trigger API endpoints."""

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import (
    get_cluster_service,
    get_crawl_service,
    get_current_user,
    get_settings_service,
    get_webhook_service,
    require_admin,
)
from app.models import (
    CrawlTriggerRequest,
    CrawlTriggerResponse,
    SettingsSectionResponse,
    SettingsUpdateRequest,
    WebhookTestRequest,
    WebhookTestResponse,
)
from app.repositories.user_repo import UserRecord
from app.services.cluster_service import ClusterService
from app.services.crawl_service import CrawlAlreadyRunningError, CrawlProgressEvent, CrawlService
from app.services.settings_service import (
    USER_SECTIONS,
    SettingsNotFoundError,
    SettingsService,
    SettingsValidationError,
)
from app.services.webhook_service import WebhookConfigError, WebhookService

router = APIRouter(prefix="/api", tags=["settings"])


def _format_sse(event_name: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/settings/{section}", response_model=SettingsSectionResponse)
def get_settings_section(
    section: str,
    current_user: UserRecord = Depends(get_current_user),
    settings_service: SettingsService = Depends(get_settings_service),
) -> SettingsSectionResponse:
    """Retrieve a masked configuration section respecting user/admin scope."""
    try:
        if section in USER_SECTIONS:
            payload, updated_at = settings_service.get_user_public_section(
                current_user.id,
                section,
                user_role=current_user.role,
            )
        else:
            if section != "domains" and current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="仅管理员可访问系统级配置",
                )
            payload, updated_at = settings_service.get_public_section(section)
    except SettingsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SettingsSectionResponse(section=section, payload=payload, updated_at=updated_at)


@router.put("/settings/{section}", response_model=SettingsSectionResponse)
def update_settings_section(
    section: str,
    body: SettingsUpdateRequest,
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
    settings_service: SettingsService = Depends(get_settings_service),
) -> SettingsSectionResponse:
    """Validate and persist updates to a user-scoped or admin-scoped configuration section."""
    try:
        if section in USER_SECTIONS:
            payload, updated_at = settings_service.update_user_section(
                current_user.id,
                section,
                body.payload,
            )
        else:
            if current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="仅管理员可修改系统级配置",
                )
            payload, updated_at = settings_service.update_section(section, body.payload)
    except SettingsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SettingsValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if section == "schedule":
        rescheduler = getattr(request.app.state, "reschedule_jobs", None)
        if callable(rescheduler):
            rescheduler(payload)
    return SettingsSectionResponse(section=section, payload=payload, updated_at=updated_at)


@router.post("/webhooks/test", response_model=WebhookTestResponse)
def test_webhooks(
    body: WebhookTestRequest,
    current_user: UserRecord = Depends(get_current_user),
    webhook_service: WebhookService = Depends(get_webhook_service),
) -> WebhookTestResponse:
    """Send a test notification to the calling user's configured webhook channels."""
    try:
        results = webhook_service.send_test(
            current_user.id,
            channel=body.channel,
            user_role=current_user.role,
        )
    except WebhookConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return WebhookTestResponse(results=results)


@router.post("/jobs/crawl/trigger", response_model=CrawlTriggerResponse)
async def trigger_crawl(
    body: CrawlTriggerRequest,
    __: UserRecord = Depends(require_admin),
    crawl_service: CrawlService = Depends(get_crawl_service),
    cluster_service: ClusterService = Depends(get_cluster_service),
) -> CrawlTriggerResponse:
    """Trigger a parallel collection run in a worker thread plus optional incremental clustering."""
    try:
        summary = await asyncio.to_thread(crawl_service.run_once)
    except CrawlAlreadyRunningError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if body.run_cluster:
        summary.clustered_count = await cluster_service.run_incremental_clustering()
        cluster_err = getattr(cluster_service, "last_error", None)
        if cluster_err:
            summary.errors.append(cluster_err)
            if summary.status in ("completed", "ok"):
                summary.status = "partial"
    return summary


@router.post("/jobs/crawl/stream")
async def stream_crawl(
    body: CrawlTriggerRequest,
    __: UserRecord = Depends(require_admin),
    crawl_service: CrawlService = Depends(get_crawl_service),
    cluster_service: ClusterService = Depends(get_cluster_service),
) -> StreamingResponse:
    """Stream per-source crawl completion events over SSE so the UI can render progressively."""
    if getattr(crawl_service, "is_running", False):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="数据正在更新中，请稍后再试")

    async def _event_stream() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        def _on_progress(ev: CrawlProgressEvent) -> None:
            if ev.stage == "start":
                frame = _format_sse(
                    "start",
                    {
                        "completed_sources": ev.completed_sources,
                        "total_sources": ev.total_sources,
                    },
                )
            elif ev.stage == "source_done":
                frame = _format_sse(
                    "source_done",
                    {
                        "source_kind": ev.source_kind,
                        "source_id": ev.source_id,
                        "source_name": ev.source_name,
                        "count": ev.count,
                        "completed_sources": ev.completed_sources,
                        "total_sources": ev.total_sources,
                        "error": ev.error,
                    },
                )
            else:
                return
            loop.call_soon_threadsafe(queue.put_nowait, frame)

        async def _runner() -> None:
            try:
                summary = await asyncio.to_thread(crawl_service.run_once, _on_progress)
                if body.run_cluster:
                    clustered = await cluster_service.run_incremental_clustering()
                    summary.clustered_count = clustered
                    cluster_err = getattr(cluster_service, "last_error", None)
                    if cluster_err:
                        summary.errors.append(cluster_err)
                        if summary.status in ("completed", "ok"):
                            summary.status = "partial"
                    await queue.put(
                        _format_sse(
                            "cluster_done",
                            {"clustered_count": clustered, "error": cluster_err},
                        )
                    )
                await queue.put(_format_sse("done", summary.model_dump()))
            except CrawlAlreadyRunningError as exc:
                await queue.put(_format_sse("error", {"code": "crawl_conflict", "message": str(exc)}))
            except Exception as exc:
                await queue.put(_format_sse("error", {"code": "crawl_error", "message": str(exc)}))
            finally:
                await queue.put(None)

        runner_task = asyncio.create_task(_runner())
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if frame is None:
                    break
                yield frame
        finally:
            if not runner_task.done():
                runner_task.cancel()

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
