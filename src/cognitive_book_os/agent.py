"""Agentic tool-based extraction for Cognitive Book OS.

Instead of structured outputs, this module gives the LLM actual tools
to create/update/read files, making it more like a natural agent workflow.

The agent loop is unified - a single implementation works for all providers
(OpenAI, Anthropic, OpenRouter, MiniMax) via the LLMClient.complete_with_tools()
method that abstracts provider differences.
"""

import json
from typing import Callable, Any
from pydantic import BaseModel, Field
from rich.console import Console

from .brain import Brain
from .claim_store import ClaimStore, claims_versioning_enabled, generate_run_id
from .llm import LLMClient, STANDARD_TOOLS

console = Console()


# Tool result models
class ToolResult(BaseModel):
    """Result of a tool execution."""
    success: bool
    message: str
    data: str | None = None


class AgentToolExecutor:
    """Executes tools called by the LLM agent.

    This class handles the tool execution logic, decoupled from the
    provider-specific API calls. This makes it easy to test and maintain.
    """

    def __init__(self, brain: Brain, chapter_num: int, run_id: str | None = None):
        self.brain = brain
        self.chapter_num = chapter_num
        self.files_created = 0
        self.files_updated = 0
        self.is_done = False
        self.summary = ""
        self.run_id = run_id or generate_run_id("extract", brain.name)
        self.claim_store = ClaimStore(brain) if claims_versioning_enabled() else None

    def execute(self, tool_name: str, args: dict) -> ToolResult:
        """Execute a tool and return the result."""
        handler = getattr(self, f"_handle_{tool_name}", None)
        if handler:
            return handler(args)
        return ToolResult(success=False, message=f"Unknown tool: {tool_name}")

    def _handle_create_file(self, args: dict) -> ToolResult:
        """Create a new file."""
        path = args.get("path")
        content = args.get("content")
        if not path or not content:
            return ToolResult(success=False, message="Path and content are required")

        if not path.endswith(".md"):
            path = path + ".md"

        existing = self.brain.read_file(path)
        if existing:
            return ToolResult(
                success=False,
                message=f"File already exists: {path}. Use update_file instead."
            )

        self.brain.write_file(path, content)
        tracking_error = self._track_claims(path=path, content=content)
        if tracking_error:
            return ToolResult(success=False, message=tracking_error)
        self.files_created += 1
        console.print(f"    [green]+ Created:[/green] {path}")
        return ToolResult(success=True, message=f"Created {path}")

    def _handle_update_file(self, args: dict) -> ToolResult:
        """Update an existing file."""
        path = args.get("path")
        content = args.get("content")
        if not path or not content:
            return ToolResult(success=False, message="Path and content are required")

        if not path.endswith(".md"):
            path = path + ".md"

        self.brain.write_file(path, content)
        tracking_error = self._track_claims(path=path, content=content)
        if tracking_error:
            return ToolResult(success=False, message=tracking_error)
        self.files_updated += 1
        console.print(f"    [yellow]~ Updated:[/yellow] {path}")
        return ToolResult(success=True, message=f"Updated {path}")

    def _track_claims(self, path: str, content: str) -> str | None:
        if not self.claim_store:
            return None
        try:
            result = self.claim_store.track_file_claims(
                file_path=path,
                content=content,
                run_id=self.run_id,
            )
            warnings = result.get("warnings", 0)
            if warnings:
                console.print(f"    [dim]Claim audit warnings: {warnings}[/dim]")
            return None
        except ValueError as exc:
            return f"Claim provenance enforcement failed: {exc}"
        except Exception as exc:
            return f"Claim tracking failed: {exc}"

    def _handle_read_file(self, args: dict) -> ToolResult:
        """Read a file's content."""
        path = args.get("path")
        if not path:
            return ToolResult(success=False, message="Path is required")

        content = self.brain.read_file(path)
        if content:
            return ToolResult(success=True, message="File read successfully", data=content)
        return ToolResult(success=False, message=f"File not found: {path}")

    def _handle_list_files(self, args: dict) -> ToolResult:
        """List all files in the brain."""
        files = self.brain.list_files()
        return ToolResult(
            success=True,
            message=f"Found {len(files)} files",
            data="\n".join(files)
        )

    def _handle_done(self, args: dict) -> ToolResult:
        """Mark extraction as complete."""
        self.is_done = True
        self.summary = args.get("summary", "")
        return ToolResult(success=True, message="Extraction complete")


