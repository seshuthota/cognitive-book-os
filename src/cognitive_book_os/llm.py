"""LLM client configuration and utilities."""

import os
import json
import instructor
from openai import OpenAI
from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel
import logging
from typing import TypeVar, Type, Any
from langfuse import observe

logger = logging.getLogger(__name__)

from .config import (
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENROUTER,
    PROVIDER_MINIMAX,
    OPENROUTER_BASE_URL,
    MINIMAX_BASE_URL,
    get_default_model,
)

load_dotenv()

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """
    Wrapper for LLM API calls using instructor for structured outputs.

    Supports:
    - OpenAI (direct)
    - Anthropic (direct)
    - OpenRouter (access to many models via OpenAI-compatible API)
    - MiniMax (via Anthropic-compatible API)
    """

    def __init__(self, provider: str = "anthropic", model: str | None = None):
        """
        Initialize the LLM client.

        Args:
            provider: "openai", "anthropic", "openrouter", or "minimax"
            model: Model name (defaults to provider's best model)
        """
        self.provider = provider
        self.model = model or get_default_model(provider)

        if provider == PROVIDER_OPENAI:
            self.client = instructor.from_openai(OpenAI())
            self._raw_client = OpenAI()

        elif provider == PROVIDER_ANTHROPIC:
            self.client = instructor.from_anthropic(Anthropic())
            self._raw_client = Anthropic()

        elif provider == PROVIDER_OPENROUTER:
            # OpenRouter uses OpenAI-compatible API
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise ValueError("OPENROUTER_API_KEY environment variable not set")

            openrouter_client = OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=api_key,
                default_headers={
                    "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "https://github.com/cognitive-book-os"),
                    "X-Title": "Cognitive Book OS"
                }
            )
            self.client = instructor.from_openai(openrouter_client)
            self._raw_client = openrouter_client

        elif provider == PROVIDER_MINIMAX:
            # MiniMax uses Anthropic-compatible API
            api_key = os.getenv("MINIMAX_API_KEY")
            if not api_key:
                raise ValueError("MINIMAX_API_KEY environment variable not set")

            minimax_client = Anthropic(
                base_url=MINIMAX_BASE_URL,
                api_key=api_key,
            )
            self.client = instructor.from_anthropic(minimax_client)
            self._raw_client = minimax_client

        else:
            raise ValueError(f"Unknown provider: {provider}. Use 'openai', 'anthropic', 'openrouter', or 'minimax'")

    @observe(as_type="generation")
    def generate(
        self,
        response_model: Type[T],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_retries: int = 3,
        max_tokens: int = 65536
    ) -> T:
        """
        Generate a structured response from the LLM.

        Args:
            response_model: Pydantic model for the response
            system_prompt: System message
            user_prompt: User message
            temperature: Sampling temperature
            max_retries: Number of retries for parsing failures
            max_tokens: Maximum tokens in response

        Returns:
            Parsed response as the specified Pydantic model
        """
        # Build kwargs - Anthropic requires max_tokens, OpenAI it's optional
        kwargs = {
            "model": self.model,
            "response_model": response_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_retries": max_retries,
            "timeout": 120.0,
        }

        # Add max_tokens for all providers (Anthropic requires it, others accept it)
        kwargs["max_tokens"] = max_tokens

        # Enable streaming for Anthropic/MiniMax to avoid timeouts on long requests
        if self.provider in (PROVIDER_ANTHROPIC, PROVIDER_MINIMAX):
            try:
                # Use create_partial which handles formatting for streaming correctly
                # and prevents "Stream object has no attribute content" errors
                stream_result = self.client.chat.completions.create_partial(**kwargs)

                final_obj = None
                for obj in stream_result:
                    # Update status if we have a way to track it, otherwise just collect patches
                    final_obj = obj

                # Ensure we return a strict instance of the model
                if final_obj:
                    try:
                        # Re-validate to ensure it's the strict model T, not Partial[T]
                        return response_model.model_validate(final_obj.model_dump())
                    except Exception as e:
                        logger.error(f"Validation failed for streaming response. Error: {e}")
                        logger.error(f"Raw object content: {final_obj.model_dump()}")
                        raise e

                # If streaming failed to return anything, fall back to non-streaming
                if final_obj is None:
                    logger.warning("Streaming returned no results. Falling back to non-streaming call.")
                    return self.client.chat.completions.create(**kwargs)

            except Exception as e:
                logger.warning(f"Streaming call failed: {e}. Falling back to non-streaming.")
                return self.client.chat.completions.create(**kwargs)

        # Standard non-streaming call for others
        return self.client.chat.completions.create(**kwargs)

    @observe(as_type="generation")
    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 65536
    ) -> str:
        """
        Generate a plain text response (no structured output).

        Args:
            system_prompt: System message
            user_prompt: User message
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response

        Returns:
            Raw text response
        """
        if self.provider in (PROVIDER_ANTHROPIC, PROVIDER_MINIMAX):
            # Anthropic and MiniMax use same API structure
            # Use streaming to avoid timeouts
            stream = self._raw_client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                stream=True,
                timeout=120.0
            )

            # Iterate stream to collect text
            full_text = ""
            for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    full_text += event.delta.text
            return full_text
        else:
            # OpenAI and OpenRouter use same API structure
            response = self._raw_client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature
            )
            return response.choices[0].message.content or ""

    @observe(as_type="generation")
    def complete_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 16384,
        temperature: float = 0.3
    ) -> dict:
        """
        Make a tool-capable LLM call, abstracting provider differences.

        Args:
            system_prompt: System message
            messages: Message history (will be modified in place for some providers)
            tools: Tool definitions (OpenAI format). If None, uses STANDARD_TOOLS.
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            Dict with:
                - content: Assistant message content (str or list of blocks)
                - tool_calls: List of tool calls made (empty if none)
                - stop_reason: Why the response ended (for logging/debugging)
        """
        tools = tools or STANDARD_TOOLS

        if self.provider in (PROVIDER_ANTHROPIC, PROVIDER_MINIMAX):
            # Anthropic/MiniMax API - convert OpenAI tool format to Anthropic format
            anthropic_tools = _convert_tools_to_anthropic(tools)
            response = self._raw_client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=messages,
                tools=anthropic_tools,
                max_tokens=max_tokens,
                temperature=temperature
            )

            # Extract tool calls and content blocks
            tool_uses = []
            assistant_content = []

            for block in response.content:
                if block.type == "thinking":
                    assistant_content.append({
                        "type": "thinking",
                        "thinking": block.thinking,
                        "signature": getattr(block, 'signature', '')
                    })
                elif block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input
                    })

            return {
                "content": assistant_content,
                "tool_calls": tool_uses,
                "stop_reason": response.stop_reason
            }
        else:
            # OpenAI/OpenRouter API
            response = self._raw_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system_prompt}] + messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=max_tokens,
                temperature=temperature
            )

            assistant_message = response.choices[0].message

            return {
                "content": assistant_message.content or "",
                "tool_calls": assistant_message.tool_calls or [],
                "stop_reason": getattr(assistant_message, "stop_reason", None)
            }


