"""Agentic tool-based extraction for Cognitive Book OS.

Instead of structured outputs, this module gives the LLM actual tools
to create/update/read files, making it more like a natural agent workflow.
"""

import json
from typing import Callable, Any
from pydantic import BaseModel, Field
from rich.console import Console

from .brain import Brain
from .llm import LLMClient

console = Console()


# Tool result models
class ToolResult(BaseModel):
    """Result of a tool execution."""
    success: bool
    message: str
    data: str | None = None


# Tool definitions for the LLM
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new file in the knowledge base. Use for new characters, events, themes, or facts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path for the file, e.g., 'characters/steve_jobs.md' or 'themes/reality_distortion.md'"
                    },
                    "content": {
                        "type": "string",
                        "description": "Full markdown content. MUST include YAML frontmatter with a 'summary' field (1-sentence description of key unique facts) for searchability."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_file",
            "description": "Update an existing file with new information. Provide the complete updated content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the existing file to update"
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete updated markdown content (replaces existing)"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the current content of a file in the knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List all files currently in the knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Signal that you have finished extracting and organizing all information from this chapter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of what was extracted and organized"
                    }
                },
                "required": ["summary"]
            }
        }
    }
]


class AgentToolExecutor:
    """Executes tools called by the LLM agent."""
    
    def __init__(self, brain: Brain, chapter_num: int):
        self.brain = brain
        self.chapter_num = chapter_num
        self.files_created = 0
        self.files_updated = 0
        self.is_done = False
        self.summary = ""
    
    def execute(self, tool_name: str, args: dict) -> ToolResult:
        """Execute a tool and return the result."""
        
        if tool_name == "create_file":
            return self._create_file(args["path"], args["content"])
        elif tool_name == "update_file":
            return self._update_file(args["path"], args["content"])
        elif tool_name == "read_file":
            return self._read_file(args["path"])
        elif tool_name == "list_files":
            return self._list_files()
        elif tool_name == "done":
            return self._done(args.get("summary", ""))
        else:
            return ToolResult(success=False, message=f"Unknown tool: {tool_name}")
    
    def _create_file(self, path: str, content: str) -> ToolResult:
        """Create a new file."""
        if not path or not content:
            return ToolResult(success=False, message="Path and content are required")
        
        # Ensure path has .md extension
        if not path.endswith(".md"):
            path = path + ".md"
        
        # Check if file exists
        existing = self.brain.read_file(path)
        if existing:
            return ToolResult(
                success=False, 
                message=f"File already exists: {path}. Use update_file instead."
            )
        
        self.brain.write_file(path, content)
        self.files_created += 1
        console.print(f"    [green]+ Created:[/green] {path}")
        
        return ToolResult(success=True, message=f"Created {path}")
    
    def _update_file(self, path: str, content: str) -> ToolResult:
        """Update an existing file."""
        if not path or not content:
            return ToolResult(success=False, message="Path and content are required")
        
        if not path.endswith(".md"):
            path = path + ".md"
        
        self.brain.write_file(path, content)
        self.files_updated += 1
        console.print(f"    [yellow]~ Updated:[/yellow] {path}")
        
        return ToolResult(success=True, message=f"Updated {path}")
    
    def _read_file(self, path: str) -> ToolResult:
        """Read a file's content."""
        content = self.brain.read_file(path)
        if content:
            return ToolResult(success=True, message="File read successfully", data=content)
        else:
            return ToolResult(success=False, message=f"File not found: {path}")
    
    def _list_files(self) -> ToolResult:
        """List all files in the brain."""
        files = self.brain.list_files()
        return ToolResult(
            success=True, 
            message=f"Found {len(files)} files",
            data="\n".join(files)
        )
    
    def _done(self, summary: str) -> ToolResult:
        """Mark extraction as complete."""
        self.is_done = True
        self.summary = summary
        return ToolResult(success=True, message="Extraction complete")


def run_extraction_agent(
    chapter_content: str,
    chapter_title: str,
    chapter_num: int,
    brain: Brain,
    client: LLMClient,
    max_iterations: int = 40  # Higher for thinking models
) -> dict:
    """
    Run the extraction agent with tool calling.
    
    Args:
        chapter_content: The chapter text
        chapter_title: Title of the chapter
        chapter_num: Chapter number
        brain: The brain to write to
        client: LLM client
        max_iterations: Maximum tool calls before forcing completion
        
    Returns:
        Dict with files_created, files_updated, summary
    """
    from .config import PROVIDER_ANTHROPIC, PROVIDER_MINIMAX
    
    executor = AgentToolExecutor(brain, chapter_num)
    
    # Get brain structure for context
    brain_structure = brain.get_structure()
    existing_files = brain.list_files()
    objective = brain.get_objective()
    
    # Check if objective is generic/comprehensive
    is_generic = "General Comprehensive Knowledge Extraction" in objective
    
    if is_generic:
        # Broader prompt for general ingestion
        system_prompt = f"""You are the Archivist for Cognitive Book OS. Your job is to read a chapter and organize information into a structured knowledge base.
    
## Your Goal: FORENSIC DATA LOGGER
Capture ALL significant structure, facts, events, and themes. Do not filter for a specific user question. But you must be High-Fidelity.

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
You MUST use this format. The `summary` field in YAML is critical for search.

```markdown
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
- [Detail]: Specific fact.

**Quotes**:
> "Relevant text from source"
```

## Rules
1. Extract what is explicitly stated, not implied
2. Use direct quotes where relevant
3. Create separate files for distinct entities/concepts
4. Be comprehensive - if it seems important to the author, extract it
5. Cross-reference related existing files in the `related` YAML field
6. Call `done` when finished with this chapter
 
## Current Brain Structure
{brain_structure}

## Existing Files
{chr(10).join(existing_files) if existing_files else "(No files yet)"}
"""
    else:
        # Targeted prompt for specific objective
        system_prompt = f"""You are the Archivist for Cognitive Book OS. Your job is to read a chapter and organize information into a structured knowledge base.

## The User's Objective
{objective}

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
You MUST use this format. The `summary` field in YAML is critical for search.

```markdown
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
- [Detail]: Specific fact.

**Quotes**:
> "Relevant text from source"
```

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
{chr(10).join(existing_files) if existing_files else "(No files yet)"}
"""

    user_message = f"""## Chapter {chapter_num}: {chapter_title}

{chapter_content}

---

Please extract and organize the important information from this chapter. Use the tools to create/update files as needed. Call `done` when finished."""

    # Determine if using Anthropic-style API (Anthropic or MiniMax)
    is_anthropic_style = client.provider in (PROVIDER_ANTHROPIC, PROVIDER_MINIMAX)
    
    iterations = 0
    
    if is_anthropic_style:
        # Anthropic-style tool calling
        return _run_anthropic_agent(
            client, executor, system_prompt, user_message,
            max_iterations, chapter_num
        )
    else:
        # OpenAI-style tool calling
        return _run_openai_agent(
            client, executor, system_prompt, user_message,
            max_iterations
        )


