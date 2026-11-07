"""Security and supply-chain enrichment from OSV, CVE, and CISA KEV.

Providers are deliberately small and tolerant: each one fetches advisories
for a set of package names and returns normalized :class:`Finding` records.
Provider failures (network errors, HTTP errors, rate limits) are captured in
the report instead of aborting the whole enrichment run.

Matching model
--------------
Each repository contributes candidate package names derived from its name
(e.g. ``aquasecurity/trivy`` → ``trivy``) plus any explicitly configured
``package_names``. A finding is linked to a repository when its package name
matches one of those candidates; findings may also exist at package level
without a repository link.
"""

import base64
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

OSV_QUERY_URL = "https://api.osv.dev/v1/query"
KEV_FEED_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/"
    "known_exploited_vulnerabilities.json"
)
CVE_SEARCH_URL = "https://cve.circl.lu/api/search/{keyword}"


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_package_name(name: str) -> str:
    """Normalize a repo/package name for matching (lowercase, -/_ unified)."""
    return re.sub(r"[-_.]+", "-", (name or "").strip().lower())


@dataclass
class Finding:
    source: str                 # "osv" | "cisa-kev" | "cve"
    advisory_id: str
    package: str
    ecosystem: str = ""
    severity: str = ""
    summary: str = ""
    url: str = ""
    cve_ids: list[str] = field(default_factory=list)
    repository_id: str | None = None
    observed_at: str = ""

    def dedupe_key(self) -> tuple:
        return (self.source, self.advisory_id, self.package, self.repository_id)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "advisory_id": self.advisory_id,
            "package": self.package,
            "ecosystem": self.ecosystem,
            "severity": self.severity,
            "summary": self.summary,
            "url": self.url,
            "cve_ids": self.cve_ids,
            "repository_id": self.repository_id,
            "observed_at": self.observed_at,
        }


class ProviderError(RuntimeError):
    """Raised when an enrichment provider cannot complete a request."""


