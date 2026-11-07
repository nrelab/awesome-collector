"""Dedicated tests for parser modules (links, categories, markdown)."""


from src.models import Repository
from src.parser.categories import (
    categorize_by_keywords,
    categorize_by_language,
    categorize_by_topics,
    category_parents,
    classify_repository,
    extract_categories_from_markdown,
    normalize_section_name,
    section_to_category,
)
from src.parser.links import (
    extract_awesome_list_metadata,
    is_awesome_list_repo,
    is_awesome_list_url,
)
from src.parser.markdown import (
    extract_github_urls,
    extract_links,
    extract_ossfuzz_links,
    extract_readme_quality,
    extract_section_headings,
    find_repository_references,
    is_github_repo_url,
    parse_awesome_list,
)


def _repo(**kw):
    base = {"id": "github:o/r", "owner": "o", "name": "r",
            "url": "https://github.com/o/r"}
    base.update(kw)
    return Repository(**base)


class TestLinksParser:
    def test_is_awesome_list_url(self):
        assert is_awesome_list_url("https://github.com/vinta/awesome-python")
        assert is_awesome_list_url("https://github.com/foo/awesome-ml")
        assert is_awesome_list_url("https://github.com/foo/my-awesome-thing")
        assert not is_awesome_list_url("https://github.com/foo/requests")
        assert not is_awesome_list_url("https://gitlab.com/foo/awesome")
        assert not is_awesome_list_url("")

    def test_is_awesome_list_repo(self):
        assert is_awesome_list_repo(_repo(name="awesome-x"))
        assert is_awesome_list_repo(_repo(name="x-awesome"))
        assert is_awesome_list_repo(_repo(topics=["awesome-list"]))
        assert is_awesome_list_repo(
            _repo(description="A curated awesome repository list"))
        assert not is_awesome_list_repo(_repo(name="requests", language="Python"))

    def test_extract_awesome_list_metadata(self):
        md = "# Title\n## Sec\n- [a](https://github.com/a/b)\n- [c](https://x.com)"
        meta = extract_awesome_list_metadata(md)
        assert meta["is_awesome_list"] is True
        assert meta["section_count"] == 2
        assert meta["repository_count"] == 1
        assert meta["github_links"] == [("a", "https://github.com/a/b")]


class TestCategoriesParser:
    def test_categorize_by_keywords(self):
        repo = _repo(description="machine learning model", topics=["ai"])
        taxonomy = {"AI": ["machine learning", "llm"], "Web": ["react"]}
        assert categorize_by_keywords(repo, taxonomy) == ["AI"]

    def test_categorize_by_language(self):
        assert categorize_by_language(_repo(language="Python")) == ["Python"]
        assert categorize_by_language(_repo(language="Go")) == ["Go"]
        assert categorize_by_language(_repo(language="Unknown")) == []
        assert categorize_by_language(_repo(language=None)) == []

    def test_categorize_by_topics(self):
        repo = _repo(topics=["llm", "agents"])
        topic_map = {"AI": ["llm"], "Robotics": ["robotics"]}
        assert categorize_by_topics(repo, topic_map) == ["AI"]

    def test_normalize_section_name(self):
        assert normalize_section_name("## [awesome] Security 🔐 Tools") == \
            "awesome Security Tools"
        assert normalize_section_name("  -- Web --  ") == "Web"

    def test_extract_categories_from_markdown(self):
        md = "# Top\n## Cat A\n- [r](https://github.com/a/b)\n## Cat B\ntext"
        cats = extract_categories_from_markdown(md)
        names = [c["name"] for c in cats]
        assert "Cat A" in names and "Cat B" in names

    def test_category_parents(self):
        from src.config import CategoryTaxonomy
        taxonomy = CategoryTaxonomy(parents={"AI": ["LLM"], "Languages": ["Rust"]})
        assert category_parents(["LLM", "Unknown"], taxonomy) == {"LLM": "AI"}


class TestClassifyRepository:
    def _taxonomy(self):
        from src.config import CategoryTaxonomy
        return CategoryTaxonomy(
            parents={"AI": ["LLM", "Agents"], "Languages": ["Rust"]},
            keywords={"LLM": ["large language model"]},
            topics={"LLM": ["llm"], "Rust": ["rust"]},
        )

    def test_topics_win_first(self):
        repo = _repo(topics=["llm"], language="Rust",
                     description="large language model")
        cats = classify_repository(repo, self._taxonomy())
        assert cats[0] == "LLM"  # topic signal ranks before language
        assert "Rust" in cats

    def test_unknown_categories_filtered(self):
        repo = _repo(topics=["not-a-real-topic"])
        assert classify_repository(repo, self._taxonomy()) == []

    def test_max_categories_respected(self):
        from src.config import CategoryTaxonomy
        taxonomy = CategoryTaxonomy(
            parents={"P": [f"L{i}" for i in range(10)]},
            keywords={f"L{i}": [f"kw{i}"] for i in range(10)},
        )
        repo = _repo(description=" ".join(f"kw{i}" for i in range(10)))
        assert len(classify_repository(repo, taxonomy)) <= 5


class TestSectionToCategory:
    def _taxonomy(self):
        from src.config import CategoryTaxonomy
        return CategoryTaxonomy(
            parents={"Security": ["AppSec", "Threat Intel"]},
            keywords={"AppSec": ["application security"]},
        )

    def test_exact_leaf_match(self):
        assert section_to_category("AppSec", self._taxonomy()) == "AppSec"

    def test_keyword_match(self):
        assert section_to_category("Application Security Tools",
                                   self._taxonomy()) == "AppSec"

    def test_unmatched_returns_none(self):
        assert section_to_category("Quantum Baking", self._taxonomy()) is None


class TestMarkdownParser:
    def test_extract_links(self):
        md = "[a](https://x.com) [b](https://y.com)"
        assert extract_links(md) == [("a", "https://x.com"), ("b", "https://y.com")]

    def test_extract_github_urls(self):
        md = "see https://github.com/a/b and https://github.com/c/d"
        assert len(extract_github_urls(md)) == 2

    def test_extract_ossfuzz_links(self):
        md = "<https://github.com/a/b>"
        assert extract_ossfuzz_links(md) == ["https://github.com/a/b"]

    def test_extract_section_headings_levels(self):
        headings = extract_section_headings("# A\n### B")
        assert headings == [("A", 1), ("B", 3)]

    def test_find_repository_references_dedupes(self):
        md = "[x](https://github.com/a/b) https://github.com/a/b"
        refs = find_repository_references(md)
        assert len(refs) == 1

    def test_readme_quality_bounds(self):
        q = extract_readme_quality("# Title\n\nSome words here. " * 30)
        assert 0 <= q["quality_score"] <= 100
        assert q["word_count"] > 0

    def test_parse_awesome_list_structure(self):
        md = "## Sec\n- [Tool](https://github.com/a/tool)\ntext"
        parsed = parse_awesome_list(md, source_repo="me/list")
        assert parsed["is_awesome_list"] is True
        assert parsed["source_repository"] == "me/list"
        assert parsed["total_repositories"] == 1
        assert parsed["repositories"][0]["repo_id"] == "github:a/tool"

    def test_is_github_repo_url(self):
        assert is_github_repo_url("https://github.com/a/b")
        assert not is_github_repo_url("https://example.com")
