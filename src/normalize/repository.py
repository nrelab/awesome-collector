from typing import Optional

from src.models import Repository
from src.normalize.urls import (
    repository_id,
    repository_id_from_url,
    to_canonical_url,
)


def normalize_repository(repo: Repository) -> Repository:
    repo.id = repository_id(repo.owner, repo.name)
    repo.url = to_canonical_url(repo.id)
    repo.owner = repo.owner.strip().lower()
    repo.name = repo.name.strip().lower()
    return repo


def create_repository_from_api(data: dict, collected_at: str) -> Repository:
    owner = data.get("owner", {}).get("login", "")
    name = data.get("name", "")
    return Repository(
        id=repository_id(owner, name),
        owner=owner,
        name=name,
        url=data.get("html_url", f"https://github.com/{owner}/{name}"),
        description=data.get("description"),
        stars=data.get("stargazers_count"),
        forks=data.get("forks_count", data.get("forks")),
        issues=data.get("open_issues_count"),
        language=data.get("language"),
        topics=data.get("topics", []),
        license=data.get("license", {}).get("key") if data.get("license") else None,
        archived=data.get("archived", False),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        pushed_at=data.get("pushed_at"),
        collected_at=collected_at,
    )


def create_repository_from_url(url: str, collected_at: str) -> Optional[Repository]:
    repo_id = repository_id_from_url(url)
    if not repo_id:
        return None
    owner, name = repo_id[len("github:"):].split("/", 1)
    return Repository(
        id=repo_id,
        owner=owner,
        name=name,
        url=f"https://github.com/{owner}/{name}",
        collected_at=collected_at,
    )


def merge_sources(existing: Repository, new_sources: list[dict]) -> Repository:
    existing_sources = {
        (s.get("repository", ""), s.get("section", "")) for s in existing.sources
    }
    for source in new_sources:
        key = (source.get("repository", ""), source.get("section", ""))
        if key not in existing_sources:
            existing.sources.append(source)
            existing_sources.add(key)
    return existing