def _build_system_prompt(
    brain_structure: str,
    existing_files: list[str],
    objective: str,
    chapter_num: int,
    is_generic: bool
) -> str:
    """Build the system prompt based on whether objective is generic or specific."""
    file_format = f"""```markdown
---
source: chapter_{chapter_num}
tags: [tag1, tag2]
summary: "One sentence specific summary of the unique data in this file."
related: [path/to/related_file1.md, path/to/related_file2.md]
---

# Title

**Synopsis**: Brief overview.

**Key Details**:
- [Detail]: Specific fact.

**Quotes**:
> "Relevant text from source"
```"""

    if is_generic:
        return f"""You are the Archivist for Cognitive Book OS. Your job is to read a chapter and organize information into a structured knowledge base.

## Your Goal: FORENSIC DATA LOGGER
Capture ALL significant structure, facts, events, and themes. Be comprehensive.

## Universal Extraction Protocol
1. **Specifics over Generics**:
   - BAD: "They negotiated a deal."
   - GOOD: "They agreed to a $5M acquisition with a 6-month vesting period."

2. **Quotes as Evidence**:
   - Use direct quotes for key definitions, surprising facts, or specific phrasing.

3. **Causal Chains**:
   - Record *how* things happen, not just *that* they happened.

## Directory Structure
- `characters/` - People/Entities. Focus on motivations and relationships.
- `timeline/` - Events. Focus on specific mechanics and outcomes.
- `themes/` - Concepts. Focus on definitions and evolution.
- `facts/` - Data. Focus on raw numbers and tables.

## File Format (Strict)
{file_format}

## Rules
1. Extract what is explicitly stated, not implied
2. Use direct quotes where relevant
3. Create separate files for distinct entities/concepts
4. Be comprehensive
5. Cross-reference related existing files in the `related` YAML field
6. Call `done` when finished with this chapter

## Current Brain Structure
{brain_structure}

## Existing Files
{chr(10).join(existing_files) if existing_files else "(No files yet)"}"""
    else:
        return f"""You are the Archivist for Cognitive Book OS. Your job is to read a chapter and organize information into a structured knowledge base.

## The User's Objective
{objective}

You are an expert Archivist Agent. Extract knowledge and organize it into the Brain.

## PROVENANCE PROTOCOL (CRITICAL)
For every single fact/claim, you MUST provide a direct quote from the text.
Format:
- **Claim**: Description.
  > "Direct quote." (Source: Chapter X)

## Tools
- `create_file`, `update_file`, `read_file`, `list_files`, `done`.

## Instructions
1. Check existing files.
2. Extract specific details (Characters, Timeline, Themes).
3. **Always cite quotes.**
4. Organize into directories.

## Your Role: FORENSIC DATA LOGGER
You are NOT a summarizer. Summaries lose data. Your job is to preserve specific details, numbers, and mechanics.

## Universal Extraction Protocol
1. **Specifics over Generics**:
   - BAD: "They negotiated a deal."
   - GOOD: "They agreed to a $5M acquisition with a 6-month vesting period."
   - BAD: "The attack failed."
   - GOOD: "The missiles passed through the hull without detonating."

2. **Quotes as Evidence**:
   - Use direct quotes for key definitions, surprising facts, or specific phrasing.

3. **Causal Chains**:
   - Record *how* things happen, not just *that* they happened.

## Directory Structure
- `characters/` - People/Entities. Focus on motivations and relationships.
- `timeline/` - Events. Focus on specific mechanics and outcomes.
- `themes/` - Concepts. Focus on definitions and evolution.
- `facts/` - Data. Focus on raw numbers and tables.

## File Format (Strict)
{file_format}

## Rules
1. Extract what is explicitly stated, not implied
2. Use direct quotes where relevant
3. Create separate files for distinct entities/concepts
4. Cross-reference related existing files in the `related` YAML field
5. Focus on information relevant to the user's objective
6. Call `done` when finished with this chapter

## Current Brain Structure
{brain_structure}

## Existing Files
{chr(10).join(existing_files) if existing_files else "(No files yet)"}"""


from langfuse import observe

