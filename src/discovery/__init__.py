import time
from dataclasses import dataclass, field
from typing import Optional

from src.github.client import GitHubClient
from src.models import Repository
from src.normalize.urls import normalize_url, repository_id_from_url, repository_id
from src.parser.markdown import find_repository_references, parse_awesome_list
from src.parser.categories import categorize_by_keywords, categorize_by_language, categorize_by_topics
from src.parser.links import is_awesome_list_repo, extract_awesome_list_metadata


class DiscoveryEngine:
    def __init__(self, client: GitHubClient, config: Optional[dict] = None):
        self.client = client
        self.config = config or {}
        self._discovered_repos: dict[str, dict] = {}

    def discover_awesome_lists(
        self, queries: Optional[list[str]] = None, per_page: int = 100
    ) -> list[dict]:
        from src.discovery.github_search import GithubSearcher
        from src.discovery.awesome_lists import AwesomeListDiscoverer

        searcher = GithubSearcher(self.client)
        discoverer = AwesomeListDiscoverer(self.client)

        queries = queries or [
            "awesome in:name", "awesome-list in:name", '"awesome list" in:readme',
        ]

        all_results = []
        for query in queries:
            results = searcher.search_by_name(query, per_page)
            all_results.extend(results)
            time.sleep(0.5)

        awesome_lists = discoverer.filter_awesome_lists(all_results)
        return awesome_lists

    def discover_from_awesome_list(
        self, owner: str, repo: str, markdown: Optional[str] = None
    ) -> list[dict]:
        return self.client.discover_from_awesome_list(owner, repo, markdown)

    def discover_all(
        self,
        awesome_patterns: Optional[list[str]] = None,
        topics: Optional[list[str]] = None,
        per_page: int = 100,
    ) -> list[dict]:
        from src.discovery.github_search import GithubSearcher
        from src.discovery.topics import TopicDiscoverer

        awesome_patterns = awesome_patterns or ["awesome", "awesome-list", "awesome-*"]
        topics = topics or ["awesome", "awesome-list", "awesome-lists", "curated-list", "resources"]

        searcher = GithubSearcher(self.client)
        topic_discoverer = TopicDiscoverer(self.client)

        results = []
        results.extend(searcher.search(awesome_patterns, per_page))
        time.sleep(1)
        results.extend(topic_discoverer.discover_by_topics(topics, per_page))

        return self._deduplicate_results(results)

    def _deduplicate_results(self, results: list[dict]) -> list[dict]:
        seen = set()
        deduped = []
        for result in results:
            repo_data = result.get("repository", {})
            owner = repo_data.get("owner", {}).get("login", "")
            name = repo_data.get("name", "")
            if not owner or not name:
                continue
            repo_id = repository_id(owner, name)
            if repo_id not in seen:
                seen.add(repo_id)
                deduped.append(result)
        return deduped