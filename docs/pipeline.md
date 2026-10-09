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
- Repository content extraction
- `sitemap.md` generation
- `llms.txt` generation
- `agents.md` generation

### Phase 6 — Knowledge Graph
- NRE Lab knowledge graph
- Security intelligence enrichment (CVE/OSV/CISA KEV)
- Supply-chain intelligence
- Semantic/vector search