"""Tests for security/supply-chain enrichment (OSV, CVE, CISA KEV)."""

import tempfile

import pytest

from src.enrichment.security import (
    CisaKevProvider,
    CveProvider,
    Finding,
    OsvProvider,
    ProviderError,
    SecurityEnricher,
    normalize_package_name,
)
from src.main import CLICommands
from src.models import Repository
from src.storage.sqlite import SqliteStore


def _osv_vuln(vid="OSV-1", cve="CVE-2026-0001", severity="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"):
    return {
        "id": vid,
        "summary": f"vuln in {vid}",
        "severity": [{"type": "CVSS_V3", "score": severity}],
        "aliases": [cve],
    }


class TestProviders:
    def test_osv_query_parses_vulns(self):
        calls = []

        def fake_post(url, payload):
            calls.append(payload)
            return {"vulns": [_osv_vuln()]}

        provider = OsvProvider(http_post=fake_post, delay=0)
        findings = provider.query("trivy", "Go")
        assert len(findings) == 1
        f = findings[0]
        assert f.source == "osv"
        assert f.advisory_id == "OSV-1"
        assert f.cve_ids == ["CVE-2026-0001"]
        assert f.ecosystem == "Go"
        assert f.observed_at
        assert calls[0]["package"]["name"] == "trivy"

    def test_osv_provider_error_raises_provider_error(self):
        def bad_post(url, payload):
            raise RuntimeError("rate limited")

        provider = OsvProvider(http_post=bad_post, delay=0)
        with pytest.raises(ProviderError):
            provider.query("x")

    def test_kev_matches_product_and_vendor(self):
        feed = {"vulnerabilities": [
            {"cveID": "CVE-2026-1111", "vendorProject": "Apache",
             "product": "Log4j", "vulnerabilityName": "RCE", "dateAdded": "2026-01-01"},
            {"cveID": "CVE-2026-2222", "vendorProject": "Other",
             "product": "Unrelated", "vulnerabilityName": "X", "dateAdded": "2026-01-02"},
        ]}
        provider = CisaKevProvider(http_get=lambda url: feed)
        findings = provider.query({"log4j", "something-else"})
        assert len(findings) == 1
        assert findings[0].advisory_id == "CVE-2026-1111"
        assert findings[0].severity == "KNOWN_EXPLOITED"
        assert findings[0].cve_ids == ["CVE-2026-1111"]

    def test_kev_feed_failure_raises_provider_error(self):
        provider = CisaKevProvider(http_get=lambda url: (_ for _ in ()).throw(
            RuntimeError("down")))
        with pytest.raises(ProviderError):
            provider.fetch_catalog()

    def test_cve_provider_parses_entries(self):
        entries = [{
            "id": "CVE-2026-9999", "summary": "bad bug",
            "cvss": [{"score": "9.8"}],
        }]
        provider = CveProvider(http_get=lambda url: entries, delay=0)
        findings = provider.query("openssl")
        assert len(findings) == 1
        assert findings[0].source == "cve"
        assert findings[0].severity == "9.8"

    def test_normalize_package_name(self):
        assert normalize_package_name("My_Package.Name") == "my-package-name"


class _FakeProvider:
    name = "fake"

    def __init__(self, findings=None, error=None):
        self._findings = findings or []
        self._error = error

    def query(self, package, *args, **kwargs):
        if self._error:
            raise ProviderError(self._error)
        return list(self._findings)


class TestSecurityEnricher:
    def _repo(self, repo_id="github:o/trivy", stars=100):
        return Repository(
            id=repo_id, owner="o", name=repo_id.split("/")[-1],
            url=f"https://github.com/{repo_id}", stars=stars,
        )

    def test_collect_links_findings_to_repositories(self):
        finding = Finding(source="osv", advisory_id="OSV-1", package="trivy",
                          severity="HIGH", observed_at="2026-01-01T00:00:00Z")
        enricher = SecurityEnricher(providers=[_FakeProvider([finding])])
        report = enricher.collect([self._repo()], min_stars=0)
        assert report["finding_count"] == 1
        assert report["findings"][0]["repository_id"] == "github:o/trivy"

    def test_deduplication(self):
        f = Finding(source="osv", advisory_id="OSV-1", package="trivy",
                    observed_at="2026-01-01T00:00:00Z")
        enricher = SecurityEnricher(
            providers=[_FakeProvider([f]), _FakeProvider([f])])
        report = enricher.collect([self._repo()])
        assert report["finding_count"] == 1

    def test_provider_errors_do_not_abort(self):
        good = Finding(source="osv", advisory_id="OSV-9", package="trivy",
                       observed_at="2026-01-01T00:00:00Z")
        enricher = SecurityEnricher(providers=[
            _FakeProvider(error="boom"),
            _FakeProvider([good]),
        ])
        report = enricher.collect([self._repo()])
        assert report["finding_count"] == 1
        assert any("boom" in e for e in report["provider_errors"])

    def test_min_stars_filter(self):
        finding = Finding(source="osv", advisory_id="OSV-1", package="trivy",
                          observed_at="2026-01-01T00:00:00Z")
        enricher = SecurityEnricher(providers=[_FakeProvider([finding])])
        report = enricher.collect([self._repo(stars=5)], min_stars=100)
        assert report["repositories_scanned"] == 0
        assert report["finding_count"] == 0

    def test_package_candidates_from_repo_name(self):
        enricher = SecurityEnricher(providers=[])
        assert enricher.package_candidates(self._repo("github:o/My_Tool")) == [
            "my-tool"]


