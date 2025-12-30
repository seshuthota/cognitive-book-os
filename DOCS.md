# Cognitive Book OS — User Documentation (v4.0)

> **Transform long documents into structured, queryable knowledge bases using AI.**

Cognitive Book OS reads documents chapter-by-chapter, extracts and organizes information, and builds a comprehensive understanding focused on your specific objective. Instead of simple RAG (Retrieval Augmented Generation), it creates a structured "second brain" that you can query naturally.

---

## What's New in v4.0 (Foundation First)
- **Provenance Protocol**: All extracted facts and claims MUST include direct quotes (`> "Quote" (Source: Page)`) for maximum reliability.
- **User Ground Truth**: Use the `notes/` directory to add manual observations or overrides. The engine treats these as absolute truth.
- **Hypothesis Testing (`verify`)**: New dual-pass command to scientifically test claims against the brain.
- **Knowledge Mapping (`summary`)**: Generates lightweight synopses of entire topic directories.

### Previous (v3.0)
- Enrichment Loop / Active Learning
- Hybrid Gap Detection (Literal + LLM)
- State Tracking & File Locking
- Ingestion Strategies (Standard/Triage)
- Knowledge Graph & Interactive Visualizer

---

## Installation

```bash
# Clone and install
git clone https://github.com/seshuthota/cognitive-book-os.git
cd cognitive-book-os
uv sync

# Configure API keys (.env file)
MINIMAX_API_KEY=your-key-here       # Recommended (fast + good tool calling)
# OR
OPENROUTER_API_KEY=your-key-here    # Access to many models
# OR
ANTHROPIC_API_KEY=your-key-here
```

---

## Commands

### 1. `ingest` — Process a Document

```bash
uv run python -m src.cognitive_book_os ingest <PDF> --brain <NAME> [--strategy <TYPE>]
```

| Argument | Description |
|----------|-------------|
| `<PDF>` | Path to PDF document |
| `--brain`, `-b` | Name for the knowledge base (creates a folder) |
| `--strategy` | `standard` (Default) or `triage` (Relevance filter) |
| `--objective` | Optional. Required for `triage`. Filters content based on this goal. |
| `--fast` | Skip the "Synthesis" pass (faster ingestion). |

**Strategy: Standard (The Reader)**
Reads EVERY chapter. Builds a complete knowledge base.
```bash
uv run python -m src.cognitive_book_os ingest "books/Steve Jobs.pdf" --brain steve_jobs
```

**Strategy: Triage (The Skimmer)**
Checks relevance first. Skips chapters that don't match the objective. Saves money/time.
```bash
uv run python -m src.cognitive_book_os ingest "books/Legal_Case.pdf" \
    --brain legal_case \
    --strategy triage \
    --objective "Find the contract signature date"
```

---

### 2. `query` — Ask Questions

```bash
# Single question
uv run python -m src.cognitive_book_os query <BRAIN> -q "Your question here"

# Interactive mode
uv run python -m src.cognitive_book_os query <BRAIN>

# With Auto-Enrichment (Active Learning)
uv run python -m src.cognitive_book_os query <BRAIN> -q "Question" --auto-enrich
```

**With `--auto-enrich`**: If the brain has low confidence or can't find an answer, it will:
1. Check if skipped chapters might contain the answer (Gap Detection)
2. Automatically enrich the brain with relevant chapters
3. Re-query with the expanded knowledge base

The system uses **Graph Retrieval**:
1.  **Selection**: Picks the top relevant files.
2.  **Expansion**: Follows `related` links in the Frontmatter.
3.  **Answer**: Synthesizes a grounded response.

---

### 3. `enrich` — Add New Knowledge

Scan previously skipped chapters for a **new** objective without re-processing the entire book.

```bash
uv run python -m src.cognitive_book_os enrich <BRAIN> --objective "New topic to find"
```

**Use Case**: You initially ingested a book looking for "nuclear events". Now you want to learn about "alien technology" from the same book. Instead of re-reading everything, `enrich` only scans the chapters that were skipped the first time.

---

### 4. `optimize` — The Gardener

Clean up your brain. Detects duplicate files and offers to merge them.

```bash
uv run python -m src.cognitive_book_os optimize <BRAIN>
```

---

### 5. `verify` — Hypothesis Testing

Scientifically test a claim or hypothesis. Performs dual-pass retrieval (searching for both supporting and conflicting evidence) and presents a structured verdict.

```bash
uv run python -m src.cognitive_book_os verify <BRAIN> --claim "Topic to test"
```

### 6. `summary` — Knowledge Mapping

Generate a lightweight summary of a specific topic directory (e.g., `characters/` or `themes/`).

```bash
uv run python -m src.cognitive_book_os summary <BRAIN> <TOPIC_DIR>
```

---

### 7. `viz` — Visualize Knowledge

Generate an interactive HTML visualization of your brain's connections.

```bash
uv run python -m src.cognitive_book_os viz <BRAIN>
```
Opens `graph.html` in your browser.

---

## Brain Structure

Each brain is a folder of markdown files organized by type:

```
brains/<name>/
├── characters/             # People and entities
├── timeline/               # Chronological events
├── themes/                 # Patterns and concepts
├── facts/                  # Quotes, data, statistics
├── notes/                  # USER NOTES (Ground Truth)
├── meta/
│   ├── processing_log.json # Chapter status tracking
│   └── anchor_state.json   # Dynamic context
├── _objective.md           # Your original objective
├── _response.md            # Synthesized response
└── _index.md               # File inventory
```

### Processing Log (State Tracking)

The `processing_log.json` now tracks per-chapter status:

```json
{
  "chapter_map": {
    "1": {"status": "extracted", "reason": null},
    "2": {"status": "skipped", "reason": "No mentions of the objective..."},
    "3": {"status": "extracted", "source_objective": "Find aliens"}
  },
  "secondary_objectives": ["Find aliens", "Who is Dr. Kruger?"]
}
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI (cli.py)                         │
├─────────────────────────────────────────────────────────────┤
│                 Ingestion Pipeline (pipeline.py)            │
│  ┌────────────────────┐   ┌──────────────────────────────┐  │
│  │ Standard Strategy  │   │      Triage Strategy         │  │
│  │ (Deep Read)        │   │ (Filter -> Delegate)         │  │
│  └────────────────────┘   └──────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                 Enrichment Manager (enrichment.py)          │
│  ┌────────────────────┐   ┌──────────────────────────────┐  │
│  │ enrich Command     │   │     Gap Detector             │  │
│  │ (Delta Scan)       │   │ (Literal + LLM Hybrid)       │  │
│  └────────────────────┘   └──────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                     Query Engine (query.py)                 │
│  File Selection -> Graph Expansion -> Answer + Auto-Enrich  │
├─────────────────────────────────────────────────────────────┤
│                     Knowledge Graph                         │
│  Files + Frontmatter Links (`related`)                      │
├─────────────────────────────────────────────────────────────┤
│                     The Gardener (gardener.py)              │
│  Optimize & Merge                                           │
└─────────────────────────────────────────────────────────────┘
```

**Built with**: Python 3.10+, Instructor, Typer, Rich, PyMuPDF, PyVis, MiniMax/Anthropic/OpenRouter
