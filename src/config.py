"""Loader for the YAML files under ``config/``.

The taxonomy in ``config/categories.yml`` is the single source of truth for
category names. Nothing else in the pipeline is allowed to invent a category
name: every value written to the ``categories`` table must appear in
``taxonomy``.
"""

import os
from dataclasses import dataclass, field
from typing import Any

import yaml


class ConfigError(RuntimeError):
    """Raised when a config file is missing or malformed."""


@dataclass(frozen=True)
class CategoryTaxonomy:
    parents: dict[str, list[str]] = field(default_factory=dict)
    keywords: dict[str, list[str]] = field(default_factory=dict)
    topics: dict[str, list[str]] = field(default_factory=dict)

    @property
    def leaf_parent(self) -> dict[str, str]:
        return {leaf: parent for parent, leaves in self.parents.items() for leaf in leaves}

    @property
    def leaves(self) -> list[str]:
        return [leaf for leaves in self.parents.values() for leaf in leaves]

    def parent_of(self, name: str) -> str | None:
        return self.leaf_parent.get(name)

    def has(self, name: str) -> bool:
        return name in self.leaf_parent

    def as_parent_map(self) -> dict[str, str]:
        """Map every known leaf name to its parent name."""
        return dict(self.leaf_parent)

    def keyword_map(self) -> dict[str, list[str]]:
        return {leaf: list(values) for leaf, values in self.keywords.items()}

    def topic_map(self) -> dict[str, list[str]]:
        return {leaf: list(values) for leaf, values in self.topics.items()}

    def filter_leaves(self, names: list[str]) -> list[str]:
        """Drop anything that is not a declared leaf, preserving order and uniqueness."""
        seen: set[str] = set()
        kept: list[str] = []
        for name in names:
            if self.has(name) and name not in seen:
                seen.add(name)
                kept.append(name)
        return kept


def _read_yaml(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        raise ConfigError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        try:
            data = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"Expected a mapping at the top level of {path}")
    return data


def _string_list(value: Any, context: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"Expected a list under {context}")
    return [str(item).strip() for item in value if str(item).strip()]


def load_categories(config_dir: str = "config") -> CategoryTaxonomy:
    """Load and validate the category taxonomy."""
    path = os.path.join(config_dir, "categories.yml")
    data = _read_yaml(path)

    raw_taxonomy = data.get("taxonomy") or {}
    if not isinstance(raw_taxonomy, dict) or not raw_taxonomy:
        raise ConfigError(f"{path}: 'taxonomy' must be a non-empty mapping")

    parents: dict[str, list[str]] = {}
    leaf_parent: dict[str, str] = {}
    for parent, leaves in raw_taxonomy.items():
        if parent in leaf_parent:
            raise ConfigError(f"{path}: '{parent}' is both a parent and a leaf")
        entries = _string_list(leaves, f"{path}: taxonomy.{parent}")
        if not entries:
            raise ConfigError(f"{path}: taxonomy.{parent} has no categories")
        parents[str(parent)] = entries
        for leaf in entries:
            if leaf in leaf_parent:
                raise ConfigError(
                    f"{path}: '{leaf}' appears under both "
                    f"'{leaf_parent[leaf]}' and '{parent}'"
                )
            leaf_parent[leaf] = str(parent)

    keywords = _load_index(data, "keywords", path, set(leaf_parent))
    topics = _load_index(data, "topics", path, set(leaf_parent))

    return CategoryTaxonomy(parents=parents, keywords=keywords, topics=topics)


def _load_index(
    data: dict[str, Any], key: str, path: str, known: set[str]
) -> dict[str, list[str]]:
    raw = data.get(key) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: '{key}' must be a mapping")
    result: dict[str, list[str]] = {}
    for name, values in raw.items():
        if name not in known:
            raise ConfigError(f"{path}: {key}.'{name}' is not a category in 'taxonomy'")
        entries = _string_list(values, f"{path}: {key}.{name}")
        if entries:
            result[name] = entries
    return result


def load_config(config_dir: str = "config", name: str = "") -> dict[str, Any]:
    """Load an arbitrary config file by base name (without the ``.yml`` suffix)."""
    path = os.path.join(config_dir, f"{name}.yml")
    return _read_yaml(path)
