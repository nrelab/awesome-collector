import os

import pytest
import yaml

from src.config import ConfigError, load_categories, load_config

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
)


def write_config(tmp_path, payload: dict) -> str:
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    with open(config_dir / "categories.yml", "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f)
    return str(config_dir)


class TestShippedConfig:
    def setup_method(self):
        self.taxonomy = load_categories(CONFIG_DIR)

    def test_all_config_files_parse(self):
        for name in ["categories", "filters", "scoring", "sources"]:
            assert isinstance(load_config(CONFIG_DIR, name), dict)

    def test_taxonomy_has_parents_and_leaves(self):
        assert len(self.taxonomy.parents) >= 5
        assert len(self.taxonomy.leaves) >= 30

    def test_leaf_names_are_unique_across_parents(self):
        assert len(self.taxonomy.leaves) == len(set(self.taxonomy.leaves))

    def test_every_leaf_resolves_to_a_parent(self):
        for leaf in self.taxonomy.leaves:
            assert self.taxonomy.parent_of(leaf) in self.taxonomy.parents

    def test_no_parent_is_also_a_leaf(self):
        for parent in self.taxonomy.parents:
            assert not self.taxonomy.has(parent)

    def test_keyword_and_topic_keys_are_declared_categories(self):
        declared = set(self.taxonomy.leaves)
        assert set(self.taxonomy.keywords) <= declared
        assert set(self.taxonomy.topics) <= declared

    def test_every_leaf_has_keywords_and_topics(self):
        declared = set(self.taxonomy.leaves)
        assert declared <= set(self.taxonomy.keywords)
        assert declared <= set(self.taxonomy.topics)

    def test_filter_leaves_drops_unknown_names(self):
        kept = self.taxonomy.filter_leaves(["LLM", "Not A Category", "Rust", "LLM"])
        assert kept == ["LLM", "Rust"]

    def test_parent_names_do_not_conflict_with_previous_taxonomy(self):
        """The old file duplicated leaves across Infrastructure/DevOps and Data."""
        parents = set(self.taxonomy.parents)
        assert parents == {
            "AI", "Security", "Development", "Infrastructure",
            "Data", "Web3", "Mobile", "Programming Languages",
        }

    def test_language_leaves_cover_every_mapped_language(self):
        from src.parser.categories import _LANGUAGE_CATEGORIES

        for category in _LANGUAGE_CATEGORIES.values():
            assert self.taxonomy.has(category), category


class TestConfigErrors:
    def test_missing_file(self):
        with pytest.raises(ConfigError, match="not found"):
            load_categories("/nonexistent/config")

    def test_invalid_yaml(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        with open(config_dir / "categories.yml", "w", encoding="utf-8") as f:
            f.write("taxonomy:\n  AI:\n   -LLM\n  Broken\n")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_categories(str(config_dir))

    def test_empty_taxonomy(self, tmp_path):
        config_dir = write_config(tmp_path, {"keywords": {}})
        with pytest.raises(ConfigError, match="taxonomy"):
            load_categories(config_dir)

    def test_duplicate_leaf_across_parents(self, tmp_path):
        config_dir = write_config(tmp_path, {
            "taxonomy": {"AI": ["LLM"], "Data": ["LLM"]},
        })
        with pytest.raises(ConfigError, match="appears under both"):
            load_categories(config_dir)

    def test_keyword_key_not_in_taxonomy(self, tmp_path):
        config_dir = write_config(tmp_path, {
            "taxonomy": {"AI": ["LLM"]},
            "keywords": {"Robotics": ["robot"]},
        })
        with pytest.raises(ConfigError, match="not a category in 'taxonomy'"):
            load_categories(config_dir)

    def test_top_level_not_a_mapping(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        with open(config_dir / "categories.yml", "w", encoding="utf-8") as f:
            f.write("- a\n- b\n")
        with pytest.raises(ConfigError, match="mapping"):
            load_categories(str(config_dir))
