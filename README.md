# Cognitive Book OS

> **Transform long documents into structured, queryable knowledge bases using AI.**

Cognitive Book OS reads documents chapter-by-chapter, extracts and organizes information, and builds a comprehensive understanding focused on your specific objective.

**See [DOCS.md](DOCS.md) for full documentation, installation, and usage guides.**

## Quick Start

```bash
# Install dependencies
uv sync

# Process a book
uv run python -m cognitive_book_os ingest "books/Steve Jobs.pdf" --brain steve_jobs
```
