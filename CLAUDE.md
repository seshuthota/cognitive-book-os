# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cognitive Book OS is a structured knowledge extraction system that transforms documents (PDFs) into queryable "brains" (knowledge bases). It extracts entities, events, themes, and facts with provenance tracking, hypothesis testing, and active learning capabilities.

## Commands

```bash
# Install dependencies
uv sync

# Configure API keys (copy .env.example and add keys)
cp .env.example .env

# CLI entry point
uv run bookos --help

# Ingest a PDF into a brain
uv run bookos ingest <pdf> --brain <name> [--objective "<goal>"]

# Query a brain
uv run bookos query <brain> -q "<question>" [--auto-enrich]

# Run FastAPI backend (port 8001)
uv run uvicorn src.cognitive_book_os.server:app --reload --port 8001

# Run Streamlit legacy UI (port 8501)
uv run streamlit run src/cognitive_book_os/app.py

# Run React frontend (port 5173)
cd frontend && npm install && npm run dev

# Combined launch (both backend + frontend)
./scripts/launch_gui.sh
```

## Architecture

```
PDF → parser.py → chunk_document() → pipeline.py (Standard/Triage strategy)
    → agent.py (LLM with tools) → brain/<name>/ (markdown files)
    → ingest.py (_response.md synthesis)

Query: query.py → select_relevant_files() → answer_from_brain() → graph expansion
```

**Core modules:**
- `brain.py` - Knowledge base file management with locking
- `pipeline.py` - Ingestion strategies
- `agent.py` - Tool-calling extraction agent (OpenAI/Anthropic style)
- `llm.py` - Unified LLM client (OpenAI, Anthropic, OpenRouter, MiniMax)
- `server.py` - FastAPI REST API
- `models.py` - Pydantic data models

## Brain Structure

Each brain in `brains/<name>/` contains:
- `characters/` - People and entities
- `timeline/` - Chronological events
- `themes/` - Concepts and patterns
- `facts/` - Quotes and data
- `notes/` - User ground truth overrides
- `meta/` - Processing logs and locking
- `_objective.md` - Original extraction goal
- `_response.md` - Synthesized answer
- `_index.md` - File inventory

**File format:** Frontmatter with `source`, `tags`, `summary`, `related`; body with synopsis, key details, and sourced quotes.

## Key Patterns

- **LLM Provider Abstraction**: `llm.py` auto-detects provider from API keys
- **Tool-Calling Agents**: LLM creates/updates files directly via `brain.write_file()`
- **Structured Outputs**: Uses `instructor` for Pydantic-validated responses
- **File Locking**: `fcntl.flock()` for concurrent processing log access
- **Provenance**: Every fact includes source chapter and direct quotes

## API Endpoints (FastAPI)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/brains` | List all brains |
| POST | `/brains/{name}/query` | Query a brain |
| POST | `/ingest` | Upload PDF and start ingestion |
| GET | `/jobs/{job_id}` | Get job status |
