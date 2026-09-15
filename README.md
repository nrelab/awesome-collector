# Awesome Collector

Daily GitHub Actions Awesome Repository Collector for the NRE Lab knowledge-base ecosystem.

## Quick Start

```bash
# Install
pip install -e .

# Collect repositories
awesome collect

# Discover awesome lists
awesome discover

# Sync data
awesome sync

# Score repositories
awesome score

# Validate dataset
awesome validate

# Generate report
awesome report
awesome report --daily

# Diff two dates
awesome diff 2026-09-14 2026-09-15

# Export data
awesome export --format json
awesome export --format sqlite

# Show trending
awesome trending
```

## Commands

| Command | Description |
|---|---|
| `awesome collect` | Collect repositories from GitHub |
| `awesome discover` | Discover awesome lists |
| `awesome sync` | Full sync |
| `awesome update` | Update metadata |
| `awesome validate` | Validate data integrity |
| `awesome score` | Score all repositories |
| `awesome report` | Generate reports |
| `awesome diff DATE1 DATE2` | Compare daily snapshots |
| `awesome export --format` | Export data |
| `awesome trending` | Show trending repos |

## Architecture

- **Discovery**: GitHub Search API + Topic search + Awesome list parsing
- **Parser**: Markdown parsing for README files, link extraction, category detection
- **Normalization**: URL normalization, deduplication, canonical IDs
- **Storage**: SQLite (structured) + JSON (documents)
- **Scoring**: Multi-factor quality scoring (0-100)
- **Health**: ACTIVE, MAINTAINED, SLOW, STALE, ARCHIVED, UNKNOWN

## Configuration

Configuration files in `config/`:
- `sources.yml` - Discovery sources and queries
- `categories.yml` - Taxonomy and keyword mapping
- `filters.yml` - Inclusion/exclusion rules
- `scoring.yml` - Score weights and thresholds

## Data Model

See [schema.md](docs/schema.md) for full data model documentation.

## Pipeline

See [pipeline.md](docs/pipeline.md) for architecture and flow details.

## GitHub Actions

Three automated workflows:
- `.github/workflows/daily.yml` - Daily at 02:30 UTC
- `.github/workflows/weekly-maintenance.yml` - Weekly maintenance
- `.github/workflows/manual.yml` - Manual dispatch with inputs

## Development

```bash
pytest
pytest tests/ -v
ruff check src/
mypy src/
```

## Integration

Designed to feed into the NRE Lab documentation crawler:
- Score >= 80 → Clone/read → Extract README/docs/API → Generate `llms.txt`, `agents.md`, `sitemap.md`
- Repository graph tracking via `sources` field
- Knowledge graph relationships in Phase 6