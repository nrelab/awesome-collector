import re
from urllib.parse import urlparse
from typing import Optional

from src.normalize.urls import normalize_url, repository_id_from_url

_LINK_PATTERN = re.compile(
    r"\[([^\]]*)\]\(([^)]+)\)", re.IGNORECASE
)
_URL_PATTERN = re.compile(
    r"(https?://github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", re.IGNORECASE
)
_SECTION_PATTERN = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_GITHUB_RAW_PATTERN = re.compile(
    r"(https?://github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", re.MULTILINE
)
_GITHUB_LINK_PATTERN = re.compile(
    r"^[\s\-\*]*\[([^\]]+)\]\((https?://[^\)]+)\)", re.MULTILINE
)


def extract_links(markdown: str) -> list[tuple[str, str]]:
    return [(match.group(1), match.group(2)) for match in _LINK_PATTERN.finditer(markdown)]


def extract_github_urls(markdown: str) -> list[str]:
    return _URL_PATTERN.findall(markdown)


def extract_ossfuzz_links(markdown: str) -> list[str]:
    return [
        m.group(1)
        for m in re.finditer(
            r"<(https://github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)>", markdown
        )
    ]


def extract_section_headings(markdown: str) -> list[tuple[str, int]]:
    result = []
    for m in _SECTION_PATTERN.finditer(markdown):
        title = m.group(1)
        level = sum(1 for c in m.group(0) if c == "#")
        result.append((title, level))
    return result


def extract_repo_info_from_link(
    link_text: str, link_url: str
) -> Optional[tuple[str, str]]:
    repo_id = _parse_github_url(link_url)
    if repo_id:
        return (link_text.strip(), repo_id)
    return None


def _parse_github_url(url: str) -> Optional[str]:
    url = url.strip()
    if url.startswith("github:"):
        return repository_id_from_url(f"https://github.com/{url[len('github:'):]}")
    return repository_id_from_url(url)


def find_repository_references(markdown: str) -> list[dict]:
    results = []

    for text, url in extract_links(markdown):
        repo_id = _parse_github_url(url)
        if repo_id:
            results.append({"text": text, "url": url, "repo_id": repo_id, "type": "link"})

    for url in extract_github_urls(markdown):
        repo_id = _parse_github_url(url)
        if repo_id and not any(r["repo_id"] == repo_id for r in results):
            results.append({"text": url, "url": url, "repo_id": repo_id, "type": "raw_url"})

    for url in extract_ossfuzz_links(markdown):
        repo_id = _parse_github_url(url)
        if repo_id and not any(r["repo_id"] == repo_id for r in results):
            results.append({"text": url, "url": url, "repo_id": repo_id, "type": "ossfuzz"})

    return results


def extract_readme_quality(markdown: str) -> dict:
    word_count = len(markdown.split())
    has_toc = bool(re.search(r"^\[?\[?[^]]+\]:?\s+#", markdown, re.MULTILINE))
    has_badges = bool(re.search(r"!\[[^\]]*\]\([^)]*\)", markdown))
    has_tables = bool(re.search(r"^\|.*\|.*\|", markdown, re.MULTILINE))
    has_code_blocks = bool(re.search(r"```", markdown))
    score = _readme_quality_score(
        word_count, has_toc, has_badges, has_tables, has_code_blocks
    )
    return {
        "word_count": word_count,
        "has_toc": has_toc,
        "has_badges": has_badges,
        "has_tables": has_tables,
        "has_code_blocks": has_code_blocks,
        "quality_score": score,
    }


def _readme_quality_score(
    words: int, toc: bool, badges: bool, tables: bool, code: bool
) -> int:
    score = 0
    if words >= 50:
        score += 25
    elif words >= 20:
        score += 15
    if toc:
        score += 25
    if badges:
        score += 15
    if tables:
        score += 20
    if code:
        score += 15
    return min(score, 100)


def parse_awesome_list(markdown: str, source_repo: str = "") -> dict:
    sections = _extract_sections(markdown)
    all_repos = _extract_all_repositories(markdown)
    categories = _extract_categories(markdown)

    return {
        "is_awesome_list": True,
        "source_repository": source_repo,
        "sections": sections,
        "repositories": all_repos,
        "categories": categories,
        "total_repositories": len(all_repos),
    }


def _extract_sections(markdown: str) -> list[dict]:
    sections = []
    for match in _SECTION_PATTERN.finditer(markdown):
        title = match.group(1).strip()
        level = len(match.group(0)) - len(title)
        sections.append({"title": title, "level": level, "match": match.group(0)})
    return sections


def _extract_all_repositories(markdown: str) -> list[dict]:
    repos = []
    seen = set()

    for match in _GITHUB_LINK_PATTERN.finditer(markdown):
        text = match.group(1).strip()
        raw_url = match.group(2)
        repo_id = repository_id_from_url(raw_url)
        if repo_id and repo_id not in seen:
            seen.add(repo_id)
            repos.append(
                {"repo_id": repo_id, "name": text, "url": normalize_url(raw_url), "source": "link"}
            )

    for match in _GITHUB_RAW_PATTERN.finditer(markdown):
        raw_url = match.group(1)
        repo_id = repository_id_from_url(raw_url)
        if repo_id and repo_id not in seen:
            seen.add(repo_id)
            repos.append(
                {"repo_id": repo_id, "name": raw_url, "url": normalize_url(raw_url), "source": "raw_url"}
            )

    return repos


def _extract_categories(markdown: str) -> list[str]:
    categories = []
    for match in _SECTION_PATTERN.finditer(markdown):
        title = match.group(1).strip()
        level = len(match.group(0)) - len(title)
        if level == 2:
            categories.append(title)
    return categories


def is_github_repo_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc in ("github.com", "www.github.com", "github.com")