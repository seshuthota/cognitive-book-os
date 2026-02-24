# Cognitive Book OS: System Report (Updated)

## 1) What This Project Is
Cognitive Book OS is a **knowledge operating system for long-form documents**. Instead of treating a PDF as temporary prompt context, it converts the content into a persistent, inspectable "Brain" made of linked Markdown files, run logs, and claim metadata. The goal is not just retrieval; it is to maintain a living knowledge base that can be queried, audited, enriched, and maintained over time.

## 2) Core Product Idea (Big Picture)
The project is centered on three shifts:
1. **Objective-driven processing**: ingestion can be guided by a specific objective, not just generic extraction.
2. **Evidence-first answers**: answers can include claim-level traceability, confidence, and provenance warnings.
3. **Closed-loop learning**: query -> confidence check -> gap detection -> enrichment -> re-query.

This makes the system closer to a personal research memory layer than a one-shot "chat with PDF" tool.

## 3) What Has Been Built

### 3.1 Brain as a persistent knowledge unit
Each brain is a filesystem-native knowledge base under `brains/<brain_name>/` with:
- domain files (`characters/`, `timeline/`, `themes/`, `facts/`, `notes/`)
- objective and synthesis (`_objective.md`, `_response.md`)
- operational metadata (`meta/processing_log.json`, `meta/anchor_state.json`)
- optional claim/runs/event history (`meta/claims_current.json`, `meta/claims_events.jsonl`, `meta/runs.jsonl`)

### 3.2 Ingestion pipeline
Ingestion is chapter-based and supports:
- **Standard strategy**: extract each chapter, then synthesize toward objective
- **Triage strategy**: first classify chapter relevance to objective, then process only relevant chapters
- **Fast mode**: skip per-chapter synthesis and run final synthesis once

Extraction is agentic (`agent.py`) with tools (`create_file`, `update_file`, `read_file`, `list_files`, `done`) so the model actively builds and updates the Brain.

### 3.3 Query engine
Query flow:
1. Select relevant files (`select_relevant_files`)
2. Expand via graph links (`related` frontmatter)
3. Generate grounded answer with confidence + sources

The standard query endpoint is `POST /brains/{name}/query`.

### 3.4 Query audit and provenance layer
When enabled (`ENABLE_CLAIM_VERSIONING=1` and `ENABLE_QUERY_AUDIT_ENDPOINTS=1`), audited queries return:
- `claim_trace` entries (claim id, text, evidence quote, source locator)
- trace completeness metrics
- run IDs for auditability

Provenance policy supports `PROVENANCE_ENFORCEMENT=warn|strict|off`.

### 3.5 Auto-enrichment (active learning loop)
If a query returns low confidence/no answer and `auto_enrich=true`, the enrichment manager evaluates skipped chapters and optionally processes them, then supports a follow-up re-query path. This is exposed in API and integrated in the React chat workflow.

### 3.6 Multi-brain orchestration
Cross-brain query exists in backend/CLI (`/multi-brain/query`, `multi-query` command) with:
- per-brain answer bundles
- optional conflict classification (support/refute/ambiguous)
- unified synthesis answer
- aggregate traceability summary

Feature-flagged via `ENABLE_MULTI_BRAIN_QUERY=1`.

### 3.7 Gardener subsystem
The Gardener detects duplicate clusters and can recommend/apply merges. It supports:
- dry-run and apply modes
- scheduler (`hourly`/`daily`/`weekly` or raw seconds)
- run history and report persistence
- API endpoints (`/gardener/status`, `/gardener/trigger`, `/gardener/history`)

### 3.8 Interfaces
- **FastAPI backend** (`server.py`)
- **Typer CLI** (`cli.py`) for ingest/query/enrich/verify/viz/multi-query/claims
- **React frontend** (`frontend/`) with a 3-pane workspace:
  - left: brain structure explorer
  - center: synthesis chat + briefing
  - right: evidence/file/run inspector
  - jobs drawer for ingestion/enrichment status

The frontend prefers audited query mode and gracefully falls back to standard mode when audit endpoints are disabled.

## 4) How It Works End-to-End
1. User uploads PDF + objective + strategy.
2. Server stores upload, starts background ingestion job.
3. Ingestion parses chapters, extraction agent writes structured markdown into Brain.
4. Processing log tracks chapter states (`extracted`, `skipped`, `pending`).
5. Optional synthesis updates `_response.md` toward objective.
6. Query selects files + graph expansion, returns answer/confidence/sources.
7. If enabled, claim audit links answer to claim snapshots and evidence quotes.
8. If low confidence, enrichment can scan skipped chapters and expand knowledge.
9. Multi-brain orchestration can combine several brains into one unified answer.
10. Gardener periodically reduces entropy (duplicates/merge recommendations).

## 5) Operational and Platform Capabilities
- Provider abstraction for `minimax`, `anthropic`, `openrouter`, `openai`
- Job persistence backends: JSON or SQLite
- Health/readiness and metrics endpoints
- API-key auth, rate limiting, CORS controls
- Upload limits/timeouts and persistent source PDF tracking for later enrichment

## 6) Current Maturity and Gaps
What is production-oriented already:
- persistent jobs, safer ingestion lifecycle, feature flags, audit-ready models, UI for evidence inspection

What remains for next phases:
- first-class multi-brain UX in frontend
- richer claim-level diff/version views in UI
- stronger objective inheritance and cross-brain planning
- broader automated evaluation on real corpora

## 7) Bottom Line
This project already functions as a practical knowledge OS: it ingests documents into persistent memory, supports evidence-aware querying, performs adaptive enrichment, and has the foundation for cross-brain reasoning and ongoing maintenance. The key differentiator is not just answering questions, but maintaining a transparent and evolvable knowledge substrate over time.
