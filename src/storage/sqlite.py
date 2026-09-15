import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from src.models import Repository


class SqliteStore:
    def __init__(self, db_path: str = "data/database/awesome.sqlite"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS repositories (
                    id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    description TEXT,
                    stars INTEGER,
                    forks INTEGER,
                    language TEXT,
                    license TEXT,
                    archived BOOLEAN DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    pushed_at TEXT,
                    collected_at TEXT,
                    health_status TEXT DEFAULT 'UNKNOWN',
                    score_overall REAL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS repository_categories (
                    repository_id TEXT,
                    category_id INTEGER,
                    PRIMARY KEY(repository_id, category_id),
                    FOREIGN KEY(category_id) REFERENCES categories(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sources (
                    repository_id TEXT,
                    source_repository TEXT,
                    source_section TEXT,
                    PRIMARY KEY(repository_id, source_repository, source_section)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_metrics (
                    repository_id TEXT,
                    date TEXT,
                    stars INTEGER,
                    forks INTEGER,
                    issues INTEGER,
                    PRIMARY KEY(repository_id, date)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_repos_stars ON repositories(stars)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_repos_collected ON repositories(collected_at)
            """)
            conn.commit()

    def save_repository(self, repo: Repository) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO repositories
                (id, owner, name, url, description, stars, forks, language, license,
                 archived, created_at, updated_at, pushed_at, collected_at, health_status, score_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                repo.id, repo.owner, repo.name, repo.url, repo.description,
                repo.stars, repo.forks, repo.language, repo.license,
                repo.archived, repo.created_at, repo.updated_at, repo.pushed_at,
                repo.collected_at,
                repo.health.get("status", "UNKNOWN") if repo.health else "UNKNOWN",
                repo.score.get("overall", 0) if repo.score else 0,
            ))
            conn.commit()

    def save_categories(self, repo_id: str, categories: list[str]) -> None:
        with self._lock, self._get_connection() as conn:
            for cat_name in categories:
                cat_id = conn.execute(
                    "INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat_name,)
                ).lastrowid
                if cat_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO repository_categories (repository_id, category_id) VALUES (?, ?)",
                        (repo_id, cat_id),
                    )
            conn.commit()

    def save_sources(self, repo_id: str, sources: list[dict]) -> None:
        with self._lock, self._get_connection() as conn:
            for source in sources:
                conn.execute(
                    "INSERT OR IGNORE INTO sources (repository_id, source_repository, source_section) VALUES (?, ?, ?)",
                    (repo_id, source.get("repository", ""), source.get("section", "")),
                )
            conn.commit()

    def save_daily_metric(self, repo_id: str, date: str, stars: int, forks: int, issues: int) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_metrics (repository_id, date, stars, forks, issues) VALUES (?, ?, ?, ?, ?)",
                (repo_id, date, stars, forks, issues),
            )
            conn.commit()

    def get_repository(self, repo_id: str) -> Optional[dict]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
            if row:
                return dict(row)
        return None

    def get_all_repositories(self, limit: Optional[int] = None) -> list[dict]:
        query = "SELECT * FROM repositories"
        if limit:
            query += f" LIMIT {limit}"
        with self._get_connection() as conn:
            return [dict(row) for row in conn.execute(query).fetchall()]

    def get_by_health(self, status: str) -> list[dict]:
        with self._get_connection() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM repositories WHERE health_status = ?", (status,)
            ).fetchall()]

    def get_by_category(self, category_name: str) -> list[dict]:
        with self._get_connection() as conn:
            return [dict(row) for row in conn.execute("""
                SELECT r.* FROM repositories r
                JOIN repository_categories rc ON r.id = rc.repository_id
                JOIN categories c ON rc.category_id = c.id
                WHERE c.name = ?
            """, (category_name,)).fetchall()]

    def get_stale_repos(self, max_days: int = 180) -> list[dict]:
        with self._get_connection() as conn:
            return [dict(row) for row in conn.execute("""
                SELECT * FROM repositories
                WHERE archived = 0 AND health_status != 'ARCHIVED'
                AND (pushed_at IS NULL OR julianday('now') - julianday(pushed_at) > ?)
            """, (max_days,)).fetchall()]

    def get_total_count(self) -> int:
        with self._get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0]

    def vacuum(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("VACUUM")

    def get_stats(self) -> dict:
        with self._get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0]
            by_health = dict(conn.execute("""
                SELECT health_status, COUNT(*) FROM repositories GROUP BY health_status
            """).fetchall())
            by_language = dict(conn.execute("""
                SELECT language, COUNT(*) FROM repositories WHERE language IS NOT NULL GROUP BY language
            """).fetchall())
            total_stars = conn.execute("SELECT COALESCE(SUM(stars), 0) FROM repositories").fetchone()[0]
            return {
                "total": total,
                "by_health": by_health,
                "by_language": by_language,
                "total_stars": total_stars,
            }