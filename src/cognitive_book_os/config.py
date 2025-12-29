"""LLM model configurations and provider settings."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ModelConfig:
    """Configuration for an LLM model."""
    id: str
    name: str
    provider: str
    context_window: int
    cost_per_1k_input: float  # USD
    cost_per_1k_output: float  # USD
    supports_structured_output: bool = True
    notes: str = ""


# Provider constants
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_MINIMAX = "minimax"

# Default models per provider
DEFAULT_MODELS = {
    PROVIDER_OPENAI: "gpt-4o",
    PROVIDER_ANTHROPIC: "claude-sonnet-4-20250514",
    PROVIDER_OPENROUTER: "deepseek/deepseek-chat",
    PROVIDER_MINIMAX: "MiniMax-M2.1",  # Fast, good at tool calling
}

# OpenRouter settings
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# MiniMax settings (Anthropic-compatible API)
MINIMAX_BASE_URL = "https://api.minimax.io/anthropic"

# Default Brain Model (Primary high-intelligence model)
BRAIN_MODEL = "claude-3-5-sonnet-20241022"

# Model catalog - popular models with their configs
MODELS = {
    # OpenAI models
    "gpt-4o": ModelConfig(
        id="gpt-4o",
        name="GPT-4o",
        provider=PROVIDER_OPENAI,
        context_window=128000,
        cost_per_1k_input=0.0025,
        cost_per_1k_output=0.01,
    ),
    "gpt-4o-mini": ModelConfig(
        id="gpt-4o-mini",
        name="GPT-4o Mini",
        provider=PROVIDER_OPENAI,
        context_window=128000,
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
    ),
    
    # Anthropic models
    "claude-sonnet-4-20250514": ModelConfig(
        id="claude-sonnet-4-20250514",
        name="Claude Sonnet 4",
        provider=PROVIDER_ANTHROPIC,
        context_window=200000,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
    ),
    "claude-3-5-sonnet-20241022": ModelConfig(
        id="claude-3-5-sonnet-20241022",
        name="Claude 3.5 Sonnet",
        provider=PROVIDER_ANTHROPIC,
        context_window=200000,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
    ),
    
    # OpenRouter models (use provider/model format)
    "anthropic/claude-sonnet-4-20250514": ModelConfig(
        id="anthropic/claude-sonnet-4-20250514",
        name="Claude Sonnet 4 (via OpenRouter)",
        provider=PROVIDER_OPENROUTER,
        context_window=200000,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
    ),
    "openai/gpt-4o": ModelConfig(
        id="openai/gpt-4o",
        name="GPT-4o (via OpenRouter)",
        provider=PROVIDER_OPENROUTER,
        context_window=128000,
        cost_per_1k_input=0.0025,
        cost_per_1k_output=0.01,
    ),
    "google/gemini-pro-1.5": ModelConfig(
        id="google/gemini-pro-1.5",
        name="Gemini Pro 1.5 (via OpenRouter)",
        provider=PROVIDER_OPENROUTER,
        context_window=1000000,
        cost_per_1k_input=0.00125,
        cost_per_1k_output=0.005,
    ),
    "google/gemini-flash-1.5": ModelConfig(
        id="google/gemini-flash-1.5",
        name="Gemini Flash 1.5 (via OpenRouter)",
        provider=PROVIDER_OPENROUTER,
        context_window=1000000,
        cost_per_1k_input=0.000075,
        cost_per_1k_output=0.0003,
        notes="Very fast and cheap",
    ),
    "meta-llama/llama-3.1-70b-instruct": ModelConfig(
        id="meta-llama/llama-3.1-70b-instruct",
        name="Llama 3.1 70B (via OpenRouter)",
        provider=PROVIDER_OPENROUTER,
        context_window=131072,
        cost_per_1k_input=0.00052,
        cost_per_1k_output=0.00075,
    ),
    "deepseek/deepseek-chat": ModelConfig(
        id="deepseek/deepseek-chat",
        name="DeepSeek Chat (via OpenRouter)",
        provider=PROVIDER_OPENROUTER,
        context_window=64000,
        cost_per_1k_input=0.00014,
        cost_per_1k_output=0.00028,
        notes="Very cost-effective",
    ),
    "qwen/qwen-2.5-72b-instruct": ModelConfig(
        id="qwen/qwen-2.5-72b-instruct",
        name="Qwen 2.5 72B (via OpenRouter)",
        provider=PROVIDER_OPENROUTER,
        context_window=32768,
        cost_per_1k_input=0.00035,
        cost_per_1k_output=0.0004,
    ),
}


def get_model_config(model_id: str) -> Optional[ModelConfig]:
    """Get configuration for a model by ID."""
    return MODELS.get(model_id)


def get_default_model(provider: str) -> str:
    """Get the default model for a provider."""
    return DEFAULT_MODELS.get(provider, "gpt-4o")


def list_models(provider: Optional[str] = None) -> list[ModelConfig]:
    """List available models, optionally filtered by provider."""
    if provider:
        return [m for m in MODELS.values() if m.provider == provider]
    return list(MODELS.values())


def print_models(provider: Optional[str] = None) -> None:
    """Print available models in a formatted table."""
    models = list_models(provider)
    
    print("\nAvailable Models:")
    print("-" * 80)
    print(f"{'Model ID':<45} {'Name':<25} {'Context':<10}")
    print("-" * 80)
    
    for model in models:
        ctx = f"{model.context_window // 1000}K"
        print(f"{model.id:<45} {model.name:<25} {ctx:<10}")
    
    print("-" * 80)
    print(f"\nTotal: {len(models)} models")
    if not provider:
        print("Filter by provider: openai, anthropic, openrouter")
