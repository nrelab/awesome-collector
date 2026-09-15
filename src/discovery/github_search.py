import re
from typing import Optional

from src.github.client import GitHubClient
from src.models import Repository
from src.normalize.urls import normalize_url, repository_id_from_url, repository_id


class GithubSearcher:
    SEARCH_LANGUAGES = ["Markdown"]

    def __init__(self, client: GitHubClient):
        self.client = client

    def search_by_name(self, query: str = "awesome", per_page: int = 100) -> list[dict]:
        results = []
        try:
            data = self.client.search_repositories(query=f'"{query}" in:name', per_page=per_page)
            for item in data.get("items", []):
                results.append({"source": "search_name", "query": f'"{query}" in:name', "repository": item})
        except Exception as e:
            print(f"Search error: {e}")
        return results

    def search_by_description(self, query: str = "awesome", per_page: int = 100) -> list[dict]:
        results = []
        try:
            data = self.client.search_repositories(query=f'"{query}" in:description', per_page=per_page)
            for item in data.get("items", []):
                results.append({"source": "search_description", "query": f'"{query}" in:description', "repository": item})
        except Exception as e:
            print(f"Search error: {e}")
        return results

    def search_by_readme(self, query: str = "awesome list", per_page: int = 100) -> list[dict]:
        results = []
        try:
            data = self.client.search_repositories(query=f'"{query}" in:readme', per_page=per_page)
            for item in data.get("items", []):
                results.append({"source": "search_readme", "query": f'"{query}" in:readme', "repository": item})
        except Exception as e:
            print(f"Search error: {e}")
        return results

    def search(
        self,
        awesome_patterns: Optional[list[str]] = None,
        per_page: int = 100,
    ) -> list[dict]:
        patterns = awesome_patterns or ["awesome", "awesome-list", "awesome-*"]
        all_results = []
        for pattern in patterns:
            query = f'repository:{pattern}'
            try:
                data = self.client.search_repositories(query=query, per_page=per_page)
                for item in data.get("items", []):
                    all_results.append({
                        "source": "search_pattern",
                        "pattern": pattern,
                        "repository": item,
                    })
            except Exception as e:
                print(f"Pattern search failed for {pattern}: {e}")
        return all_results

    def enrich_repository_data(self, repo_data: dict) -> dict:
        owner = repo_data.get("owner", {}).get("login", "")
        name = repo_data.get("name", "")
        if not owner or not name:
            return repo_data

        try:
            topics = self.client.get_topics(owner, name)
            repo_data["topics"] = topics
        except Exception:
            repo_data.setdefault("topics", [])

        try:
            license_data = self.client.get_license(owner, name)
            if license_data:
                repo_data["license"] = license_data.get("key", license_data.get("spdx_id"))
        except Exception:
            pass

        try:
            contributors = self.client.get_contributors(owner, name, per_page=1)
            repo_data["contributors_count"] = len(contributors) if contributors else 0
        except Exception:
            repo_data["contributors_count"] = 0

        return repo_data


def extract_repo_from_search_result(result: dict) -> Optional[dict]:
    repo = result.get("repository", {})
    owner = repo.get("owner", {}).get("login", "")
    name = repo.get("name", "")
    if not owner or not name:
        return None
    return {
        "id": repository_id(owner, name),
        "owner": owner,
        "name": name,
        "url": repo.get("html_url", f"https://github.com/{owner}/{name}"),
        "description": repo.get("description"),
        "stars": repo.get("stargazers_count"),
        "forks": repo.get("forks_count", repo.get("forks")),
        "language": repo.get("language"),
        "archived": repo.get("archived", False),
        "name_with_owner": f"{owner}/{name}",
    }