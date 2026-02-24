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


def get_system_prompt(name: str) -> str:
    """
    Get a system prompt by name from the prompts directory.

    Args:
        name: Prompt name (e.g., "extract", "synthesize", "query")

    Returns:
        Prompt content

    Raises:
        FileNotFoundError: If prompt file doesn't exist
    """
    return load_prompt(name)
