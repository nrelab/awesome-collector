import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.models import Repository


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class JsonStore:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_repository(self, repo: Repository, subdir: Optional[str] = None) -> None:
        dir_path = self.base_dir / (subdir or "repositories")
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{repo.id.replace('/', '_')}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(repo.to_dict(), f, indent=2, default=str)

    def load_repository(self, repo_id: str, subdir: Optional[str] = None) -> Optional[dict]:
        dir_path = self.base_dir / (subdir or "repositories")
        file_path = dir_path / f"{repo_id.replace('/', '_')}.json"
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def save_daily_snapshot(self, date_str: str, data: dict) -> None:
        dir_path = self.base_dir / "daily"
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{date_str}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def load_daily_snapshot(self, date_str: str) -> Optional[dict]:
        file_path = self.base_dir / "daily" / f"{date_str}.json"
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def save_awesome_list(self, repo_id: str, data: dict) -> None:
        dir_path = self.base_dir / "awesome-lists"
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{repo_id.replace('/', '_')}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def load_awesome_list(self, repo_id: str) -> Optional[dict]:
        file_path = self.base_dir / "awesome-lists" / f"{repo_id.replace('/', '_')}.json"
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def load_index(self) -> dict:
        index_path = self.base_dir / "index.json"
        if index_path.exists():
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"repositories": [], "last_updated": None, "total": 0}

    def save_index(self, index: dict) -> None:
        index_path = self.base_dir / "index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, default=str)

    def list_daily_snapshots(self) -> list[str]:
        dir_path = self.base_dir / "daily"
        if not dir_path.exists():
            return []
        return sorted([f.stem for f in dir_path.glob("*.json")])

    def get_all_repositories(self) -> list[Repository]:
        repos = []
        dir_path = self.base_dir / "repositories"
        if dir_path.exists():
            for f in dir_path.glob("*.json"):
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                        repos.append(Repository.from_dict(data))
                except Exception:
                    continue
        return repos