def get_client(provider: str = "anthropic", model: str | None = None) -> LLMClient:
    """
    Get an LLM client instance.

    Args:
        provider: "openai", "anthropic", or "openrouter"
        model: Optional model override
               For OpenRouter, use "provider/model" format, e.g.:
               - "anthropic/claude-sonnet-4-20250514"
               - "openai/gpt-4o"
               - "google/gemini-pro-1.5"
               - "meta-llama/llama-3.1-70b-instruct"

    Returns:
        Configured LLMClient
    """
    return LLMClient(provider=provider, model=model)


# Standard tool definitions (OpenAI format)
STANDARD_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new file in the knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path for the file"},
                    "content": {"type": "string", "description": "Full markdown content"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_file",
            "description": "Update an existing file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the existing file"},
                    "content": {"type": "string", "description": "Complete updated content"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file's content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List all files in the knowledge base.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Signal extraction is complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Summary of what was extracted"}
                },
                "required": ["summary"]
            }
        }
    }
]


def _convert_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert OpenAI-format tool definitions to Anthropic format.

    OpenAI format:
        {"type": "function", "function": {"name": "...", "parameters": {...}}}

    Anthropic format:
        {"name": "...", "input_schema": {...}}
    """
    anthropic_tools = []
    for tool in tools:
        if tool.get("type") == "function":
            func = tool["function"]
            anthropic_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}})
            })
        else:
            # Already in a format without type wrapper, assume Anthropic-compatible
            anthropic_tools.append(tool)
    return anthropic_tools


def _to_openai_tool_calls(tool_uses: list[Any]) -> list[dict]:
    """Convert Anthropic tool_use blocks to OpenAI tool_calls format."""
    return [
        {
            "id": block.id,
            "type": "function",
            "function": {
                "name": block.name,
                "arguments": json.dumps(block.input)
            }
        }
        for block in tool_uses
    ]


def _to_anthropic_content_blocks(tool_calls: list[Any], assistant_content: str = "") -> list[dict]:
    """Convert OpenAI tool_calls to Anthropic content_blocks format."""
    blocks = []
    if assistant_content:
        blocks.append({"type": "text", "text": assistant_content})
    for tc in tool_calls:
        blocks.append({
            "type": "tool_use",
            "id": tc.id,
            "name": tc.function.name,
            "input": json.loads(tc.function.arguments)
        })
    return blocks