def _run_openai_agent(
    client: LLMClient,
    executor: AgentToolExecutor,
    system_prompt: str,
    user_message: str,
    max_iterations: int
) -> dict:
    """Run agent loop using OpenAI-style tool calling."""
    messages = [
        {"role": "user", "content": user_message}
    ]
    
    iterations = 0
    
    while not executor.is_done and iterations < max_iterations:
        iterations += 1
        
        # Call LLM with tools
        response = client._raw_client.chat.completions.create(
            model=client.model,
            messages=[{"role": "system", "content": system_prompt}] + messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=16384,
            temperature=0.3
        )
        
        assistant_message = response.choices[0].message
        
        # Check if there are tool calls
        if assistant_message.tool_calls:
            # Add assistant message to history
            messages.append({
                "role": "assistant",
                "content": assistant_message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in assistant_message.tool_calls
                ]
            })
            
            # Execute each tool call
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                
                result = executor.execute(tool_name, args)
                
                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({
                        "success": result.success,
                        "message": result.message,
                        "data": result.data
                    })
                })
        else:
            # No tool calls - LLM is done or confused
            if assistant_message.content:
                console.print(f"    [dim]Agent: {assistant_message.content[:100]}...[/dim]")
            break
    
    if iterations >= max_iterations and not executor.is_done:
        console.print(f"    [yellow]Warning: Hit max iterations ({max_iterations})[/yellow]")
    
    return {
        "files_created": executor.files_created,
        "files_updated": executor.files_updated,
        "summary": executor.summary,
        "iterations": iterations
    }


# Anthropic-style tool definitions
ANTHROPIC_TOOLS = [
    {
        "name": "create_file",
        "description": "Create a new file in the knowledge base. Use for new characters, events, themes, or facts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path for the file, e.g., 'characters/steve_jobs.md'"
                },
                "content": {
                    "type": "string",
                    "description": "Full markdown content. MUST include YAML frontmatter with a 'summary' field."
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "update_file",
        "description": "Update an existing file with new information. Provide the complete updated content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the existing file to update"},
                "content": {"type": "string", "description": "Complete updated markdown content"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "read_file",
        "description": "Read the current content of a file in the knowledge base.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "list_files",
        "description": "List all files currently in the knowledge base.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "done",
        "description": "Signal that you have finished extracting and organizing all information from this chapter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Brief summary of what was extracted"}
            },
            "required": ["summary"]
        }
    }
]


def _run_anthropic_agent(
    client: LLMClient,
    executor: AgentToolExecutor,
    system_prompt: str,
    user_message: str,
    max_iterations: int,
    chapter_num: int
) -> dict:
    """Run agent loop using Anthropic-style tool calling (for Anthropic and MiniMax)."""
    messages = [
        {"role": "user", "content": user_message}
    ]
    
    iterations = 0
    
    while not executor.is_done and iterations < max_iterations:
        iterations += 1
        
        # Call LLM with tools (Anthropic API style)
        response = client._raw_client.messages.create(
            model=client.model,
            system=system_prompt,
            messages=messages,
            tools=ANTHROPIC_TOOLS,
            max_tokens=16384,  # Higher for thinking models like MiniMax M2.1
            temperature=0.3
        )
        
        # Process response content blocks
        assistant_content = []
        tool_uses = []
        
        for block in response.content:
            if block.type == "thinking":
                # MiniMax M2.1 returns thinking blocks - need to preserve them
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
        
        # Add assistant message to history
        messages.append({"role": "assistant", "content": assistant_content})
        
        if tool_uses:
            # Execute tool calls and build results
            tool_results = []
            for tool_use in tool_uses:
                result = executor.execute(tool_use.name, tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps({
                        "success": result.success,
                        "message": result.message,
                        "data": result.data
                    })
                })
            
            # Add tool results to messages
            messages.append({"role": "user", "content": tool_results})
        
        # Check if we should stop
        if response.stop_reason == "end_turn" and not tool_uses:
            break
    
    if iterations >= max_iterations and not executor.is_done:
        console.print(f"    [yellow]Warning: Hit max iterations ({max_iterations})[/yellow]")
    
    return {
        "files_created": executor.files_created,
        "files_updated": executor.files_updated,
        "summary": executor.summary,
        "iterations": iterations
    }

