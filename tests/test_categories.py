import os

import pytest

from src.config import load_categories
from src.models import Repository
from src.parser.categories import (
    category_parents,
    classify_repository,
    normalize_section_name,
    section_to_category,
)

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
)


@pytest.fixture(scope="module")
def taxonomy():
    return load_categories(CONFIG_DIR)


def make_repo(**kwargs) -> Repository:
    defaults = {
        "id": "github:owner/name",
        "owner": "owner",
        "name": "name",
        "url": "https://github.com/owner/name",
    }
    defaults.update(kwargs)
    return Repository(**defaults)


class TestNormalizeSectionName:
    def test_strips_markdown_decoration(self):
        assert normalize_section_name("## Databases") == "Databases"

    def test_strips_badges_and_emoji(self):
        assert normalize_section_name("[awesome] Security 🔐 Tools") == "awesome Security Tools"

    def test_strips_brackets_and_bold(self):
        assert normalize_section_name("**Data Engineering**") == "Data Engineering"

    def test_empty_input(self):
        assert normalize_section_name("") == ""
        assert normalize_section_name(None) == ""


class TestSectionToCategory:
    def test_exact_leaf_match(self, taxonomy):
        assert section_to_category("Databases", taxonomy) == "Databases"

    def test_case_insensitive_match(self, taxonomy):
        assert section_to_category("databases", taxonomy) == "Databases"

    def test_keyword_match_on_decorated_heading(self, taxonomy):
        assert section_to_category("[awesome] Security 🔐 Tools", taxonomy) == "AppSec"

    def test_parent_heading_resolves_within_that_parent(self, taxonomy):
        assert section_to_category("Security", taxonomy) == "AppSec"
        assert taxonomy.parent_of(section_to_category("Security", taxonomy)) == "Security"

    def test_unresolvable_heading_returns_none(self, taxonomy):
        assert section_to_category("Table of Contents", taxonomy) is None

    def test_never_returns_a_parent_name(self, taxonomy):
        for parent in taxonomy.parents:
            result = section_to_category(parent, taxonomy)
            assert result is None or taxonomy.has(result)

    def test_empty_heading_returns_none(self, taxonomy):
        assert section_to_category("", taxonomy) is None


class TestClassifyRepository:
    def test_matches_topics_first(self, taxonomy):
        repo = make_repo(topics=["vector-database"], language="Python")
        categories = classify_repository(repo, taxonomy)
        assert categories[0] == "RAG"
        assert "Python" in categories

    def test_matches_language(self, taxonomy):
        repo = make_repo(language="Rust")
        assert "Rust" in classify_repository(repo, taxonomy)

    def test_cpp_language_maps_to_c_plus_plus(self, taxonomy):
        assert "C++" in classify_repository(make_repo(language="C++"), taxonomy)

    def test_matches_description_keywords(self, taxonomy):
        repo = make_repo(description="A collection of kubernetes operators")
        assert "Kubernetes" in classify_repository(repo, taxonomy)

    def test_matches_repo_name(self, taxonomy):
        assert "Terraform" in classify_repository(make_repo(name="terraform-docs"), taxonomy)

    def test_word_boundaries_prevent_false_positives(self, taxonomy):
        """Substring matching used to tag every repo containing 'c' or 'go'."""
        repo = make_repo(
            name="maintainer",
            description="Going places since 1998",
            language="Python",
        )
        assert "Go" not in classify_repository(repo, taxonomy)

    def test_results_are_always_taxonomy_leaves(self, taxonomy):
        repo = make_repo(
            description="LLM agents with retrieval augmented generation and vector search",
            language="TypeScript",
            topics=["ai-agents", "prompt-engineering"],
        )
        for name in classify_repository(repo, taxonomy):
            assert taxonomy.has(name), name

    def test_respects_max_categories(self, taxonomy):
        repo = make_repo(
            description=(
                "LLM agents, retrieval augmented generation, kubernetes operators, "
                "terraform modules, postgres database, prometheus monitoring"
            ),
            language="Python",
            topics=["ai-agents", "kubernetes", "terraform"],
        )
        assert len(classify_repository(repo, taxonomy, max_categories=3)) == 3

    def test_deduplicates_categories(self, taxonomy):
        repo = make_repo(
            description="rust tooling",
            language="Rust",
            topics=["rust"],
        )
        categories = classify_repository(repo, taxonomy)
        assert categories.count("Rust") == 1

    def test_repo_with_no_signals_gets_nothing(self, taxonomy):
        repo = make_repo(name="x", description="", language=None, topics=[])
        assert classify_repository(repo, taxonomy) == []


class TestCategoryParents:
    def test_maps_leaves_to_parents(self, taxonomy):
        assert category_parents(["LLM", "Rust"], taxonomy) == {
            "LLM": "AI",
            "Rust": "Programming Languages",
        }

    def test_ignores_unknown_names(self, taxonomy):
        assert category_parents(["Not A Category"], taxonomy) == {}
