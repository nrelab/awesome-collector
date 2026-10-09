import pytest

from src.models import Repository
from src.normalize.dedupe import dedupe_repositories
from src.normalize.urls import (
    extract_owner_name_from_id,
    is_github_url,
    normalize_github_url,
    normalize_url,
    repository_id,
    repository_id_from_url,
    repository_from_row,
)
from src.parser.categories import categorize_by_keywords, categorize_by_language
from src.parser.links import is_awesome_list_repo, is_awesome_list_url
from src.parser.markdown import (
    extract_github_urls,
    extract_links,
    extract_readme_quality,
    extract_section_headings,
    find_repository_references,
    parse_awesome_list,
)
from src.scoring.quality import (
    calculate_activity_score,
    calculate_community_score,
    calculate_maintenance_score,
    calculate_popularity_score,
)
from src.scoring.security import (
    calculate_license_score,
    calculate_security_score,
    health_status,
)


class TestRepositoryFromRow:
    def test_maps_score_and_health_columns(self):
        repo = repository_from_row({
            "id": "github:foo/bar", "owner": "foo", "name": "bar",
            "url": "https://github.com/foo/bar", "stars": 10,
            "score_overall": 88.5, "health_status": "ACTIVE",
        })
        assert repo.score == {"overall": 88.5}
        assert repo.health == {"status": "ACTIVE"}

    def test_handles_null_score_and_health(self):
        repo = repository_from_row({
            "id": "github:foo/bar", "owner": "foo", "name": "bar",
            "url": "https://github.com/foo/bar",
            "score_overall": None, "health_status": None,
        })
        assert repo.score == {"overall": 0.0}
        assert repo.health == {"status": "UNKNOWN"}

    def test_preserves_existing_score_dict(self):
        repo = repository_from_row({
            "id": "github:foo/bar", "owner": "foo", "name": "bar",
            "url": "https://github.com/foo/bar",
            "score_overall": 10.0, "health_status": "STALE",
            "score": {"overall": 99.0}, "health": {"status": "ACTIVE"},
        })
        assert repo.score == {"overall": 99.0}
        assert repo.health == {"status": "ACTIVE"}


class TestNormalizeURLs:
    def test_normalize_https(self):
        assert normalize_url("https://github.com/foo/bar") == "github:foo/bar"

    def test_normalize_https_trailing_slash(self):
        assert normalize_url("https://github.com/foo/bar/") == "github:foo/bar"

    def test_normalize_dot_git(self):
        assert normalize_url("https://github.com/foo/bar.git") == "github:foo/bar"

    def test_normalize_ssh(self):
        assert normalize_url("git@github.com:foo/bar.git") == "github:foo/bar"

    def test_normalize_git_protocol(self):
        assert normalize_url("git://github.com/foo/bar.git") == "github:foo/bar"

    def test_normalize_ssh_github(self):
        assert normalize_url("git@ssh.github.com:/foo/bar") == "github:foo/bar"

    def test_repository_id(self):
        assert repository_id("Foo", "Bar") == "github:foo/bar"
        assert repository_id("FOO", "BAR") == "github:foo/bar"

    def test_repository_id_from_url(self):
        assert repository_id_from_url("https://github.com/user/repo") == "github:user/repo"
        assert repository_id_from_url("git@github.com:user/repo.git") == "github:user/repo"
        assert repository_id_from_url("https://gitlab.com/user/repo") is None



    def test_is_github_url(self):
        assert is_github_url("https://github.com/foo/bar") is True
        assert is_github_url("https://gitlab.com/foo/bar") is False

    def test_extract_owner_name(self):
        assert extract_owner_name_from_id("github:foo/bar") == ("foo", "bar")

    def test_extract_owner_name_invalid(self):
        with pytest.raises(ValueError):
            extract_owner_name_from_id("invalid")

    def test_normalize_github_url_strips_only_git_suffix(self):
        assert normalize_github_url("https://github.com/rust-lang/rust.git") == \
            "https://github.com/rust-lang/rust"

    def test_normalize_github_url_keeps_repo_name(self):
        assert normalize_github_url("https://github.com/abc/defigit") == \
            "https://github.com/abc/defigit"

    def test_repository_id_from_url_keeps_repo_name(self):
        assert repository_id_from_url("https://github.com/abc/defigit") == "github:abc/defigit"


