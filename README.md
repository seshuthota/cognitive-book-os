# Cognitive Book OS

> **Transform long documents into structured, queryable knowledge bases using AI.**

Cognitive Book OS reads documents chapter-by-chapter, extracts and organizes information, and builds a comprehensive understanding focused on your specific objective.

**See [DOCS.md](DOCS.md) for full documentation, installation, and usage guides.**

## Quick Start

### Configure Environment
Create `.env` in project root (or copy `.env.example`) and set at least one provider key:
- `ANTHROPIC_API_KEY`
- `MINIMAX_API_KEY`
- `OPENROUTER_API_KEY`
- `OPENAI_API_KEY`

### Backend
1. **Install Dependencies**: `uv sync`
2. **Run Server**: `uv run uvicorn src.cognitive_book_os.server:app --reload --port 8001`
3. **Health Checks**: `GET /health` and `GET /health/ready`

### Frontend (New)
1. **Navigate**: `cd frontend`
2. **Install**: `npm install`
3. **Optional Config**: copy `.env.example` to `.env` and adjust `VITE_API_URL`/`VITE_PROVIDER`/`VITE_API_KEY`
4. **Run**: `npm run dev`
5. **Open**: [http://localhost:5173](http://localhost:5173)

### CLI (Legacy)
- **Ingest**: `uv run python -m src.cognitive_book_os ingest <pdf>`
- **Query**: `uv run python -m src.cognitive_book_os query <brain> -q "<question>"`

## Production Notes
- Optional API key auth: set `REQUIRE_API_KEY` (clients send `x-api-key`)
- Optional rate limiting: set `RATE_LIMIT_PER_MINUTE`
- Job persistence backend: `JOB_STORE_BACKEND=json|sqlite` (`JOB_STORE_PATH` or `JOB_STORE_SQLITE_PATH`)
- Upload size cap for `/ingest`: set `MAX_UPLOAD_MB` (default `100`)
- Ingestion runtime controls: `UPLOAD_DIR`, `INGEST_TIMEOUT_SEC`
- Optional operational metrics endpoint: `GET /metrics` (`ENABLE_METRICS`, optional `METRICS_API_KEY`)
- Structured request logs: `REQUEST_LOG_JSON` and `REQUEST_LOG_LEVEL`
- Restrict CORS in production via `CORS_ALLOW_ORIGINS`

## Quality Gate
- Run full local release checks: `./scripts/check.sh`
- CI workflow (GitHub Actions) mirrors this: `.github/workflows/ci.yml`
