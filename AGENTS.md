# Repository Guidelines

## Project Structure & Module Organization
- `src/cognitive_book_os/`: core backend package. `server.py` hosts the FastAPI API, `cli.py` defines the Typer CLI, and ingestion/query logic lives in modules like `ingest.py`, `query.py`, and `brain.py`.
- `src/cognitive_book_os/prompts/`: prompt templates (`*.md`) used by extraction/synthesis flows.
- `tests/`: primary pytest suite with shared fixtures in `tests/conftest.py`. A legacy `test_graph.py` also exists at the repository root.
- `frontend/`: Vite + React + TypeScript app (`src/components`, `src/api`, `src/types`).
- Runtime/output paths: `books/` (inputs), `brains/` (generated knowledge bases), `dist/` (uploads/job store artifacts).
- `scripts/`: helper scripts, including `check.sh` for local release checks.

## Build, Test, and Development Commands
- `uv sync`: install backend dependencies.
- `uv run uvicorn src.cognitive_book_os.server:app --reload --port 8001`: run backend API locally.
- `uv run --extra dev pytest -q`: run backend test suite.
- `./scripts/check.sh`: project quality gate (backend tests + frontend build), mirrors CI.
- `cd frontend && npm ci`: install frontend dependencies.
- `cd frontend && npm run dev`: run frontend dev server (`http://localhost:5173`).
- `cd frontend && npm run lint`: run ESLint for TypeScript/React code.
- `cd frontend && npm run build`: type-check and produce production frontend bundle.

## Coding Style & Naming Conventions
- Python: 4-space indentation, type hints where practical, `snake_case` for modules/functions, `PascalCase` for classes.
- TypeScript/React: component files use `PascalCase` (for example `Chat.tsx`), variables/functions use `camelCase`.
- Keep prompts in `src/cognitive_book_os/prompts/` instead of embedding large prompt text inline.
- Prefer focused, single-purpose modules over large mixed-responsibility files.

## Testing Guidelines
- Framework: `pytest` (configured in `pyproject.toml`).
- Naming: test files follow `test_*.py`; keep test names descriptive and behavior-focused.
- Reuse fixtures from `tests/conftest.py`; add new fixtures there when shared by multiple suites.
- During development, run targeted tests first (example: `uv run --extra dev pytest tests/test_parser.py -q`), then `./scripts/check.sh` before PR.

## Commit & Pull Request Guidelines
- Follow the repo's observed commit style: `type(scope): summary` (examples: `test(parser): ...`, `docs: ...`).
- Write imperative, specific commit summaries and include a scope when it adds clarity.
- PRs should include:
  - what changed and why,
  - verification steps/results (tests, build, lint),
  - screenshots/video for frontend UI changes,
  - linked issue(s) when applicable.
- If configuration changes are introduced, update `.env.example` and relevant docs in `README.md`/`DOCS.md`.
