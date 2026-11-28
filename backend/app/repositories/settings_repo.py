"""Key-value section persistence repository for `app_settings` and per-user preferences."""

import json
from typing import Any, Dict, List, Optional, Set, Tuple

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

    def get_user_section(self, user_id: int, section: str) -> Optional[Tuple[Dict[str, Any], str]]:
        """Read a user-scoped settings section if stored.

        Args:
            user_id: Target user ID.
            section: Section name (`keywords` or `webhooks`).

        Returns:
            Optional[Tuple[Dict[str, Any], str]]: `(payload_dict, updated_at)` or None.
        """
        with self._db.read_connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json, updated_at
                FROM user_settings
                WHERE user_id = ? AND section = ?
                """,
                (user_id, section),
            ).fetchone()
            if row is None:
                return None
            return json.loads(str(row["payload_json"])), str(row["updated_at"])

    def upsert_user_section(
        self,
        user_id: int,
        section: str,
        payload: Dict[str, Any],
        now_iso: str,
    ) -> str:
        """Insert or update a user-scoped settings section.

        Args:
            user_id: Target user ID.
            section: Section name.
            payload: JSON-serializable payload dictionary.
            now_iso: ISO-8601 update timestamp.

        Returns:
            str: Persisted `updated_at` timestamp.
        """
        encoded = json.dumps(payload, ensure_ascii=False)
        with self._db.write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO user_settings (user_id, section, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, section) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, section, encoded, now_iso),
            )
        return now_iso

    def list_active_user_sections(self, section: str) -> List[Tuple[int, Dict[str, Any]]]:
        """Return `(user_id, payload)` pairs for all active users having `section` configured."""
        with self._db.read_connection() as conn:
            rows = conn.execute(
                """
                SELECT us.user_id, us.payload_json
                FROM user_settings us
                JOIN users u ON u.id = us.user_id
                WHERE u.is_active = 1 AND us.section = ?
                ORDER BY us.user_id ASC
                """,
                (section,),
            ).fetchall()
            return [(int(r["user_id"]), json.loads(str(r["payload_json"]))) for r in rows]

    def get_delivered_keys(self, user_id: int) -> Set[Tuple[str, int]]:
        """Return previously delivered `(source_type, item_id)` tuples for a user."""
        with self._db.read_connection() as conn:
            rows = conn.execute(
                "SELECT source_type, item_id FROM user_webhook_deliveries WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            return {(str(r["source_type"]), int(r["item_id"])) for r in rows}

    def record_deliveries(
        self,
        user_id: int,
        keys: List[Tuple[str, int]],
        now_iso: str,
    ) -> None:
        """Persist delivered `(source_type, item_id)` markers idempotently."""
        if not keys:
            return
        with self._db.write_transaction() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO user_webhook_deliveries (
                    user_id, source_type, item_id, delivered_at
                )
                VALUES (?, ?, ?, ?)
                """,
                [(user_id, st, item_id, now_iso) for st, item_id in keys],
            )

    def prune_old_deliveries(self, cutoff_iso: str) -> None:
        """Delete delivery dedup records older than `cutoff_iso`."""
        with self._db.write_transaction() as conn:
            conn.execute(
                "DELETE FROM user_webhook_deliveries WHERE delivered_at < ?",
                (cutoff_iso,),
            )