class TestDedup:
    def test_dedupe_basic(self):
        repos = [
            Repository(id="github:foo/bar", owner="foo", name="bar", url="https://github.com/foo/bar"),
            Repository(id="github:foo/bar", owner="foo", name="bar", url="https://github.com/foo/bar"),
        ]
        unique, dups = dedupe_repositories(repos)
        assert len(unique) == 1
        assert len(dups) == 1

    def test_dedupe_different_repos(self):
        repos = [
            Repository(id="github:foo/a", owner="foo", name="a", url="https://github.com/foo/a"),
            Repository(id="github:foo/b", owner="foo", name="b", url="https://github.com/foo/b"),
        ]
        unique, dups = dedupe_repositories(repos)
        assert len(unique) == 2
        assert len(dups) == 0


class TestMarkdownParser:
    def test_extract_links(self):
        md = "[link text](https://example.com) and [other](https://github.com/foo/bar)"
        links = extract_links(md)
        assert len(links) == 2
        assert links[0] == ("link text", "https://example.com")

    def test_extract_github_urls(self):
        md = "Check https://github.com/user/repo and https://github.com/other/parser"
        urls = extract_github_urls(md)
        assert len(urls) == 2

    def test_extract_section_headings(self):
        md = "# Title\n## Section\n### Subsection"
        headings = extract_section_headings(md)
        assert len(headings) == 3
        assert headings[0] == ("Title", 1)
        assert headings[1] == ("Section", 2)
        assert headings[2] == ("Subsection", 3)

    def test_find_repository_references(self):
        md = "See [repo](https://github.com/user/repo) for details"
        refs = find_repository_references(md)
        assert len(refs) == 1
        assert refs[0]["repo_id"] == "github:user/repo"

    def test_extract_readme_quality(self):
        md = "# Title\n\nThis is a decent readme with some content here.\n\n```python\ncode\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |"
        quality = extract_readme_quality(md)
        assert quality["word_count"] > 0
        assert "quality_score" in quality
        assert 0 <= quality["quality_score"] <= 100

    def test_parse_awesome_list_extracts_repositories(self):
        md = (
            "- [Rust](https://github.com/rust-lang/rust)\n"
            "- https://github.com/tokio-rs/tokio\n"
        )
        parsed = parse_awesome_list(md, source_repo="me/list")
        ids = sorted(r["repo_id"] for r in parsed["repositories"])
        assert ids == ["github:rust-lang/rust", "github:tokio-rs/tokio"]
        assert parsed["total_repositories"] == 2

    def test_parse_awesome_list_dedupes(self):
        md = (
            "- [Rust](https://github.com/rust-lang/rust)\n"
            "- [Rust again](https://github.com/rust-lang/rust)\n"
        )
        parsed = parse_awesome_list(md)
        assert parsed["total_repositories"] == 1

    def test_parse_awesome_list_preserves_repo_name_suffix(self):
        md = "- [Digit](https://github.com/abc/defigit)\n"
        parsed = parse_awesome_list(md)
        assert parsed["repositories"][0]["repo_id"] == "github:abc/defigit"

    def test_parse_awesome_list_handles_git_suffix(self):
        md = "- [Tokio](https://github.com/tokio-rs/tokio.git)\n"
        parsed = parse_awesome_list(md)
        assert parsed["repositories"][0]["repo_id"] == "github:tokio-rs/tokio"


class TestAwesomeListDetection:
    def test_awesome_list_url(self):
        assert is_awesome_list_url("https://github.com/vinta/awesome-python")
        assert is_awesome_list_url("https://github.com/sindresorhus/awesome")
        assert is_awesome_list_url("https://github.com/jfryan/awesome-llm")

    def test_is_awesome_list_repo_by_name(self):
        repo = Repository(id="github:vinta/awesome-python", owner="vinta", name="awesome-python", url="https://github.com/vinta/awesome-python")
        assert is_awesome_list_repo(repo)

    def test_is_not_awesome_list_repo(self):
        repo = Repository(id="github:psf/requests", owner="psf", name="requests", url="https://github.com/psf/requests", language="Python")
        assert not is_awesome_list_repo(repo)

    def test_awesome_list_url_strips_git_suffix(self):
        assert is_awesome_list_url("https://github.com/sindresorhus/awesome.git")

    def test_awesome_list_url_name_ending_in_git_chars(self):
        assert is_awesome_list_url("https://github.com/user/awesome-defigit")

    def test_awesome_list_url_rejects_non_github(self):
        assert not is_awesome_list_url("https://gitlab.com/user/awesome")