def _default_http() -> tuple[Callable, Callable]:
    import httpx

    def http_get(url: str, **kwargs):
        resp = httpx.get(url, timeout=30.0, follow_redirects=True, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def http_post(url: str, payload: dict, **kwargs):
        resp = httpx.post(url, json=payload, timeout=30.0, **kwargs)
        resp.raise_for_status()
        return resp.json()

    return http_get, http_post


class OsvProvider:
    """Queries the OSV API (https://api.osv.dev) per package name."""

    name = "osv"

    def __init__(self, http_post: Callable | None = None, delay: float = 0.2):
        self._post = http_post
        self.delay = delay
        self._calls = 0

    def _post_fn(self):
        if self._post is None:
            _, self._post = _default_http()
        return self._post

    def query(self, package: str, ecosystem: str = "") -> list[Finding]:
        body: dict = {"package": {"name": package, "ecosystem": ecosystem}}
        if self._calls and self.delay:
            time.sleep(self.delay)
        try:
            data = self._post_fn()(OSV_QUERY_URL, body)
        except Exception as exc:
            raise ProviderError(f"osv query failed for {package}: {exc}") from exc
        self._calls += 1
        findings = []
        for vuln in data.get("vulns", []) or []:
            severity = ""
            for entry in vuln.get("severity", []) or []:
                if entry.get("score"):
                    severity = str(entry["score"])
                    break
            if not severity:
                db = (vuln.get("database_specific") or {}).get("severity")
                severity = str(db) if db else ""
            cve_ids = [
                a for a in (vuln.get("aliases") or []) if a.upper().startswith("CVE-")
            ]
            findings.append(Finding(
                source="osv",
                advisory_id=vuln.get("id", ""),
                package=package,
                ecosystem=ecosystem,
                severity=severity,
                summary=(vuln.get("summary") or "")[:500],
                url=f"https://osv.dev/vulnerability/{vuln.get('id', '')}",
                cve_ids=cve_ids,
                observed_at=utc_now_iso(),
            ))
        return findings


class CisaKevProvider:
    """Fetches the CISA Known Exploited Vulnerabilities catalog feed."""

    name = "cisa-kev"

    def __init__(self, http_get: Callable | None = None):
        self._get = http_get

    def _get_fn(self):
        if self._get is None:
            self._get, _ = _default_http()
        return self._get

    def fetch_catalog(self) -> list[dict]:
        try:
            data = self._get_fn()(KEV_FEED_URL)
        except Exception as exc:
            raise ProviderError(f"cisa-kev feed fetch failed: {exc}") from exc
        return data.get("vulnerabilities", []) or []

    def query(self, packages: set[str]) -> list[Finding]:
        """Return KEV entries whose product matches one of ``packages``."""
        wanted = {normalize_package_name(p) for p in packages if p}
        findings = []
        for entry in self.fetch_catalog():
            product = normalize_package_name(entry.get("product", ""))
            vendor = normalize_package_name(entry.get("vendorProject", ""))
            matched = product in wanted or vendor in wanted
            if not matched:
                continue
            cve_id = entry.get("cveID", "")
            findings.append(Finding(
                source="cisa-kev",
                advisory_id=cve_id or entry.get("dateAdded", "unknown"),
                package=product or vendor,
                severity="KNOWN_EXPLOITED",
                summary=(entry.get("vulnerabilityName") or "")[:500],
                url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
                cve_ids=[cve_id] if cve_id else [],
                observed_at=utc_now_iso(),
            ))
        return findings


class CveProvider:
    """Searches the CIRCL CVE API (cve.circl.lu) per package name."""

    name = "cve"

    def __init__(self, http_get: Callable | None = None, delay: float = 0.2):
        self._get = http_get
        self.delay = delay

    def _get_fn(self):
        if self._get is None:
            self._get, _ = _default_http()
        return self._get

    def query(self, package: str) -> list[Finding]:
        try:
            if self.delay:
                time.sleep(self.delay)
            data = self._get_fn()(CVE_SEARCH_URL.format(keyword=package))
        except Exception as exc:
            raise ProviderError(f"cve search failed for {package}: {exc}") from exc
        entries = data if isinstance(data, list) else [data]
        findings = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cve_id = entry.get("id", "")
            if not cve_id.upper().startswith("CVE-"):
                continue
            cvss = ""
            for metric in (entry.get("cvss") or [])[:1]:
                cvss = str(metric.get("score", ""))
            findings.append(Finding(
                source="cve",
                advisory_id=cve_id,
                package=package,
                severity=cvss,
                summary=(entry.get("summary") or "")[:500],
                url=f"https://www.cve.org/CVERecord?id={cve_id}",
                cve_ids=[cve_id],
                observed_at=utc_now_iso(),
            ))
        return findings


class SecurityEnricher:
    """Runs enrichment providers over tracked repositories.

    ``providers`` may mix :class:`OsvProvider`, :class:`CisaKevProvider`,
    and :class:`CveProvider` instances (or test doubles exposing ``query``).
    Provider errors are recorded in the returned report under ``errors``
    and never abort the run.
    """

    PROVIDERS: ClassVar[dict] = {
        "osv": OsvProvider, "cisa-kev": CisaKevProvider, "cve": CveProvider,
    }

    def __init__(
        self,
        providers: list | None = None,
        sources: list[str] | None = None,
    ):
        if providers is not None:
            self.providers = providers
        else:
            wanted = sources or list(self.PROVIDERS)
            self.providers = [self.PROVIDERS[s]() for s in wanted if s in self.PROVIDERS]

    def package_candidates(self, repo) -> list[str]:
        """Derive package names to query for a repository."""
        candidates = []
        name = getattr(repo, "name", "") or ""
        normalized = normalize_package_name(name)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
        extra = (getattr(repo, "awesome", None) or {}).get("package_names") or []
        for pkg in extra:
            norm = normalize_package_name(pkg)
            if norm and norm not in candidates:
                candidates.append(norm)
        return candidates

    def collect(self, repos: list, min_stars: int = 0) -> dict:
        """Query all providers and return deduplicated findings + report."""
        eligible = [
            r for r in repos
            if (getattr(r, "stars", None) or 0) >= min_stars
        ]
        package_to_repo: dict[str, str] = {}
        for repo in eligible:
            for pkg in self.package_candidates(repo):
                package_to_repo.setdefault(pkg, getattr(repo, "id", ""))

        findings: list[Finding] = []
        errors: list[str] = []
        for provider in self.providers:
            pname = getattr(provider, "name", provider.__class__.__name__)
            try:
                if isinstance(provider, CisaKevProvider):
                    found = provider.query(set(package_to_repo))
                elif isinstance(provider, CveProvider):
                    found = []
                    for pkg in package_to_repo:
                        try:
                            found.extend(provider.query(pkg))
                        except ProviderError as exc:
                            errors.append(str(exc))
                else:
                    found = []
                    for pkg in package_to_repo:
                        try:
                            found.extend(provider.query(pkg))
                        except ProviderError as exc:
                            errors.append(str(exc))
                for f in found:
                    f.repository_id = package_to_repo.get(
                        normalize_package_name(f.package)
                    ) or f.repository_id
                findings.extend(found)
            except ProviderError as exc:
                errors.append(str(exc))
            except Exception as exc:  # provider bug must not kill the run
                errors.append(f"{pname}: unexpected error: {exc}")

        deduped = self._dedupe(findings)
        return {
            "findings": [f.to_dict() for f in deduped],
            "finding_count": len(deduped),
            "repositories_scanned": len(eligible),
            "packages_queried": len(package_to_repo),
            "provider_errors": errors,
            "observed_at": utc_now_iso(),
        }

    @staticmethod
    def _dedupe(findings: list[Finding]) -> list[Finding]:
        seen: set[tuple] = set()
        out = []
        for f in findings:
            key = f.dedupe_key()
            if key not in seen:
                seen.add(key)
                out.append(f)
        return out


def decode_readme_content(payload: dict) -> str:
    """Decode a GitHub contents-API payload to text (base64 or download_url)."""
    content = payload.get("content")
    if content:
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            pass
    return ""
