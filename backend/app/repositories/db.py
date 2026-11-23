"""SQLite WAL database connection manager and schema initialization."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
from typing import Iterator

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin', 'user')),
        is_active INTEGER NOT NULL DEFAULT 1,
        invited_by_code_id INTEGER DEFAULT NULL,
        last_login_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS news_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_type TEXT NOT NULL DEFAULT 'hotlist',
        platform_id TEXT NOT NULL,
        platform_name TEXT NOT NULL,
        domain TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL,
        title_hash TEXT NOT NULL,
        url TEXT NOT NULL DEFAULT '',
        mobile_url TEXT NOT NULL DEFAULT '',
        raw_summary TEXT NOT NULL DEFAULT '',
        extra_metrics_json TEXT NOT NULL DEFAULT '{}',
        latest_rank INTEGER NOT NULL,
        velocity REAL NOT NULL DEFAULT 0.0,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        crawl_count INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_news_platform_url
        ON news_items(platform_id, url) WHERE url != '';
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_news_platform_title_hash
        ON news_items(platform_id, title_hash) WHERE url = '';
    """,
    "CREATE INDEX IF NOT EXISTS idx_news_last_seen ON news_items(last_seen_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_news_velocity ON news_items(velocity DESC, last_seen_at DESC);",
    """
    CREATE TABLE IF NOT EXISTS rank_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        news_item_id INTEGER NOT NULL,
        rank INTEGER NOT NULL,
        metric_value REAL DEFAULT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY (news_item_id) REFERENCES news_items(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_rank_history_item_time
        ON rank_history(news_item_id, recorded_at DESC);
    """,
    """
    CREATE TABLE IF NOT EXISTS rss_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feed_id TEXT NOT NULL,
        feed_name TEXT NOT NULL,
        domain TEXT NOT NULL DEFAULT '其他',
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        guid TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        published_at TEXT NOT NULL DEFAULT '',
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    );
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rss_feed_url ON rss_items(feed_id, url);",
    "CREATE INDEX IF NOT EXISTS idx_rss_published ON rss_items(published_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_rss_domain ON rss_items(domain, published_at DESC);",
    """
    CREATE TABLE IF NOT EXISTS hot_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        canonical_title TEXT NOT NULL,
        domain TEXT NOT NULL DEFAULT '其他',
        summary TEXT NOT NULL DEFAULT '',
        first_seen_date TEXT NOT NULL,
        last_seen_date TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_hot_events_dates ON hot_events(last_seen_date DESC, domain);",
    """
    CREATE TABLE IF NOT EXISTS event_news_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        source_type TEXT NOT NULL CHECK(source_type IN ('hotlist', 'rss')),
        item_id INTEGER NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL,
        UNIQUE(source_type, item_id),
        FOREIGN KEY (event_id) REFERENCES hot_events(id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_event_links_event ON event_news_links(event_id);",
    """
    CREATE TABLE IF NOT EXISTS event_daily_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_date TEXT NOT NULL,
        event_id INTEGER NOT NULL,
        hot_index REAL NOT NULL,
        velocity REAL NOT NULL DEFAULT 0.0,
        platform_count INTEGER NOT NULL DEFAULT 1,
        mention_count INTEGER NOT NULL DEFAULT 1,
        daily_rank INTEGER NOT NULL,
        is_top_n INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        UNIQUE(metric_date, event_id),
        FOREIGN KEY (event_id) REFERENCES hot_events(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_daily_metrics_date_rank
        ON event_daily_metrics(metric_date, daily_rank ASC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_daily_metrics_event
        ON event_daily_metrics(event_id, metric_date ASC);
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_providers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        protocol TEXT NOT NULL CHECK(protocol IN ('openai', 'anthropic', 'antigravity')),
        base_url TEXT NOT NULL DEFAULT '',
        api_key_encrypted TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL,
        extra_params_json TEXT NOT NULL DEFAULT '{}',
        role_bindings_json TEXT NOT NULL DEFAULT '[]',
        is_enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS prompt_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        category TEXT NOT NULL DEFAULT 'chat_system',
        content TEXT NOT NULL,
        is_default INTEGER NOT NULL DEFAULT 0,
        is_enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        provider_slot_id INTEGER,
        external_conversation_id TEXT NOT NULL DEFAULT '',
        prompt_template_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (provider_slot_id) REFERENCES ai_providers(id) ON DELETE SET NULL,
        FOREIGN KEY (prompt_template_id) REFERENCES prompt_templates(id) ON DELETE SET NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at DESC);",
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('system', 'user', 'assistant')),
        content TEXT NOT NULL,
        context_items_json TEXT NOT NULL DEFAULT '[]',
        usage_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, id ASC);",
    """
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_type TEXT NOT NULL CHECK(
            report_type IN ('daily_overall', 'domain_trend', 'item_analysis', 'chat_generated')
        ),
        report_date TEXT NOT NULL,
        domain TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL,
        content_md TEXT NOT NULL,
        related_event_ids_json TEXT NOT NULL DEFAULT '[]',
        related_news_ids_json TEXT NOT NULL DEFAULT '[]',
        source_session_id INTEGER,
        provider_slot_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (source_session_id) REFERENCES chat_sessions(id) ON DELETE SET NULL,
        FOREIGN KEY (provider_slot_id) REFERENCES ai_providers(id) ON DELETE SET NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_reports_date_type ON reports(report_date DESC, report_type);",
    "CREATE INDEX IF NOT EXISTS idx_reports_domain ON reports(domain, report_date DESC);",
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        section TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS invite_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        note TEXT NOT NULL DEFAULT '',
        max_uses INTEGER NOT NULL DEFAULT 1 CHECK(max_uses >= 0),
        used_count INTEGER NOT NULL DEFAULT 0 CHECK(used_count >= 0),
        expires_at TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_invite_codes_created ON invite_codes(created_at DESC);",
)


class Database:
    """Thread-safe SQLite WAL database coordinator."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the database coordinator and ensure parent directory exists.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a short-lived read connection with WAL pragmas configured.

        Yields:
            sqlite3.Connection: Open SQLite connection closed automatically on exit.
        """
        conn = self._open_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a serialized write connection wrapped in a transaction.

        Yields:
            sqlite3.Connection: Open SQLite connection committed on success, rolled back on error.
        """
        with self._write_lock:
            conn = self._open_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    @staticmethod
    def _migrate_users_table(conn: sqlite3.Connection) -> None:
        """Add role and invite-lineage columns idempotently for pre-existing databases."""
        cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "role" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
            # Existing pre-upgrade users were single-tenant operators and must remain admins.
            conn.execute("UPDATE users SET role = 'admin'")
        if "invited_by_code_id" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN invited_by_code_id INTEGER DEFAULT NULL")

    def init_schema(self) -> None:
        """Create all tables and indexes idempotently and run lightweight migrations."""
        with self.write_transaction() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            self._migrate_users_table(conn)
