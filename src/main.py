import json
import sys
import click
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.models import Repository
from src.normalize.urls import repository_id_from_url, normalize_url
from src.normalize.repository import normalize_repository, create_repository_from_api
from src.normalize.dedupe import dedupe_repositories
from src.scoring.security import health_status, get_refresh_interval
from src.storage.json_store import JsonStore, utc_now_iso
from src.storage.sqlite import SqliteStore
from src.storage.markdown import MarkdownRenderer, utc_today


def _get_github_client(token: Optional[str]):
    from src.github.client import GitHubClient
    return GitHubClient(token=token) if token else None


class CLICommands:
    def __init__(self, config_dir: str = "config", data_dir: str = "data"):
        self.config_dir = config_dir
        self.data_dir = data_dir
        self.json_store = JsonStore(data_dir)
        self.sqlite_store = SqliteStore(f"{data_dir}/database/awesome.sqlite")
        self.renderer = MarkdownRenderer()

    def collect(
        self,
        category: Optional[str] = None,
        github_token: Optional[str] = None,
        dry_run: bool = False,
    ) -> dict:
        client = _get_github_client(github_token)
        try:
            from src.discovery import DiscoveryEngine
            from src.discovery.awesome_lists import AwesomeListDiscoverer

            collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            engine = DiscoveryEngine(client)
            results = engine.discover_all()

            raw_repos = []
            for result in results:
                repo_data = result.get("repository", {})
                repo = create_repository_from_api(repo_data, collected_at)
                repo = normalize_repository(repo)
                raw_repos.append(repo)

            deduped, duplicates = dedupe_repositories(raw_repos)

            for repo in deduped:
                for dup in duplicates:
                    if dup.primary.id == repo.id:
                        for d in dup.duplicates:
                            for s in d.sources:
                                repo.sources.append(s)

                if repo.sources and not repo.awesome:
                    repo.awesome = {"is_awesome_list": False}

                if not dry_run:
                    self.json_store.save_repository(repo)
                    self.sqlite_store.save_repository(repo)

                    categories = []
                    if repo.awesome and repo.awesome.get("categories"):
                        categories = repo.awesome["categories"]
                    if categories:
                        self.sqlite_store.save_categories(repo.id, categories)
                    if repo.sources:
                        self.sqlite_store.save_sources(repo.id, repo.sources)

            return {
                "collected": len(deduped),
                "duplicates_merged": len(duplicates),
                "new": len(deduped),
                "collected_at": collected_at,
                "category": category,
                "dry_run": dry_run,
            }
        finally:
            if client:
                client.close()

    def sync(self, github_token: Optional[str] = None) -> dict:
        return self.collect(github_token=github_token)

    def update(self, github_token: Optional[str] = None) -> dict:
        return self.collect(github_token=github_token)

    def validate(self) -> dict:
        repos = self.json_store.get_all_repositories()
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

    def score(self, github_token: Optional[str] = None) -> dict:
        from src.scoring import ScoringEngine

        client = _get_github_client(github_token)
        try:
            engine = ScoringEngine(client)
            repos = self.sqlite_store.get_all_repositories()
            scored = 0
            for repo_data in repos:
                repo = Repository.from_dict(repo_data)
                score = engine.score_repository(repo)
                repo.score = score
                repo.health = engine.classify_health(repo)
                self.sqlite_store.save_repository(repo)
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

    def diff(self, date1: str, date2: str) -> dict:
        snap1 = self._load_daily_snapshot(date1)
        snap2 = self._load_daily_snapshot(date2)
        if not snap1 or not snap2:
            return {"error": "Missing snapshots for one or both dates"}

        repos1 = {r["id"]: r for r in snap1.get("repositories", [])}
        repos2 = {r["id"]: r for r in snap2.get("repositories", [])}

        new_repos = []
        trending = []
        for rid, repo in repos2.items():
            if rid not in repos1:
                new_repos.append(repo)
            else:
                star_gain = (repo.get("stars", 0) or 0) - (repos1[rid].get("stars", 0) or 0)
                if star_gain >= 500:
                    trending.append({**repo, "star_gain": star_gain})

        removed = [repos1[rid] for rid in repos1 if rid not in repos2]

        return {
            "date1": date1,
            "date2": date2,
            "new": new_repos,
            "new_count": len(new_repos),
            "trending": trending,
            "trending_count": len(trending),
            "updated": [r for r in repos2.values() if r["id"] in repos1],
            "updated_count": len([r for r in repos2.values() if r["id"] in repos1]),
            "stale": [],
            "archived": [],
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

    def trending(self, github_token: Optional[str] = None) -> dict:
        repos = self.sqlite_store.get_all_repositories()
        scored = []
        for r in repos:
            repo = Repository.from_dict(r)
            if repo.score and repo.score.get("overall", 0) >= 75:
                scored.append(repo)
        scored.sort(key=lambda r: (r.score.get("overall", 0) if r.score else 0), reverse=True)
        return {"trending": [r.to_dict() for r in scored[:20]], "total": len(scored)}

    def _load_daily_snapshot(self, date_str: str) -> Optional[dict]:
        snap_path = Path(self.data_dir) / "daily" / f"{date_str}.json"
        if snap_path.exists():
            with open(snap_path, "r") as f:
                return json.load(f)
        return None


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Awesome Collector - Daily GitHub Awesome Repository Collector"""
    pass


@cli.command()
@click.option("--category", default=None, help="Filter by category")
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
def export(fmt):
    """Export data"""
    commands = CLICommands()
    result = commands.export(fmt=fmt)
    if isinstance(result, str) and (result.startswith("[") or result.startswith("{")):
        click.echo(result[:5000])
    else:
        click.echo(result)


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