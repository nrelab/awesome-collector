import io
from datetime import datetime, timezone
from typing import Any, Optional

from src.models import Repository


def _walk_leaves(leaves: dict, parent: str) -> list[tuple[str, list, str]]:
    """Yield ``(leaf, entries, heading_level)`` for one category group.

    A group whose only leaf is the parent itself (the Uncategorized bucket) has
    no heading of its own, so it renders flat instead of repeating itself.
    """
    out: list[tuple[str, list, str]] = []
    for leaf in sorted(leaves):
        level = "" if leaf == parent else "###"
        out.append((leaf, leaves[leaf], level))
    return out


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
            leaves = section.get("repositories", {})
            if not isinstance(leaves, dict):
                continue
            if not leaves:
                continue
            lines.append(f"## {title}")
            lines.append("")
            lines.append("| Repository | Stars | Category | Score |")
            lines.append("|---|---:|---|---:|")
            for leaf, entries, _level in _walk_leaves(leaves, title):
                for repo in entries:
                    name = repo.get("name", "")
                    stars = repo.get("stars", 0) or 0
                    score = repo.get("score", 0) or 0
                    lines.append(f"| {name} | {stars:,} | {leaf} | {score} |")
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

    def render_category_index(self, tree: dict[str, dict[str, list[str]]]) -> str:
        lines = ["# Category Index", "", ""]
        for parent in sorted(tree):
            leaves = tree[parent]
            lines.append(f"## {parent}")
            lines.append("")
            for leaf, entries, _level in _walk_leaves(leaves, parent):
                for repo_id in entries:
                    lines.append(f"- {repo_id}")
            lines.append("")
        return "\n".join(lines)

    def render_sitemap(
        self,
        tree: dict[str, dict[str, list[dict]]],
        total: int,
        generated_at: Optional[str] = None,
    ) -> str:
        lines = ["# Awesome Repository Sitemap", ""]
        if generated_at:
            lines.append(f"Generated: {generated_at}")
            lines.append("")
        lines.append(f"Total repositories: {total}")
        lines.append("")
        for parent in sorted(tree):
            lines.append(f"## {parent}")
            lines.append("")
            for leaf, repos, level in _walk_leaves(tree[parent], parent):
                if level:
                    lines.append(f"{level} {leaf}")
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
        tree: dict[str, dict[str, list[dict]]],
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
        for parent in sorted(tree):
            lines.append(f"## {parent}")
            lines.append("")
            for leaf, repos, level in _walk_leaves(tree[parent], parent):
                if level:
                    lines.append(f"{level} {leaf}")
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
        tree: dict[str, dict[str, list[dict]]],
        stats: Optional[dict] = None,
        total: Optional[int] = None,
    ) -> str:
        if total is None:
            total = len({
                r.get("id")
                for leaves in tree.values()
                for entries in leaves.values()
                for r in entries
            })
        lines = [
            "# Agent Guide",
            "",
            "Machine-readable entry points for automated consumers of this dataset.",
            "",
            "## Dataset",
            "",
            f"- Total repositories: {total}",
            f"- Categories: {sum(len(leaves) for leaves in tree.values())}",
            f"- Category groups: {len(tree)}",
        ]
        if stats:
            lines.append(f"- Total stars: {stats.get('total_stars', 0):,}")
            by_health = stats.get("by_health", {})
            for status, count in sorted(by_health.items()):
                lines.append(f"- Health {status}: {count}")
        lines.append("")
        lines.append("## Categories")
        lines.append("")
        for parent in sorted(tree):
            parent_count = sum(len(entries) for entries in tree[parent].values())
            parent_label = "repository" if parent_count == 1 else "repositories"
            lines.append(f"- `{parent}` ({parent_count} {parent_label})")
            for leaf in sorted(tree[parent]):
                if leaf == parent:
                    continue
                count = len(tree[parent][leaf])
                label = "repository" if count == 1 else "repositories"
                lines.append(f"  - `{leaf}` ({count} {label})")
        lines.append("")
        lines.append("## High-scoring repositories")
        lines.append("")
        seen: set[str] = set()
        scored: list[dict] = []
        for parent in sorted(tree):
            for leaf in sorted(tree[parent]):
                for repo in tree[parent][leaf]:
                    if repo.get("id") in seen:
                        continue
                    seen.add(repo.get("id"))
                    scored.append(repo)
        scored.sort(
            key=lambda r: (r.get("score", 0) or 0, r.get("stars", 0) or 0),
            reverse=True,
        )
        lines.append("| Repository | Score | Stars | Category | Group |")
        lines.append("|---|---:|---:|---|---|")
        for repo in scored[:50]:
            name = repo.get("name", "")
            url = repo.get("url", "")
            lines.append(
                f"| [{name}]({url}) | {repo.get('score', 0) or 0} "
                f"| {repo.get('stars', 0) or 0:,} | {repo.get('category', '')} "
                f"| {repo.get('parent', '')} |"
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