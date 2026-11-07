import json
import os
from datetime import UTC, datetime
from pathlib import Path

import click

from src.config import load_categories
from src.normalize.dedupe import dedupe_repositories
from src.normalize.repository import create_repository_from_api, normalize_repository
from src.normalize.urls import repository_from_row
from src.parser.categories import (
    category_parents,
    classify_repository,
    section_to_category,
)
from src.storage.json_store import JsonStore, utc_now_iso
from src.storage.markdown import MarkdownRenderer, utc_today
from src.storage.sqlite import SqliteStore

_GENERATED_DOCS = ("sitemap.md", "llms.txt", "agents.md")
UNCATEGORIZED = "Uncategorized"


def _sort_key(entry: dict) -> tuple:
    return (entry.get("score", 0) or 0, entry.get("stars", 0) or 0)


def _get_github_client(token: str | None):
    from src.github.client import GitHubClient
    if token:
        return GitHubClient(token=token)
    if os.environ.get("GITHUB_TOKEN"):
        return GitHubClient(token=os.environ["GITHUB_TOKEN"])
    return None


class CLICommands:
    def __init__(self, config_dir: str = "config", data_dir: str = "data"):
        self.config_dir = config_dir
        self.data_dir = data_dir
        self.json_store = JsonStore(data_dir)
        self.sqlite_store = SqliteStore(f"{data_dir}/database/awesome.sqlite")
        self.renderer = MarkdownRenderer()
        self._taxonomy = None

    @property
    def taxonomy(self):
        """The category taxonomy, loaded lazily so commands that never
        categorize still run without ``config/categories.yml`` on disk."""
        if self._taxonomy is None:
            self._taxonomy = load_categories(self.config_dir)
        return self._taxonomy

    def _persist_categories(self, repo, categories: list[str]) -> None:
        if not categories:
            return
        self.sqlite_store.save_categories(
            repo.id, categories, category_parents(categories, self.taxonomy)
        )

    def collect_from_list(
        self,
        owner: str,
        repo: str,
        github_token: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        from src.discovery.awesome_lists import AwesomeListDiscoverer

        client = _get_github_client(github_token)
        collected_at = utc_now_iso()
        try:
            if client is None:
                return {
                    "source": f"{owner}/{repo}",
                    "collected": 0,
                    "error": "GITHUB_TOKEN is required to fetch repository metadata",
                }
            discoverer = AwesomeListDiscoverer(client)
            references = discoverer.discover_from_awesome_list(owner, repo)

            raw_repos = []
            for ref in references:
                repo_data = ref.get("repository", {})
                enriched = self._enrich(client, repo_data)
                item = normalize_repository(
                    create_repository_from_api(enriched, collected_at)
                )
                item.sources = [{
                    "repository": f"github:{owner}/{repo}",
                    "section": ref.get("section", ""),
                }]
                section = section_to_category(ref.get("section", ""), self.taxonomy)
                categories = list(self.taxonomy.filter_leaves(
                    [section] if section else []
                ))
                for name in classify_repository(item, self.taxonomy):
                    if name not in categories:
                        categories.append(name)
                item.awesome = {
                    "is_awesome_list": True,
                    "categories": categories,
                }
                raw_repos.append(item)

            deduped, duplicates = dedupe_repositories(raw_repos)
            if not dry_run:
                for item in deduped:
                    self.json_store.save_repository(item)
                    self.sqlite_store.save_repository(item)
                    categories = (item.awesome or {}).get("categories") or []
                    self._persist_categories(item, categories)
                    if item.sources:
                        self.sqlite_store.save_sources(item.id, item.sources)

            return {
                "source": f"{owner}/{repo}",
                "collected": len(deduped),
                "duplicates_merged": len(duplicates),
                "categorized": sum(
                    1 for item in deduped
                    if ((item.awesome or {}).get("categories") or [])
                ),
                "collected_at": collected_at,
                "dry_run": dry_run,
            }
        finally:
            if client:
                client.close()

    @staticmethod
    def _enrich(client, repo_data: dict) -> dict:
        from src.discovery.github_search import GithubSearcher
        data = dict(repo_data)
        owner = data.get("owner")
        if isinstance(owner, str):
            data["owner"] = {"login": owner}
        return GithubSearcher(client).enrich_repository_data(data)

    def collect(
        self,
        category: str | None = None,
        github_token: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        client = _get_github_client(github_token)
        try:
            from src.discovery import DiscoveryEngine

            collected_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            engine = DiscoveryEngine(client)
            results = engine.discover_all()

            raw_repos = []
            for result in results:
                repo_data = self._enrich(client, result.get("repository", {}))
                repo = create_repository_from_api(repo_data, collected_at)
                repo = normalize_repository(repo)
                raw_repos.append(repo)

            deduped, duplicates = dedupe_repositories(raw_repos)
            wanted = self._resolve_category_filter(category)

            categorized = 0
            for repo in deduped:
                for dup in duplicates:
                    if dup.primary.id == repo.id:
                        for d in dup.duplicates:
                            for s in d.sources:
                                repo.sources.append(s)

                repo.awesome = repo.awesome or {"is_awesome_list": False}
                categories = classify_repository(repo, self.taxonomy)
                if categories:
                    categorized += 1
                repo.awesome["categories"] = categories

                if not dry_run and (wanted is None or self._matches(repo, wanted)):
                    self.json_store.save_repository(repo)
                    self.sqlite_store.save_repository(repo)
                    self._persist_categories(repo, categories)
                    if repo.sources:
                        self.sqlite_store.save_sources(repo.id, repo.sources)

            return {
                "collected": len(deduped),
                "duplicates_merged": len(duplicates),
                "new": len(deduped),
                "categorized": categorized,
                "collected_at": collected_at,
                "category": category,
                "dry_run": dry_run,
            }
        finally:
            if client:
                client.close()

    def _resolve_category_filter(self, category: str | None) -> set[str] | None:
        """Turn a ``--category`` value into the set of leaves it selects."""
        if not category or category.lower() == "all":
            return None
        name = category.strip()
        taxonomy = self.taxonomy
        if taxonomy.has(name):
            return {name}
        if name in taxonomy.parents:
            return {leaf for leaf, parent in taxonomy.leaf_parent.items() if parent == name}
        return {leaf for leaf in taxonomy.leaves if leaf.lower() == name.lower()}

    @staticmethod
    def _matches(repo, wanted: set[str] | None) -> bool:
        if wanted is None:
            return True
        return bool(wanted & set((repo.awesome or {}).get("categories") or []))

    def discover(self, github_token: str | None = None) -> dict:
        from src.discovery import DiscoveryEngine
        from src.discovery.awesome_lists import AwesomeListDiscoverer

        client = _get_github_client(github_token)
        try:
            if client is None:
                return {
                    "discovered": 0,
                    "saved": 0,
                    "error": "GITHUB_TOKEN is required for discovery",
                }
            engine = DiscoveryEngine(client)
            lists = engine.discover_awesome_lists()
            discoverer = AwesomeListDiscoverer(client)

            saved = 0
            for item in lists:
                repo_data = item.get("repository", {})
                owner = repo_data.get("owner", {}).get("login", "")
                name = repo_data.get("name", "")
                if not owner or not name:
                    continue
                collected_at = utc_now_iso()
                self.json_store.save_awesome_list(
                    f"{owner}/{name}",
                    {
                        "id": f"github:{owner}/{name}",
                        "name": name,
                        "owner": owner,
                        "url": repo_data.get("html_url", f"https://github.com/{owner}/{name}"),
                        "description": repo_data.get("description"),
                        "stars": repo_data.get("stargazers_count"),
                        "language": repo_data.get("language"),
                        "topics": repo_data.get("topics", []),
                        "is_awesome_list": discoverer.is_awesome_list(repo_data),
                        "source": item.get("source"),
                        "query": item.get("query"),
                        "collected_at": collected_at,
                    },
                )
                saved += 1
            return {
                "discovered": len(lists),
                "saved": saved,
                "collected_at": utc_now_iso(),
            }
        finally:
            if client:
                client.close()

    def generate(self, docs_dir: str = "docs") -> dict:
        repos = self.sqlite_store.get_all_repositories()
        if not repos:
            repos = [r.to_dict() for r in self.json_store.get_all_repositories()]
        category_map = self.sqlite_store.get_all_categories()
        parent_map = self.sqlite_store.get_category_parents()

        generated_at = utc_now_iso()
        tree: dict[str, dict[str, list[dict]]] = {}
        for repo in repos:
            names = category_map.get(repo["id"], [])
            if not names:
                names = [UNCATEGORIZED]
            for name in names:
                parent = parent_map.get(name) or UNCATEGORIZED
                leaf = UNCATEGORIZED if name == UNCATEGORIZED else name
                tree.setdefault(parent, {}).setdefault(leaf, []).append({
                    "id": repo["id"],
                    "name": f"{repo['owner']}/{repo['name']}",
                    "url": repo["url"],
                    "description": repo.get("description"),
                    "stars": repo.get("stars") or 0,
                    "language": repo.get("language"),
                    "score": repo.get("score_overall") or 0,
                    "health": repo.get("health_status", "UNKNOWN"),
                    "category": name,
                    "parent": parent,
                })

        for leaves in tree.values():
            for entries in leaves.values():
                entries.sort(key=_sort_key, reverse=True)

        leaf_names = {leaf for leaves in tree.values() for leaf in leaves}
        total = len(repos)
        docs_path = Path(docs_dir)
        docs_path.mkdir(parents=True, exist_ok=True)

        if total == 0 and any((docs_path / name).exists() for name in _GENERATED_DOCS):
            return {
                "generated_at": generated_at,
                "repositories": 0,
                "categories": 0,
                "skipped": True,
                "reason": "No repositories collected; existing docs left untouched",
                "files": [],
            }

        stats = self.sqlite_store.get_stats()

        sitemap = self.renderer.render_sitemap(tree, total, generated_at)
        llms_txt = self.renderer.render_llms_txt(tree, total, generated_at)
        agents_md = self.renderer.render_agents_md(tree, stats, total)

        with open(docs_path / "sitemap.md", "w", encoding="utf-8") as f:
            f.write(sitemap)
        with open(docs_path / "llms.txt", "w", encoding="utf-8") as f:
            f.write(llms_txt)
        with open(docs_path / "agents.md", "w", encoding="utf-8") as f:
            f.write(agents_md)

        self.json_store.save_index({
            "last_updated": generated_at,
            "total": total,
            "categories": {
                parent: [entry["id"] for entries in leaves.values() for entry in entries]
                for parent, leaves in tree.items()
            },
            "category_tree": {
                parent: {leaf: [e["id"] for e in entries] for leaf, entries in leaves.items()}
                for parent, leaves in tree.items()
            },
            "repositories": [
                {
                    "id": r["id"],
                    "name": f"{r['owner']}/{r['name']}",
                    "url": r["url"],
                    "stars": r.get("stars"),
                    "score": r.get("score_overall"),
                    "health": r.get("health_status"),
                }
                for r in repos
            ],
        })

        snapshot = {
            "date": utc_today(),
            "generated_at": generated_at,
            "summary": {"total": total, "categories": len(leaf_names), "parents": len(tree)},
            "sections": [
                {"title": parent, "category": parent, "repositories": leaves}
                for parent, leaves in sorted(tree.items())
            ],
            "repositories": repos,
        }
        self.json_store.save_daily_snapshot(utc_today(), snapshot)

        return {
            "generated_at": generated_at,
            "repositories": total,
            "categories": len(leaf_names),
            "category_parents": len(tree),
            "files": [
                f"{docs_path}/sitemap.md",
                f"{docs_path}/llms.txt",
                f"{docs_path}/agents.md",
                f"{self.data_dir}/index.json",
                f"{self.data_dir}/daily/{utc_today()}.json",
            ],
        }

    def sync(self, github_token: str | None = None) -> dict:
        return self.collect(github_token=github_token)

    def update(self, github_token: str | None = None) -> dict:
        return self.collect(github_token=github_token)

    def _refresh_policy(self) -> dict[str, int]:
        """Load health→interval-days mapping from ``config/sources.yml``."""
        from src.config import load_config
        from src.refresh import DEFAULT_REFRESH_POLICY

        try:
            sources = load_config(self.config_dir, "sources")
            policy = (sources.get("incremental") or {}).get("refresh_policy")
            if isinstance(policy, dict) and policy:
                return {str(k): int(v) for k, v in policy.items()}
        except Exception:
            pass
        return dict(DEFAULT_REFRESH_POLICY)

    def refresh(
        self,
        github_token: str | None = None,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> dict:
        """Incrementally refresh repository metadata based on health status.

        Only repositories whose last check (``collected_at``) is older than
        the interval for their health status are re-fetched, which reduces
        GitHub API usage compared to a full ``collect`` run.
        """
        from src.refresh import select_due_repositories
        from src.scoring.activity import ActivityTracker

        client = _get_github_client(github_token)
        if client is None:
            return {
                "checked": 0,
                "updated": 0,
                "skipped": 0,
                "failed": 0,
                "error": "GITHUB_TOKEN is required to refresh repository metadata",
            }

        try:
            rows = self.sqlite_store.get_all_repositories()
            repos = [repository_from_row(r) for r in rows]
            selection = select_due_repositories(repos, policy=self._refresh_policy())
            due = selection.due[:limit] if limit else selection.due

            tracker = ActivityTracker(client)
            checked = updated = failed = 0
            refreshed_at = utc_now_iso()
            for repo in due:
                checked += 1
                try:
                    owner, name = repo.id[len("github:"):].split("/", 1)
                    data = client.get_repository(owner, name)
                    fresh = create_repository_from_api(data, refreshed_at)
                    fresh = normalize_repository(fresh)
                    fresh.id = repo.id
                    fresh.owner = repo.owner
                    fresh.name = repo.name
                    fresh.awesome = repo.awesome
                    fresh.sources = repo.sources
                    fresh.score = repo.score
                    health = tracker.get_push_health(fresh)
                    fresh.health = {
                        "status": health.get("status", "UNKNOWN"),
                        "last_commit_days": health.get("last_push_days"),
                        "release_days": None,
                        "contributors_90d": None,
                    }
                    if not dry_run:
                        self.json_store.save_repository(fresh)
                        self.sqlite_store.save_repository(fresh)
                        if fresh.sources:
                            self.sqlite_store.save_sources(fresh.id, fresh.sources)
                    updated += 1
                except Exception:
                    failed += 1

            return {
                "checked": checked,
                "updated": updated,
                "skipped": len(selection.skipped) + max(0, len(selection.due) - len(due)),
                "failed": failed,
                "due": len(selection.due),
                "refreshed_at": refreshed_at,
                "dry_run": dry_run,
                "policy": self._refresh_policy(),
            }
        finally:
            client.close()

    def validate(self) -> dict:
        repos = self.json_store.get_all_repositories()
        if not repos:
            repos = [
                repository_from_row(r) for r in self.sqlite_store.get_all_repositories()
            ]
        errors = []
        valid = []
        for repo in repos:
            missing = []
            if not repo.id:
                missing.append("id")
            if not repo.owner:
                missing.append("owner")
            if not repo.name:
                missing.append("name")
            if not repo.url:
                missing.append("url")
            if not repo.collected_at:
                missing.append("collected_at")
            if missing:
                errors.append(f"{repo.id or 'unknown'}: missing {', '.join(missing)}")
            else:
                valid.append(repo)
        return {
            "total": len(repos),
            "valid": len(valid),
            "errors": len(errors),
            "error_details": errors[:20],
        }

    def score(self, github_token: str | None = None) -> dict:
        from src.scoring import ScoringEngine

        client = _get_github_client(github_token)
        try:
            engine = ScoringEngine(client)
            repos = self.sqlite_store.get_all_repositories()
            scored = 0
            for repo_data in repos:
                repo = repository_from_row(repo_data)
                score = engine.score_repository(repo)
                repo.score = score
                repo.health = engine.classify_health(repo)
                self.sqlite_store.save_repository(repo)
                self.json_store.save_repository(repo)
                scored += 1
            return {"scored": scored}
        finally:
            if client:
                client.close()

    def report(self, daily: bool = False) -> str:
        if daily:
            date_str = utc_today()
            snapshot = self._load_daily_snapshot(date_str)
            if snapshot:
                return self.renderer.render_report(
                    date_str,
                    snapshot.get("summary", {}),
                    snapshot.get("sections", []),
                )
            return f"No daily report available for {date_str}"

        stats = self.sqlite_store.get_stats()
        repos = self.sqlite_store.get_all_repositories(limit=20)
        rows = []
        for r in repos:
            rows.append([r["id"], r.get("stars", 0), r.get("language", ""), r.get("score_overall", 0)])
        table = self.renderer.render_markdown_table(
            ["Repository", "Stars", "Language", "Score"], rows
        )
        return f"# Repository Report\n\nTotal: {stats['total']}\n\n{table}"

    # Fields compared between two daily snapshots to detect "updated" repos.
    # ``health``/``score`` are normalized from both storage shapes
    # (sqlite columns ``health_status``/``score_overall`` and the nested
    # ``health.status``/``score.overall`` dicts produced by ``to_dict``).
    DIFF_FIELDS = (
        "stars",
        "forks",
        "issues",
        "language",
        "description",
        "license",
        "topics",
        "archived",
        "pushed_at",
        "updated_at",
        "health_status",
        "score_overall",
    )

    @classmethod
    def _snapshot_comparable(cls, repo: dict) -> dict:
        """Extract the comparable fields from a snapshot repository record."""
        health = repo.get("health") or {}
        score = repo.get("score") or {}
        comparable = {field: repo.get(field) for field in cls.DIFF_FIELDS}
        comparable["health_status"] = (
            repo.get("health_status") or health.get("status")
        )
        comparable["score_overall"] = (
            repo.get("score_overall")
            if repo.get("score_overall") is not None
            else score.get("overall")
        )
        return comparable

    @classmethod
    def _repo_changes(cls, old: dict, new: dict) -> dict:
        """Return ``{field: {"from": old, "to": new}}`` for fields that differ."""
        old_cmp = cls._snapshot_comparable(old)
        new_cmp = cls._snapshot_comparable(new)
        changes = {}
        for field in cls.DIFF_FIELDS:
            old_val = old_cmp.get(field)
            new_val = new_cmp.get(field)
            if old_val != new_val:
                changes[field] = {"from": old_val, "to": new_val}
        return changes

    @staticmethod
    def _snapshot_health(repo: dict) -> str:
        health = repo.get("health") or {}
        return repo.get("health_status") or health.get("status") or "UNKNOWN"

    @staticmethod
    def _is_stale(repo: dict) -> bool:
        if CLICommands._snapshot_health(repo) == "STALE":
            return True
        pushed_at = repo.get("pushed_at")
        if not pushed_at:
            return False
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(str(pushed_at))
            return (datetime.now(UTC) - dt).days > 180
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _is_archived(repo: dict) -> bool:
        return bool(repo.get("archived")) or CLICommands._snapshot_health(repo) == "ARCHIVED"

    def diff(self, date1: str, date2: str) -> dict:
        snap1 = self._load_daily_snapshot(date1)
        snap2 = self._load_daily_snapshot(date2)
        if not snap1 or not snap2:
            return {"error": "Missing snapshots for one or both dates"}

        repos1 = {r["id"]: r for r in snap1.get("repositories", [])}
        repos2 = {r["id"]: r for r in snap2.get("repositories", [])}

        new_repos = []
        trending = []
        updated = []
        for rid, repo in repos2.items():
            if rid not in repos1:
                new_repos.append(repo)
                continue
            old = repos1[rid]
            star_gain = (repo.get("stars", 0) or 0) - (old.get("stars", 0) or 0)
            if star_gain >= 500:
                trending.append({**repo, "star_gain": star_gain})
            changes = self._repo_changes(old, repo)
            if changes:
                updated.append({**repo, "changes": changes})

        removed = [repos1[rid] for rid in repos1 if rid not in repos2]

        current = list(repos2.values())
        stale = [r for r in current if self._is_stale(r)]
        archived = [r for r in current if self._is_archived(r)]

        return {
            "date1": date1,
            "date2": date2,
            "compared_fields": list(self.DIFF_FIELDS),
            "new": new_repos,
            "new_count": len(new_repos),
            "trending": trending,
            "trending_count": len(trending),
            "updated": updated,
            "updated_count": len(updated),
            "stale": stale,
            "stale_count": len(stale),
            "archived": archived,
            "archived_count": len(archived),
            "removed": removed,
            "removed_count": len(removed),
        }

    def export(self, fmt: str = "json") -> str:
        if fmt == "json":
            repos = self.sqlite_store.get_all_repositories()
            data = [dict(r) for r in repos]
            return json.dumps(data, default=str)
        elif fmt == "sqlite":
            return self.sqlite_store.db_path
        return f"Unsupported format: {fmt}"

    def export_to_file(self, path: str, fmt: str = "json") -> dict:
        """Write a full export to ``path`` without truncating the payload."""
        payload = self.export(fmt=fmt)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
        return {"format": fmt, "path": str(out), "bytes": out.stat().st_size}

    def enrich_security(
        self,
        sources: list[str] | None = None,
        min_stars: int = 0,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Run security/supply-chain enrichment (OSV, CVE, CISA KEV).

        Provider outages and rate limits are reported under
        ``provider_errors`` and never abort the run.
        """
        from src.enrichment.security import SecurityEnricher

        rows = self.sqlite_store.get_all_repositories()
        if not rows:
            rows = [r.to_dict() for r in self.json_store.get_all_repositories()]
        repos = [repository_from_row(r) for r in rows]
        if limit:
            repos = repos[:limit]

        enricher = SecurityEnricher(sources=sources)
        report = enricher.collect(repos, min_stars=min_stars)
        report["dry_run"] = dry_run
        if not dry_run and report["findings"]:
            report["stored"] = self.sqlite_store.save_security_findings(
                report["findings"]
            )
        return report

    def security_findings(self, repository_id: str | None = None) -> dict:
        findings = self.sqlite_store.get_security_findings(repository_id)
        return {"findings": findings, "count": len(findings)}

    def extract_content(
        self,
        github_token: str | None = None,
        min_score: float = 0.0,
        max_repositories: int = 100,
        dry_run: bool = False,
    ) -> dict:
        """Extract README/docs/API references for repos above a score threshold."""
        from src.extraction.content import ContentExtractor, ExtractionConfig

        client = _get_github_client(github_token)
        if client is None:
            return {
                "selected": 0, "succeeded": 0, "skipped": 0, "failed": 0,
                "error": "GITHUB_TOKEN is required to fetch repository content",
            }
        try:
            rows = self.sqlite_store.get_all_repositories()
            if not rows:
                rows = []
                for r in self.json_store.get_all_repositories():
                    d = r.to_dict()
                    d["score_overall"] = (r.score or {}).get("overall", 0)
                    rows.append(d)
            extractor = ContentExtractor(
                client,
                ExtractionConfig(
                    min_score=min_score, max_repositories=max_repositories
                ),
            )
            report, payloads = extractor.run(rows)
            if not dry_run:
                for payload in payloads:
                    self.json_store.save_content(payload["repository_id"], payload)
            result = report.to_dict()
            result["dry_run"] = dry_run
            result["min_score"] = min_score
            return result
        finally:
            client.close()

    def trending(self, github_token: str | None = None) -> dict:
        repos = self.sqlite_store.get_all_repositories()
        scored = []
        for r in repos:
            repo = repository_from_row(r)
            if repo.score and repo.score.get("overall", 0) >= 75:
                scored.append(repo)
        scored.sort(key=lambda r: (r.score.get("overall", 0) if r.score else 0), reverse=True)
        return {"trending": [r.to_dict() for r in scored[:20]], "total": len(scored)}

    def _load_daily_snapshot(self, date_str: str) -> dict | None:
        snap_path = Path(self.data_dir) / "daily" / f"{date_str}.json"
        if snap_path.exists():
            with open(snap_path, "r") as f:
                return json.load(f)
        return None


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Awesome Collector - Daily GitHub Awesome Repository Collector"""


@cli.command()
@click.option(
    "--category",
    default=None,
    help="Only collect repositories in this category (taxonomy leaf or parent name)",
)
@click.option("--github-token", envvar="GITHUB_TOKEN", default=None)
@click.option("--dry-run", is_flag=True, help="Preview without saving")
def collect(category, github_token, dry_run):
    """Collect awesome repositories"""
    commands = CLICommands()
    result = commands.collect(category=category, github_token=github_token, dry_run=dry_run)
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.option("--github-token", envvar="GITHUB_TOKEN", default=None)
def discover(github_token):
    """Discover awesome lists"""
    commands = CLICommands()
    result = commands.discover(github_token=github_token)
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.argument("owner")
@click.argument("repo")
@click.option("--github-token", envvar="GITHUB_TOKEN", default=None)
@click.option("--dry-run", is_flag=True, help="Preview without saving")
def collect_from(owner, repo, github_token, dry_run):
    """Collect repositories referenced by one awesome list"""
    commands = CLICommands()
    result = commands.collect_from_list(
        owner=owner, repo=repo, github_token=github_token, dry_run=dry_run
    )
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.option("--docs-dir", default="docs", help="Directory for generated docs")
def generate(docs_dir):
    """Generate indexes and documentation artifacts"""
    commands = CLICommands()
    result = commands.generate(docs_dir=docs_dir)
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.option("--github-token", envvar="GITHUB_TOKEN", default=None)
def sync(github_token):
    """Sync repository data"""
    commands = CLICommands()
    result = commands.sync(github_token=github_token)
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.option("--github-token", envvar="GITHUB_TOKEN", default=None)
def update(github_token):
    """Update repository metadata"""
    commands = CLICommands()
    result = commands.update(github_token=github_token)
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.option("--github-token", envvar="GITHUB_TOKEN", default=None)
@click.option("--dry-run", is_flag=True, help="Preview without saving")
@click.option("--limit", type=int, default=None, help="Max repositories to refresh")
def refresh(github_token, dry_run, limit):
    """Incrementally refresh metadata for repositories due per health policy"""
    commands = CLICommands()
    result = commands.refresh(
        github_token=github_token, dry_run=dry_run, limit=limit
    )
    click.echo(json.dumps(result, indent=2))


@cli.command()
def validate():
    """Validate dataset integrity"""
    commands = CLICommands()
    result = commands.validate()
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.option("--github-token", envvar="GITHUB_TOKEN", default=None)
def score(github_token):
    """Score all repositories"""
    commands = CLICommands()
    result = commands.score(github_token=github_token)
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.option("--daily", is_flag=True, help="Generate daily report")
def report(daily):
    """Generate reports"""
    commands = CLICommands()
    result = commands.report(daily=daily)
    click.echo(result)


@cli.command()
@click.argument("date1")
@click.argument("date2")
def diff(date1, date2):
    """Compare two daily snapshots"""
    commands = CLICommands()
    result = commands.diff(date1, date2)
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "sqlite"]))
@click.option(
    "--output", "-o", default=None,
    help="Write the export to this file path instead of stdout",
)
@click.option(
    "--include-findings", is_flag=True,
    help="Include stored security/supply-chain findings in JSON export",
)
def export(fmt, output, include_findings):
    """Export data"""
    commands = CLICommands()
    if include_findings and fmt == "json":
        payload = {
            "repositories": json.loads(commands.export(fmt="json")),
            "security_findings": commands.security_findings()["findings"],
        }
        text = json.dumps(payload, default=str)
        if output:
            out = Path(output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")
            click.echo(json.dumps({"path": str(out), "bytes": out.stat().st_size}))
        else:
            click.echo(text)
        return
    if output:
        result = commands.export_to_file(output, fmt=fmt)
        click.echo(json.dumps(result, indent=2))
        return
    result = commands.export(fmt=fmt)
    click.echo(result)


@cli.command()
@click.option(
    "--source", "sources", multiple=True,
    type=click.Choice(["osv", "cve", "cisa-kev"]),
    help="Enrichment provider to query (repeatable; default: all)",
)
@click.option("--min-stars", type=int, default=0, help="Only enrich repos with >= N stars")
@click.option("--limit", type=int, default=None, help="Max repositories to enrich")
@click.option("--dry-run", is_flag=True, help="Query providers without storing findings")
def enrich(sources, min_stars, limit, dry_run):
    """Enrich repositories with security/supply-chain findings (OSV, CVE, CISA KEV)"""
    commands = CLICommands()
    result = commands.enrich_security(
        sources=list(sources) or None,
        min_stars=min_stars,
        limit=limit,
        dry_run=dry_run,
    )
    click.echo(json.dumps(result, indent=2, default=str))


@cli.command()
@click.option("--github-token", envvar="GITHUB_TOKEN", default=None)
@click.option("--min-score", type=float, default=0.0, help="Minimum quality score")
@click.option("--max-repositories", type=int, default=100, help="Max repos per run")
@click.option("--dry-run", is_flag=True, help="Extract without saving")
def extract(github_token, min_score, max_repositories, dry_run):
    """Extract README/docs/API references for high-quality repositories"""
    commands = CLICommands()
    result = commands.extract_content(
        github_token=github_token,
        min_score=min_score,
        max_repositories=max_repositories,
        dry_run=dry_run,
    )
    click.echo(json.dumps(result, indent=2, default=str))


@cli.command()
@click.option("--repository", default=None, help="Filter findings to one repository id")
def findings(repository):
    """List stored security/supply-chain findings"""
    commands = CLICommands()
    result = commands.security_findings(repository_id=repository)
    click.echo(json.dumps(result, indent=2, default=str))


@cli.command()
@click.option("--github-token", envvar="GITHUB_TOKEN", default=None)
def trending(github_token):
    """Show trending repositories"""
    commands = CLICommands()
    result = commands.trending(github_token=github_token)
    top = result["trending"][:10]
    for i, repo in enumerate(top, 1):
        name = repo.get("name", repo.get("id", "?"))
        score = repo.get("score", {}).get("overall", "N/A") if repo.get("score") else "N/A"
        stars = repo.get("stars", 0) or 0
        health = repo.get("health", {}).get("status", "N/A")
        click.echo(f"{i:2d}. {name} | {stars:,} stars | Score: {score} | {health}")


if __name__ == "__main__":
    cli()