"""Admin invite code lifecycle and registered user management service."""

from datetime import datetime, timedelta
import re
import secrets
import sqlite3
from typing import List, Optional
import zoneinfo

from app.models import (
    AdminUserDTO,
    AdminUserUpdateRequest,
    InviteCodeCreateRequest,
    InviteCodeDTO,
    InviteCodeStatus,
    InviteCodeUpdateRequest,
    UserRole,
)
from app.repositories.invite_repo import InviteCodeRecord, InviteRepository
from app.repositories.user_repo import UserRepository

_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_CUSTOM_CODE_RE = re.compile(r"^[A-Z0-9_-]{4,64}$")


class AdminNotFoundError(Exception):
    """Raised when a target invite code or user does not exist."""


class AdminValidationError(Exception):
    """Raised when an admin update fails business constraints."""


class AdminConflictError(Exception):
    """Raised when creating an invite code whose code already exists."""


class AdminService:
    """Service managing invite codes, quotas, expiration, and registered accounts."""

    def __init__(
        self,
        invite_repo: InviteRepository,
        user_repo: UserRepository,
        timezone_name: str,
    ) -> None:
        """Initialize the admin management service.

        Args:
            invite_repo: Invite code repository.
            user_repo: User persistence repository.
            timezone_name: Configured application timezone name.
        """
        self._invites = invite_repo
        self._users = user_repo
        self._tz = zoneinfo.ZoneInfo(timezone_name)

    def _now(self) -> datetime:
        return datetime.now(self._tz)

    def _generate_random_code(self) -> str:
        part1 = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
        part2 = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
        return f"TR-{part1}-{part2}"

    def _resolve_custom_code(self, raw_code: Optional[str]) -> str:
        if raw_code is None or not raw_code.strip():
            for _ in range(8):
                candidate = self._generate_random_code()
                if self._invites.get_by_code(candidate) is None:
                    return candidate
            raise AdminConflictError("自动生成唯一邀请码失败，请重试")

        normalized = raw_code.strip().upper()
        if not _CUSTOM_CODE_RE.fullmatch(normalized):
            raise AdminValidationError("自定义邀请码仅支持 4-64 位字母、数字、下划线或短横线")
        if self._invites.get_by_code(normalized) is not None:
            raise AdminConflictError("该邀请码已存在")
        return normalized

    def _resolve_expiry(
        self,
        expires_in_hours: Optional[int],
        expires_at: Optional[str],
        now: datetime,
    ) -> Optional[str]:
        if expires_in_hours is not None and expires_at:
            raise AdminValidationError("不能同时指定有效小时数和固定过期时间")
        if expires_in_hours is not None:
            return (now + timedelta(hours=expires_in_hours)).isoformat(timespec="seconds")
        if not expires_at or not expires_at.strip():
            return None

        raw = expires_at.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise AdminValidationError("过期时间格式无效，请使用有效日期时间") from exc

        normalized = parsed.replace(tzinfo=self._tz) if parsed.tzinfo is None else parsed.astimezone(self._tz)
        if normalized <= now:
            raise AdminValidationError("过期时间必须晚于当前时间")
        return normalized.isoformat(timespec="seconds")

    def _derive_status(self, rec: InviteCodeRecord, now: datetime) -> InviteCodeStatus:
        if not rec.is_active:
            return "disabled"
        if rec.expires_at:
            try:
                if datetime.fromisoformat(rec.expires_at) <= now:
                    return "expired"
            except ValueError:
                if rec.expires_at <= now.isoformat(timespec="seconds"):
                    return "expired"
        if rec.max_uses > 0 and rec.used_count >= rec.max_uses:
            return "exhausted"
        return "active"

    def _to_invite_dto(self, rec: InviteCodeRecord, now: datetime) -> InviteCodeDTO:
        remaining = None if rec.max_uses == 0 else max(0, rec.max_uses - rec.used_count)
        return InviteCodeDTO(
            id=rec.id,
            code=rec.code,
            note=rec.note,
            max_uses=rec.max_uses,
            used_count=rec.used_count,
            remaining_uses=remaining,
            expires_at=rec.expires_at,
            is_active=rec.is_active,
            status=self._derive_status(rec, now),
            created_by=rec.created_by,
            created_by_username=rec.created_by_username,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
        )

    def list_invite_codes(self) -> List[InviteCodeDTO]:
        """List all invite codes with computed live usage and expiry statuses."""
        now = self._now()
        return [self._to_invite_dto(rec, now) for rec in self._invites.list_all()]

    def create_invite_code(self, body: InviteCodeCreateRequest, admin_user_id: int) -> InviteCodeDTO:
        """Create a new invite code with configurable max uses and expiration."""
        now = self._now()
        now_iso = now.isoformat(timespec="seconds")
        code = self._resolve_custom_code(body.code)
        expiry = self._resolve_expiry(body.expires_in_hours, body.expires_at, now)
        try:
            created = self._invites.create(
                code=code,
                note=body.note.strip(),
                max_uses=body.max_uses,
                expires_at=expiry,
                created_by=admin_user_id,
                now_iso=now_iso,
            )
        except sqlite3.IntegrityError as exc:
            raise AdminConflictError("该邀请码已存在") from exc
        return self._to_invite_dto(created, now)

    def update_invite_code(self, code_id: int, body: InviteCodeUpdateRequest) -> InviteCodeDTO:
        """Update an invite code's quota, expiration, note, or active flag."""
        existing = self._invites.get_by_id(code_id)
        if existing is None:
            raise AdminNotFoundError("邀请码不存在")

        if body.max_uses is not None and body.max_uses > 0 and body.max_uses < existing.used_count:
            raise AdminValidationError(f"最大有效次数不能小于已使用次数 ({existing.used_count})")

        now = self._now()
        now_iso = now.isoformat(timespec="seconds")
        next_expiry = (
            None
            if body.clear_expires_at
            else self._resolve_expiry(body.expires_in_hours, body.expires_at, now)
        )
        updated = self._invites.update(
            code_id,
            note=body.note.strip() if body.note is not None else None,
            max_uses=body.max_uses,
            expires_at=next_expiry,
            clear_expires_at=body.clear_expires_at,
            is_active=body.is_active,
            now_iso=now_iso,
        )
        if updated is None:
            raise AdminNotFoundError("邀请码不存在")
        return self._to_invite_dto(updated, now)

    def delete_invite_code(self, code_id: int) -> None:
        """Delete an invite code permanently."""
        if not self._invites.delete(code_id):
            raise AdminNotFoundError("邀请码不存在")

    def list_users(self) -> List[AdminUserDTO]:
        """List all registered accounts and their originating invite codes."""
        rows = self._users.list_all_with_invite()
        return [
            AdminUserDTO(
                id=int(r["id"]),
                username=str(r["username"]),
                role=str(r["role"]) if r["role"] in ("admin", "user") else "user",  # type: ignore[arg-type]
                is_active=bool(r["is_active"]),
                invited_by_code=str(r["invited_by_code"]) if r["invited_by_code"] else None,
                last_login_at=str(r["last_login_at"]) if r["last_login_at"] else None,
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def update_user(
        self,
        target_user_id: int,
        body: AdminUserUpdateRequest,
        acting_admin_id: int,
    ) -> AdminUserDTO:
        """Update an account's active flag or role with admin lockout safeguards."""
        target = self._users.get_by_id(target_user_id)
        if target is None:
            raise AdminNotFoundError("用户不存在")

        if target.id == acting_admin_id:
            if body.is_active is False:
                raise AdminValidationError("不能停用当前登录的管理员账号")
            if body.role == "user":
                raise AdminValidationError("不能取消当前登录账号的管理员权限")

        if target.role == "admin" and target.is_active:
            disabling = body.is_active is False
            demoting = body.role == "user"
            if (disabling or demoting) and self._users.count_active_admins() <= 1:
                raise AdminValidationError("系统至少需要保留一名启用状态的管理员")

        now_iso = self._now().isoformat(timespec="seconds")
        updated = self._users.update_user_flags(
            target_user_id,
            is_active=body.is_active,
            role=body.role,
            now_iso=now_iso,
        )
        if updated is None:
            raise AdminNotFoundError("用户不存在")

        for dto in self.list_users():
            if dto.id == updated.id:
                return dto
        role_val: UserRole = "admin" if updated.role == "admin" else "user"
        return AdminUserDTO(
            id=updated.id,
            username=updated.username,
            role=role_val,
            is_active=updated.is_active,
            last_login_at=updated.last_login_at,
            created_at=updated.created_at,
            updated_at=updated.updated_at,
        )
