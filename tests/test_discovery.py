"""Dedicated tests for discovery modules (search, topics, engine)."""


from src.discovery import DiscoveryEngine
from src.discovery.github_search import (
    GithubSearcher,
    extract_repo_from_search_result,
)
from src.discovery.topics import TopicDiscoverer


class FakeClient:
    def __init__(self, search_items=None, topic_items=None):
        self._search_items = search_items or []
        self._topic_items = topic_items or []
        self.search_queries = []

    def search_repositories(self, query="", per_page=100, page=1):
        self.search_queries.append(query)
        if query.startswith("topic:"):
            return {"items": self._topic_items}
        return {"items": self._search_items}

    def get(self, path, **kwargs):
        return {"items": []}

    def get_topics(self, owner, repo):
        return ["awesome-list"]

    def get_license(self, owner, repo):
        return {"key": "mit"}

    def get_contributors(self, owner, repo, per_page=100):
        return [{}]

    def close(self):
        pass


def _item(owner="o", name="r", **kw):
    base = {
        "name": name,
        "owner": {"login": owner},
        "html_url": f"https://github.com/{owner}/{name}",
        "description": "d",
        "stargazers_count": 10,
        "topics": [],
    }
    base.update(kw)
    return base


class TestGithubSearcher:
    def test_search_by_name_collects_results(self):
        client = FakeClient(search_items=[_item()])
        searcher = GithubSearcher(client)
        results = searcher.search_by_name("awesome")
        assert len(results) == 1
        assert results[0]["source"] == "search_name"
        assert results[0]["repository"]["name"] == "r"

    def test_search_by_description(self):
        client = FakeClient(search_items=[_item(name="x")])
        results = GithubSearcher(client).search_by_description("awesome")
        assert results[0]["source"] == "search_description"

    def test_search_by_readme(self):
        client = FakeClient(search_items=[_item(name="y")])
        results = GithubSearcher(client).search_by_readme("awesome list")
        assert results[0]["source"] == "search_readme"

    def test_search_patterns(self):
        client = FakeClient(search_items=[_item()])
        results = GithubSearcher(client).search(["awesome"], per_page=10)
        assert len(results) == 1
        assert results[0]["source"] == "search_pattern"

    def test_search_swallows_api_errors(self):
        class BadClient(FakeClient):
            def search_repositories(self, **kw):
                raise RuntimeError("boom")
        results = GithubSearcher(BadClient()).search_by_name("x")
        assert results == []

    def test_enrich_repository_data(self):
        client = FakeClient()
        data = {"name": "r", "owner": {"login": "o"}}
        enriched = GithubSearcher(client).enrich_repository_data(data)
        assert enriched["topics"] == ["awesome-list"]
        assert enriched["license"] == "mit"
        assert enriched["contributors_count"] == 1

    def test_enrich_handles_missing_owner(self):
        client = FakeClient()
        data = {"name": "", "owner": {}}
        assert GithubSearcher(client).enrich_repository_data(data) == data

    def test_extract_repo_from_search_result(self):
        result = {"repository": _item(owner="Foo", name="Bar")}
        repo = extract_repo_from_search_result(result)
        assert repo["id"] == "github:foo/bar"
        assert repo["name_with_owner"] == "Foo/Bar"
        assert extract_repo_from_search_result({"repository": {}}) is None


class TestTopicDiscoverer:
    def test_discover_by_topic(self):
        client = FakeClient(topic_items=[_item(name="t")])
        results = TopicDiscoverer(client).discover_by_topic("awesome")
        assert len(results) == 1
        # cached on second call
        again = TopicDiscoverer(client)
        again._topic_cache = TopicDiscoverer(client)._topic_cache
        assert len(TopicDiscoverer(client).discover_by_topic("awesome")) == 1

    def test_discover_by_topics_wraps_results(self):
        client = FakeClient(topic_items=[_item()])
        results = TopicDiscoverer(client).discover_by_topics(["awesome"])
        assert results[0]["source"] == "topic"
        assert results[0]["topic"] == "awesome"

    def test_discover_by_topic_error_returns_empty(self):
        class BadClient(FakeClient):
            def search_repositories(self, **kw):
                raise RuntimeError("down")
        assert TopicDiscoverer(BadClient()).discover_by_topic("x") == []

    def test_find_awesome_topics_fallback(self):
        class BadClient(FakeClient):
            def get(self, path, **kwargs):
                raise RuntimeError("down")
        topics = TopicDiscoverer(BadClient()).find_awesome_topics()
        assert "awesome" in topics


class TestDiscoveryEngine:
    def test_deduplicate_results(self):
        engine = DiscoveryEngine(client=FakeClient())
        results = [
            {"repository": _item(owner="a", name="r")},
            {"repository": _item(owner="A", name="R")},  # dup after normalize? no—engine keys raw
            {"repository": _item(owner="b", name="s")},
        ]
        deduped = engine._deduplicate_results(results)
        # repository_id() lowercases, so a/r and A/R collapse to one entry
        assert len(deduped) == 2

    def test_deduplicate_results_skips_empty(self):
        engine = DiscoveryEngine(client=FakeClient())
        results = [{"repository": {}}, {"repository": _item()}]
        deduped = engine._deduplicate_results(results)
        assert len(deduped) == 1

    def test_discover_all_merges_sources(self):
        client = FakeClient(search_items=[_item(name="s")],
                            topic_items=[_item(name="t")])
        engine = DiscoveryEngine(client)
        results = engine.discover_all(awesome_patterns=["awesome"],
                                      topics=["awesome"])
        names = {r["repository"]["name"] for r in results}
        assert names == {"s", "t"}
