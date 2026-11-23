"""Domain aggregation, trend chart time-series, and event drilldown API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user, get_trend_service
from app.models import DomainsResponse, EventDetailResponse, TrendsResponse
from app.repositories.user_repo import UserRecord
from app.services.trend_service import EventNotFoundError, TrendService

router = APIRouter(prefix="/api", tags=["trends"])


@router.get("/domains", response_model=DomainsResponse)
def get_domains(
    date: Optional[str] = None,
    domain: Optional[str] = None,
    _: UserRecord = Depends(get_current_user),
    trend_service: TrendService = Depends(get_trend_service),
) -> DomainsResponse:
    """Return clustered events and RSS items grouped or filtered by configured domains."""
    return trend_service.get_domains_view(target_date=date or None, domain=domain or None)


@router.get("/trends", response_model=TrendsResponse)
def get_trends(
    days: int = Query(default=14, ge=1, le=90),
    top_n: Optional[int] = Query(default=None, ge=1, le=50),
    domain: Optional[str] = None,
    _: UserRecord = Depends(get_current_user),
    trend_service: TrendService = Depends(get_trend_service),
) -> TrendsResponse:
    """Return multi-day trend trajectories and single-day points for ECharts rendering."""
    return trend_service.get_trends_view(days=days, top_n=top_n, domain=domain or None)


@router.get("/events/{event_id}", response_model=EventDetailResponse)
def get_event_detail(
    event_id: int,
    _: UserRecord = Depends(get_current_user),
    trend_service: TrendService = Depends(get_trend_service),
) -> EventDetailResponse:
    """Retrieve detailed cluster summary, linked source items, and daily metrics history."""
    try:
        return trend_service.get_event_detail(event_id)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc