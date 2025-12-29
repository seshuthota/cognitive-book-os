"""Ingestion pipeline - processes documents into the brain."""

from pathlib import Path
from rich.console import Console

from .brain import Brain
from .llm import LLMClient, get_client
from .models import ObjectiveSynthesis
from .parser import chunk_document
from .prompts import get_system_prompt
from .agent import run_extraction_agent

console = Console()


def synthesize_objective(
    chapter_content: str,
    chapter_title: str,
    chapter_num: int,
    brain: Brain,
    client: LLMClient
) -> ObjectiveSynthesis:
    """
    Pass 2: Synthesize progress toward the user's objective.
    
    Args:
        chapter_content: The chapter text
        chapter_title: Title of the chapter
        chapter_num: Chapter number
        brain: The brain
        client: LLM client
        
    Returns:
        ObjectiveSynthesis with updated response
    """
    system_prompt = get_system_prompt("synthesize")
    
    objective = brain.get_objective()
    current_response = brain.get_response()
    brain_index = brain.get_index()
    
    user_prompt = f"""## User's Objective
{objective}

## Current Response (so far)
{current_response}

## Brain Index
{brain_index}

## Chapter to Process
**Chapter {chapter_num}: {chapter_title}**

{chapter_content}

---

What new insights from this chapter are relevant to the objective?
Provide an updated, comprehensive response to the objective.
"""

    result = client.generate(
        response_model=ObjectiveSynthesis,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.5
    )
    
    # Update the response file
    response_content = f"""# Response to Objective

**Objective:** {objective}

**Status:** Processing chapter {chapter_num}
**Confidence:** {result.confidence.value}

---

{result.updated_response}

---

## Open Questions
"""
    for q in result.open_questions:
        response_content += f"- {q}\n"
    
    brain.update_response(response_content)
    
    return result



def process_document(
    document_path: str | Path,
    brain_name: str,
    objective: str | None = None,
    provider: str = "anthropic",
    model: str | None = None,
    brains_dir: str = "brains",
    fast_mode: bool = False,
    strategy_name: str = "standard",
    allowed_chapters: list[int] | None = None
) -> Brain:
    """
    Process a document into a brain using agentic tool calling.
    
    Args:
        document_path: Path to the PDF document
        objective: The user's objective/question
        brain_name: Name for the brain
        provider: LLM provider
        model: Optional model override
        brains_dir: Directory to store brains
        fast_mode: If True, skip per-chapter synthesis and only synthesize at end
        strategy_name: Ingestion strategy ("standard" or "triage")
        allowed_chapters: Optional list of chapter numbers (1-indexed) to process. 
                          If provided, skips all others.
        
    Returns:
        The populated Brain
    """
    from .pipeline import get_strategy
    
    document_path = Path(document_path)
    console.print(f"\n[bold blue]Cognitive Book OS[/bold blue]")
    console.print(f"Processing: {document_path.name}")
    console.print(f"Objective: {objective}")
    console.print(f"Strategy: {strategy_name}")
    if allowed_chapters:
        console.print(f"[yellow]Enrichment Mode: Processing {len(allowed_chapters)} targeted chapters[/yellow]")
    if fast_mode:
        console.print(f"[cyan]Fast mode: ON (synthesis at end only)[/cyan]")
    console.print()
    
    # Initialize brain
    brain = Brain(name=brain_name, base_path=brains_dir)
    
    # Determine effective objective for logging/archiving
    effective_objective = objective or "General Comprehensive Knowledge Extraction"
    
    if brain.exists():
        console.print(f"[yellow]Brain '{brain_name}' already exists. Resuming...[/yellow]")
        log = brain.get_processing_log()
        # In enrichment mode (allowed_chapters set), we don't start from log; we jump around.
        start_from = log.chapters_processed if not allowed_chapters else 0
    else:
        brain.initialize(effective_objective)
        brain.update_processing_log(
            book_path=str(document_path),
            objective=effective_objective
        )
        start_from = 0
        console.print(f"[green]Created brain: {brain.path}[/green]")
    
    # Initialize LLM client
    client = get_client(provider=provider, model=model)
    console.print(f"Using: {client.provider} / {client.model}")
    console.print()
    
    # Get Strategy
    strategy = get_strategy(strategy_name)
    
    # Process document chapter by chapter
    chunks = list(chunk_document(document_path))
    total_chapters = len(chunks)
    
    brain.update_processing_log(total_chapters=total_chapters)
    
    console.print(f"Found {total_chapters} chapters/chunks to process")
    console.print()
    
    for i, (chunk_num, chunk_title, chunk_content) in enumerate(chunks):
        current_chapter_num = i + 1
        
        # 1. Skip if before start_from (Resume logic)
        # 2. Skip if not in allowed_chapters (Enrichment logic)
        
        if allowed_chapters:
            if current_chapter_num not in allowed_chapters:
                continue
        elif i < start_from:
            continue
            
        console.print(f"[bold]Chapter {current_chapter_num}/{total_chapters}: {chunk_title}[/bold]")
        
        # Execute Strategy (Expects ChapterState return now)
        chapter_state = strategy.process_chapter(
            chapter_content=chunk_content,
            chapter_title=chunk_title,
            chapter_num=current_chapter_num,
            brain=brain,
            client=client,
            objective=objective,
            fast_mode=fast_mode
        )
        
        # Update progress and log state
        log = brain.get_processing_log()
        
        # Update the chapter map
        log.chapter_map[str(current_chapter_num)] = chapter_state
        
        # Update counters (only if linear)
        if not allowed_chapters:
            log.chapters_processed = current_chapter_num
            log.last_processed_chapter = current_chapter_num
            
        # Write back to file
        brain.update_processing_log(
            chapter_map=log.chapter_map,
            chapters_processed=log.chapters_processed,
            last_processed_chapter=log.last_processed_chapter
        )
        
        console.print()
    
    # Final synthesis (only if objective provided)
    if objective:
        if fast_mode:
            console.print("[bold cyan]Running final synthesis...[/bold cyan]")
            final_synthesis(brain, client)
    else:
        console.print("[dim]Skipping synthesis (no objective provided). Brain built successfully.[/dim]")
    
    # Mark as complete ONLY if linear run finished
    if not allowed_chapters:
        brain.update_processing_log(status="complete")
    
    console.print(f"[bold green]Processing complete![/bold green]")
    console.print(f"Brain saved to: {brain.path}")
    console.print(f"Final response: {brain.path}/_response.md")
    
    return brain


def final_synthesis(brain: Brain, client) -> None:
    """
    Perform final synthesis using the complete knowledge base.
    This is used in fast mode after all extraction is complete.
    """
    system_prompt = get_system_prompt("synthesize")
    
    objective = brain.get_objective()
    brain_index = brain.get_index()
    
    # Get all knowledge files
    all_files = brain.list_files()
    knowledge_content = ""
    for file_path in all_files:
        if not file_path.startswith("meta/") and not file_path.startswith("_"):
            content = brain.read_file(file_path)
            if content:
                knowledge_content += f"\n## {file_path}\n{content}\n"
    
    # Truncate if too long (keep most recent/relevant)
    max_context = 100000  # Characters
    if len(knowledge_content) > max_context:
        knowledge_content = knowledge_content[-max_context:]
        console.print(f"  [dim]Context truncated to {max_context} chars[/dim]")
    
    user_prompt = f"""## User's Objective
{objective}

## Complete Knowledge Base
{brain_index}

{knowledge_content}

---

Based on ALL the information in the knowledge base, provide a comprehensive response to the user's objective.
"""

    console.print("  [dim]Generating final response...[/dim]")
    
    result = client.generate(
        response_model=ObjectiveSynthesis,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.5
    )
    
    # Update the response file
    response_content = f"""# Response to Objective

**Objective:** {objective}

**Status:** Complete
**Confidence:** {result.confidence.value}

---

{result.updated_response}

---

## Open Questions
"""
    for q in result.open_questions:
        response_content += f"- {q}\n"
    
    brain.update_response(response_content)
    console.print(f"  [dim]Confidence: {result.confidence.value}[/dim]")

