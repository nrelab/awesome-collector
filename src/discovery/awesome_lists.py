import time
from dataclasses import dataclass, field
from typing import Optional

from src.github.client import GitHubClient


@dataclass
class DiscoveryConfig:
    awesome_patterns: list[str] = field(default_factory=lambda: [
        "awesome", "awesome-list", "awesome-*", "awesome list"
    ])
    search_queries: list[str] = field(default_factory=lambda: [
        "awesome in:name", "awesome in:description", "awesome-list in:name",
        '"awesome list" in:readme', "curated resources in:description",
    ])
    topics: list[str] = field(default_factory=lambda: [
        "awesome", "awesome-list", "awesome-lists",
        "curated-list", "resources", "developer-resources",
    ])
    max_results_per_query: int = 100
    min_stars: int = 10
    exclude_archived: bool = False
    exclude_fork: bool = False


class AwesomeListDiscoverer:
    def __init__(self, client: GitHubClient, config: Optional[DiscoveryConfig] = None):
        self.client = client
        self.config = config or DiscoveryConfig()
        self._discovered_lists: set[str] = set()

    def discover_by_search(self) -> list[dict]:
        results = []
        for query in self.config.search_queries:
            try:
                data = self.client.search_repositories(
                    query=query, per_page=self.config.max_results_per_query
                )
                for item in data.get("items", []):
                    results.append({
                        "source": "search",
                        "query": query,
                        "repository": item,
                    })
                time.sleep(0.5)
            except Exception as e:
                print(f"Search query failed: {query}: {e}")
        return results

    def discover_by_topics(self) -> list[dict]:
        results = []
        for topic in self.config.topics:
            try:
                data = self.client.search_repositories(
                    query=f"topic:{topic}", per_page=self.config.max_results_per_query
                )
                for item in data.get("items", []):
                    results.append({
                        "source": "topic",
                        "topic": topic,
                        "repository": item,
                    })
                time.sleep(0.5)
            except Exception as e:
                print(f"Topic search failed: {topic}: {e}")
        return results

    def is_awesome_list(self, repo_data: dict) -> bool:
        name = repo_data.get("name", "").lower()
        description = (repo_data.get("description") or "").lower()
        topics = repo_data.get("topics", [])
        if name.startswith("awesome"):
            return True
        if "-awesome" in name:
            return True
        if "awesome-list" in topics:
            return True
        if "awesome list" in description or "awesome repository" in description:
            return True
        return False

    def filter_awesome_lists(self, search_results: list[dict]) -> list[dict]:
        awesome_lists = []
        for result in search_results:
            repo = result.get("repository", {})
            if self.is_awesome_list(repo):
                awesome_lists.append(result)
        return awesome_lists

    def discover_awesome_lists(self) -> list[dict]:
        search_results = self.discover_by_search()
        topic_results = self.discover_by_topics()
        all_results = search_results + topic_results
        return self.filter_awesome_lists(all_results)

    def discover_from_awesome_list(
        self, owner: str, repo: str, markdown: Optional[str] = None
    ) -> list[dict]:
        from src.parser.markdown import find_repository_references, parse_awesome_list

        if markdown is None:
            try:
                readme_data = self.client.get_readme(owner, repo)
                content_url = readme_data.get("download_url", "")
                import httpx
                if content_url:
                    resp = httpx.get(content_url)
                    markdown = resp.text if resp.status_code == 200 else ""
            except Exception:
                markdown = ""

        parse_awesome_list(markdown or "", source_repo=f"{owner}/{repo}")
        self_id = f"github:{owner.lower()}/{repo.lower()}"
        references = []
        seen: set[str] = set()
        for ref in find_repository_references(markdown or ""):
            repo_id = ref["repo_id"]
            if repo_id == self_id or repo_id in seen:
                continue
            seen.add(repo_id)
            references.append(ref)

        repo_ids = [ref["repo_id"] for ref in references]
        sections = _infer_sections(markdown or "", repo_ids)

        results = []
        for ref in references:
            repo_id = ref["repo_id"]
            owner_name = repo_id[len("github:"):]
            results.append({
                "source": "awesome-list",
                "parent_list": f"{owner}/{repo}",
                "repo_id": repo_id,
                "section": sections.get(repo_id, ""),
                "repository": {
                    "name": owner_name.split("/")[-1] if "/" in owner_name else owner_name,
                    "owner": owner_name.split("/")[0],
                    "html_url": f"https://github.com/{owner_name}",
                },
            })
        return results


def _infer_sections(markdown: str, repo_ids: list[str]) -> dict[str, str]:
    from src.parser.markdown import _SECTION_PATTERN

    remaining = set(repo_ids)
    sections: dict[str, str] = {}
    current_section = ""
    for line in markdown.split("\n"):
        heading_match = _SECTION_PATTERN.match(line)
        if heading_match:
            current_section = heading_match.group(1).strip()
            continue
        if not remaining:
            break
        lowered = line.lower()
        for repo_id in list(remaining):
            name = repo_id.split("/")[-1]
            if f"github.com/{repo_id[len('github:'):]}" in lowered or f"/{name}" in lowered:
                sections[repo_id] = current_section
                remaining.discard(repo_id)
    return sections