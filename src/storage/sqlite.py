import os
import sqlite3
import threading

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
                    name TEXT UNIQUE,
                    parent_id INTEGER REFERENCES categories(id)
                )
            """)
            self._ensure_category_parent_column(conn)

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
                CREATE TABLE IF NOT EXISTS security_findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repository_id TEXT,
                    source TEXT NOT NULL,
                    advisory_id TEXT NOT NULL,
                    package TEXT,
                    ecosystem TEXT,
                    severity TEXT,
                    summary TEXT,
                    url TEXT,
                    cve_ids TEXT,
                    observed_at TEXT,
                    UNIQUE(source, advisory_id, package, repository_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_repos_stars ON repositories(stars)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_repos_collected ON repositories(collected_at)
            """)
            conn.commit()

    @staticmethod
    def _ensure_category_parent_column(conn: sqlite3.Connection) -> None:
        """Add ``categories.parent_id`` to databases created before it existed."""
        columns = {row[1] for row in conn.execute("PRAGMA table_info(categories)")}
        if "parent_id" in columns:
            return
        conn.execute("ALTER TABLE categories ADD COLUMN parent_id INTEGER REFERENCES categories(id)")

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

    def save_categories(
        self,
        repo_id: str,
        categories: list[str],
        parents: dict[str, str] | None = None,
    ) -> None:
        """Attach leaf categories to a repository.

        ``parents`` maps a leaf name to its parent name; parents are persisted as
        their own rows so the two-level taxonomy survives a round-trip.
        """
        parent_names = parents or {}
        with self._lock, self._get_connection() as conn:
            parent_ids: dict[str, int] = {}
            for parent_name in dict.fromkeys(parent_names.values()):
                parent_ids[parent_name] = self._upsert_category(conn, parent_name)

            for cat_name in categories:
                cat_id = self._upsert_category(conn, cat_name, parent_names.get(cat_name))
                conn.execute(
                    "INSERT OR IGNORE INTO repository_categories (repository_id, category_id) VALUES (?, ?)",
                    (repo_id, cat_id),
                )
            conn.commit()

    @staticmethod
    def _upsert_category(
        conn: sqlite3.Connection, name: str, parent_name: str | None = None
    ) -> int:
        parent_id = None
        if parent_name and parent_name != name:
            conn.execute(
                "INSERT OR IGNORE INTO categories (name, parent_id) VALUES (?, NULL)",
                (parent_name,),
            )
            parent_id = conn.execute(
                "SELECT id FROM categories WHERE name = ?", (parent_name,)
            ).fetchone()[0]

        conn.execute(
            "INSERT OR IGNORE INTO categories (name, parent_id) VALUES (?, ?)",
            (name, parent_id),
        )
        row = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise ValueError(f"Failed to persist category: {name}")
        return row[0]

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

    def get_repository(self, repo_id: str) -> dict | None:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
            if row:
                return dict(row)
        return None

    def get_all_repositories(self, limit: int | None = None) -> list[dict]:
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

    def get_all_categories(self) -> dict[str, list[str]]:
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT rc.repository_id, c.name FROM repository_categories rc
                JOIN categories c ON rc.category_id = c.id
            """).fetchall()
        categories: dict[str, list[str]] = {}
        for repo_id, name in rows:
            categories.setdefault(repo_id, []).append(name)
        for names in categories.values():
            names.sort()
        return categories

    def get_category_parents(self) -> dict[str, str | None]:
        """Map every known category name to its parent name, or ``None`` for parents."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT child.name, parent.name FROM categories child
                LEFT JOIN categories parent ON child.parent_id = parent.id
            """).fetchall()
        return {child: parent for child, parent in rows}

    def get_category_tree(self) -> dict[str, list[str]]:
        """Return ``{parent: [leaf, ...]}`` for every category that has a parent."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT parent.name, child.name FROM categories child
                JOIN categories parent ON child.parent_id = parent.id
                ORDER BY parent.name, child.name
            """).fetchall()
        tree: dict[str, list[str]] = {}
        for parent, child in rows:
            tree.setdefault(parent, []).append(child)
        return tree

    def get_all_sources(self) -> dict[str, list[dict]]:
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT repository_id, source_repository, source_section FROM sources
            """).fetchall()
        sources: dict[str, list[dict]] = {}
        for repo_id, source_repo, section in rows:
            sources.setdefault(repo_id, []).append({
                "repository": source_repo,
                "section": section,
            })
        return sources

    def save_security_findings(self, findings: list[dict]) -> int:
        """Upsert enrichment findings; returns the number of rows written."""
        import json as _json

        written = 0
        with self._lock, self._get_connection() as conn:
            for f in findings:
                conn.execute("""
                    INSERT INTO security_findings
                    (repository_id, source, advisory_id, package, ecosystem,
                     severity, summary, url, cve_ids, observed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source, advisory_id, package, repository_id)
                    DO UPDATE SET severity = excluded.severity,
                                  summary = excluded.summary,
                                  observed_at = excluded.observed_at
                """, (
                    f.get("repository_id") or "",
                    f.get("source", ""),
                    f.get("advisory_id", ""),
                    f.get("package", ""),
                    f.get("ecosystem", ""),
                    f.get("severity", ""),
                    f.get("summary", ""),
                    f.get("url", ""),
                    _json.dumps(f.get("cve_ids") or []),
                    f.get("observed_at", ""),
                ))
                written += 1
            conn.commit()
        return written

    def get_security_findings(
        self, repository_id: str | None = None
    ) -> list[dict]:
        import json as _json

        with self._get_connection() as conn:
            if repository_id:
                rows = conn.execute(
                    "SELECT * FROM security_findings WHERE repository_id = ?",
                    (repository_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM security_findings ORDER BY source, advisory_id"
                ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            try:
                d["cve_ids"] = _json.loads(d.get("cve_ids") or "[]")
            except Exception:
                d["cve_ids"] = []
            out.append(d)
        return out

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