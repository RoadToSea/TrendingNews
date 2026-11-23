"""Persistence repository for generated and archived Markdown reports."""

import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from app.repositories.db import Database


def _parse_int_list(raw: str) -> List[int]:
    try:
        parsed = json.loads(raw)
        return [int(x) for x in parsed] if isinstance(parsed, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


class ReportRepository:
    """Data access layer for the `reports` table."""

    def __init__(self, db: Database) -> None:
        """Bind repository to the database coordinator.

        Args:
            db: Shared `Database` instance.
        """
        self._db = db

    def create(
        self,
        *,
        report_type: str,
        report_date: str,
        domain: str,
        title: str,
        content_md: str,
        related_event_ids: List[int],
        related_news_ids: List[int],
        source_session_id: Optional[int],
        provider_slot_id: Optional[int],
        now_iso: str,
    ) -> Dict[str, Any]:
        """Insert a report record and return the stored DTO-ready dictionary.

        Args:
            report_type: Report category (`daily_overall`, `domain_trend`, `item_analysis`, `chat_generated`).
            report_date: Logical report date (`YYYY-MM-DD`).
            domain: Optional domain scope.
            title: Report title.
            content_md: Markdown body.
            related_event_ids: Referenced hot event IDs.
            related_news_ids: Referenced news item IDs.
            source_session_id: Originating chat session ID if exported from chat.
            provider_slot_id: AI provider slot ID used to generate the report.
            now_iso: ISO-8601 timestamp.

        Returns:
            Dict[str, Any]: Inserted report record.
        """
        with self._db.write_transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reports (
                    report_type, report_date, domain, title, content_md,
                    related_event_ids_json, related_news_ids_json,
                    source_session_id, provider_slot_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_type,
                    report_date,
                    domain,
                    title,
                    content_md,
                    json.dumps(related_event_ids),
                    json.dumps(related_news_ids),
                    source_session_id,
                    provider_slot_id,
                    now_iso,
                    now_iso,
                ),
            )
            report_id = int(cursor.lastrowid)
        created = self.get_by_id(report_id)
        if created is None:
            raise RuntimeError("Inserted report could not be read back")
        return created

    def get_by_id(self, report_id: int) -> Optional[Dict[str, Any]]:
        """Fetch one report by ID with its generating provider name.

        Args:
            report_id: Report primary key.

        Returns:
            Optional[Dict[str, Any]]: Report dictionary or None.
        """
        sql = """
            SELECT r.*, p.name AS provider_name
            FROM reports r
            LEFT JOIN ai_providers p ON p.id = r.provider_slot_id
            WHERE r.id = ?
        """
        with self._db.read_connection() as conn:
            row = conn.execute(sql, (report_id,)).fetchone()
            return self._row_to_dict(row) if row else None

    def list_reports(
        self,
        *,
        report_type: Optional[str] = None,
        domain: Optional[str] = None,
        report_date: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List archived reports with optional filters and pagination.

        Args:
            report_type: Optional filter on `report_type`.
            domain: Optional domain filter.
            report_date: Optional `YYYY-MM-DD` date filter.
            page: 1-based page number.
            page_size: Page size limit.

        Returns:
            Tuple[List[Dict[str, Any]], int]: `(items, total_count)`.
        """
        clauses = ["1 = 1"]
        params: List[Any] = []
        if report_type:
            clauses.append("r.report_type = ?")
            params.append(report_type)
        if domain:
            clauses.append("r.domain = ?")
            params.append(domain)
        if report_date:
            clauses.append("r.report_date = ?")
            params.append(report_date)

        where_sql = " AND ".join(clauses)
        offset = max(0, (page - 1) * page_size)
        with self._db.read_connection() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM reports r WHERE {where_sql}",
                params,
            ).fetchone()
            total = int(total_row["cnt"]) if total_row else 0
            rows = conn.execute(
                f"""
                SELECT r.*, p.name AS provider_name
                FROM reports r
                LEFT JOIN ai_providers p ON p.id = r.provider_slot_id
                WHERE {where_sql}
                ORDER BY r.report_date DESC, r.id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
            return [self._row_to_dict(row) for row in rows], total

    def delete(self, report_id: int) -> bool:
        """Delete a report record by ID.

        Args:
            report_id: Target report ID.

        Returns:
            bool: True if a row was removed.
        """
        with self._db.write_transaction() as conn:
            cur = conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
            return int(cur.rowcount or 0) > 0

    def find_daily_report_map(self, dates: List[str]) -> Dict[str, int]:
        """Map each date string to its latest `daily_overall` report ID if present.

        Args:
            dates: List of `YYYY-MM-DD` dates.

        Returns:
            Dict[str, int]: Mapping from date string to report ID.
        """
        if not dates:
            return {}
        placeholders = ",".join("?" for _ in dates)
        sql = f"""
            SELECT report_date, MAX(id) AS latest_id
            FROM reports
            WHERE report_type = 'daily_overall' AND report_date IN ({placeholders})
            GROUP BY report_date
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, list(dates)).fetchall()
            return {str(r["report_date"]): int(r["latest_id"]) for r in rows}

    def find_event_report_map(self, event_ids: List[int]) -> Dict[int, int]:
        """Map event IDs to the latest report referencing each event.

        Args:
            event_ids: List of `hot_events.id` values.

        Returns:
            Dict[int, int]: Mapping from `event_id` to most recent `report_id`.
        """
        if not event_ids:
            return {}
        target = set(event_ids)
        result: Dict[int, int] = {}
        with self._db.read_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, related_event_ids_json
                FROM reports
                WHERE related_event_ids_json != '[]'
                ORDER BY id DESC
                LIMIT 500
                """
            ).fetchall()
        for row in rows:
            rep_id = int(row["id"])
            for eid in _parse_int_list(str(row["related_event_ids_json"] or "[]")):
                if eid in target and eid not in result:
                    result[eid] = rep_id
        return result

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "report_type": str(row["report_type"]),
            "report_date": str(row["report_date"]),
            "domain": str(row["domain"] or ""),
            "title": str(row["title"]),
            "content_md": str(row["content_md"]),
            "related_event_ids": _parse_int_list(str(row["related_event_ids_json"] or "[]")),
            "related_news_ids": _parse_int_list(str(row["related_news_ids_json"] or "[]")),
            "source_session_id": int(row["source_session_id"]) if row["source_session_id"] is not None else None,
            "provider_name": str(row["provider_name"]) if row["provider_name"] is not None else None,
            "created_at": str(row["created_at"]),
        }