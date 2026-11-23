"""Persistence repository for AI provider slots, prompt templates, and chat histories."""

import json
import sqlite3
from typing import Any, Dict, List, Optional

from app.repositories.db import Database


def _loads_json(raw: str, default: Any) -> Any:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, json.JSONDecodeError):
        return default


class ChatRepository:
    """Data access layer for `ai_providers`, `prompt_templates`, `chat_sessions`, and `chat_messages`."""

    def __init__(self, db: Database) -> None:
        """Bind repository to the database coordinator.

        Args:
            db: Shared `Database` instance.
        """
        self._db = db

    def ensure_default_prompt_template(self, name: str, content: str, now_iso: str) -> None:
        """Seed the default chat system prompt template when `prompt_templates` is empty.

        Args:
            name: Default template name.
            content: Default system prompt content.
            now_iso: ISO-8601 timestamp.
        """
        with self._db.write_transaction() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM prompt_templates").fetchone()
            if row and int(row["cnt"]) > 0:
                return
            conn.execute(
                """
                INSERT INTO prompt_templates (
                    name, category, content, is_default, is_enabled, created_at, updated_at
                )
                VALUES (?, 'chat_system', ?, 1, 1, ?, ?)
                """,
                (name, content, now_iso, now_iso),
            )

    def ensure_default_antigravity_provider(self, now_iso: str) -> None:
        """Seed a default Antigravity CLI slot when `ai_providers` is completely empty.

        Args:
            now_iso: ISO-8601 timestamp.
        """
        with self._db.write_transaction() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM ai_providers").fetchone()
            if row and int(row["cnt"]) > 0:
                return
            conn.execute(
                """
                INSERT INTO ai_providers (
                    name, protocol, base_url, api_key_encrypted, model,
                    extra_params_json, role_bindings_json, is_enabled, created_at, updated_at
                )
                VALUES (?, 'antigravity', '', '', 'gemini-3.8-flash-medium', '{}', ?, 1, ?, ?)
                """,
                ("Antigravity 主力", json.dumps(["chat_default", "summary_report", "event_cluster"]), now_iso, now_iso),
            )

    def list_ai_providers(self) -> List[Dict[str, Any]]:
        """List all configured AI provider slots ordered by ID.

        Returns:
            List[Dict[str, Any]]: Provider slot records with parsed JSON fields.
        """
        with self._db.read_connection() as conn:
            rows = conn.execute("SELECT * FROM ai_providers ORDER BY id ASC").fetchall()
            return [self._provider_row_to_dict(r) for r in rows]

    def get_ai_provider(self, slot_id: int) -> Optional[Dict[str, Any]]:
        """Fetch an AI provider slot by primary key.

        Args:
            slot_id: Slot primary key.

        Returns:
            Optional[Dict[str, Any]]: Provider slot dict or None.
        """
        with self._db.read_connection() as conn:
            row = conn.execute("SELECT * FROM ai_providers WHERE id = ?", (slot_id,)).fetchone()
            return self._provider_row_to_dict(row) if row else None

    def get_ai_provider_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Fetch an AI provider slot by unique name.

        Args:
            name: Provider slot name.

        Returns:
            Optional[Dict[str, Any]]: Provider slot dict or None.
        """
        with self._db.read_connection() as conn:
            row = conn.execute("SELECT * FROM ai_providers WHERE name = ?", (name,)).fetchone()
            return self._provider_row_to_dict(row) if row else None

    def create_ai_provider(
        self,
        *,
        name: str,
        protocol: str,
        base_url: str,
        api_key_encrypted: str,
        model: str,
        extra_params: Dict[str, Any],
        role_bindings: List[str],
        is_enabled: bool,
        now_iso: str,
    ) -> Dict[str, Any]:
        """Insert a new AI provider slot and return the stored record.

        Args:
            name: Unique slot display name.
            protocol: `'openai'`, `'anthropic'`, or `'antigravity'`.
            base_url: Optional endpoint base URL.
            api_key_encrypted: Fernet-encrypted API key token or empty string.
            model: Model identifier string.
            extra_params: Arbitrary model parameter overrides.
            role_bindings: Assigned functional roles.
            is_enabled: Whether the slot is active.
            now_iso: ISO-8601 timestamp.

        Returns:
            Dict[str, Any]: Stored provider record.
        """
        with self._db.write_transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ai_providers (
                    name, protocol, base_url, api_key_encrypted, model,
                    extra_params_json, role_bindings_json, is_enabled, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    protocol,
                    base_url,
                    api_key_encrypted,
                    model,
                    json.dumps(extra_params, ensure_ascii=False),
                    json.dumps(role_bindings),
                    1 if is_enabled else 0,
                    now_iso,
                    now_iso,
                ),
            )
            slot_id = int(cursor.lastrowid)
        self.strip_role_from_other_providers(role_bindings, exclude_id=slot_id, now_iso=now_iso)
        created = self.get_ai_provider(slot_id)
        if created is None:
            raise RuntimeError("Created AI provider could not be read back")
        return created

    def update_ai_provider(
        self,
        slot_id: int,
        *,
        name: str,
        protocol: str,
        base_url: str,
        api_key_encrypted: str,
        model: str,
        extra_params: Dict[str, Any],
        role_bindings: List[str],
        is_enabled: bool,
        now_iso: str,
    ) -> Optional[Dict[str, Any]]:
        """Update an AI provider slot and enforce exclusive role bindings across slots.

        Args:
            slot_id: Target slot ID.
            name: Slot name.
            protocol: Protocol name.
            base_url: Endpoint base URL.
            api_key_encrypted: Encrypted API key string.
            model: Model name.
            extra_params: Extra parameters dict.
            role_bindings: Assigned role bindings.
            is_enabled: Enabled state.
            now_iso: ISO-8601 update timestamp.

        Returns:
            Optional[Dict[str, Any]]: Updated provider record or None if missing.
        """
        with self._db.write_transaction() as conn:
            cur = conn.execute(
                """
                UPDATE ai_providers
                SET name = ?, protocol = ?, base_url = ?, api_key_encrypted = ?, model = ?,
                    extra_params_json = ?, role_bindings_json = ?, is_enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    name,
                    protocol,
                    base_url,
                    api_key_encrypted,
                    model,
                    json.dumps(extra_params, ensure_ascii=False),
                    json.dumps(role_bindings),
                    1 if is_enabled else 0,
                    now_iso,
                    slot_id,
                ),
            )
            if int(cur.rowcount or 0) == 0:
                return None
        self.strip_role_from_other_providers(role_bindings, exclude_id=slot_id, now_iso=now_iso)
        return self.get_ai_provider(slot_id)

    def strip_role_from_other_providers(
        self,
        roles: List[str],
        exclude_id: int,
        now_iso: str,
    ) -> None:
        """Remove `roles` from all other slots so each role binds to at most one slot.

        Args:
            roles: Role keys now claimed by `exclude_id`.
            exclude_id: Slot ID retaining the roles.
            now_iso: ISO-8601 timestamp.
        """
        if not roles:
            return
        role_set = set(roles)
        with self._db.write_transaction() as conn:
            rows = conn.execute(
                "SELECT id, role_bindings_json FROM ai_providers WHERE id != ?",
                (exclude_id,),
            ).fetchall()
            for row in rows:
                current = _loads_json(str(row["role_bindings_json"] or "[]"), [])
                filtered = [r for r in current if r not in role_set]
                if filtered != current:
                    conn.execute(
                        "UPDATE ai_providers SET role_bindings_json = ?, updated_at = ? WHERE id = ?",
                        (json.dumps(filtered), now_iso, int(row["id"])),
                    )

    def delete_ai_provider(self, slot_id: int) -> bool:
        """Delete an AI provider slot by primary key.

        Args:
            slot_id: Slot primary key.

        Returns:
            bool: True if a row was deleted.
        """
        with self._db.write_transaction() as conn:
            cur = conn.execute("DELETE FROM ai_providers WHERE id = ?", (slot_id,))
            return int(cur.rowcount or 0) > 0

    def list_prompt_templates(self) -> List[Dict[str, Any]]:
        """List all configured prompt templates ordered by default flag then ID.

        Returns:
            List[Dict[str, Any]]: Template records.
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM prompt_templates ORDER BY is_default DESC, id ASC"
            ).fetchall()
            return [self._prompt_row_to_dict(r) for r in rows]

    def get_prompt_template(self, template_id: int) -> Optional[Dict[str, Any]]:
        """Fetch one prompt template by primary key.

        Args:
            template_id: Template primary key.

        Returns:
            Optional[Dict[str, Any]]: Template dict or None.
        """
        with self._db.read_connection() as conn:
            row = conn.execute("SELECT * FROM prompt_templates WHERE id = ?", (template_id,)).fetchone()
            return self._prompt_row_to_dict(row) if row else None

    def get_default_prompt_template(self) -> Optional[Dict[str, Any]]:
        """Fetch the active default enabled prompt template if one exists.

        Returns:
            Optional[Dict[str, Any]]: Default template record or first enabled template.
        """
        with self._db.read_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM prompt_templates
                WHERE is_enabled = 1
                ORDER BY is_default DESC, id ASC
                LIMIT 1
                """
            ).fetchone()
            return self._prompt_row_to_dict(row) if row else None

    def create_prompt_template(
        self,
        *,
        name: str,
        category: str,
        content: str,
        is_default: bool,
        is_enabled: bool,
        now_iso: str,
    ) -> Dict[str, Any]:
        """Insert a new prompt template, keeping `is_default` unique across templates.

        Args:
            name: Unique template name.
            category: Category tag (`chat_system`).
            content: System prompt body.
            is_default: Whether this becomes the default template.
            is_enabled: Active state.
            now_iso: ISO-8601 timestamp.

        Returns:
            Dict[str, Any]: Created template record.
        """
        with self._db.write_transaction() as conn:
            if is_default:
                conn.execute("UPDATE prompt_templates SET is_default = 0")
            cursor = conn.execute(
                """
                INSERT INTO prompt_templates (
                    name, category, content, is_default, is_enabled, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, category, content, 1 if is_default else 0, 1 if is_enabled else 0, now_iso, now_iso),
            )
            tpl_id = int(cursor.lastrowid)
        created = self.get_prompt_template(tpl_id)
        if created is None:
            raise RuntimeError("Created prompt template could not be read back")
        return created

    def update_prompt_template(
        self,
        template_id: int,
        *,
        name: str,
        content: str,
        is_default: bool,
        is_enabled: bool,
        now_iso: str,
    ) -> Optional[Dict[str, Any]]:
        """Update an existing prompt template, keeping at most one default row.

        Args:
            template_id: Target template ID.
            name: Template name.
            content: Prompt content.
            is_default: Whether this template is default.
            is_enabled: Enabled state.
            now_iso: ISO-8601 update timestamp.

        Returns:
            Optional[Dict[str, Any]]: Updated template dict or None if missing.
        """
        with self._db.write_transaction() as conn:
            if is_default:
                conn.execute("UPDATE prompt_templates SET is_default = 0 WHERE id != ?", (template_id,))
            cur = conn.execute(
                """
                UPDATE prompt_templates
                SET name = ?, content = ?, is_default = ?, is_enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, content, 1 if is_default else 0, 1 if is_enabled else 0, now_iso, template_id),
            )
            if int(cur.rowcount or 0) == 0:
                return None
        return self.get_prompt_template(template_id)

    def delete_prompt_template(self, template_id: int) -> bool:
        """Delete a prompt template by primary key.

        Args:
            template_id: Template primary key.

        Returns:
            bool: True if deleted.
        """
        with self._db.write_transaction() as conn:
            cur = conn.execute("DELETE FROM prompt_templates WHERE id = ?", (template_id,))
            return int(cur.rowcount or 0) > 0

    def list_sessions(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """List chat sessions owned by `user_id` ordered by recent activity.

        Args:
            user_id: Owner user ID.
            limit: Maximum number of sessions returned.

        Returns:
            List[Dict[str, Any]]: Session dictionaries.
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM chat_sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a chat session by primary key.

        Args:
            session_id: Chat session ID.

        Returns:
            Optional[Dict[str, Any]]: Session record or None.
        """
        with self._db.read_connection() as conn:
            row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(row) if row else None

    def create_session(
        self,
        *,
        user_id: int,
        title: str,
        provider_slot_id: Optional[int],
        prompt_template_id: Optional[int],
        now_iso: str,
    ) -> Dict[str, Any]:
        """Insert a new chat session and return its record.

        Args:
            user_id: Owner user ID.
            title: Initial session title.
            provider_slot_id: Optional pinned AI provider slot ID.
            prompt_template_id: Optional pinned system prompt template ID.
            now_iso: ISO-8601 creation timestamp.

        Returns:
            Dict[str, Any]: Stored session dict.
        """
        with self._db.write_transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO chat_sessions (
                    user_id, title, provider_slot_id, external_conversation_id,
                    prompt_template_id, created_at, updated_at
                )
                VALUES (?, ?, ?, '', ?, ?, ?)
                """,
                (user_id, title, provider_slot_id, prompt_template_id, now_iso, now_iso),
            )
            session_id = int(cursor.lastrowid)
        created = self.get_session(session_id)
        if created is None:
            raise RuntimeError("Created chat session could not be read back")
        return created

    def update_session_state(
        self,
        session_id: int,
        *,
        title: Optional[str] = None,
        provider_slot_id: Optional[int] = None,
        external_conversation_id: Optional[str] = None,
        prompt_template_id: Optional[int] = None,
        now_iso: str,
    ) -> None:
        """Update mutable session metadata fields after a chat turn.

        Args:
            session_id: Target session ID.
            title: Optional new session title.
            provider_slot_id: Optional slot ID override.
            external_conversation_id: Optional external ID (e.g., `agy` conversation_id).
            prompt_template_id: Optional prompt template ID override.
            now_iso: ISO-8601 update timestamp.
        """
        fields = ["updated_at = ?"]
        params: List[Any] = [now_iso]
        if title is not None:
            fields.append("title = ?")
            params.append(title)
        if provider_slot_id is not None:
            fields.append("provider_slot_id = ?")
            params.append(provider_slot_id)
        if external_conversation_id is not None:
            fields.append("external_conversation_id = ?")
            params.append(external_conversation_id)
        if prompt_template_id is not None:
            fields.append("prompt_template_id = ?")
            params.append(prompt_template_id)
        params.append(session_id)

        with self._db.write_transaction() as conn:
            conn.execute(f"UPDATE chat_sessions SET {', '.join(fields)} WHERE id = ?", params)

    def delete_session(self, session_id: int, user_id: int) -> bool:
        """Delete a user's chat session (cascade-deletes its messages).

        Args:
            session_id: Session ID.
            user_id: Owner user ID check.

        Returns:
            bool: True if a session was deleted.
        """
        with self._db.write_transaction() as conn:
            cur = conn.execute(
                "DELETE FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            )
            return int(cur.rowcount or 0) > 0

    def add_message(
        self,
        *,
        session_id: int,
        role: str,
        content: str,
        context_items: List[Dict[str, Any]],
        usage: Dict[str, Any],
        now_iso: str,
    ) -> Dict[str, Any]:
        """Append a message to `chat_messages` and update the session timestamp.

        Args:
            session_id: Parent session ID.
            role: `'system'`, `'user'`, or `'assistant'`.
            content: Message body text/Markdown.
            context_items: Structured context chips attached to this message.
            usage: Token/cost usage metadata dict.
            now_iso: ISO-8601 timestamp.

        Returns:
            Dict[str, Any]: Inserted message record.
        """
        with self._db.write_transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO chat_messages (
                    session_id, role, content, context_items_json, usage_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content,
                    json.dumps(context_items, ensure_ascii=False),
                    json.dumps(usage, ensure_ascii=False),
                    now_iso,
                ),
            )
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
                (now_iso, session_id),
            )
            msg_id = int(cursor.lastrowid)
        with self._db.read_connection() as conn:
            row = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
            if row is None:
                raise RuntimeError("Inserted chat message could not be read back")
            return self._message_row_to_dict(row)

    def list_messages(self, session_id: int) -> List[Dict[str, Any]]:
        """List all messages in a chat session ordered chronologically.

        Args:
            session_id: Target session ID.

        Returns:
            List[Dict[str, Any]]: Message records.
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
            return [self._message_row_to_dict(r) for r in rows]

    def list_messages_by_ids(self, session_id: int, message_ids: List[int]) -> List[Dict[str, Any]]:
        """List selected messages belonging to a session ordered by ID.

        Args:
            session_id: Parent session ID.
            message_ids: Message IDs to include.

        Returns:
            List[Dict[str, Any]]: Filtered message records.
        """
        if not message_ids:
            return []
        placeholders = ",".join("?" for _ in message_ids)
        with self._db.read_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM chat_messages
                WHERE session_id = ? AND id IN ({placeholders})
                ORDER BY id ASC
                """,
                [session_id, *message_ids],
            ).fetchall()
            return [self._message_row_to_dict(r) for r in rows]

    @staticmethod
    def _provider_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "protocol": str(row["protocol"]),
            "base_url": str(row["base_url"] or ""),
            "api_key_encrypted": str(row["api_key_encrypted"] or ""),
            "model": str(row["model"]),
            "extra_params": _loads_json(str(row["extra_params_json"] or "{}"), {}),
            "role_bindings": _loads_json(str(row["role_bindings_json"] or "[]"), []),
            "is_enabled": bool(row["is_enabled"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _prompt_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "category": str(row["category"]),
            "content": str(row["content"]),
            "is_default": bool(row["is_default"]),
            "is_enabled": bool(row["is_enabled"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _message_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "session_id": int(row["session_id"]),
            "role": str(row["role"]),
            "content": str(row["content"]),
            "context_items": _loads_json(str(row["context_items_json"] or "[]"), []),
            "usage": _loads_json(str(row["usage_json"] or "{}"), {}),
            "created_at": str(row["created_at"]),
        }