class TestEnrichmentStorage:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.store = SqliteStore(f"{self.tmp}/test.sqlite")

    def test_save_and_get_findings(self):
        findings = [{
            "repository_id": "github:o/trivy", "source": "osv",
            "advisory_id": "OSV-1", "package": "trivy", "ecosystem": "Go",
            "severity": "HIGH", "summary": "s", "url": "u",
            "cve_ids": ["CVE-1"], "observed_at": "2026-01-01T00:00:00Z",
        }]
        assert self.store.save_security_findings(findings) == 1
        rows = self.store.get_security_findings()
        assert len(rows) == 1
        assert rows[0]["cve_ids"] == ["CVE-1"]
        assert rows[0]["repository_id"] == "github:o/trivy"

    def test_dedupes_on_conflict(self):
        f = {
            "repository_id": "github:o/trivy", "source": "osv",
            "advisory_id": "OSV-1", "package": "trivy",
            "severity": "LOW", "observed_at": "2026-01-01T00:00:00Z",
        }
        self.store.save_security_findings([f])
        f2 = dict(f, severity="CRITICAL", observed_at="2026-02-01T00:00:00Z")
        self.store.save_security_findings([f2])
        rows = self.store.get_security_findings()
        assert len(rows) == 1
        assert rows[0]["severity"] == "CRITICAL"
        assert rows[0]["observed_at"] == "2026-02-01T00:00:00Z"

    def test_package_level_findings_dedupe(self):
        f = {"repository_id": "", "source": "cisa-kev",
             "advisory_id": "CVE-1", "package": "log4j"}
        self.store.save_security_findings([f, dict(f)])
        assert len(self.store.get_security_findings()) == 1

    def test_filter_by_repository(self):
        self.store.save_security_findings([
            {"repository_id": "github:o/a", "source": "osv",
             "advisory_id": "X", "package": "a"},
            {"repository_id": "github:o/b", "source": "osv",
             "advisory_id": "Y", "package": "b"},
        ])
        rows = self.store.get_security_findings("github:o/a")
        assert len(rows) == 1
        assert rows[0]["package"] == "a"


class TestEnrichCommand:
    def test_enrich_security_end_to_end(self, monkeypatch):
        tmp = tempfile.mkdtemp()
        commands = CLICommands(config_dir="config", data_dir=tmp)
        commands.sqlite_store.save_repository(Repository(
            id="github:o/trivy", owner="o", name="trivy",
            url="https://github.com/o/trivy", stars=500,
        ))
        finding = Finding(source="osv", advisory_id="OSV-1", package="trivy",
                          observed_at="2026-01-01T00:00:00Z")

        class FakeEnricher:
            def __init__(self, *a, **k):
                pass
            def collect(self, repos, min_stars=0):
                return {
                    "findings": [finding.to_dict() | {"repository_id": "github:o/trivy"}],
                    "finding_count": 1, "repositories_scanned": 1,
                    "packages_queried": 1, "provider_errors": [],
                    "observed_at": "2026-01-01T00:00:00Z",
                }

        monkeypatch.setattr(
            "src.enrichment.security.SecurityEnricher", FakeEnricher)
        # enrich_security imports inside the function, so patch the module attr
        import src.enrichment.security as sec
        monkeypatch.setattr(sec, "SecurityEnricher", FakeEnricher)
        result = commands.enrich_security(sources=["osv"])
        assert result["finding_count"] == 1
        assert result["stored"] == 1
        findings = commands.security_findings()
        assert findings["count"] == 1
