"""Settings management service with transparent secret encryption and API masking."""

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Tuple
import zoneinfo

from app.repositories.settings_repo import SettingsRepository
from app.security import SecretCipher

GLOBAL_SECTIONS = (
    "platforms",
    "rss",
    "domains",
    "schedule",
    "trends",
    "foreign_sources",
)
USER_SECTIONS = ("keywords", "webhooks")
ALLOWED_SECTIONS = (*GLOBAL_SECTIONS, *USER_SECTIONS)

_ENCRYPTED_PREFIX = "enc:"

_WEBHOOK_ALLOWED_FIELDS = frozenset(
    {
        "enabled",
        "feishu_webhook_url",
        "dingtalk_webhook_url",
        "wework_webhook_url",
        "wework_msg_type",
        "generic_webhook_url",
        "generic_webhook_payload_template",
    }
)

_SECTION_SECRET_FIELDS: Dict[str, Tuple[str, ...]] = {
    "webhooks": (
        "feishu_webhook_url",
        "dingtalk_webhook_url",
        "wework_webhook_url",
        "generic_webhook_url",
    ),
    "foreign_sources": (
        "reddit_client_secret",
        "youtube_api_key",
        "github_token",
    ),
}


class SettingsNotFoundError(Exception):
    """Raised when requesting an unknown or uninitialized settings section."""


class SettingsValidationError(Exception):
    """Raised when a settings update fails structural validation."""


def _is_masked_placeholder(value: str) -> bool:
    return bool(value) and (set(value) == {"*"} or "***" in value)


