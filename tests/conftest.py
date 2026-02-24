"""Pytest configuration and fixtures for cognitive-book-os tests."""

import pytest
import sys
import os
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Prevent noisy OTEL export attempts during tests unless explicitly overridden.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")


@pytest.fixture
def sample_chapter_content():
    """Sample chapter content for testing."""
    return """
# Chapter 5: The Rise of Artificial Intelligence

The year 2024 marked a significant turning point in the development of artificial intelligence.
Major technology companies invested over $100 billion in AI research and development.
Dr. Sarah Chen, a leading researcher at DeepMind, published groundbreaking work on
reinforcement learning that achieved superhuman performance in complex games.

"Artificial intelligence is not about replacing humans," Dr. Chen stated in her keynote,
"it's about augmenting human capability." This philosophy has guided the industry toward
collaborative AI systems.

Key statistics from 2024:
- Global AI market value: $500 billion
- Number of AI startups: over 50,000
- Investment growth: 200% year-over-year
""".strip()


@pytest.fixture
def sample_file_operation():
    """Sample file operation data for testing."""
    return {
        "action": "create",
        "path": "characters/sarah_chen.md",
        "content": """---
source: chapter_5
tags: [ai, researcher, deepmind]
summary: "Dr. Sarah Chen published groundbreaking reinforcement learning work."
related: []
---

# Dr. Sarah Chen

**Synopsis**: Leading AI researcher at DeepMind known for reinforcement learning breakthroughs.

**Key Details**:
- Published groundbreaking work on reinforcement learning in 2024
- Keynote speaker at major AI conferences
- Philosophy: "AI is about augmenting human capability"

**Quotes**:
> "Artificial intelligence is not about replacing humans, it's about augmenting human capability." (Source: Chapter 5)
""",
        "reason": "New character discovered in chapter"
    }


@pytest.fixture
def sample_extraction_result():
    """Sample extraction result for testing."""
    return {
        "file_operations": [
            {
                "action": "create",
                "path": "characters/sarah_chen.md",
                "content": "...",
                "reason": "New character"
            }
        ],
        "summary": "Extracted information about Dr. Sarah Chen and AI market statistics",
        "key_entities": ["Dr. Sarah Chen", "DeepMind", "AI", "Reinforcement Learning"]
    }
