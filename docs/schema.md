# Data Schema

## Repository Record

```json
{
  "id": "github:owner/repository",
  "platform": "github",
  "owner": "example",
  "name": "awesome-security",
  "url": "https://github.com/example/awesome-security",
  "description": "...",
  "stars": 12000,
  "forks": 1300,
  "issues": 42,
  "language": "Markdown",
  "topics": ["awesome-list", "security", "resources"],
  "license": "MIT",
  "archived": false,
  "awesome": {
    "is_awesome_list": true,
    "categories": ["security", "tools", "resources"]
  },
  "sources": [
    { "repository": "github:someone/awesome-security", "section": "Security Tools" }
  ],
  "activity": { "last_push": "2026-09-14", "commits_30d": 4 },
  "score": { "overall": 91, "quality": 95, "activity": 88 },
  "health": { "status": "ACTIVE", "last_commit_days": 2, "release_days": 14 },
  "collected_at": "2026-09-15T02:30:00Z"
}
```

## SQLite Schema

```sql
CREATE TABLE repositories (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT,
    stars INTEGER,
    forks INTEGER,
    language TEXT,
    license TEXT,
    archived BOOLEAN,
    created_at TEXT,
    updated_at TEXT,
    pushed_at TEXT,
    collected_at TEXT,
    health_status TEXT DEFAULT 'UNKNOWN',
    score_overall REAL DEFAULT 0
);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE
);

CREATE TABLE repository_categories (
    repository_id TEXT,
    category_id INTEGER,
    PRIMARY KEY(repository_id, category_id),
    FOREIGN KEY(category_id) REFERENCES categories(id)
);

CREATE TABLE sources (
    repository_id TEXT,
    source_repository TEXT,
    source_section TEXT,
    PRIMARY KEY(repository_id, source_repository, source_section)
);

CREATE TABLE daily_metrics (
    repository_id TEXT,
    date TEXT,
    stars INTEGER,
    forks INTEGER,
    issues INTEGER,
    PRIMARY KEY(repository_id, date)
);
```

## Daily Snapshot

```json
{
  "date": "2026-09-15",
  "summary": {
    "awesome_lists_discovered": 2431,
    "repositories_tracked": 184293,
    "new_repositories": 183,
    "updated_repositories": 931,
    "trending_repositories": 42,
    "archived": 8
  },
  "repositories": [...],
  "changes": {
    "new": 183,
    "updated": 931,
    "trending": 42,
    "archived": 8,
    "stale": 27,
    "removed": 13
  },
  "timestamp": "2026-09-15T02:30:00Z"
}
```

## Scoring Model

| Factor | Weight | Source |
|---|---|---|
| Popularity | 20% | Stars, forks, contributors |
| Activity | 20% | Last push, commits, releases |
| Maintenance | 20% | README, license, issue response |
| Community | 15% | Contributors, forks, engagement |
| Documentation | 10% | README quality, docs |
| License | 5% | Permissive/copyleft |
| Security | 5% | Security policy, tools |
| Awesome Quality | 5% | Curation depth |

## Health Classification

| Status | Criteria |
|---|---|
| ACTIVE | Last push ≤ 7 days, release ≤ 14 days, ≥3 contributors 90d |
| MAINTAINED | Last push ≤ 30 days |
| SLOW | Last push ≤ 90 days |
| STALE | Last push ≤ 180 days |
| ARCHIVED | Repository archived |
| UNKNOWN | No data available |

## Refresh Policy

| Health | Interval |
|---|---|
| ACTIVE | 1 day |
| MAINTAINED | 3 days |
| SLOW | 7 days |
| STALE | 30 days |
| ARCHIVED | 90 days |
| UNKNOWN | 14 days |