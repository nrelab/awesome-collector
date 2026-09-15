import time
from dataclasses import dataclass, field
from typing import Optional

from src.github.client import GitHubClient
from src.models import Repository


class TopicDiscoverer:
    def __init__(self, client: GitHubClient):
        self.client = client
        self._topic_cache: dict[str, list[dict]] = {}

    def discover_by_topic(self, topic: str, per_page: int = 100) -> list[dict]:
        if topic in self._topic_cache:
            return self._topic_cache[topic]
        results = []
        try:
            data = self.client.search_repositories(query=f"topic:{topic}", per_page=per_page)
            for item in data.get("items", []):
                results.append(item)
            time.sleep(0.5)
        except Exception as e:
            print(f"Topic discovery failed for {topic}: {e}")
        self._topic_cache[topic] = results
        return results

    def discover_by_topics(
        self, topics: list[str], per_page: int = 100
    ) -> list[dict]:
        all_results = []
        for topic in topics:
            results = self.discover_by_topic(topic, per_page)
            for item in results:
                all_results.append({
                    "source": "topic",
                    "topic": topic,
                    "repository": item,
                })
        return all_results

    def find_awesome_topics(self) -> list[str]:
        awesome_keywords = [
            "awesome", "awesome-list", "awesome-lists", "curated",
            "resources", "developer-resources", "developer-resources",
        ]
        try:
            data = self.client.get("/search/topics", params={"query": "awesome"})
            return [t.get("name", "") for t in data.get("items", [])]
        except Exception:
            return awesome_keywords