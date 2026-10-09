from src.discovery.awesome_lists import AwesomeListDiscoverer, _infer_sections

README = """# Awesome

## Platforms

- [Node.js](https://github.com/sindresorhus/awesome-nodejs#readme) - Server side JS
- [Rust](https://github.com/rust-lang/rust)

## Security

- [Trivy](https://github.com/aquasecurity/trivy) - Vulnerability scanner

## Related

- [Awesome Lists](https://github.com/sindresorhus/awesome)
"""


class TestInferSections:
    def test_assigns_section_per_heading(self):
        ids = [
            "github:sindresorhus/awesome-nodejs",
            "github:rust-lang/rust",
            "github:aquasecurity/trivy",
        ]
        result = _infer_sections(README, ids)
        assert result["github:sindresorhus/awesome-nodejs"] == "Platforms"
        assert result["github:rust-lang/rust"] == "Platforms"
        assert result["github:aquasecurity/trivy"] == "Security"

    def test_does_not_assign_later_section_to_earlier_entry(self):
        result = _infer_sections(README, ["github:sindresorhus/awesome-nodejs"])
        assert result["github:sindresorhus/awesome-nodejs"] == "Platforms"

    def test_unknown_repo_gets_no_entry(self):
        assert _infer_sections(README, ["github:nobody/nothing"]) == {}


class TestDiscoverFromAwesomeList:
    def setup_method(self):
        self.discoverer = AwesomeListDiscoverer(client=None)

    def test_excludes_the_list_itself(self):
        results = self.discoverer.discover_from_awesome_list(
            "sindresorhus", "awesome", markdown=README
        )
        ids = [r["repo_id"] for r in results]
        assert "github:sindresorhus/awesome" not in ids

    def test_assigns_sections(self):
        results = self.discoverer.discover_from_awesome_list(
            "sindresorhus", "awesome", markdown=README
        )
        by_id = {r["repo_id"]: r for r in results}
        assert by_id["github:sindresorhus/awesome-nodejs"]["section"] == "Platforms"
        assert by_id["github:aquasecurity/trivy"]["section"] == "Security"

    def test_populates_repository_metadata(self):
        results = self.discoverer.discover_from_awesome_list(
            "sindresorhus", "awesome", markdown=README
        )
        by_id = {r["repo_id"]: r for r in results}
        repo = by_id["github:sindresorhus/awesome-nodejs"]["repository"]
        assert repo["owner"] == "sindresorhus"
        assert repo["name"] == "awesome-nodejs"
        assert repo["html_url"] == "https://github.com/sindresorhus/awesome-nodejs"

    def test_readme_fragments_are_deduplicated(self):
        md = (
            "- [Alpha](https://github.com/a/alpha#readme)\n"
            "- [Alpha again](https://github.com/a/alpha)\n"
        )
        results = self.discoverer.discover_from_awesome_list("x", "y", markdown=md)
        assert len(results) == 1