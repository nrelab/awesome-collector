import re
from typing import Optional
from urllib.parse import urlparse

from src.models import Repository


def normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    patterns = [
        r"^git@github\.com:(.+)\.git$",
        r"^git@ssh\.github\.com:/(.+)$",
        r"^git://github\.com/(.+)\.git$",
        r"^https://github\.com/(.+)\.git$",
        r"^https://github\.com/(.+)/?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            path = match.group(1).rstrip("/")
            parts = path.split("/")
            if len(parts) >= 2:
                owner, name = parts[0], parts[1]
                return f"github:{owner.lower()}/{name.lower()}"
    if url.startswith("https://github.com/"):
        path = url[len("https://github.com/"):].rstrip("/")
        parts = path.split("/")
        if len(parts) >= 2:
            owner, name = parts[0], parts[1]
            return f"github:{owner.lower()}/{name.lower()}"
    return url.rstrip("/")


def normalize_github_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/").rstrip(".git")
    if parsed.netloc in ("github.com", "www.github.com"):
        return f"https://github.com/{path}"
    return url


def repository_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path.strip("/").rstrip(".git")
    if parsed.netloc in ("github.com", "www.github.com", "github.com"):
        parts = path.split("/")
        if len(parts) >= 2:
            return f"github:{parts[0].lower()}/{parts[1].lower()}"

    ssh_match = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", url)
    if ssh_match:
        return f"github:{ssh_match.group(1).lower()}/{ssh_match.group(2).lower()}"

    return None


def repository_id(owner: str, name: str) -> str:
    return f"github:{owner.strip().lower()}/{name.strip().lower()}"


def is_github_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc in ("github.com", "www.github.com", "github.com")


def extract_owner_name_from_id(repo_id: str) -> tuple[str, str]:
    if not repo_id.startswith("github:"):
        raise ValueError(f"Invalid repository ID: {repo_id}")
    parts = repo_id[len("github:"):].split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid repository ID format: {repo_id}")
    return parts[0], parts[1]


def to_canonical_url(repo_id: str) -> str:
    owner, name = extract_owner_name_from_id(repo_id)
    return f"https://github.com/{owner}/{name}"


def normalize_repository_url(repo: Repository) -> str:
    return normalize_url(repo.url)