class SettingsService:
    """Service layer managing structured application settings and encrypted secrets."""

    def __init__(
        self,
        settings_repo: SettingsRepository,
        cipher: SecretCipher,
        timezone_name: str,
    ) -> None:
        """Initialize the settings service.

        Args:
            settings_repo: Settings persistence repository.
            cipher: Symmetric cipher protecting sensitive credentials.
            timezone_name: Configured timezone name.
        """
        self._repo = settings_repo
        self._cipher = cipher
        self._tz = zoneinfo.ZoneInfo(timezone_name)

    def _now_iso(self) -> str:
        return datetime.now(self._tz).isoformat(timespec="seconds")

    @staticmethod
    def _validate_section(section: str) -> None:
        if section not in ALLOWED_SECTIONS:
            raise SettingsNotFoundError(f"Unknown settings section: {section}")

    def _decrypt_value(self, raw_value: Any) -> str:
        text = str(raw_value or "")
        if text.startswith(_ENCRYPTED_PREFIX):
            return self._cipher.decrypt(text[len(_ENCRYPTED_PREFIX):])
        return text

    @staticmethod
    def _filter_section_fields(section: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if section == "webhooks":
            return {k: v for k, v in payload.items() if k in _WEBHOOK_ALLOWED_FIELDS}
        return deepcopy(payload)

    def _mask_payload(self, section: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        masked = self._filter_section_fields(section, payload)
        for field in _SECTION_SECRET_FIELDS.get(section, ()):
            if field in masked:
                plaintext = self._decrypt_value(masked[field])
                masked[field] = self._cipher.mask_secret(plaintext)
        return masked

    def _decrypt_payload(self, section: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        decrypted = self._filter_section_fields(section, payload)
        for field in _SECTION_SECRET_FIELDS.get(section, ()):
            if field in decrypted:
                decrypted[field] = self._decrypt_value(decrypted[field])
        return decrypted

    def _prepare_storage_payload(
        self,
        section: str,
        incoming: Dict[str, Any],
        existing: Dict[str, Any],
    ) -> Dict[str, Any]:
        prepared = self._filter_section_fields(section, incoming)
        for field in _SECTION_SECRET_FIELDS.get(section, ()):
            if field not in prepared:
                if field in existing:
                    prepared[field] = existing[field]
                continue
            candidate = prepared[field]
            if candidate is None or _is_masked_placeholder(str(candidate)):
                # Preserve existing encrypted secret when UI submits masked placeholder.
                prepared[field] = existing.get(field, "")
                continue
            text = str(candidate).strip()
            prepared[field] = f"{_ENCRYPTED_PREFIX}{self._cipher.encrypt(text)}" if text else ""
        return prepared

    def get_public_section(self, section: str) -> Tuple[Dict[str, Any], str]:
        """Return a settings section with sensitive credentials masked for API clients.

        Args:
            section: Target settings section name.

        Returns:
            Tuple[Dict[str, Any], str]: `(masked_payload, updated_at)`.

        Raises:
            SettingsNotFoundError: If section is unknown or missing from storage.
        """
        self._validate_section(section)
        row = self._repo.get_section(section)
        if row is None:
            raise SettingsNotFoundError(f"Settings section '{section}' is not initialized")
        payload, updated_at = row
        return self._mask_payload(section, payload), updated_at

    def get_internal_section(self, section: str) -> Dict[str, Any]:
        """Return a settings section with secrets decrypted for internal services.

        Args:
            section: Target settings section name.

        Returns:
            Dict[str, Any]: Plaintext settings dictionary (empty dict if missing).

        Raises:
            SettingsNotFoundError: If section name is invalid.
        """
        self._validate_section(section)
        row = self._repo.get_section(section)
        if row is None:
            return {}
        payload, _ = row
        return self._decrypt_payload(section, payload)

    def update_section(self, section: str, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """Validate, encrypt secrets, and persist updates to a settings section.

        Args:
            section: Target settings section name.
            payload: New configuration dictionary.

        Returns:
            Tuple[Dict[str, Any], str]: `(masked_payload, updated_at)`.

        Raises:
            SettingsNotFoundError: If section name is invalid.
            SettingsValidationError: If payload is malformed.
        """
        self._validate_section(section)
        if not isinstance(payload, dict):
            raise SettingsValidationError("Settings payload must be a JSON object")

        existing_row = self._repo.get_section(section)
        existing_payload = existing_row[0] if existing_row else {}
        stored_payload = self._prepare_storage_payload(section, payload, existing_payload)
        updated_at = self._repo.upsert_section(section, stored_payload, self._now_iso())
        return self._mask_payload(section, stored_payload), updated_at

    def _default_user_section(self, section: str, user_role: str) -> Tuple[Dict[str, Any], str]:
        if section == "keywords":
            global_row = self._repo.get_section("keywords")
            if global_row is not None:
                return deepcopy(global_row[0]), global_row[1]
            return {"raw_text": "", "include_rss": True}, ""

        if user_role == "admin":
            global_row = self._repo.get_section("webhooks")
            if global_row is not None:
                return self._filter_section_fields("webhooks", global_row[0]), global_row[1]

        return (
            {
                "enabled": False,
                "feishu_webhook_url": "",
                "dingtalk_webhook_url": "",
                "wework_webhook_url": "",
                "wework_msg_type": "markdown",
                "generic_webhook_url": "",
                "generic_webhook_payload_template": "",
            },
            "",
        )

    @staticmethod
    def _validate_user_section(section: str) -> None:
        if section not in USER_SECTIONS:
            raise SettingsNotFoundError(f"Unknown user settings section: {section}")

    def get_user_public_section(
        self,
        user_id: int,
        section: str,
        *,
        user_role: str = "user",
    ) -> Tuple[Dict[str, Any], str]:
        """Return a user-scoped settings section with sensitive credentials masked."""
        self._validate_user_section(section)
        row = self._repo.get_user_section(user_id, section)
        if row is None:
            payload, updated_at = self._default_user_section(section, user_role)
        else:
            payload, updated_at = row
        return self._mask_payload(section, payload), updated_at

    def get_user_internal_section(
        self,
        user_id: int,
        section: str,
        *,
        user_role: str = "user",
    ) -> Dict[str, Any]:
        """Return a user-scoped settings section with secrets decrypted for internal services."""
        self._validate_user_section(section)
        row = self._repo.get_user_section(user_id, section)
        if row is None:
            payload, _ = self._default_user_section(section, user_role)
        else:
            payload, _ = row
        return self._decrypt_payload(section, payload)

    def update_user_section(
        self,
        user_id: int,
        section: str,
        payload: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], str]:
        """Validate, encrypt secrets, and persist updates to a user-scoped section."""
        self._validate_user_section(section)
        if not isinstance(payload, dict):
            raise SettingsValidationError("Settings payload must be a JSON object")

        existing_row = self._repo.get_user_section(user_id, section)
        existing_payload = existing_row[0] if existing_row else {}
        stored_payload = self._prepare_storage_payload(section, payload, existing_payload)
        updated_at = self._repo.upsert_user_section(user_id, section, stored_payload, self._now_iso())
        return self._mask_payload(section, stored_payload), updated_at

    def list_active_user_webhooks(self) -> List[Tuple[int, Dict[str, Any]]]:
        """Return decrypted `(user_id, webhooks_cfg)` pairs for all active users with webhooks."""
        rows = self._repo.list_active_user_sections("webhooks")
        return [
            (uid, self._decrypt_payload("webhooks", payload))
            for uid, payload in rows
        ]
