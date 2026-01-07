"""Tests for configuration module in cognitive_book_os.config."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cognitive_book_os.config import (
    ModelConfig,
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENROUTER,
    PROVIDER_MINIMAX,
    DEFAULT_MODELS,
    MODELS,
    get_model_config,
    get_default_model,
    list_models,
    print_models,
    BRAIN_MODEL,
)


class TestModelConfig:
    """Tests for ModelConfig dataclass."""

    def test_create_model_config(self):
        """Test creating a model config."""
        config = ModelConfig(
            id="test-model",
            name="Test Model",
            provider="openai",
            context_window=128000,
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03
        )
        assert config.id == "test-model"
        assert config.name == "Test Model"
        assert config.provider == "openai"
        assert config.context_window == 128000

    def test_model_config_defaults(self):
        """Test model config default values."""
        config = ModelConfig(
            id="test-model",
            name="Test Model",
            provider="openai",
            context_window=128000,
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03
        )
        assert config.supports_structured_output is True
        assert config.notes == ""


class TestProviderConstants:
    """Tests for provider constants."""

    def test_provider_constants(self):
        """Test that provider constants are correct strings."""
        assert PROVIDER_OPENAI == "openai"
        assert PROVIDER_ANTHROPIC == "anthropic"
        assert PROVIDER_OPENROUTER == "openrouter"
        assert PROVIDER_MINIMAX == "minimax"


class TestDefaultModels:
    """Tests for default models."""

    def test_default_models_exist(self):
        """Test that default models are defined for each provider."""
        assert PROVIDER_OPENAI in DEFAULT_MODELS
        assert PROVIDER_ANTHROPIC in DEFAULT_MODELS
        assert PROVIDER_OPENROUTER in DEFAULT_MODELS
        assert PROVIDER_MINIMAX in DEFAULT_MODELS

    def test_default_model_values(self):
        """Test default model values are non-empty."""
        for provider, model in DEFAULT_MODELS.items():
            assert model is not None
            assert len(model) > 0


class TestModelCatalog:
    """Tests for the model catalog."""

    def test_models_not_empty(self):
        """Test that MODELS dictionary is not empty."""
        assert len(MODELS) > 0

    def test_gpt4o_config(self):
        """Test GPT-4o model configuration."""
        config = get_model_config("gpt-4o")
        assert config is not None
        assert config.id == "gpt-4o"
        assert config.provider == PROVIDER_OPENAI
        assert config.context_window == 128000

    def test_claude_config(self):
        """Test Claude model configuration."""
        config = get_model_config("claude-3-5-sonnet-20241022")
        assert config is not None
        assert config.provider == PROVIDER_ANTHROPIC

    def test_openrouter_models(self):
        """Test OpenRouter model configurations."""
        for model_id in MODELS:
            if "/" in model_id:
                config = get_model_config(model_id)
                assert config is not None
                assert config.provider == PROVIDER_OPENROUTER

    def test_brain_model_exists(self):
        """Test that BRAIN_MODEL is defined and exists in catalog."""
        assert BRAIN_MODEL is not None
        config = get_model_config(BRAIN_MODEL)
        assert config is not None


class TestGetModelConfig:
    """Tests for get_model_config function."""

    def test_get_existing_model(self):
        """Test getting an existing model config."""
        config = get_model_config("gpt-4o-mini")
        assert config is not None
        assert config.name == "GPT-4o Mini"

    def test_get_nonexistent_model(self):
        """Test getting a non-existent model returns None."""
        config = get_model_config("nonexistent-model")
        assert config is None


class TestGetDefaultModel:
    """Tests for get_default_model function."""

    def test_get_default_for_known_provider(self):
        """Test getting default model for known providers."""
        assert get_default_model(PROVIDER_OPENAI) is not None
        assert get_default_model(PROVIDER_ANTHROPIC) is not None

    def test_get_default_for_unknown_provider(self):
        """Test getting default model for unknown provider returns fallback."""
        default = get_default_model("unknown")
        assert default == "gpt-4o"


class TestListModels:
    """Tests for list_models function."""

    def test_list_all_models(self):
        """Test listing all models."""
        models = list_models()
        assert len(models) > 0
        assert all(isinstance(m, ModelConfig) for m in models)

    def test_filter_by_provider(self):
        """Test filtering models by provider."""
        openai_models = list_models(PROVIDER_OPENAI)
        assert len(openai_models) > 0
        assert all(m.provider == PROVIDER_OPENAI for m in openai_models)

        anthropic_models = list_models(PROVIDER_ANTHROPIC)
        assert len(anthropic_models) > 0
        assert all(m.provider == PROVIDER_ANTHROPIC for m in anthropic_models)


class TestModelCostCalculations:
    """Tests for model cost calculations."""

    def test_model_costs_are_positive(self):
        """Test that all model costs are positive."""
        for config in MODELS.values():
            assert config.cost_per_1k_input >= 0
            assert config.cost_per_1k_output >= 0

    def test_model_context_windows(self):
        """Test that all context windows are positive."""
        for config in MODELS.values():
            assert config.context_window > 0


class TestModelContextWindowSizes:
    """Tests for model context window sizes."""

    def test_large_context_models(self):
        """Test models with large context windows."""
        gemini_config = get_model_config("google/gemini-pro-1.5")
        if gemini_config:
            assert gemini_config.context_window == 1000000

    def test_standard_context_models(self):
        """Test models with standard context windows."""
        claude_config = get_model_config("claude-3-5-sonnet-20241022")
        assert claude_config is not None
        assert claude_config.context_window == 200000


class TestOpenRouterModels:
    """Tests for OpenRouter-specific model configurations."""

    def test_openrouter_base_url(self):
        """Test OpenRouter base URL is defined."""
        from cognitive_book_os.config import OPENROUTER_BASE_URL
        assert OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"

    def test_minimax_base_url(self):
        """Test MiniMax base URL is defined."""
        from cognitive_book_os.config import MINIMAX_BASE_URL
        assert MINIMAX_BASE_URL == "https://api.minimax.io/anthropic"

    def test_deepseek_model(self):
        """Test DeepSeek model configuration."""
        config = get_model_config("deepseek/deepseek-chat")
        assert config is not None
        assert config.provider == PROVIDER_OPENROUTER
        assert config.context_window == 64000


class TestPrintModels:
    """Tests for print_models CLI output function."""

    def test_print_all_models(self, capsys):
        """Test printing all available models to console."""
        print_models()
        captured = capsys.readouterr()
        
        # Verify header is present
        assert "Available Models:" in captured.out
        assert "Model ID" in captured.out
        assert "Name" in captured.out
        assert "Context" in captured.out
        
        # Verify at least one model is displayed
        assert "gpt-4o" in captured.out or "claude" in captured.out
        
        # Verify total count is shown
        assert "Total:" in captured.out
        assert "models" in captured.out

    def test_print_models_filtered_by_provider(self, capsys):
        """Test printing models filtered by specific provider."""
        print_models(provider=PROVIDER_OPENAI)
        captured = capsys.readouterr()
        
        # Should show OpenAI models
        assert "gpt-4o" in captured.out
        
        # Should not show filter hint when provider is specified
        assert "Filter by provider" not in captured.out or PROVIDER_OPENAI in captured.out
