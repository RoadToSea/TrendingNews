"""Archived report CRUD and AI report generation endpoints (`/api/reports*`)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user, get_report_service
from app.models import (
    ReportCreateRequest,
    ReportDTO,
    ReportGenerateRequest,
    ReportListResponse,
)
from app.repositories.user_repo import UserRecord
from app.services.ai_gateway.base import LLMGatewayError
from app.services.report_service import (
    ReportNotFoundError,
    ReportService,
    ReportValidationError,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=ReportListResponse)
def list_reports(
    report_type: Optional[str] = None,
    domain: Optional[str] = None,
    date: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: UserRecord = Depends(get_current_user),
    report_service: ReportService = Depends(get_report_service),
) -> ReportListResponse:
    """List persisted reports with pagination and optional type/domain/date filters."""
    return report_service.list_reports(
        report_type=report_type,
        domain=domain,
        report_date=date,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ReportDTO)
def create_report(
    body: ReportCreateRequest,
    _: UserRecord = Depends(get_current_user),
    report_service: ReportService = Depends(get_report_service),
) -> ReportDTO:
    """Manually create and archive a Markdown report."""
    return report_service.create_manual_report(body)


@router.post("/generate", response_model=ReportDTO)
async def generate_report(
    body: ReportGenerateRequest,
    _: UserRecord = Depends(get_current_user),
    report_service: ReportService = Depends(get_report_service),
) -> ReportDTO:
    """Generate a daily overall, domain trend, or item analysis report via LLM and archive it."""
    try:
        return await report_service.generate_report(body)
    except ReportValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LLMGatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{report_id}", response_model=ReportDTO)
def get_report(
    report_id: int,
    _: UserRecord = Depends(get_current_user),
    report_service: ReportService = Depends(get_report_service),
) -> ReportDTO:
    """Fetch a single report record by ID."""
    try:
        return report_service.get_report(report_id)
    except ReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{report_id}")
def delete_report(
    report_id: int,
    _: UserRecord = Depends(get_current_user),
    report_service: ReportService = Depends(get_report_service),
) -> dict:
    """Delete an archived report by ID."""
    try:
        report_service.delete_report(report_id)
    except ReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"ok": True}