class TestCategorization:
    def test_categorize_by_keywords_ai(self):
        repo = Repository(id="github:openai/chatgpt", owner="openai", name="chatgpt", url="https://github.com/openai/chatgpt", topics=["llm", "ai"], description="AI chat tool")
        taxonomy = {"AI/ML": ["artificial intelligence", "llm", "agent"], "Security": ["security", "vulnerability"]}
        cats = categorize_by_keywords(repo, taxonomy)
        assert "AI/ML" in cats

    def test_categorize_by_language_python(self):
        repo = Repository(id="github:psf/requests", owner="psf", name="requests", url="https://github.com/psf/requests", language="Python")
        cats = categorize_by_language(repo)
        assert "Python" in cats

    def test_categorize_by_language_rust(self):
        repo = Repository(id="github:rust-lang/rust", owner="rust-lang", name="rust", url="https://github.com/rust-lang/rust", language="Rust")
        cats = categorize_by_language(repo)
        assert "Rust" in cats


class TestScoring:
    def test_popularity_score_high_stars(self):
        repo = Repository(id="github:test/repo", owner="test", name="repo", url="https://github.com/test/repo", stars=80000, forks=8000, language="Python")
        score = calculate_popularity_score(repo)
        assert 0 <= score <= 100
        assert score > 50

    def test_popularity_score_zero(self):
        repo = Repository(id="github:test/repo", owner="test", name="repo", url="https://github.com/test/repo", stars=0, forks=0)
        score = calculate_popularity_score(repo)
        assert score == 0.0

    def test_activity_score_active(self):
        score = calculate_activity_score(last_push_days=2, commits_30d=15, releases_90d=3)
        assert score > 70

    def test_activity_score_stale(self):
        score = calculate_activity_score(last_push_days=200, commits_30d=0, releases_90d=0)
        assert score < 30

    def test_maintenance_score_full(self):
        score = calculate_maintenance_score(True, True, 3, 5)
        assert score > 80

    def test_maintenance_score_none(self):
        score = calculate_maintenance_score(False, False, None, 300)
        assert score < 30

    def test_community_score(self):
        score = calculate_community_score(contributors=10, forks=50, open_issues=20)
        assert 0 <= score <= 100

    def test_license_score_permissive(self):
        assert calculate_license_score("MIT") == 100
        assert calculate_license_score("Apache-2.0") == 100

    def test_license_score_copyleft(self):
        assert calculate_license_score("GPL-3.0") == 50

    def test_license_score_unlicensed(self):
        assert calculate_license_score(None) == 0

    def test_health_active(self):
        assert health_status(last_commit_days=2, release_days=10, contributors_90d=5) == "ACTIVE"

    def test_health_archived(self):
        assert health_status(archived=True) == "ARCHIVED"

    def test_health_unknown(self):
        assert health_status(last_commit_days=None) == "UNKNOWN"

    def test_health_stale(self):
        assert health_status(last_commit_days=200) == "STALE"


class TestScore:
    def test_security_score_all(self):
        assert calculate_security_score(True, True, True, True) == 100

    def test_security_score_none(self):
        assert calculate_security_score(False, False, False, False) == 0


class TestRepositoryModel:
    def test_to_dict(self):
        repo = Repository(id="github:test/repo", owner="test", name="repo", url="https://github.com/test/repo")
        d = repo.to_dict()
        assert d["id"] == "github:test/repo"
        assert d["owner"] == "test"

    def test_from_dict(self):
        data = {
            "id": "github:test/repo", "owner": "test", "name": "repo",
            "url": "https://github.com/test/repo", "stars": 100,
        }
        repo = Repository.from_dict(data)
        assert repo.id == "github:test/repo"
        assert repo.stars == 100

    def test_repository_hash(self):
        r1 = Repository(id="github:a/b", owner="a", name="b", url="https://github.com/a/b")
        r2 = Repository(id="github:a/b", owner="a", name="b", url="https://github.com/a/b")
        assert hash(r1) == hash(r2)
        assert r1 == r2

    def test_repo_path(self):
        repo = Repository(id="github:owner/name", owner="owner", name="name", url="https://github.com/owner/name")
        assert repo.repo_path == "owner/name"