"""Authentication, invite-based registration, and password management service."""

from datetime import datetime
import re
from typing import Optional, Tuple
import zoneinfo

from app.repositories.invite_repo import (
    InviteInvalidError,
    InviteRepository,
    UsernameConflictError,
)
from app.repositories.user_repo import UserRecord, UserRepository
from app.security import (
    LoginRateLimiter,
    SessionError,
    SessionManager,
    hash_password,
    verify_password,
)

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class AuthError(Exception):
    """Raised when credentials or session tokens are invalid."""


class RateLimitedError(Exception):
    """Raised when a client exceeds allowed failed authentication attempts."""


class PasswordPolicyError(Exception):
    """Raised when a password change request fails validation."""


class RegistrationError(Exception):
    """Raised when invite-based account registration fails validation or quota checks."""


class AuthService:
    """Service handling user login, invite registration, session checks, and password rotation."""

    def __init__(
        self,
        user_repo: UserRepository,
        session_manager: SessionManager,
        rate_limiter: LoginRateLimiter,
        timezone_name: str,
        invite_repo: Optional[InviteRepository] = None,
        register_rate_limiter: Optional[LoginRateLimiter] = None,
    ) -> None:
        """Initialize the authentication service.

        Args:
            user_repo: User persistence repository.
            session_manager: Signed cookie session manager.
            rate_limiter: Per-IP sliding-window login limiter.
            timezone_name: Configured application timezone name.
            invite_repo: Optional invite code repository enabling user registration.
            register_rate_limiter: Optional per-IP rate limiter for registration attempts.
        """
        self._user_repo = user_repo
        self._session_manager = session_manager
        self._rate_limiter = rate_limiter
        self._tz = zoneinfo.ZoneInfo(timezone_name)
        self._invite_repo = invite_repo
        self._register_limiter = register_rate_limiter or LoginRateLimiter(
            max_attempts=10,
            window_sec=300,
        )

    def _now_iso(self) -> str:
        return datetime.now(self._tz).isoformat(timespec="seconds")

    def login(self, username: str, password: str, client_key: str) -> Tuple[UserRecord, str]:
        """Authenticate a user and issue a signed session token."""
        if not self._rate_limiter.is_allowed(client_key):
            raise RateLimitedError("登录失败次数过多，请稍后再试")

        user = self._user_repo.get_by_username(username.strip())
        if user is None or not user.is_active or not verify_password(user.password_hash, password):
            self._rate_limiter.record_failure(client_key)
            raise AuthError("用户名或密码错误")

        self._rate_limiter.reset(client_key)
        self._user_repo.update_last_login(user.id, self._now_iso())
        token = self._session_manager.create_token(user.id, user.username)
        return user, token

    def register(
        self,
        username: str,
        password: str,
        invite_code: str,
        client_key: str,
    ) -> Tuple[UserRecord, str]:
        """Register a new standard user with a valid invite code and auto-login."""
        if not self._register_limiter.is_allowed(client_key):
            raise RateLimitedError("注册尝试过于频繁，请稍后再试")
        if self._invite_repo is None:
            raise RegistrationError("当前未启用邀请注册功能")

        clean_user = username.strip()
        if not _USERNAME_RE.fullmatch(clean_user):
            self._register_limiter.record_failure(client_key)
            raise RegistrationError("用户名需为 3-32 位字母、数字、下划线、点或短横线")
        if len(password) < 8:
            self._register_limiter.record_failure(client_key)
            raise RegistrationError("密码长度至少为 8 位")

        clean_code = invite_code.strip().upper()
        if not clean_code:
            self._register_limiter.record_failure(client_key)
            raise RegistrationError("请填写有效的邀请码")

        try:
            user = self._invite_repo.consume_and_create_user(
                code=clean_code,
                username=clean_user,
                password_hash=hash_password(password),
                now_iso=self._now_iso(),
            )
        except InviteInvalidError as exc:
            self._register_limiter.record_failure(client_key)
            raise RegistrationError("邀请码无效、已过期或已达到使用上限") from exc
        except UsernameConflictError as exc:
            self._register_limiter.record_failure(client_key)
            raise UsernameConflictError("该用户名已被占用") from exc

        self._register_limiter.reset(client_key)
        token = self._session_manager.create_token(user.id, user.username)
        return user, token

    def verify_session(self, token: str) -> UserRecord:
        """Validate a session token and load its active user record."""
        try:
            claims = self._session_manager.verify_token(token)
        except SessionError as exc:
            raise AuthError(str(exc)) from exc

        user = self._user_repo.get_by_id(int(claims["uid"]))
        if user is None or not user.is_active:
            raise AuthError("User account is inactive or missing")
        return user

    def change_password(self, user_id: int, current_password: str, new_password: str) -> None:
        """Rotate a user's password after verifying the existing credential."""
        if len(new_password) < 8:
            raise PasswordPolicyError("New password must be at least 8 characters")
        user = self._user_repo.get_by_id(user_id)
        if user is None or not verify_password(user.password_hash, current_password):
            raise AuthError("Current password is incorrect")
        self._user_repo.update_password_hash(user_id, hash_password(new_password), self._now_iso())
