"""Repository for hot events, event-news links, and daily trend metrics."""

import json
import sqlite3
from typing import Any, Dict, List, Optional

from app.repositories.db import Database


def _parse_json_dict(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


class EventRepository:
    """Data access layer for `hot_events`, `event_news_links`, and `event_daily_metrics`."""

    def __init__(self, db: Database) -> None:
        """Bind repository to the database coordinator.

        Args:
            db: Shared `Database` instance.
        """
        self._db = db

    def list_recent_events(self, since_date: str) -> List[Dict[str, Any]]:
        """Return hot events observed on or after `since_date`.

        Args:
            since_date: Inclusive `YYYY-MM-DD` date lower bound.

        Returns:
            List[Dict[str, Any]]: Event rows ordered by `last_seen_date` descending.
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM hot_events
                WHERE last_seen_date >= ?
                ORDER BY last_seen_date DESC, id DESC
                """,
                (since_date,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_unlinked_news_items(self, since_iso: str, limit: int = 60) -> List[Dict[str, Any]]:
        """Return recent hotlist/API items not yet attached to any hot event cluster.

        Args:
            since_iso: Lower bound on `last_seen_at`.
            limit: Maximum number of items returned for one incremental batch.

        Returns:
            List[Dict[str, Any]]: Unlinked item dicts sorted by importance/recency.
        """
        sql = """
            SELECT n.*
            FROM news_items n
            LEFT JOIN event_news_links enl
                ON enl.source_type = 'hotlist' AND enl.item_id = n.id
            WHERE enl.id IS NULL AND n.last_seen_at >= ?
            ORDER BY substr(n.last_seen_at, 1, 10) DESC, n.velocity DESC, n.latest_rank ASC
            LIMIT ?
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, (since_iso, limit)).fetchall()
            return [dict(r) for r in rows]

    def create_event(
        self,
        *,
        canonical_title: str,
        domain: str,
        summary: str,
        seen_date: str,
        now_iso: str,
    ) -> int:
        """Insert a new hot event cluster and return its ID.

        Args:
            canonical_title: Standardized Chinese event title.
            domain: Domain category.
            summary: Concise event summary.
            seen_date: Initial `YYYY-MM-DD` date.
            now_iso: ISO-8601 timestamp.

        Returns:
            int: Newly created event ID.
        """
        with self._db.write_transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO hot_events (
                    canonical_title, domain, summary,
                    first_seen_date, last_seen_date, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (canonical_title, domain, summary, seen_date, seen_date, now_iso, now_iso),
            )
            return int(cursor.lastrowid)

    def update_event_seen(
        self,
        *,
        event_id: int,
        last_seen_date: str,
        summary: Optional[str],
        domain: Optional[str],
        now_iso: str,
    ) -> None:
        """Extend an existing event's latest observation date and optional metadata.

        Args:
            event_id: Existing event cluster ID.
            last_seen_date: Observed `YYYY-MM-DD` date (kept monotonic forward).
            summary: Optional updated Chinese summary.
            domain: Optional updated domain if non-empty.
            now_iso: ISO-8601 update timestamp.
        """
        with self._db.write_transaction() as conn:
            conn.execute(
                """
                UPDATE hot_events
                SET last_seen_date = CASE
                        WHEN ? > last_seen_date THEN ? ELSE last_seen_date
                    END,
                    summary = CASE WHEN ? != '' THEN ? ELSE summary END,
                    domain = CASE WHEN ? != '' AND domain = '其他' THEN ? ELSE domain END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    last_seen_date,
                    last_seen_date,
                    summary or "",
                    summary or "",
                    domain or "",
                    domain or "",
                    now_iso,
                    event_id,
                ),
            )

    def link_item(
        self,
        *,
        event_id: int,
        source_type: str,
        item_id: int,
        confidence: float,
        now_iso: str,
    ) -> None:
        """Attach a hotlist or RSS item to a hot event cluster idempotently.

        Args:
            event_id: Target event cluster ID.
            source_type: `'hotlist'` or `'rss'`.
            item_id: Foreign item row ID.
            confidence: Clustering confidence in `[0, 1]`.
            now_iso: ISO-8601 timestamp.
        """
        with self._db.write_transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO event_news_links (
                    event_id, source_type, item_id, confidence, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, source_type, item_id, confidence, now_iso),
            )

    def count_daily_crawl_batches(self, metric_date: str) -> int:
        """Count distinct minute-level crawl batches observed on `metric_date`.

        Args:
            metric_date: Date formatted as `YYYY-MM-DD`.

        Returns:
            int: Number of batches (minimum `1` to prevent zero-division).
        """
        with self._db.read_connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT substr(recorded_at, 1, 16)) AS cnt
                FROM rank_history
                WHERE substr(recorded_at, 1, 10) = ?
                """,
                (metric_date,),
            ).fetchone()
            cnt = int(row["cnt"]) if row and row["cnt"] is not None else 0
            return max(1, cnt)

    def list_event_daily_observations(self, metric_date: str) -> List[Dict[str, Any]]:
        """Aggregate linked hotlist item observations for all events active on `metric_date`.

        Args:
            metric_date: Date formatted as `YYYY-MM-DD`.

        Returns:
            List[Dict[str, Any]]: Per-event rows with platform/rank/velocity/batch metrics.
        """
        sql = """
            SELECT
                enl.event_id,
                n.platform_id,
                n.velocity,
                COALESCE(MIN(rh.rank), n.latest_rank) AS best_rank,
                GROUP_CONCAT(DISTINCT substr(rh.recorded_at, 1, 16)) AS batch_keys
            FROM event_news_links enl
            JOIN news_items n
                ON enl.source_type = 'hotlist' AND enl.item_id = n.id
            LEFT JOIN rank_history rh
                ON rh.news_item_id = n.id AND substr(rh.recorded_at, 1, 10) = ?
            WHERE rh.id IS NOT NULL OR substr(n.last_seen_at, 1, 10) = ?
            GROUP BY enl.event_id, n.id
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, (metric_date, metric_date)).fetchall()
            return [dict(r) for r in rows]

    def upsert_daily_metric(
        self,
        *,
        metric_date: str,
        event_id: int,
        hot_index: float,
        velocity: float,
        platform_count: int,
        mention_count: int,
        daily_rank: int,
        is_top_n: bool,
        now_iso: str,
    ) -> None:
        """Insert or update daily aggregated metrics for one event.

        Args:
            metric_date: `YYYY-MM-DD` date key.
            event_id: Target event ID.
            hot_index: Composite score in `[0, 100]`.
            velocity: Maximum velocity among linked items.
            platform_count: Distinct platform count.
            mention_count: Total mention count.
            daily_rank: Rank within `metric_date`.
            is_top_n: Whether the event is included in daily Top N.
            now_iso: ISO-8601 update timestamp.
        """
        with self._db.write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO event_daily_metrics (
                    metric_date, event_id, hot_index, velocity,
                    platform_count, mention_count, daily_rank, is_top_n, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(metric_date, event_id) DO UPDATE SET
                    hot_index = excluded.hot_index,
                    velocity = excluded.velocity,
                    platform_count = excluded.platform_count,
                    mention_count = excluded.mention_count,
                    daily_rank = excluded.daily_rank,
                    is_top_n = excluded.is_top_n,
                    updated_at = excluded.updated_at
                """,
                (
                    metric_date,
                    event_id,
                    hot_index,
                    velocity,
                    platform_count,
                    mention_count,
                    daily_rank,
                    1 if is_top_n else 0,
                    now_iso,
                ),
            )

    def replace_daily_metrics(
        self,
        metric_date: str,
        metrics: List[Dict[str, Any]],
        now_iso: str,
    ) -> None:
        """Replace daily metrics for `metric_date` atomically in a single transaction.

        Args:
            metric_date: Date formatted as `YYYY-MM-DD`.
            metrics: Ranked event metric dicts ready for persistence.
            now_iso: ISO-8601 update timestamp.
        """
        with self._db.write_transaction() as conn:
            conn.execute("DELETE FROM event_daily_metrics WHERE metric_date = ?", (metric_date,))
            conn.executemany(
                """
                INSERT INTO event_daily_metrics (
                    metric_date, event_id, hot_index, velocity,
                    platform_count, mention_count, daily_rank, is_top_n, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        metric_date,
                        int(m["event_id"]),
                        float(m["hot_index"]),
                        float(m["velocity"]),
                        int(m["platform_count"]),
                        int(m["mention_count"]),
                        int(m["daily_rank"]),
                        1 if m["is_top_n"] else 0,
                        now_iso,
                    )
                    for m in metrics
                ],
            )

    def get_by_id(self, event_id: int) -> Optional[Dict[str, Any]]:
        """Fetch one hot event record by primary key.

        Args:
            event_id: Event primary key.

        Returns:
            Optional[Dict[str, Any]]: Event dict or None.
        """
        with self._db.read_connection() as conn:
            row = conn.execute("SELECT * FROM hot_events WHERE id = ?", (event_id,)).fetchone()
            return dict(row) if row else None

    def get_event_items(self, event_id: int) -> List[Dict[str, Any]]:
        """Return all hotlist items linked to a given hot event.

        Args:
            event_id: Hot event primary key.

        Returns:
            List[Dict[str, Any]]: Normalized item dictionaries matching `NewsItemDTO`.
        """
        return self.get_items_for_events([event_id]).get(event_id, [])

    def get_items_for_events(self, event_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        """Batch-fetch linked hotlist items grouped by event ID.

        Args:
            event_ids: List of `hot_events.id` values.

        Returns:
            Dict[int, List[Dict[str, Any]]]: Mapping from `event_id` to normalized items.
        """
        if not event_ids:
            return {}
        placeholders = ",".join("?" for _ in event_ids)
        sql = f"""
            SELECT enl.event_id, n.*
            FROM event_news_links enl
            JOIN news_items n
                ON enl.source_type = 'hotlist' AND enl.item_id = n.id
            WHERE enl.event_id IN ({placeholders})
            ORDER BY n.velocity DESC, n.latest_rank ASC
        """
        grouped: Dict[int, List[Dict[str, Any]]] = {eid: [] for eid in event_ids}
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, list(event_ids)).fetchall()
            for row in rows:
                eid = int(row["event_id"])
                grouped.setdefault(eid, []).append(self._row_to_item_dict(row, eid))
        return grouped

    def latest_metric_date(self) -> Optional[str]:
        """Return the most recent date with recorded daily event metrics.

        Returns:
            Optional[str]: `YYYY-MM-DD` date string or None when empty.
        """
        with self._db.read_connection() as conn:
            row = conn.execute("SELECT MAX(metric_date) AS dt FROM event_daily_metrics").fetchone()
            if row and row["dt"]:
                return str(row["dt"])
            return None

    def list_events_for_date(
        self,
        metric_date: str,
        domain: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return daily ranked events joined with `hot_events` for a specific date.

        Args:
            metric_date: Date formatted as `YYYY-MM-DD`.
            domain: Optional domain category filter.

        Returns:
            List[Dict[str, Any]]: Event rows sorted by `daily_rank ASC`.
        """
        clauses = ["edm.metric_date = ?"]
        params: List[Any] = [metric_date]
        if domain:
            clauses.append("he.domain = ?")
            params.append(domain)

        sql = f"""
            SELECT
                he.id, he.canonical_title, he.domain, he.summary,
                he.first_seen_date, he.last_seen_date,
                edm.hot_index, edm.velocity, edm.platform_count,
                edm.mention_count, edm.daily_rank, edm.is_top_n
            FROM event_daily_metrics edm
            JOIN hot_events he ON he.id = edm.event_id
            WHERE {' AND '.join(clauses)}
            ORDER BY edm.daily_rank ASC, edm.hot_index DESC
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def list_trend_metrics(
        self,
        start_date: str,
        end_date: str,
        domain: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query all daily event metrics inside an inclusive date window.

        Args:
            start_date: Inclusive `YYYY-MM-DD` start date.
            end_date: Inclusive `YYYY-MM-DD` end date.
            domain: Optional domain filter.

        Returns:
            List[Dict[str, Any]]: Flat metric rows ordered by `metric_date ASC, daily_rank ASC`.
        """
        clauses = ["edm.metric_date >= ?", "edm.metric_date <= ?"]
        params: List[Any] = [start_date, end_date]
        if domain:
            clauses.append("he.domain = ?")
            params.append(domain)

        sql = f"""
            SELECT
                edm.metric_date, edm.event_id, edm.hot_index, edm.velocity,
                edm.platform_count, edm.daily_rank, edm.is_top_n,
                he.canonical_title, he.domain
            FROM event_daily_metrics edm
            JOIN hot_events he ON he.id = edm.event_id
            WHERE {' AND '.join(clauses)}
            ORDER BY edm.metric_date ASC, edm.daily_rank ASC
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def list_event_metrics_history(self, event_id: int) -> List[Dict[str, Any]]:
        """Fetch historical daily metrics for one event ordered chronologically.

        Args:
            event_id: Target event primary key.

        Returns:
            List[Dict[str, Any]]: Daily metric history rows.
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(
                """
                SELECT metric_date, hot_index, daily_rank, platform_count, velocity, is_top_n
                FROM event_daily_metrics
                WHERE event_id = ?
                ORDER BY metric_date ASC
                """,
                (event_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _row_to_item_dict(row: sqlite3.Row, event_id: int) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "source_type": "hotlist",
            "platform_id": str(row["platform_id"]),
            "platform_name": str(row["platform_name"]),
            "domain": str(row["domain"] or ""),
            "title": str(row["title"]),
            "url": str(row["url"] or ""),
            "summary": str(row["raw_summary"] or ""),
            "latest_rank": int(row["latest_rank"]),
            "velocity": float(row["velocity"] or 0.0),
            "hot_index": None,
            "event_id": event_id,
            "extra_metrics": _parse_json_dict(str(row["extra_metrics_json"] or "{}")),
            "first_seen_at": str(row["first_seen_at"]),
            "last_seen_at": str(row["last_seen_at"]),
        }