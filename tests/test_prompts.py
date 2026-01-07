"""Tests for prompt management."""

import sys
import pytest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cognitive_book_os.prompts import (
    load_prompt,
    get_extract_prompt,
    get_synthesize_prompt,
    get_query_prompt,
    list_prompts,
    save_prompt,
    get_prompt_with_context,
    get_system_prompt,
)


class TestLoadPrompt:
    """Tests for loading prompt templates."""

    def test_load_existing_prompt(self):
        """Test loading a prompt that exists in the prompts directory."""
        # extract.md exists in src/cognitive_book_os/prompts/
        prompt = load_prompt("extract")
        
        # Should return non-empty string
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_load_nonexistent_prompt_raises_error(self):
        """Test that loading missing prompt raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent_prompt_xyz")


class TestGetPrompts:
    """Tests for convenience prompt getter functions."""

    def test_get_extract_prompt(self):
        """Test getting extraction prompt for document processing."""
        prompt = get_extract_prompt()
        
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_get_synthesize_prompt(self):
        """Test getting synthesis prompt for analysis."""
        prompt = get_synthesize_prompt()
        
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_get_query_prompt(self):
        """Test getting query prompt for brain navigation."""
        prompt = get_query_prompt()
        
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_get_system_prompt(self):
        """Test generic system prompt getter."""
        prompt = get_system_prompt("extract")
        
        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestListPrompts:
    """Tests for listing available prompts."""

    def test_list_prompts_returns_available_templates(self):
        """Test listing all prompts users can access."""
        prompts = list_prompts()
        
        # Should include the standard prompts
        assert isinstance(prompts, list)
        assert "extract" in prompts
        assert "query" in prompts
        assert "synthesize" in prompts


class TestPromptContext:
    """Tests for prompt variable substitution."""

    def test_get_prompt_with_context_substitutes_variables(self):
        """Test that context variables are substituted in prompts."""
        # Create a test by using an existing prompt and checking substitution
        # Since we can't predict exact content, we'll test the mechanism
        prompt = load_prompt("extract")
        
        # If prompt contains {objective}, test substitution
        if "{objective}" in prompt:
            result = get_prompt_with_context("extract", objective="Test objective")
            assert "Test objective" in result
            assert "{objective}" not in result
