"""Tests for the export CLI: output must never be silently truncated and
large exports must be writable to a file (issue: 5000-char truncation)."""

import json

from click.testing import CliRunner

from src.main import CLICommands, cli
from src.models import Repository


class TestExport:
    def setup_method(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.commands = CLICommands(config_dir="config", data_dir=self.tmp)
        # Enough repos with long descriptions to exceed the old 5000-char cap.
        for i in range(40):
            self.commands.sqlite_store.save_repository(Repository(
                id=f"github:test/repo{i:02d}", owner="test", name=f"repo{i:02d}",
                url=f"https://github.com/test/repo{i:02d}",
                description="x" * 200,
            ))

    def test_export_json_is_complete_and_parseable(self):
        payload = self.commands.export(fmt="json")
        assert len(payload) > 5000
        data = json.loads(payload)
        assert len(data) == 40

    def test_export_to_file(self):
        out = f"{self.tmp}/nested/export.json"
        result = self.commands.export_to_file(out)
        assert result["path"] == out
        with open(out) as f:
            data = json.load(f)
        assert len(data) == 40


class TestExportCLI:
    def setup_method(self):
        self.runner = CliRunner()

    def test_cli_export_stdout_not_truncated(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        commands = CLICommands()
        for i in range(30):
            commands.sqlite_store.save_repository(Repository(
                id=f"github:t/r{i}", owner="t", name=f"r{i}",
                url=f"https://github.com/t/r{i}", description="y" * 150,
            ))
        result = self.runner.invoke(cli, ["export"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 30
        assert len(result.output) > 5000

    def test_cli_export_output_file(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        commands = CLICommands()
        commands.sqlite_store.save_repository(Repository(
            id="github:t/one", owner="t", name="one",
            url="https://github.com/t/one",
        ))
        out = tmp_path / "out.json"
        result = self.runner.invoke(cli, ["export", "--output", str(out)])
        assert result.exit_code == 0
        with open(out) as f:
            data = json.load(f)
        assert len(data) == 1

    def test_cli_export_include_findings(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        commands = CLICommands()
        commands.sqlite_store.save_repository(Repository(
            id="github:t/one", owner="t", name="one",
            url="https://github.com/t/one",
        ))
        commands.sqlite_store.save_security_findings([{
            "repository_id": "github:t/one",
            "source": "osv", "advisory_id": "OSV-1", "package": "one",
            "severity": "HIGH", "summary": "test", "url": "https://osv.dev/x",
            "cve_ids": ["CVE-2026-0001"], "observed_at": "2026-01-01T00:00:00Z",
        }])
        result = self.runner.invoke(cli, ["export", "--include-findings"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["repositories"]) == 1
        assert data["security_findings"][0]["advisory_id"] == "OSV-1"
