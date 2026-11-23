"""Administrator endpoints for managing invite codes and registered accounts (`/api/admin/*`)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_admin_service, require_admin
from app.models import (
    AdminUserDTO,
    AdminUserUpdateRequest,
    InviteCodeCreateRequest,
    InviteCodeDTO,
    InviteCodeUpdateRequest,
)
from app.repositories.user_repo import UserRecord
from app.services.admin_service import (
    AdminConflictError,
    AdminNotFoundError,
    AdminService,
    AdminValidationError,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/invite-codes", response_model=List[InviteCodeDTO])
def list_invite_codes(
    _: UserRecord = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> List[InviteCodeDTO]:
    """List all invite codes and their live usage/expiry status."""
    return admin_service.list_invite_codes()


@router.post("/invite-codes", response_model=InviteCodeDTO)
def create_invite_code(
    body: InviteCodeCreateRequest,
    admin_user: UserRecord = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> InviteCodeDTO:
    """Create a new registration invite code with configurable quota and expiry."""
    try:
        return admin_service.create_invite_code(body, admin_user.id)
    except AdminConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/invite-codes/{code_id}", response_model=InviteCodeDTO)
def update_invite_code(
    code_id: int,
    body: InviteCodeUpdateRequest,
    _: UserRecord = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> InviteCodeDTO:
    """Update an invite code's usage limit, expiration, note, or active state."""
    try:
        return admin_service.update_invite_code(code_id, body)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/invite-codes/{code_id}")
def delete_invite_code(
    code_id: int,
    _: UserRecord = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> dict:
    """Delete an invite code record permanently."""
    try:
        admin_service.delete_invite_code(code_id)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/users", response_model=List[AdminUserDTO])
def list_users(
    _: UserRecord = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> List[AdminUserDTO]:
    """List all registered users, roles, and originating invite codes."""
    return admin_service.list_users()


@router.patch("/users/{user_id}", response_model=AdminUserDTO)
def update_user(
    user_id: int,
    body: AdminUserUpdateRequest,
    admin_user: UserRecord = Depends(require_admin),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminUserDTO:
    """Update an account's active flag or role."""
    try:
        return admin_service.update_user(user_id, body, admin_user.id)
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
