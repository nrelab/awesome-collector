# Pipeline Architecture

## Overview

```text
                 NRE Awesome Intelligence
                           │
             ┌─────────────┴─────────────┐
             │                           │
       Discovery Layer             GitHub API
             │                           │
             └─────────────┬─────────────┘
                           ▼
                    Normalization
                           │
                           ▼
                     Deduplication
                           │
                           ▼
                     Classification
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   GitHub topics    Primary language   Description/name
        │                  │            keyword match
        └──────────────────┼──────────────────┘
                           ▼
              config/categories.yml
              (taxonomy → parent ▸ leaf)
                           │
                           ▼
                     Quality Score
                           │
                           ▼
                    Repository Graph
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
       Daily Dataset                Documentation
             │                           │
             ▼                           ▼
        SQLite/JSON              llms.txt / agents.md
             │                           │
             └─────────────┬─────────────┘
                           ▼
                   NRE Knowledge Base
```

## Phase Roadmap

### Phase 1 — Core Infrastructure
- [x] GitHub API client
- [x] Awesome-list discovery
- [x] Markdown parser
- [x] URL normalization
- [x] Deduplication
- [x] JSON output

### Phase 2 — Storage & Tracking
- [x] SQLite storage with schema
- [x] Repository metadata enrichment
- [x] Category classification
- [x] Source tracking
- [x] Daily diff / change detection

### Phase 3 — Intelligence Layer
- [x] Quality scoring (0-100)
- [x] Health detection
- [x] Trending detection
- [x] Daily Markdown report

### Phase 4 — Automation
- [x] GitHub Actions workflows
- [x] Scheduled execution
- [x] Manual dispatch

### Phase 5 — Documentation Integration
- [x] Repository content extraction (`extract` command: README, docs, API specs)
- [x] `sitemap.md` generation
- [x] `llms.txt` generation
- [x] `agents.md` generation

### Phase 6 — Knowledge Graph
- [ ] NRE Lab knowledge graph
- [x] Security intelligence enrichment (OSV / CVE / CISA KEV — `enrich` command)
- [ ] Supply-chain intelligence
- [ ] Semantic/vector search

## Incremental Refresh

`awesome refresh` re-fetches metadata only for repositories whose last check
(`collected_at`) is older than the interval for their health status, using
`config/sources.yml` → `incremental.refresh_policy`:

| Health | Interval (days) |
|---|---|
| ACTIVE | 1 |
| MAINTAINED | 3 |
| SLOW | 7 |
| STALE | 30 |
| ARCHIVED | 90 |
| UNKNOWN | 14 |

Fallbacks: repositories with no health status use the `UNKNOWN` interval;
repositories with no `collected_at` have never been checked and are always
due. A successful refresh updates `collected_at`, which serves as the
last-checked timestamp. The command reports `checked`, `updated`, `skipped`,
and `failed` counts.

## Snapshot Diff

`awesome diff DATE1 DATE2` compares the fields listed in
`CLICommands.DIFF_FIELDS` (stars, forks, issues, language, description,
license, topics, archived, pushed_at, updated_at, health_status,
score_overall). Repositories present in both snapshots appear under
`updated` only when at least one of those fields changed, with a `changes`
map of `{field: {"from": old, "to": new}}`. `stale` and `archived` are
populated from the newer snapshot's health status, `pushed_at` age (>180
days), and the `archived` flag.

## Security Enrichment

`awesome enrich [--source osv|cve|cisa-kev] [--min-stars N] [--dry-run]`
queries advisory providers for package names derived from tracked
repositories. Findings are deduplicated on
`(source, advisory_id, package, repository_id)` and stored in the
`security_findings` SQLite table with source and `observed_at` timestamps.
Provider failures and rate limits are reported under `provider_errors` and
never abort the run. `awesome findings` lists stored findings, and
`awesome export --include-findings` embeds them in the JSON export.

## Content Extraction

`awesome extract [--min-score F] [--max-repositories N] [--dry-run]` fetches
README content, documentation files, and API specifications (OpenAPI /
Swagger) for repositories whose `score_overall` meets the threshold.
Extraction is bounded: it never clones repositories, caps files per repo,
per-file bytes, and total bytes per repo. Results are stored per repository
under `data/content/` and the run reports `selected`, `succeeded`,
`skipped`, `failed`, and `documents` counts.