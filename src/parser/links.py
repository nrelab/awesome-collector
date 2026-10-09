from typing import Optional

from src.models import Repository
from src.normalize.urls import is_github_url, normalize_url, repository_id_from_url


def is_awesome_list_url(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    if "github.com" not in url_lower and "github:" not in url_lower:
        return False
    if not is_github_url(url):
        return False

    path = _extract_path(url)
    if not path:
        return False

    parts = path.split("/")
    if len(parts) < 2:
        return False

    owner, name = parts[0].lower(), parts[1].lower()
    return (
        name.startswith("awesome")
        or name.startswith("awesome-list")
        or "-awesome" in name
        or "awesome" in name.split("-")
    )


def _extract_path(url: str) -> Optional[str]:
    from urllib.parse import urlparse
    from src.normalize.urls import _strip_git_suffix
    parsed = urlparse(url)
    if parsed.netloc in ("github.com", "www.github.com"):
        return _strip_git_suffix(parsed.path.strip("/"))
    if url.startswith("github:"):
        return _strip_git_suffix(url[len("github:"):])
    if url.startswith("git@github.com:"):
        return _strip_git_suffix(url[len("git@github.com:"):])
    return None


def is_awesome_list_repo(repo: Repository) -> bool:
    if not repo:
        return False
    if repo.name and repo.name.lower().startswith("awesome"):
        return True
    if repo.name and "-awesome" in repo.name.lower():
        return True
    if repo.topics and "awesome-list" in repo.topics:
        return True
    if repo.description:
        desc_lower = repo.description.lower()
        if "awesome list" in desc_lower or "awesome repository" in desc_lower:
            return True
    return is_awesome_list_url(repo.url)


def extract_awesome_list_metadata(markdown: str) -> dict:
    from src.parser.markdown import extract_links, extract_section_headings
    links = extract_links(markdown)
    headings = extract_section_headings(markdown)

    repo_count = 0
    github_links = [
        (text, url) for text, url in links if is_github_url(url)
    ]
    repo_count = len(github_links)

    return {
        "is_awesome_list": True,
        "section_count": len(headings),
        "sections": [h[0] for h in headings],
        "total_links": len(links),
        "github_links": github_links,
        "repository_count": repo_count,
    }