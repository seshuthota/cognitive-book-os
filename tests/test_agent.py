
import pytest
from unittest.mock import MagicMock, patch
from cognitive_book_os.agent import run_extraction_agent, AgentToolExecutor
from cognitive_book_os.brain import Brain
from cognitive_book_os.llm import LLMClient

@pytest.fixture
def mock_brain(tmp_path):
    # Create a real brain in a temp directory for file ops
    brain = Brain("test_brain", base_path=tmp_path)
    brain.initialize("Test Objective")
    return brain

def test_executor_tools(mock_brain):
    executor = AgentToolExecutor(mock_brain, chapter_num=1)
    
    # Test Create
    res = executor.execute("create_file", {"path": "test.md", "content": "# Test"})
    assert res.success
    assert mock_brain.read_file("test.md") == "# Test"
    
    # Test Read
    res = executor.execute("read_file", {"path": "test.md"})
    assert res.success
    assert res.data == "# Test"

@patch("cognitive_book_os.agent.LLMClient")
def test_checkpointing_logic(MockClient, mock_brain):
    """Verify that history is reset when it exceeds CHECKPOINT_THRESHOLD."""
    client = MockClient()
    client.provider = "anthropic"
    
    # Setup a mock response behavior
    # We want to simulate > 20 iterations
    # On the 21st call, we check if logic happened
    
    # Mock complete_with_tools to return "done" eventually
    # but initially just some tool calls to fill history
    
    mock_response_tool = {
        "content": "Thinking...",
        "tool_calls": [
            MagicMock(name="create_file", input={"path": "f.md", "content": "c"})
        ]
    }
    
    # We will invoke run_extraction_agent
    # It loops. We need to spy on the "messages" list inside.
    # Since it's a local variable, we can't easily spy directly.
    # Instead, we'll verify the SIDE EFFECTS:
    # 1. System prompt rebuilt (we can patch _build_system_prompt)
    # 2. Console printed checkpoint message
    
    with patch("cognitive_book_os.agent._build_system_prompt") as mock_build_prompt:
        # Prevent infinite loop by forcing done after 25 calls
        client.complete_with_tools.side_effect = [mock_response_tool] * 22 + [{"content": "Done", "tool_calls": []}]
        
        # We need to make the executor mark done eventually so loop exits
        # But here we just rely on max_iterations or break
        
        run_extraction_agent(
            chapter_content="Chapter Text",
            chapter_title="Title",
            chapter_num=1,
            brain=mock_brain,
            client=client,
            max_iterations=25 
        )
        
        # Checkpointing happens when len(messages) > 20.
        # So it should have triggered at least once.
        # When triggered, it calls _build_system_prompt AGAIN (initial + refresh)
        assert mock_build_prompt.call_count >= 2
