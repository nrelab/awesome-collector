import io
from datetime import datetime, timezone
from typing import Any, Optional

from src.models import Repository


class MarkdownRenderer:
    def render_report(self, date_str: str, summary: dict, sections: list[dict]) -> str:
        lines = [
            f"# Awesome Repository Report",
            f"## {date_str}",
            "",
            "### Summary",
            "",
        ]

        for key, value in summary.items():
            label = key.replace("_", " ").title()
            if isinstance(value, (int, float)):
                lines.append(f"- {label}: {value:,}" if isinstance(value, int) and value > 1000 else f"- {label}: {value}")
            else:
                lines.append(f"- {label}: {value}")

        lines.append("")

        for section in sections:
            title = section.get("title", "Unknown")
            repos = section.get("repositories", [])
            if repos:
                lines.append(f"## {title}")
                lines.append("")
                lines.append("| Repository | Stars | Category | Score |")
                lines.append("|---|---:|---|---:|")
                for repo in repos:
                    name = repo.get("name", "")
                    stars = repo.get("stars", 0) or 0
                    category = repo.get("category", "")
                    score = repo.get("score", 0) or 0
                    lines.append(f"| {name} | {stars:,} | {category} | {score} |")
                lines.append("")

        return "\n".join(lines)

    def render_daily_diff(self, changes: dict) -> str:
        lines = [
            "# Daily Change Report",
            "",
            "## NEW",
            "",
        ]
        new_repos = changes.get("new", [])
        lines.append(f"+ {len(new_repos)} new repositories")
        for repo in new_repos:
            name = repo.get("name", "")
            stars = repo.get("stars", 0) or 0
            lines.append(f"  - {name} ({stars:,} stars)")

        lines.append("")
        lines.append("## TRENDING")
        lines.append("")
        trending = changes.get("trending", [])
        lines.append(f"\u2191 {len(trending)} repositories gained >500 stars")
        for repo in trending:
            name = repo.get("name", "")
            gain = repo.get("star_gain", 0)
            lines.append(f"  - {name} (+{gain:,})")

        lines.append("")
        lines.append("## UPDATED")
        lines.append("")
        updated = changes.get("updated", [])
        lines.append(f"\u2192 {len(updated)} repositories updated")

        lines.append("")
        lines.append("## STALE")
        lines.append("")
        stale = changes.get("stale", [])
        lines.append(f"\u2193 {len(stale)} repositories became inactive")

        lines.append("")
        lines.append("## ARCHIVED")
        lines.append("")
        archived = changes.get("archived", [])
        lines.append(f"\u26a0 {len(archived)} repositories archived")

        lines.append("")
        lines.append("## REMOVED")
        lines.append("")
        removed = changes.get("removed", [])
        lines.append(f"\u2715 {len(removed)} repositories disappeared from source lists")

        return "\n".join(lines)

    def render_repo_entry(self, repo: Repository) -> str:
        score_str = f"{repo.score['overall']:.0f}" if repo.score and repo.score.get("overall") else "N/A"
        health = repo.health.get("status", "UNKNOWN") if repo.health else "UNKNOWN"
        return (
            f"- **{repo.full_name or repo.id}** "
            f"({repo.stars or 0:,} stars, {repo.forks or 0:,} forks) "
            f"- {health} - Score: {score_str}"
        )

    def render_category_index(self, categories: dict[str, list[str]]) -> str:
        lines = ["# Category Index", "", ""]
        for category, repos in categories.items():
            lines.append(f"## {category}")
            lines.append("")
            for repo_id in repos:
                lines.append(f"- {repo_id}")
            lines.append("")
        return "\n".join(lines)

    def render_sitemap(
        self,
        categories: dict[str, list[dict]],
        total: int,
        generated_at: Optional[str] = None,
    ) -> str:
        lines = ["# Awesome Repository Sitemap", ""]
        if generated_at:
            lines.append(f"Generated: {generated_at}")
            lines.append("")
        lines.append(f"Total repositories: {total}")
        lines.append("")
        for category in sorted(categories):
            repos = categories[category]
            lines.append(f"## {category}")
            lines.append("")
            for repo in repos:
                name = repo.get("name", "")
                url = repo.get("url", "")
                stars = repo.get("stars", 0) or 0
                score = repo.get("score", 0) or 0
                lines.append(f"- [{name}]({url}) - {stars:,} stars - score {score}")
            lines.append("")
        return "\n".join(lines)

    def render_llms_txt(
        self,
        categories: dict[str, list[dict]],
        total: int,
        generated_at: Optional[str] = None,
    ) -> str:
        lines = [
            "# Awesome Collector",
            "",
            "> Curated index of awesome GitHub repositories for the NRE Lab knowledge base.",
            "",
        ]
        if generated_at:
            lines.append(f"Generated: {generated_at}")
            lines.append("")
        lines.append(f"Total repositories: {total}")
        lines.append("")
        for category in sorted(categories):
            repos = categories[category]
            lines.append(f"## {category}")
            lines.append("")
            for repo in repos:
                name = repo.get("name", "")
                url = repo.get("url", "")
                description = (repo.get("description") or "No description").strip()
                lines.append(f"- [{name}]({url}): {description}")
            lines.append("")
        return "\n".join(lines)

    def render_agents_md(
        self,
        categories: dict[str, list[dict]],
        stats: Optional[dict] = None,
        total: Optional[int] = None,
    ) -> str:
        if total is None:
            total = len({r.get("id") for repos in categories.values() for r in repos})
        lines = [
            "# Agent Guide",
            "",
            "Machine-readable entry points for automated consumers of this dataset.",
            "",
            "## Dataset",
            "",
            f"- Total repositories: {total}",
            f"- Categories: {len(categories)}",
        ]
        if stats:
            lines.append(f"- Total stars: {stats.get('total_stars', 0):,}")
            by_health = stats.get("by_health", {})
            for status, count in sorted(by_health.items()):
                lines.append(f"- Health {status}: {count}")
        lines.append("")
        lines.append("## Categories")
        lines.append("")
        for category in sorted(categories):
            count = len(categories[category])
            label = "repository" if count == 1 else "repositories"
            lines.append(f"- `{category}` ({count} {label})")
        lines.append("")
        lines.append("## High-scoring repositories")
        lines.append("")
        seen: set[str] = set()
        scored: list[dict] = []
        for category in sorted(categories):
            for repo in categories[category]:
                if repo.get("id") in seen:
                    continue
                seen.add(repo.get("id"))
                scored.append(repo)
        scored.sort(
            key=lambda r: (r.get("score", 0) or 0, r.get("stars", 0) or 0),
            reverse=True,
        )
        lines.append("| Repository | Score | Stars | Category |")
        lines.append("|---|---:|---:|---|")
        for repo in scored[:50]:
            name = repo.get("name", "")
            url = repo.get("url", "")
            lines.append(
                f"| [{name}]({url}) | {repo.get('score', 0) or 0} "
                f"| {repo.get('stars', 0) or 0:,} | {repo.get('category', '')} |"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def render_markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return ""
        header_line = "| " + " | ".join(headers) + " |"
        separator = "|" + "|".join(["---"] * len(headers)) + "|"
        data_lines = [
            "| " + " | ".join(str(cell) for cell in row) + " |"
            for row in rows
        ]
        return "\n".join([header_line, separator] + data_lines)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")