from dataclasses import dataclass
from typing import Optional

from src.models import Repository
from src.normalize.urls import normalize_url


@dataclass
class DuplicateMatch:
    primary: Repository
    duplicates: list[Repository]
    match_type: str


def dedupe_repositories(
    repos: list[Repository],
    match_fields: Optional[list[str]] = None,
) -> tuple[list[Repository], list[DuplicateMatch]]:
    if match_fields is None:
        match_fields = ["id"]

    canonical: dict[str, Repository] = {}
    duplicates: list[DuplicateMatch] = []

    for repo in repos:
        key = _get_key(repo, match_fields)
        if key in canonical:
            existing = canonical[key]
            _track_duplicate(existing, repo, duplicates)
        else:
            canonical[key] = repo

    return list(canonical.values()), duplicates


def _get_key(repo: Repository, fields: list[str]) -> str:
    parts = []
    for field in fields:
        if field == "id":
            parts.append(repo.id)
        elif field == "url":
            parts.append(normalize_url(repo.url))
        elif field == "owner":
            parts.append(repo.owner.lower())
        elif field == "name":
            parts.append(repo.name.lower())
        else:
            val = getattr(repo, field, "")
            parts.append(str(val).lower() if val else "")
    return "|".join(parts)


def _track_duplicate(existing: Repository, duplicate: Repository, duplicates: list[DuplicateMatch]) -> None:
    for dm in duplicates:
        if dm.primary.id == existing.id:
            dm.duplicates.append(duplicate)
            return
    duplicates.append(DuplicateMatch(primary=existing, duplicates=[duplicate], match_type="id"))