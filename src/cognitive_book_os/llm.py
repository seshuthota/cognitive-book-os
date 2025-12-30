"""LLM client configuration and utilities."""

import os
import instructor
from openai import OpenAI
from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel
import logging
from typing import TypeVar, Type

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
