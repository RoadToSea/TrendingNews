"""Authentication API endpoints (`/api/auth/*`)."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.deps import SESSION_COOKIE_NAME, get_auth_service, get_current_user, get_settings
from app.config import Settings
from app.models import ChangePasswordRequest, LoginRequest, LoginResponse, RegisterRequest, UserDTO
from app.repositories.invite_repo import UsernameConflictError
from app.repositories.user_repo import UserRecord
from app.services.auth_service import (
    AuthError,
    AuthService,
    PasswordPolicyError,
    RateLimitedError,
    RegistrationError,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_https_request(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "").strip().lower()
    return proto == "https" or request.url.scheme == "https"


def _to_user_dto(user: UserRecord) -> UserDTO:
    role = "admin" if user.role == "admin" else "user"
    return UserDTO(id=user.id, username=user.username, role=role)


def _set_session_cookie(
    response: Response,
    token: str,
    request: Request,
    settings: Settings,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=_is_https_request(request),
        path=settings.cookie_path(),
        max_age=settings.session_max_age_sec,
    )


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    """Verify credentials and issue a subpath-scoped HttpOnly session cookie."""
    try:
        user, token = auth_service.login(body.username, body.password, _client_key(request))
    except RateLimitedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    _set_session_cookie(response, token, request, settings)
    return LoginResponse(user=_to_user_dto(user))


@router.post("/register", response_model=LoginResponse)
def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    """Register a standard user using a valid invite code and issue a session cookie."""
    try:
        user, token = auth_service.register(
            body.username,
            body.password,
            body.invite_code,
            _client_key(request),
        )
    except RateLimitedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except UsernameConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RegistrationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _set_session_cookie(response, token, request, settings)
    return LoginResponse(user=_to_user_dto(user))


@router.post("/logout")
def logout(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Clear the authentication session cookie."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=settings.cookie_path(),
    )
    return {"ok": True}


@router.get("/me", response_model=UserDTO)
def me(current_user: UserRecord = Depends(get_current_user)) -> UserDTO:
    """Return the currently authenticated user profile."""
    return _to_user_dto(current_user)


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: UserRecord = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict:
    """Rotate the authenticated user's password."""
    try:
        auth_service.change_password(current_user.id, body.current_password, body.new_password)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True}
