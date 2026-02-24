
import pytest
from unittest.mock import MagicMock, patch
from cognitive_book_os.llm import LLMClient, _convert_tools_to_anthropic, _to_openai_tool_calls

def test_convert_tools_to_anthropic():
    # Input: OpenAI format
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "test_tool",
                "description": "A test tool",
                "parameters": {
                    "type": "object",
                    "properties": {"arg1": {"type": "string"}}
                }
            }
        }
    ]
    
    # Expected: Anthropic format
    expected = [
        {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {
                "type": "object",
                "properties": {"arg1": {"type": "string"}}
            }
        }
    ]
    
    result = _convert_tools_to_anthropic(openai_tools)
    assert result == expected

@patch("cognitive_book_os.llm.OpenAI")
@patch("cognitive_book_os.llm.instructor.from_openai")
def test_llm_client_init_openai(mock_instructor, mock_openai):
    client = LLMClient(provider="openai")
    assert client.provider == "openai"
    mock_openai.assert_called()
    mock_instructor.assert_called()

@patch("cognitive_book_os.llm.Anthropic")
@patch("cognitive_book_os.llm.instructor.from_anthropic")
def test_llm_client_init_anthropic(mock_instructor, mock_anthropic):
    client = LLMClient(provider="anthropic")
    assert client.provider == "anthropic"
    mock_anthropic.assert_called()
    mock_instructor.assert_called()
