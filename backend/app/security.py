"""Security utilities: password hashing, Fernet encryption, signed sessions, and rate limiting."""

import base64
from collections import deque
import hashlib
import secrets
import threading
import time
from typing import Dict

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


class CipherError(Exception):
    """Raised when encrypting or decrypting stored secrets fails."""


class SessionError(Exception):
    """Raised when a session token is missing, tampered with, or expired."""


_PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id.

    Args:
        password: Plaintext password (must be non-empty).

    Returns:
        str: Encoded Argon2 password hash.

    Raises:
        ValueError: If `password` is empty.
    """
    if not password:
        raise ValueError("Password must not be empty")
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a plaintext password against a stored Argon2 hash.

    Args:
        password_hash: Stored Argon2 hash string.
        password: Candidate plaintext password.

    Returns:
        bool: True if the password matches, otherwise False.
    """
    if not password_hash or not password:
        return False
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def generate_random_password(length: int = 16) -> str:
    """Generate a URL-safe random password for initial bootstrap seeding.

    Args:
        length: Approximate character length before URL-safe encoding truncation.

    Returns:
        str: Random password string.
    """
    return secrets.token_urlsafe(length)[: max(length, 12)]


class SecretCipher:
    """Symmetric Fernet cipher for API keys and webhook secrets persisted in SQLite."""

    def __init__(self, secret_key: str) -> None:
        """Initialize cipher from an arbitrary application secret string.

        Args:
            secret_key: Master application secret (`TRENDRADAR_SECRET_KEY`).

        Raises:
            ValueError: If `secret_key` is empty.
        """
        if not secret_key:
            raise ValueError("secret_key must not be empty")
        digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(digest)
        self._fernet = Fernet(fernet_key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a secret string; returns empty string when input is empty.

        Args:
            plaintext: Secret string to protect.

        Returns:
            str: URL-safe encrypted token, or empty string if `plaintext` is empty.
        """
        if not plaintext:
            return ""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a stored Fernet token; returns empty string when input is empty.

        Args:
            ciphertext: Encrypted token produced by `encrypt`.

        Returns:
            str: Decrypted plaintext secret.

        Raises:
            CipherError: If the token is invalid or encrypted under a different key.
        """
        if not ciphertext:
            return ""
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise CipherError("Failed to decrypt stored secret") from exc

    @staticmethod
    def mask_secret(value: str) -> str:
        """Return a masked representation safe to return in API responses.

        Args:
            value: Raw plaintext secret.

        Returns:
            str: Masked string hiding the secret body while indicating presence.
        """
        if not value:
            return ""
        if len(value) <= 6:
            return "*" * len(value)
        return f"{value[:3]}***{value[-3:]}"


class SessionManager:
    """Signed stateless session cookie encoder/verifier backed by `itsdangerous`."""

    def __init__(self, secret_key: str, max_age_sec: int = 604800) -> None:
        """Initialize the session serializer.

        Args:
            secret_key: Signing key (`TRENDRADAR_SECRET_KEY`).
            max_age_sec: Session lifetime in seconds.

        Raises:
            ValueError: If `secret_key` is empty or `max_age_sec` is not positive.
        """
        if not secret_key:
            raise ValueError("secret_key must not be empty")
        if max_age_sec <= 0:
            raise ValueError("max_age_sec must be positive")
        self._serializer = URLSafeTimedSerializer(secret_key, salt="trendradar-session-v1")
        self._max_age_sec = max_age_sec

    def create_token(self, user_id: int, username: str) -> str:
        """Issue a signed session token for an authenticated user.

        Args:
            user_id: Authenticated user ID.
            username: Authenticated username.

        Returns:
            str: Signed token string.
        """
        return self._serializer.dumps({"uid": user_id, "sub": username})

    def verify_token(self, token: str) -> Dict[str, object]:
        """Validate a session token and return its claims.

        Args:
            token: Cookie token value.

        Returns:
            Dict[str, object]: Decoded session payload (`uid`, `sub`).

        Raises:
            SessionError: If token is empty, expired, or fails signature validation.
        """
        if not token:
            raise SessionError("Missing session token")
        try:
            payload = self._serializer.loads(token, max_age=self._max_age_sec)
        except SignatureExpired as exc:
            raise SessionError("Session expired") from exc
        except BadSignature as exc:
            raise SessionError("Invalid session signature") from exc

        if not isinstance(payload, dict) or "uid" not in payload or "sub" not in payload:
            raise SessionError("Malformed session payload")
        return payload


class LoginRateLimiter:
    """Thread-safe sliding-window rate limiter keyed by client identifier."""

    def __init__(self, max_attempts: int = 10, window_sec: int = 300) -> None:
        """Initialize limiter thresholds.

        Args:
            max_attempts: Maximum failed attempts permitted within `window_sec`.
            window_sec: Sliding window length in seconds.
        """
        self._max_attempts = max_attempts
        self._window_sec = window_sec
        self._failures: Dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._failures.setdefault(key, deque())
        cutoff = now - self._window_sec
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        return bucket

    def is_allowed(self, key: str) -> bool:
        """Check whether a client key may attempt login.

        Args:
            key: Client IP or identifier.

        Returns:
            bool: True if attempt is within quota, False when rate-limited.
        """
        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now)
            return len(bucket) < self._max_attempts

    def record_failure(self, key: str) -> None:
        """Record a failed login attempt for the given client key.

        Args:
            key: Client IP or identifier.
        """
        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now)
            bucket.append(now)

    def reset(self, key: str) -> None:
        """Clear failure history after a successful login.

        Args:
            key: Client IP or identifier.
        """
        with self._lock:
            self._failures.pop(key, None)
