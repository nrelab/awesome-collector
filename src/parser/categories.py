import re
from typing import Optional

from src.config import CategoryTaxonomy
from src.models import Repository
from src.normalize.urls import normalize_url

_CATEGORY_PATTERN = re.compile(
    r"^#{1,6}\s+\[?([^\]]+)\]?", re.MULTILINE
)
_LINK_PATTERN = re.compile(
    r"\[([^\]]*)\]\(([^)]+)\)", re.IGNORECASE
)
_GITHUB_URL_PATTERN = re.compile(
    r"(https?://github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", re.IGNORECASE
)


def extract_categories_from_markdown(markdown: str) -> list[dict]:
    categories = []
    current_category = None
    current_repos = []

    lines = markdown.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            if level <= 3:
                if current_category is not None:
                    categories.append(
                        {"name": current_category, "repositories": current_repos}
                    )
                current_category = title
                current_repos = []
            elif current_category is not None and level <= 4:
                repo = _try_extract_repo_from_line(line)
                if repo:
                    current_repos.append(repo)
        elif current_category is not None:
            repo = _try_extract_repo_from_line(line)
            if repo:
                current_repos.append(repo)
        i += 1

    if current_category is not None:
        categories.append(
            {"name": current_category, "repositories": current_repos}
        )

    return categories


def _try_extract_repo_from_line(line: str) -> Optional[dict]:
    github_urls = _GITHUB_URL_PATTERN.findall(line)
    if github_urls:
        link_match = re.match(
            r"^[\s\-\*]*\[?([^\]]*)\]?\s*\((https?://[^)]+)\)", line.strip()
        )
        text = link_match.group(1).strip() if link_match else github_urls[0]
        return {
            "url": normalize_url(github_urls[0]),
            "name": text,
        }
    return None


def categorize_by_keywords(repo: Repository, category_taxonomy: dict) -> list[str]:
    matched_categories = []

    text_to_check = " ".join([
        repo.description or "",
        " ".join(repo.topics),
        repo.name,
    ]).lower()

    for category, keywords in category_taxonomy.items():
        for keyword in keywords:
            if keyword.lower() in text_to_check:
                if category not in matched_categories:
                    matched_categories.append(category)
                break

    return matched_categories


def categorize_by_language(repo: Repository) -> list[str]:
    language = (repo.language or "").lower()
    if language == "python":
        return ["Python"]
    elif language == "rust":
        return ["Rust"]
    elif language == "go":
        return ["Go"]
    elif language in ("javascript", "typescript"):
        return ["TypeScript"] if language == "typescript" else ["JavaScript"]
    elif language == "java":
        return ["Java"]
    elif language == "cpp":
        return ["C++"]
    elif language == "c":
        return ["C"]
    elif language == "swift":
        return ["Swift"]
    elif language == "kotlin":
        return ["Kotlin"]
    elif language == "ruby":
        return ["Ruby"]
    return []


def categorize_by_topics(repo: Repository, topic_map: dict) -> list[str]:
    matched = []
    for topic in repo.topics:
        topic_lower = topic.lower()
        for category, topics in topic_map.items():
            if topic_lower in [t.lower() for t in topics]:
                if category not in matched:
                    matched.append(category)
                break
    return matched


_LANGUAGE_CATEGORIES = {
    "python": "Python",
    "rust": "Rust",
    "go": "Go",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "java": "Java",
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "csharp": "C#",
    "c": "C",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "ruby": "Ruby",
    "shell": "CLI",
    "html": "Web Development",
}

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\u2190-\u21FF"
    "\u2300-\u27BF"
    "\u2B00-\u2BFF"
    "\uFE0F"
    "\u200D"
    "]+"
)
_NOISE_PATTERN = re.compile(r"[\[\](){}*_`#•·|]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_WORD_BOUNDARY = r"(?<![a-z0-9]){}(?![a-z0-9])"


def normalize_section_name(section: str) -> str:
    """Reduce an awesome-list heading to a bare title.

    Strips emoji, bracketed decoration, badges, and collapsed whitespace so that
    headings like ``"## [awesome] Security 🔐 Tools"`` compare cleanly against
    taxonomy names.
    """
    text = _NOISE_PATTERN.sub(" ", section or "")
    text = _EMOJI_PATTERN.sub(" ", text)
    text = _WHITESPACE_PATTERN.sub(" ", text).strip()
    text = text.strip("-–—:|,")
    return text.strip()


def _keyword_matcher(keyword: str) -> re.Pattern:
    escaped = re.escape(keyword)
    if keyword.isascii():
        escaped = _WORD_BOUNDARY.format(escaped)
    return re.compile(escaped, re.IGNORECASE)


def _matched_categories(text: str, index: dict[str, list[str]]) -> list[str]:
    if not text.strip():
        return []
    matched = []
    for category, keywords in index.items():
        for keyword in keywords:
            if _keyword_matcher(keyword).search(text):
                matched.append(category)
                break
    return matched


def section_to_category(section: str, taxonomy: CategoryTaxonomy) -> Optional[str]:
    """Map an awesome-list heading onto a taxonomy leaf.

    Returns ``None`` when the heading cannot be resolved, so callers can drop
    unrecognised headings instead of polluting the category table.
    """
    title = normalize_section_name(section)
    if not title:
        return None

    lookup = {leaf.lower(): leaf for leaf in taxonomy.leaves}
    if title.lower() in lookup:
        return lookup[title.lower()]

    index = taxonomy.keyword_map()
    if title in taxonomy.parents:
        index = {
            leaf: keywords
            for leaf, keywords in index.items()
            if taxonomy.parent_of(leaf) == title
        }

    matches = _matched_categories(title, index)
    return matches[0] if matches else None


def classify_repository(
    repo: Repository, taxonomy: CategoryTaxonomy, max_categories: int = 5
) -> list[str]:
    """Assign taxonomy leaves to a repository.

    Signals are gathered strongest-first — explicit GitHub topics, then the
    primary language, then free-text keyword matches — so that when the result
    is truncated the surviving categories are the most reliable ones. Every
    returned value is guaranteed to be a declared leaf in ``taxonomy``.
    """
    ranked: list[str] = []

    def add(names: list[str]) -> None:
        for name in taxonomy.filter_leaves(names):
            if name not in ranked:
                ranked.append(name)

    add(categorize_by_topics(repo, taxonomy.topic_map()))

    language = (repo.language or "").strip().lower()
    if language in _LANGUAGE_CATEGORIES:
        add([_LANGUAGE_CATEGORIES[language]])

    text = " ".join(
        [repo.description or "", " ".join(repo.topics or []), repo.name or ""]
    )
    add(_matched_categories(text, taxonomy.keyword_map()))

    return ranked[:max_categories]


def category_parents(categories: list[str], taxonomy: CategoryTaxonomy) -> dict[str, str]:
    """Map each leaf name in ``categories`` to its parent name."""
    return {name: taxonomy.leaf_parent[name] for name in categories if taxonomy.has(name)}
