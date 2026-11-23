"""Invite code repository and atomic invite-backed registration transactions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional

from app.repositories.db import Database
from app.repositories.user_repo import UserRecord, row_to_user


class InviteInvalidError(Exception):
    """Raised when a registration invite code is missing, disabled, expired, or exhausted."""


class UsernameConflictError(Exception):
    """Raised when registering with a username that already exists."""


@dataclass(frozen=True)
class InviteCodeRecord:
    """Stored invite code entity with creator metadata."""

    id: int
    code: str
    note: str
    max_uses: int
    used_count: int
    expires_at: Optional[str]
    is_active: bool
    created_by: Optional[int]
    created_by_username: Optional[str]
    created_at: str
    updated_at: str


_INVITE_SELECT = """
    SELECT ic.*, u.username AS created_by_username
    FROM invite_codes ic
    LEFT JOIN users u ON ic.created_by = u.id
"""


def _row_to_invite(row) -> InviteCodeRecord:
    keys = row.keys()
    creator_name = row["created_by_username"] if "created_by_username" in keys else None
    return InviteCodeRecord(
        id=int(row["id"]),
        code=str(row["code"]),
        note=str(row["note"] or ""),
        max_uses=int(row["max_uses"]),
        used_count=int(row["used_count"]),
        expires_at=str(row["expires_at"]) if row["expires_at"] is not None else None,
        is_active=bool(row["is_active"]),
        created_by=int(row["created_by"]) if row["created_by"] is not None else None,
        created_by_username=str(creator_name) if creator_name is not None else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _is_expired(expires_at: Optional[str], now_iso: str) -> bool:
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) <= datetime.fromisoformat(now_iso)
    except ValueError:
        return expires_at <= now_iso


class InviteRepository:
    """Data access layer for `invite_codes` and atomic user registration."""

    def __init__(self, db: Database) -> None:
        """Bind repository to the database coordinator.

        Args:
            db: Shared `Database` instance.
        """
        self._db = db

    def list_all(self) -> List[InviteCodeRecord]:
        """List all invite codes ordered newest-first."""
        with self._db.read_connection() as conn:
            rows = conn.execute(f"{_INVITE_SELECT} ORDER BY ic.id DESC").fetchall()
            return [_row_to_invite(r) for r in rows]

    def get_by_id(self, code_id: int) -> Optional[InviteCodeRecord]:
        """Fetch an invite code record by primary key."""
        with self._db.read_connection() as conn:
            row = conn.execute(f"{_INVITE_SELECT} WHERE ic.id = ?", (code_id,)).fetchone()
            return _row_to_invite(row) if row else None

    def get_by_code(self, code: str) -> Optional[InviteCodeRecord]:
        """Fetch an invite code record by exact uppercase code string."""
        with self._db.read_connection() as conn:
            row = conn.execute(f"{_INVITE_SELECT} WHERE ic.code = ?", (code,)).fetchone()
            return _row_to_invite(row) if row else None

    def create(
        self,
        *,
        code: str,
        note: str,
        max_uses: int,
        expires_at: Optional[str],
        created_by: Optional[int],
        now_iso: str,
    ) -> InviteCodeRecord:
        """Insert a new invite code record and return the stored entity."""
        with self._db.write_transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO invite_codes (
                    code, note, max_uses, used_count, expires_at,
                    is_active, created_by, created_at, updated_at
                )
                VALUES (?, ?, ?, 0, ?, 1, ?, ?, ?)
                """,
                (code, note, max_uses, expires_at, created_by, now_iso, now_iso),
            )
            code_id = int(cur.lastrowid)
        created = self.get_by_id(code_id)
        if created is None:
            raise RuntimeError("Inserted invite code could not be read back")
        return created

    def update(
        self,
        code_id: int,
        *,
        note: Optional[str],
        max_uses: Optional[int],
        expires_at: Optional[str],
        clear_expires_at: bool,
        is_active: Optional[bool],
        now_iso: str,
    ) -> Optional[InviteCodeRecord]:
        """Patch mutable attributes of an existing invite code."""
        clauses: List[str] = []
        params: List[Any] = []
        if note is not None:
            clauses.append("note = ?")
            params.append(note)
        if max_uses is not None:
            clauses.append("max_uses = ?")
            params.append(max_uses)
        if clear_expires_at:
            clauses.append("expires_at = NULL")
        elif expires_at is not None:
            clauses.append("expires_at = ?")
            params.append(expires_at)
        if is_active is not None:
            clauses.append("is_active = ?")
            params.append(1 if is_active else 0)
        if not clauses:
            return self.get_by_id(code_id)

        clauses.append("updated_at = ?")
        params.append(now_iso)
        params.append(code_id)

        with self._db.write_transaction() as conn:
            conn.execute(f"UPDATE invite_codes SET {', '.join(clauses)} WHERE id = ?", params)
        return self.get_by_id(code_id)

    def delete(self, code_id: int) -> bool:
        """Delete an invite code row and return True when removed."""
        with self._db.write_transaction() as conn:
            cur = conn.execute("DELETE FROM invite_codes WHERE id = ?", (code_id,))
            return cur.rowcount > 0

    def consume_and_create_user(
        self,
        *,
        code: str,
        username: str,
        password_hash: str,
        now_iso: str,
    ) -> UserRecord:
        """Atomically validate invite quota/expiry, increment usage, and register user.

        Runs inside a single SQLite write transaction so concurrent sign-ups cannot
        oversell finite invite codes or waste quota on duplicate usernames.
        """
        with self._db.write_transaction() as conn:
            inv = conn.execute("SELECT * FROM invite_codes WHERE code = ?", (code,)).fetchone()
            if inv is None or not bool(inv["is_active"]):
                raise InviteInvalidError("邀请码无效或已停用")
            if _is_expired(inv["expires_at"], now_iso):
                raise InviteInvalidError("邀请码已过期")
            max_uses = int(inv["max_uses"])
            if max_uses > 0 and int(inv["used_count"]) >= max_uses:
                raise InviteInvalidError("邀请码已达到使用次数上限")

            dup = conn.execute(
                "SELECT id FROM users WHERE lower(username) = lower(?)",
                (username,),
            ).fetchone()
            if dup is not None:
                raise UsernameConflictError("该用户名已被占用")

            invite_id = int(inv["id"])
            upd = conn.execute(
                """
                UPDATE invite_codes
                SET used_count = used_count + 1, updated_at = ?
                WHERE id = ?
                  AND is_active = 1
                  AND (max_uses = 0 OR used_count < max_uses)
                  AND (expires_at IS NULL OR expires_at > ?)
                """,
                (now_iso, invite_id, now_iso),
            )
            if upd.rowcount != 1:
                raise InviteInvalidError("邀请码无效、已过期或已达到使用上限")

            cur = conn.execute(
                """
                INSERT INTO users (
                    username, password_hash, role, is_active,
                    invited_by_code_id, last_login_at, created_at, updated_at
                )
                VALUES (?, ?, 'user', 1, ?, ?, ?, ?)
                """,
                (username, password_hash, invite_id, now_iso, now_iso, now_iso),
            )
            user_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise RuntimeError("Inserted user could not be read back")
            return row_to_user(row)
