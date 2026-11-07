"""Repository content extraction for the knowledge-base pipeline.

Fetches README content, documentation files, and API references (OpenAPI /
Swagger specs) for repositories that meet a configurable quality threshold.

Bounds
------
Extraction never clones repositories and never fetches unbounded content:

- ``max_repositories`` caps how many repos are processed per run.
- ``max_files_per_repo`` caps documentation/API files per repository.
- ``max_bytes_per_file`` truncates any single fetched file.
- ``max_total_bytes_per_repo`` caps the total stored content per repo.

Failures for individual repositories are recorded and never abort the run.
"""

import base64
from dataclasses import dataclass, field
from datetime import UTC

import httpx

API_SPEC_NAMES = {
    "openapi.json", "openapi.yaml", "openapi.yml",
    "swagger.json", "swagger.yaml", "swagger.yml",
}
DOC_DIR_CANDIDATES = ("docs", "doc", "documentation", "wiki")


@dataclass
class ExtractionConfig:
    min_score: float = 0.0
    max_repositories: int = 100
    max_files_per_repo: int = 10
    max_bytes_per_file: int = 200_000
    max_total_bytes_per_repo: int = 1_000_000
    include_readme: bool = True
    include_docs: bool = True
    include_api_specs: bool = True


@dataclass
class ExtractionReport:
    selected: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[dict] = field(default_factory=list)
    documents: int = 0

    def to_dict(self) -> dict:
        return {
            "selected": self.selected,
            "succeeded": self.succeeded,
            "skipped": self.skipped,
            "failed": self.failed,
            "failures": self.failures,
            "documents": self.documents,
        }


def _decode_content(payload: dict) -> str:
    content = payload.get("content")
    if content:
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return ""


class ContentExtractor:
    def __init__(self, client, config: ExtractionConfig | None = None):
        self.client = client
        self.config = config or ExtractionConfig()

    def select_repositories(self, rows: list[dict]) -> list[dict]:
        """Pick rows whose score meets ``min_score``, best first, capped."""
        eligible = [
            r for r in rows
            if (r.get("score_overall") or 0) >= self.config.min_score
        ]
        eligible.sort(key=lambda r: r.get("score_overall") or 0, reverse=True)
        return eligible[: self.config.max_repositories]

    def extract(self, row: dict) -> dict:
        """Extract content for one repository row. Raises on hard failure."""
        repo_id = row.get("id", "")
        if not repo_id.startswith("github:"):
            raise ValueError(f"unsupported repository id: {repo_id}")
        owner, name = repo_id[len("github:"):].split("/", 1)

        documents: list[dict] = []
        total_bytes = 0
        cfg = self.config

        def add_document(kind: str, path: str, url: str, text: str) -> bool:
            nonlocal total_bytes
            if not text:
                return False
            encoded = text.encode("utf-8", errors="replace")
            if len(encoded) > cfg.max_bytes_per_file:
                text = encoded[: cfg.max_bytes_per_file].decode("utf-8", errors="replace")
                truncated = True
            else:
                truncated = False
            size = len(text.encode("utf-8", errors="replace"))
            if total_bytes + size > cfg.max_total_bytes_per_repo:
                return False
            total_bytes += size
            documents.append({
                "kind": kind,
                "path": path,
                "url": url,
                "content": text,
                "bytes": size,
                "truncated": truncated,
            })
            return True

        if cfg.include_readme:
            readme = self.client.get_readme(owner, name)
            if readme:
                text = _decode_content(readme)
                if not text and readme.get("download_url"):
                    text = self._fetch_text(readme["download_url"])
                add_document(
                    "readme",
                    readme.get("name", "README"),
                    readme.get("html_url", f"https://github.com/{owner}/{name}"),
                    text,
                )

        if cfg.include_docs or cfg.include_api_specs:
            for doc_path in DOC_DIR_CANDIDATES + ("",):
                try:
                    listing = self.client.get(
                        f"/repos/{owner}/{name}/contents/{doc_path}".rstrip("/")
                        if doc_path else f"/repos/{owner}/{name}/contents"
                    )
                except Exception:
                    continue
                if not isinstance(listing, list):
                    continue
                files = 0
                for item in listing:
                    if files >= cfg.max_files_per_repo:
                        break
                    if item.get("type") != "file":
                        continue
                    item_name = item.get("name", "")
                    item_path = item.get("path", item_name)
                    lower = item_name.lower()
                    is_doc = lower.endswith((".md", ".mdx", ".rst", ".txt"))
                    is_api = lower in API_SPEC_NAMES
                    if cfg.include_api_specs and is_api:
                        kind = "api"
                    elif cfg.include_docs and is_doc:
                        kind = "docs"
                    else:
                        continue
                    try:
                        payload = self.client.get(
                            f"/repos/{owner}/{name}/contents/{item_path}"
                        )
                        text = _decode_content(payload)
                    except Exception:
                        continue
                    if add_document(kind, item_path, item.get("html_url", ""), text):
                        files += 1

        return {
            "repository_id": repo_id,
            "owner": owner,
            "name": name,
            "url": f"https://github.com/{owner}/{name}",
            "extracted_at": _utc_now(),
            "documents": documents,
            "document_count": len(documents),
        }

    @staticmethod
    def _fetch_text(url: str, max_bytes: int = 1_000_000) -> str:
        try:
            resp = httpx.get(url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.content[:max_bytes].decode("utf-8", errors="replace")
        except Exception:
            return ""

    def run(self, rows: list[dict]) -> tuple[ExtractionReport, list[dict]]:
        """Extract content for all selected rows; returns (report, payloads)."""
        selected = self.select_repositories(rows)
        report = ExtractionReport(selected=len(selected))
        payloads = []
        for row in selected:
            try:
                payload = self.extract(row)
            except Exception as exc:
                report.failed += 1
                report.failures.append({
                    "id": row.get("id"),
                    "error": str(exc)[:300],
                })
                continue
            if payload["document_count"] == 0:
                report.skipped += 1
                continue
            report.succeeded += 1
            report.documents += payload["document_count"]
            payloads.append(payload)
        return report, payloads


def _utc_now() -> str:
    from datetime import datetime
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
