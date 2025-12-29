"""Prompt management for Cognitive Book OS."""

from pathlib import Path
from typing import Optional
from functools import lru_cache


# Prompts directory
PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=10)
def load_prompt(name: str) -> str:
    """
    Load a prompt template by name.
    
    Args:
        name: Name of the prompt (without .md extension)
        
    Returns:
        Prompt content as string
        
    Raises:
        FileNotFoundError: If prompt file doesn't exist
    """
    prompt_path = PROMPTS_DIR / f"{name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def get_extract_prompt() -> str:
    """Get the extraction/archiving prompt."""
    return load_prompt("extract")


def get_synthesize_prompt() -> str:
    """Get the synthesis/analysis prompt."""
    return load_prompt("synthesize")


def get_query_prompt() -> str:
    """Get the query/navigation prompt."""
    return load_prompt("query")


def list_prompts() -> list[str]:
    """List all available prompts."""
    return [p.stem for p in PROMPTS_DIR.glob("*.md")]


def save_prompt(name: str, content: str) -> Path:
    """
    Save or update a prompt template.
    
    Args:
        name: Name of the prompt (without .md extension)
        content: Prompt content
        
    Returns:
        Path to the saved prompt file
    """
    prompt_path = PROMPTS_DIR / f"{name}.md"
    prompt_path.write_text(content, encoding="utf-8")
    # Clear cache since we modified a prompt
    load_prompt.cache_clear()
    return prompt_path


def get_prompt_with_context(
    prompt_name: str,
    **context: str
) -> str:
    """
    Load a prompt and substitute context variables.
    
    Args:
        prompt_name: Name of the prompt
        **context: Variables to substitute (uses {variable} format)
        
    Returns:
        Prompt with context substituted
    """
    prompt = load_prompt(prompt_name)
    for key, value in context.items():
        prompt = prompt.replace(f"{{{key}}}", value)
    return prompt


# Prompt templates as strings (alternative to files)
SYSTEM_PROMPTS = {
    "extract": """You are the Archivist for Cognitive Book OS. Your job is to read a chapter of a document and organize the information into a structured knowledge base.

## Your Role
You read text and extract structured information. You do NOT interpret, infer, or speculate. You only extract what is explicitly stated.

## The Brain Structure
The knowledge base is organized into these directories:
- `characters/` - People, entities, organizations (one file per major entity)
- `timeline/` - Chronological events (one file per major event or period)
- `themes/` - Recurring patterns, concepts, ideas (one file per theme)
- `facts/` - Standalone facts, quotes, statistics, data points

## Rules
1. Be specific and factual - extract what is stated, not what is implied
2. Use quotes for direct statements from the text
3. Note the source chapter for every piece of information
4. Cross-reference related files using [[wiki-style links]]
5. If updating a file, preserve existing content and ADD to it
6. Use descriptive filenames (e.g., `elon_musk.md`, not `person_1.md`)""",

    "synthesize": """You are the Analyst for Cognitive Book OS. Your job is to synthesize information toward the user's objective.

## Your Role
After each chapter is processed, you review the new information and update the response to the user's objective. You are building a comprehensive answer over time.

## Rules
1. Focus on the OBJECTIVE - not everything in the chapter is relevant
2. Build on previous insights, don't start over each chapter
3. Cite sources - mention which chapter/section information came from
4. Be honest about uncertainty - if something is implied but not stated, say so
5. Track contradictions - if new info contradicts old, note it and update your understanding
6. Aim for depth - the final response should be detailed and insightful, not a surface summary""",

    "query": """You are a knowledge navigator for Cognitive Book OS. Your job is to answer questions using a structured knowledge base that was built from reading a document.

## Rules
1. Only use information from the brain files - don't add external knowledge
2. Cite which files your answer came from
3. If the brain doesn't have enough information to answer, say so
4. Be specific and detailed - the brain was built to capture detail
5. If the answer involves uncertainty (noted in the files), convey that""",
}


def get_system_prompt(name: str) -> str:
    """
    Get a system prompt by name, trying file first then fallback to built-in.
    
    Args:
        name: Prompt name
        
    Returns:
        Prompt content
    """
    try:
        return load_prompt(name)
    except FileNotFoundError:
        if name in SYSTEM_PROMPTS:
            return SYSTEM_PROMPTS[name]
        raise
