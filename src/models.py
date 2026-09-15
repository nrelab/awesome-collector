from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Repository:
    id: str
    owner: str
    name: str
    url: str
    platform: str = "github"
    description: Optional[str] = None
    stars: Optional[int] = None
    forks: Optional[int] = None
    issues: Optional[int] = None
    language: Optional[str] = None
    topics: list[str] = field(default_factory=list)
    license: Optional[str] = None
    archived: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    pushed_at: Optional[str] = None
    collected_at: Optional[str] = None

    awesome: Optional[dict[str, Any]] = None
    sources: list[dict[str, str]] = field(default_factory=list)
    activity: Optional[dict[str, Any]] = None
    score: Optional[dict[str, float]] = None
    health: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "platform": self.platform,
            "owner": self.owner,
            "name": self.name,
            "url": self.url,
            "description": self.description,
            "stars": self.stars,
            "forks": self.forks,
            "issues": self.issues,
            "language": self.language,
            "topics": self.topics,
            "license": self.license,
            "archived": self.archived,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pushed_at": self.pushed_at,
            "collected_at": self.collected_at,
            "awesome": self.awesome,
            "sources": self.sources,
            "activity": self.activity,
            "score": self.score,
            "health": self.health,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Repository":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @property
    def repo_path(self) -> str:
        return f"{self.owner}/{self.name}"

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Repository):
            return NotImplemented
        return self.id == other.id