"""Key-value section persistence repository for `app_settings`."""

import json
from typing import Any, Dict, Optional, Tuple

from app.repositories.db import Database


class SettingsRepository:
    """Data access layer for structured JSON payloads in `app_settings`."""

    def __init__(self, db: Database) -> None:
        """Bind repository to the database coordinator.

        Args:
            db: Shared `Database` instance.
        """
        self._db = db

    def get_section(self, section: str) -> Optional[Tuple[Dict[str, Any], str]]:
        """Read one settings section and its last updated timestamp.

        Args:
            section: Settings section name.

        Returns:
            Optional[Tuple[Dict[str, Any], str]]: `(payload_dict, updated_at)` or None.
        """
        with self._db.read_connection() as conn:
            row = conn.execute(
                "SELECT payload_json, updated_at FROM app_settings WHERE section = ?",
                (section,),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(str(row["payload_json"]))
            return payload, str(row["updated_at"])

    def upsert_section(self, section: str, payload: Dict[str, Any], now_iso: str) -> str:
        """Insert or replace one settings section payload.

        Args:
            section: Settings section name.
            payload: JSON-serializable configuration dictionary.
            now_iso: ISO-8601 update timestamp.

        Returns:
            str: Persisted `updated_at` timestamp.
        """
        encoded = json.dumps(payload, ensure_ascii=False)
        with self._db.write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (section, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(section) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (section, encoded, now_iso),
            )
        return now_iso

    def list_sections(self) -> Dict[str, Dict[str, Any]]:
        """Return all stored configuration sections keyed by section name.

        Returns:
            Dict[str, Dict[str, Any]]: Mapping of section name to decoded JSON dictionary.
        """
        with self._db.read_connection() as conn:
            rows = conn.execute("SELECT section, payload_json FROM app_settings").fetchall()
            return {str(r["section"]): json.loads(str(r["payload_json"])) for r in rows}

    def ensure_defaults(self, defaults: Dict[str, Dict[str, Any]], now_iso: str) -> None:
        """Seed missing settings sections without overwriting user edits.

        Args:
            defaults: Mapping of section name to default payload dict.
            now_iso: ISO-8601 timestamp recorded for newly created rows.
        """
        with self._db.write_transaction() as conn:
            for section, payload in defaults.items():
                encoded = json.dumps(payload, ensure_ascii=False)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO app_settings (section, payload_json, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (section, encoded, now_iso),
                )
