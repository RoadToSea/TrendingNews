"""Persistence repository for hotlist items, rank/metric histories, and RSS items."""

import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from app.repositories.db import Database


def _parse_json_dict(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


class NewsRepository:
    """Data access layer for `news_items`, `rank_history`, and `rss_items`."""

    def __init__(self, db: Database) -> None:
        """Bind repository to the database coordinator.

        Args:
            db: Shared `Database` instance.
        """
        self._db = db

    def upsert_news_item(
        self,
        *,
        source_type: str,
        platform_id: str,
        platform_name: str,
        domain: str,
        title: str,
        title_hash: str,
        url: str,
        mobile_url: str,
        summary: str,
        extra_metrics: Dict[str, Any],
        rank: int,
        seen_at: str,
    ) -> Tuple[int, str]:
        """Insert or update a hotlist/API news item deduplicated by platform + url or title_hash.

        Args:
            source_type: Origin type (`hotlist`).
            platform_id: Platform identifier.
            platform_name: Human-readable platform name.
            domain: Optional domain label.
            title: Item title.
            title_hash: Deterministic SHA-256 hex digest of normalized title.
            url: Canonical item URL (may be empty).
            mobile_url: Optional mobile URL.
            summary: Optional summary text.
            extra_metrics: Optional native metrics dictionary.
            rank: Position within current crawl batch.
            seen_at: ISO-8601 observation timestamp.

        Returns:
            Tuple[int, str]: `(news_item_id, first_seen_at)` for velocity calculation.
        """
        metrics_json = json.dumps(extra_metrics, ensure_ascii=False)
        with self._db.write_transaction() as conn:
            return self._upsert_news_on_conn(
                conn,
                source_type=source_type,
                platform_id=platform_id,
                platform_name=platform_name,
                domain=domain,
                title=title,
                title_hash=title_hash,
                url=url,
                mobile_url=mobile_url,
                summary=summary,
                metrics_json=metrics_json,
                rank=rank,
                seen_at=seen_at,
            )

    def _upsert_news_on_conn(
        self,
        conn: sqlite3.Connection,
        *,
        source_type: str,
        platform_id: str,
        platform_name: str,
        domain: str,
        title: str,
        title_hash: str,
        url: str,
        mobile_url: str,
        summary: str,
        metrics_json: str,
        rank: int,
        seen_at: str,
    ) -> Tuple[int, str]:
        existing = self._find_existing_news(conn, platform_id, url, title_hash)
        if existing is not None:
            item_id = int(existing["id"])
            first_seen = str(existing["first_seen_at"])
            resolved_summary = summary or str(existing["raw_summary"] or "")
            resolved_domain = domain or str(existing["domain"] or "")
            conn.execute(
                """
                UPDATE news_items
                SET source_type = ?, platform_name = ?, domain = ?, title = ?,
                    mobile_url = CASE WHEN ? != '' THEN ? ELSE mobile_url END,
                    raw_summary = ?, extra_metrics_json = ?,
                    latest_rank = ?, last_seen_at = ?, crawl_count = crawl_count + 1
                WHERE id = ?
                """,
                (
                    source_type,
                    platform_name,
                    resolved_domain,
                    title,
                    mobile_url,
                    mobile_url,
                    resolved_summary,
                    metrics_json,
                    rank,
                    seen_at,
                    item_id,
                ),
            )
            return item_id, first_seen

        cursor = conn.execute(
            """
            INSERT INTO news_items (
                source_type, platform_id, platform_name, domain, title, title_hash,
                url, mobile_url, raw_summary, extra_metrics_json,
                latest_rank, velocity, first_seen_at, last_seen_at, crawl_count, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?, 1, ?)
            """,
            (
                source_type,
                platform_id,
                platform_name,
                domain,
                title,
                title_hash,
                url,
                mobile_url,
                summary,
                metrics_json,
                rank,
                seen_at,
                seen_at,
                seen_at,
            ),
        )
        return int(cursor.lastrowid), seen_at

    def bulk_upsert_news_and_history(
        self,
        items: List[Dict[str, Any]],
        seen_at: str,
    ) -> List[Tuple[int, str, str, List[Tuple[str, int, Optional[float]]]]]:
        """Upsert items, append rank samples, and load recent histories in one SQLite transaction.

        Args:
            items: Normalized item dicts containing `platform_id`, `platform_name`, `domain`,
                `title`, `title_hash`, `url`, `mobile_url`, `summary`, `extra_metrics`,
                `rank`, and `primary_metric`.
            seen_at: ISO-8601 observation timestamp for the batch.

        Returns:
            List[Tuple[int, str, str, List[Tuple[str, int, Optional[float]]]]]: Per-item tuples
            of `(news_item_id, platform_id, first_seen_at, recent_history)`.
        """
        if not items:
            return []
        collected: List[Tuple[int, str, str, List[Tuple[str, int, Optional[float]]]]] = []
        with self._db.write_transaction() as conn:
            for item in items:
                metrics_json = json.dumps(item["extra_metrics"], ensure_ascii=False)
                item_id, first_seen = self._upsert_news_on_conn(
                    conn,
                    source_type="hotlist",
                    platform_id=item["platform_id"],
                    platform_name=item["platform_name"],
                    domain=item["domain"],
                    title=item["title"],
                    title_hash=item["title_hash"],
                    url=item["url"],
                    mobile_url=item["mobile_url"],
                    summary=item["summary"],
                    metrics_json=metrics_json,
                    rank=item["rank"],
                    seen_at=seen_at,
                )
                conn.execute(
                    """
                    INSERT INTO rank_history (news_item_id, rank, metric_value, recorded_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item_id, item["rank"], item.get("primary_metric"), seen_at),
                )
                history = self._get_recent_rank_history_on_conn(conn, item_id, limit=50)
                collected.append((item_id, item["platform_id"], first_seen, history))
        return collected

    @staticmethod
    def _find_existing_news(
        conn: sqlite3.Connection,
        platform_id: str,
        url: str,
        title_hash: str,
    ) -> Optional[sqlite3.Row]:
        if url:
            return conn.execute(
                "SELECT id, first_seen_at, raw_summary, domain FROM news_items WHERE platform_id = ? AND url = ?",
                (platform_id, url),
            ).fetchone()
        return conn.execute(
            "SELECT id, first_seen_at, raw_summary, domain FROM news_items WHERE platform_id = ? AND url = '' AND title_hash = ?",
            (platform_id, title_hash),
        ).fetchone()

    def insert_rank_history(
        self,
        news_item_id: int,
        rank: int,
        recorded_at: str,
        metric_value: Optional[float] = None,
    ) -> None:
        """Append one sample to `rank_history` for velocity and timeline tracking.

        Args:
            news_item_id: Foreign key to `news_items.id`.
            rank: Rank in current batch.
            recorded_at: ISO-8601 observation timestamp.
            metric_value: Optional primary native metric (views/ups/score/stars).
        """
        with self._db.write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO rank_history (news_item_id, rank, metric_value, recorded_at)
                VALUES (?, ?, ?, ?)
                """,
                (news_item_id, rank, metric_value, recorded_at),
            )

    def get_recent_rank_history(
        self,
        news_item_id: int,
        limit: int = 50,
    ) -> List[Tuple[str, int, Optional[float]]]:
        """Fetch chronological rank/metric samples for a news item.

        Args:
            news_item_id: Target news item ID.
            limit: Maximum recent samples to inspect.

        Returns:
            List[Tuple[str, int, Optional[float]]]: `(recorded_at, rank, metric_value)` sorted ascending.
        """
        with self._db.read_connection() as conn:
            return self._get_recent_rank_history_on_conn(conn, news_item_id, limit)

    @staticmethod
    def _get_recent_rank_history_on_conn(
        conn: sqlite3.Connection,
        news_item_id: int,
        limit: int = 50,
    ) -> List[Tuple[str, int, Optional[float]]]:
        rows = conn.execute(
            """
            SELECT recorded_at, rank, metric_value
            FROM (
                SELECT recorded_at, rank, metric_value, id
                FROM rank_history
                WHERE news_item_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT ?
            )
            ORDER BY recorded_at ASC, id ASC
            """,
            (news_item_id, limit),
        ).fetchall()
        return [
            (
                str(r["recorded_at"]),
                int(r["rank"]),
                float(r["metric_value"]) if r["metric_value"] is not None else None,
            )
            for r in rows
        ]

    def batch_update_velocities(self, updates: List[Tuple[int, float]]) -> None:
        """Persist calculated velocity scores in one transaction.

        Args:
            updates: Sequence of `(news_item_id, velocity)` pairs.
        """
        if not updates:
            return
        with self._db.write_transaction() as conn:
            conn.executemany(
                "UPDATE news_items SET velocity = ? WHERE id = ?",
                [(velocity, item_id) for item_id, velocity in updates],
            )

    def list_hotlist(
        self,
        *,
        platform_id: Optional[str] = None,
        query: Optional[str] = None,
        since_iso: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query stored hotlist/API items ordered by recency and rank.

        Args:
            platform_id: Optional platform filter.
            query: Optional case-insensitive title substring filter.
            since_iso: Optional lower bound on `last_seen_at`.
            limit: Maximum returned items.

        Returns:
            List[Dict[str, Any]]: Normalized item dictionaries including optional linked event metrics.
        """
        clauses = ["1 = 1"]
        params: List[Any] = []
        if platform_id:
            clauses.append("n.platform_id = ?")
            params.append(platform_id)
        if query:
            clauses.append("LOWER(n.title) LIKE ?")
            params.append(f"%{query.strip().lower()}%")
        if since_iso:
            clauses.append("n.last_seen_at >= ?")
            params.append(since_iso)
        params.append(limit)

        sql = f"""
            SELECT
                n.*,
                enl.event_id AS linked_event_id,
                (
                    SELECT edm.hot_index
                    FROM event_daily_metrics edm
                    WHERE edm.event_id = enl.event_id
                    ORDER BY edm.metric_date DESC
                    LIMIT 1
                ) AS event_hot_index
            FROM news_items n
            LEFT JOIN event_news_links enl
                ON enl.source_type = 'hotlist' AND enl.item_id = n.id
            WHERE {' AND '.join(clauses)}
            ORDER BY substr(n.last_seen_at, 1, 10) DESC, n.latest_rank ASC, n.velocity DESC
            LIMIT ?
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_news_dict(row) for row in rows]

    def list_rising(self, since_iso: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Query items with positive velocity updated since `since_iso`.

        Args:
            since_iso: Minimum `last_seen_at` ISO timestamp.
            limit: Maximum items returned.

        Returns:
            List[Dict[str, Any]]: Items sorted by `velocity` descending.
        """
        sql = """
            SELECT
                n.*,
                enl.event_id AS linked_event_id,
                (
                    SELECT edm.hot_index
                    FROM event_daily_metrics edm
                    WHERE edm.event_id = enl.event_id
                    ORDER BY edm.metric_date DESC
                    LIMIT 1
                ) AS event_hot_index
            FROM news_items n
            LEFT JOIN event_news_links enl
                ON enl.source_type = 'hotlist' AND enl.item_id = n.id
            WHERE n.last_seen_at >= ? AND n.velocity > 0
            ORDER BY n.velocity DESC, n.latest_rank ASC
            LIMIT ?
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, (since_iso, limit)).fetchall()
            return [self._row_to_news_dict(row) for row in rows]

    def list_platforms(self, since_iso: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return distinct active platforms with item counts.

        Args:
            since_iso: Optional lower bound on `last_seen_at`.

        Returns:
            List[Dict[str, Any]]: `{id, name, count}` dictionaries.
        """
        where_clause = "WHERE last_seen_at >= ?" if since_iso else ""
        params = [since_iso] if since_iso else []
        sql = f"""
            SELECT platform_id AS id, MAX(platform_name) AS name, COUNT(*) AS count
            FROM news_items
            {where_clause}
            GROUP BY platform_id
            ORDER BY count DESC, platform_id ASC
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [
                {"id": str(r["id"]), "name": str(r["name"]), "count": int(r["count"])}
                for r in rows
            ]

    def upsert_rss_item(
        self,
        *,
        feed_id: str,
        feed_name: str,
        domain: str,
        title: str,
        url: str,
        guid: str,
        author: str,
        summary: str,
        published_at: str,
        seen_at: str,
    ) -> int:
        """Insert or update an RSS item deduplicated by `(feed_id, url)`.

        Args:
            feed_id: Configured RSS feed ID.
            feed_name: Display name of the feed.
            domain: Domain classification.
            title: Entry title.
            url: Entry link URL.
            guid: Optional GUID/Atom ID.
            author: Optional author string.
            summary: Cleaned entry summary.
            published_at: Published timestamp string.
            seen_at: ISO-8601 observation timestamp.

        Returns:
            int: Row ID in `rss_items`.
        """
        with self._db.write_transaction() as conn:
            return self._upsert_rss_on_conn(
                conn,
                feed_id=feed_id,
                feed_name=feed_name,
                domain=domain,
                title=title,
                url=url,
                guid=guid,
                author=author,
                summary=summary,
                published_at=published_at,
                seen_at=seen_at,
            )

    def bulk_upsert_rss_items(self, items: List[Dict[str, Any]], seen_at: str) -> int:
        """Persist a batch of RSS items in one SQLite write transaction.

        Args:
            items: List of normalized RSS dictionaries (`feed_id`, `feed_name`, `domain`,
                `title`, `url`, `guid`, `author`, `summary`, `published_at`).
            seen_at: ISO-8601 observation timestamp.

        Returns:
            int: Number of RSS items persisted.
        """
        if not items:
            return 0
        with self._db.write_transaction() as conn:
            for item in items:
                self._upsert_rss_on_conn(
                    conn,
                    feed_id=item["feed_id"],
                    feed_name=item["feed_name"],
                    domain=item["domain"],
                    title=item["title"],
                    url=item["url"],
                    guid=item["guid"],
                    author=item["author"],
                    summary=item["summary"],
                    published_at=item["published_at"],
                    seen_at=seen_at,
                )
        return len(items)

    @staticmethod
    def _upsert_rss_on_conn(
        conn: sqlite3.Connection,
        *,
        feed_id: str,
        feed_name: str,
        domain: str,
        title: str,
        url: str,
        guid: str,
        author: str,
        summary: str,
        published_at: str,
        seen_at: str,
    ) -> int:
        existing = conn.execute(
            "SELECT id FROM rss_items WHERE feed_id = ? AND url = ?",
            (feed_id, url),
        ).fetchone()
        if existing is not None:
            item_id = int(existing["id"])
            conn.execute(
                """
                UPDATE rss_items
                SET feed_name = ?, domain = ?, title = ?, guid = ?, author = ?,
                    summary = CASE WHEN ? != '' THEN ? ELSE summary END,
                    published_at = CASE WHEN ? != '' THEN ? ELSE published_at END,
                    last_seen_at = ?
                WHERE id = ?
                """,
                (
                    feed_name,
                    domain,
                    title,
                    guid,
                    author,
                    summary,
                    summary,
                    published_at,
                    published_at,
                    seen_at,
                    item_id,
                ),
            )
            return item_id

        cursor = conn.execute(
            """
            INSERT INTO rss_items (
                feed_id, feed_name, domain, title, url, guid, author,
                summary, published_at, first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feed_id,
                feed_name,
                domain,
                title,
                url,
                guid,
                author,
                summary,
                published_at,
                seen_at,
                seen_at,
            ),
        )
        return int(cursor.lastrowid)

    def list_rss(
        self,
        *,
        feed_id: Optional[str] = None,
        domain: Optional[str] = None,
        since_iso: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query RSS items sorted by published/observation timestamp descending.

        Args:
            feed_id: Optional feed filter.
            domain: Optional domain filter.
            since_iso: Optional lower bound on `last_seen_at`.
            limit: Maximum items returned.

        Returns:
            List[Dict[str, Any]]: RSS items formatted consistently with `NewsItemDTO`.
        """
        clauses = ["1 = 1"]
        params: List[Any] = []
        if feed_id:
            clauses.append("r.feed_id = ?")
            params.append(feed_id)
        if domain:
            clauses.append("r.domain = ?")
            params.append(domain)
        if since_iso:
            clauses.append("r.last_seen_at >= ?")
            params.append(since_iso)
        params.append(limit)

        sql = f"""
            SELECT
                r.*,
                enl.event_id AS linked_event_id,
                (
                    SELECT edm.hot_index
                    FROM event_daily_metrics edm
                    WHERE edm.event_id = enl.event_id
                    ORDER BY edm.metric_date DESC
                    LIMIT 1
                ) AS event_hot_index
            FROM rss_items r
            LEFT JOIN event_news_links enl
                ON enl.source_type = 'rss' AND enl.item_id = r.id
            WHERE {' AND '.join(clauses)}
            ORDER BY CASE WHEN r.published_at != '' THEN r.published_at ELSE r.last_seen_at END DESC
            LIMIT ?
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_rss_dict(row) for row in rows]

    def list_rss_feeds(self, since_iso: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return distinct RSS feeds with stored item counts.

        Args:
            since_iso: Optional lower bound on `last_seen_at`.

        Returns:
            List[Dict[str, Any]]: `{id, name, domain, count}` dictionaries.
        """
        where_clause = "WHERE last_seen_at >= ?" if since_iso else ""
        params = [since_iso] if since_iso else []
        sql = f"""
            SELECT feed_id AS id, MAX(feed_name) AS name, MAX(domain) AS domain, COUNT(*) AS count
            FROM rss_items
            {where_clause}
            GROUP BY feed_id
            ORDER BY count DESC, feed_id ASC
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "id": str(r["id"]),
                    "name": str(r["name"]),
                    "domain": str(r["domain"]),
                    "count": int(r["count"]),
                }
                for r in rows
            ]

    def get_items_for_keywords(
        self,
        since_iso: str,
        include_rss: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fetch recent hotlist and optional RSS items for keyword matching.

        Args:
            since_iso: Lower bound timestamp for matching items.
            include_rss: Whether to include `rss_items` alongside `news_items`.

        Returns:
            List[Dict[str, Any]]: Combined list of normalized item dicts.
        """
        items = self.list_hotlist(since_iso=since_iso, limit=2000)
        if include_rss:
            items.extend(self.list_rss(since_iso=since_iso, limit=1000))
        return items

    def get_news_items_by_ids(self, item_ids: List[int]) -> List[Dict[str, Any]]:
        """Fetch normalized hotlist/API items matching the given primary keys.

        Args:
            item_ids: List of `news_items.id` values.

        Returns:
            List[Dict[str, Any]]: Matching item dictionaries preserving `id IN (...)` results.
        """
        if not item_ids:
            return []
        placeholders = ",".join("?" for _ in item_ids)
        sql = f"""
            SELECT
                n.*,
                enl.event_id AS linked_event_id,
                (
                    SELECT edm.hot_index
                    FROM event_daily_metrics edm
                    WHERE edm.event_id = enl.event_id
                    ORDER BY edm.metric_date DESC
                    LIMIT 1
                ) AS event_hot_index
            FROM news_items n
            LEFT JOIN event_news_links enl
                ON enl.source_type = 'hotlist' AND enl.item_id = n.id
            WHERE n.id IN ({placeholders})
            ORDER BY n.velocity DESC, n.latest_rank ASC
        """
        with self._db.read_connection() as conn:
            rows = conn.execute(sql, list(item_ids)).fetchall()
            return [self._row_to_news_dict(row) for row in rows]

    def update_news_item_domain(self, item_id: int, domain: str) -> None:
        """Assign an inferred domain label to a news item when empty or updated.

        Args:
            item_id: Target `news_items.id`.
            domain: Classified domain category name.
        """
        with self._db.write_transaction() as conn:
            conn.execute(
                "UPDATE news_items SET domain = ? WHERE id = ?",
                (domain, item_id),
            )

    def cleanup_older_than(self, cutoff_iso: str) -> int:
        """Delete news and RSS items not observed since `cutoff_iso`.

        Args:
            cutoff_iso: Exclusive cutoff ISO timestamp.

        Returns:
            int: Total rows deleted across `news_items` and `rss_items`.
        """
        with self._db.write_transaction() as conn:
            cur1 = conn.execute("DELETE FROM news_items WHERE last_seen_at < ?", (cutoff_iso,))
            cur2 = conn.execute("DELETE FROM rss_items WHERE last_seen_at < ?", (cutoff_iso,))
            return int(cur1.rowcount or 0) + int(cur2.rowcount or 0)

    @staticmethod
    def _row_to_news_dict(row: sqlite3.Row) -> Dict[str, Any]:
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
            "hot_index": float(row["event_hot_index"]) if row["event_hot_index"] is not None else None,
            "event_id": int(row["linked_event_id"]) if row["linked_event_id"] is not None else None,
            "extra_metrics": _parse_json_dict(str(row["extra_metrics_json"] or "{}")),
            "first_seen_at": str(row["first_seen_at"]),
            "last_seen_at": str(row["last_seen_at"]),
        }

    @staticmethod
    def _row_to_rss_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "source_type": "rss",
            "platform_id": str(row["feed_id"]),
            "platform_name": str(row["feed_name"]),
            "domain": str(row["domain"] or "其他"),
            "title": str(row["title"]),
            "url": str(row["url"] or ""),
            "summary": str(row["summary"] or ""),
            "latest_rank": None,
            "velocity": 0.0,
            "hot_index": float(row["event_hot_index"]) if row["event_hot_index"] is not None else None,
            "event_id": int(row["linked_event_id"]) if row["linked_event_id"] is not None else None,
            "extra_metrics": {},
            "first_seen_at": str(row["first_seen_at"]),
            "last_seen_at": str(row["last_seen_at"]),
        }