@observe(name="Extraction Agent")
def run_extraction_agent(
    chapter_content: str,
    chapter_title: str,
    chapter_num: int,
    brain: Brain,
    client: LLMClient,
    max_iterations: int = 40,  # Higher for thinking models
    run_id: str | None = None,
) -> dict:
    """
    Run the extraction agent with tool calling.

    This unified implementation works for all LLM providers (OpenAI, Anthropic,
    OpenRouter, MiniMax) by using LLMClient.complete_with_tools().

    Args:
        chapter_content: The chapter text
        chapter_title: Title of the chapter
        chapter_num: Chapter number
        brain: The brain to write to
        client: LLM client
        max_iterations: Maximum tool calls before forcing completion

    Returns:
        Dict with files_created, files_updated, summary, iterations
    """
    executor = AgentToolExecutor(brain, chapter_num, run_id=run_id)

    # Get brain structure for context
    brain_structure = brain.get_structure()
    existing_files = brain.list_files()
    objective = brain.get_objective()

    # Check if objective is generic/comprehensive
    is_generic = "General Comprehensive Knowledge Extraction" in objective

    # Build system prompt
    system_prompt = _build_system_prompt(
        brain_structure, existing_files, objective, chapter_num, is_generic
    )

    user_message = f"""## Chapter {chapter_num}: {chapter_title}

{chapter_content}

---

Please extract and organize the important information from this chapter. Use the tools to create/update files as needed. Call `done` when finished."""

    # Unified agent loop - works for all providers
    messages = [{"role": "user", "content": user_message}]
    iterations = 0

    while not executor.is_done and iterations < max_iterations:
        iterations += 1

        # Make LLM call - unified across all providers
        response = client.complete_with_tools(
            system_prompt=system_prompt,
            messages=messages,
            tools=STANDARD_TOOLS,
            max_tokens=16384,
            temperature=0.3
        )

        tool_calls = response.get("tool_calls", [])
        assistant_content = response.get("content", "")

        # Process tool calls and add to message history
        if tool_calls:
            # Add assistant message to history
            if client.provider in ("anthropic", "minimax"):
                messages.append({"role": "assistant", "content": assistant_content})
            else:
                # OpenAI format - need to serialize tool calls
                messages.append({
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": [
                        {
                            "id": tc.id if hasattr(tc, 'id') else tc.get('id'),
                            "type": "function",
                            "function": {
                                "name": tc.name if hasattr(tc, 'name') else tc.get('name'),
                                "arguments": json.dumps(tc.input if hasattr(tc, 'input') else tc.get('input'))
                            }
                        }
                        for tc in tool_calls
                    ]
                })

            # Execute each tool call
            tool_results = []
            for tool in tool_calls:
                if hasattr(tool, 'name'):
                    tool_name = tool.name
                    args = tool.input if hasattr(tool, 'input') else tool.get('input')
                else:
                    tool_name = tool.get('name')
                    args = tool.get('input', {})

                try:
                    result = executor.execute(tool_name, args)
                except Exception as e:
                    result = ToolResult(success=False, message=f"Error: {str(e)}")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool.id if hasattr(tool, 'id') else tool.get('id'),
                    "content": json.dumps({
                        "success": result.success,
                        "message": result.message,
                        "data": result.data
                    })
                })

            # Add tool results to messages
            messages.append({"role": "user", "content": tool_results})

        else:
            # No tool calls - LLM is done or confused
            if assistant_content:
                content_text = assistant_content
                if isinstance(assistant_content, list):
                    content_text = "".join(
                        b.get("text", "") for b in assistant_content
                        if b.get("type") == "text"
                    )
                if content_text:
                    console.print(f"    [dim]Agent: {content_text[:100]}...[/dim]")
            break

        # Checkpointing Strategy (Manus Style)
        # Prevent context window from growing indefinitely by "committing" the state
        # to the file system and clearing the tool history.
        CHECKPOINT_THRESHOLD = 20
        if len(messages) > CHECKPOINT_THRESHOLD:
            # 1. READ THE FILE SYSTEM (Ground Truth)
            current_files = executor.brain.list_files()
            current_structure = executor.brain.get_structure()

            # 2. REFRESH SYSTEM PROMPT
            # We must update the system prompt so the agent knows what files *now* exist
            # instead of what existed at the start of the chapter.
            system_prompt = _build_system_prompt(
                current_structure, current_files, objective, chapter_num, is_generic
            )

            # 3. CREATE A CHECKPOINT MESSAGE
            checkpoint_msg = {
                "role": "user",
                "content": f"""[SYSTEM INTERVENTION]
You have completed {len(messages)} actions. To save context, we are clearing the action history.

CURRENT STATUS:
- Files Created/Updated: {len(current_files)}
- Last Action: {messages[-1].get('content', 'Tool Execution')}

The Chapter Text is still provided above. Continue extracting information based on the current file system state."""
            }

            # 4. RESET HISTORY
            # Keep messages[0] (User Prompt with Chapter Text) to preserve KV-Cache
            # Discard intermediate tool calls
            # Add checkpoint message
            messages = [messages[0], checkpoint_msg]
            console.print(f"    [dim]Context Checkpoint: History cleared to save tokens (Files: {len(current_files)})[/dim]")

    if iterations >= max_iterations and not executor.is_done:
        console.print(f"    [yellow]Warning: Hit max iterations ({max_iterations})[/yellow]")

    return {
        "files_created": executor.files_created,
        "files_updated": executor.files_updated,
        "summary": executor.summary,
        "iterations": iterations
    }
