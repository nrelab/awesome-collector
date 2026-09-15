import re
from typing import Optional

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