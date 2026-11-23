"""User persistence repository."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.repositories.db import Database


@dataclass(frozen=True)
class UserRecord:
    """Stored user entity."""

    id: int
    username: str
    password_hash: str
    is_active: bool
    last_login_at: Optional[str]
    created_at: str
    updated_at: str
    role: str = "user"
    invited_by_code_id: Optional[int] = None


def row_to_user(row) -> UserRecord:
    """Map a SQLite row from `users` into an immutable `UserRecord`."""
    keys = row.keys()
    raw_role = str(row["role"]) if "role" in keys and row["role"] else "user"
    invited_id = (
        int(row["invited_by_code_id"])
        if "invited_by_code_id" in keys and row["invited_by_code_id"] is not None
        else None
    )
    return UserRecord(
        id=int(row["id"]),
        username=str(row["username"]),
        password_hash=str(row["password_hash"]),
        is_active=bool(row["is_active"]),
        last_login_at=row["last_login_at"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        role=raw_role,
        invited_by_code_id=invited_id,
    )


class UserRepository:
    """Data access operations for the `users` table."""

    def __init__(self, db: Database) -> None:
        """Bind repository to the database coordinator.

        Args:
            db: Shared `Database` instance.
        """
        self._db = db

    def count(self) -> int:
        """Return total number of registered users."""
        with self._db.read_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
            return int(row["cnt"]) if row else 0

    def count_active_admins(self) -> int:
        """Return count of active accounts holding the `admin` role."""
        with self._db.read_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()
            return int(row["cnt"]) if row else 0

    def get_by_username(self, username: str) -> Optional[UserRecord]:
        """Look up a user by exact username."""
        with self._db.read_connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            return row_to_user(row) if row else None

    def get_by_id(self, user_id: int) -> Optional[UserRecord]:
        """Look up a user by primary key."""
        with self._db.read_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return row_to_user(row) if row else None

    def list_all_with_invite(self) -> List[Dict[str, Any]]:
        """List all registered accounts joined with their originating invite code."""
        sql = """
            SELECT
                u.id,
                u.username,
                u.role,
                u.is_active,
                u.invited_by_code_id,
                ic.code AS invited_by_code,
                u.last_login_at,
                u.created_at,
                u.updated_at
            FROM users u
            LEFT JOIN invite_codes ic ON ic.id = u.invited_by_code_id
            ORDER BY u.id ASC
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]

    def create(
        self,
        username: str,
        password_hash: str,
        now_iso: str,
        *,
        role: str = "user",
        invited_by_code_id: Optional[int] = None,
    ) -> UserRecord:
        """Insert a new active user record.

        Args:
            username: Unique username.
            password_hash: Argon2 password hash.
            now_iso: ISO-8601 creation timestamp.
            role: Account role (`admin` or `user`).
            invited_by_code_id: Optional originating invite code row ID.

        Returns:
            UserRecord: Newly created user entity.
        """
        with self._db.write_transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (
                    username, password_hash, role, is_active,
                    invited_by_code_id, created_at, updated_at
                )
                VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (username, password_hash, role, invited_by_code_id, now_iso, now_iso),
            )
            user_id = int(cursor.lastrowid)
        created = self.get_by_id(user_id)
        if created is None:
            raise RuntimeError("Inserted user could not be read back")
        return created

    def update_last_login(self, user_id: int, now_iso: str) -> None:
        """Update `last_login_at` after successful authentication."""
        with self._db.write_transaction() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (now_iso, now_iso, user_id),
            )

    def update_password_hash(self, user_id: int, password_hash: str, now_iso: str) -> None:
        """Persist a rotated password hash for an existing user."""
        with self._db.write_transaction() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (password_hash, now_iso, user_id),
            )

    def update_user_flags(
        self,
        user_id: int,
        *,
        is_active: Optional[bool],
        role: Optional[str],
        now_iso: str,
    ) -> Optional[UserRecord]:
        """Update account active state and/or role cleanly and return updated record."""
        clauses: List[str] = []
        params: List[Any] = []
        if is_active is not None:
            clauses.append("is_active = ?")
            params.append(1 if is_active else 0)
        if role is not None:
            clauses.append("role = ?")
            params.append(role)
        if not clauses:
            return self.get_by_id(user_id)

        clauses.append("updated_at = ?")
        params.append(now_iso)
        params.append(user_id)

        with self._db.write_transaction() as conn:
            conn.execute(f"UPDATE users SET {', '.join(clauses)} WHERE id = ?", params)
        return self.get_by_id(user_id)
