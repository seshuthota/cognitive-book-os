"""Query system - answer questions using the brain."""

from pathlib import Path
from rich.console import Console

from .brain import Brain
from .llm import LLMClient, get_client
from .models import FileSelection, QueryResult, Confidence
from .enrichment import EnrichmentManager
from .prompts import get_system_prompt

console = Console()

def query_brain(
    brain_name: str,
    question: str,
    provider: str = "anthropic",
    model: str | None = None,
    brains_dir: str = "brains",
    auto_enrich: bool = False
) -> str:
    """
    Answer a question using an existing brain.
    
    Args:
        brain_name: Name of the brain to query
        question: The question to answer
        provider: LLM provider
        model: Optional model override
        brains_dir: Directory containing brains
        auto_enrich: Whether to automatically scan skipped chapters if answer is unknown
        
    Returns:
        The answer string
    """
    brain = Brain(name=brain_name, base_path=brains_dir)
    
    if not brain.exists():
        console.print(f"[red]Brain '{brain_name}' not found![/red]")
        return ""
    
    client = get_client(provider=provider, model=model)
    
    console.print(f"[bold blue]Querying brain: {brain_name}[/bold blue]")
    console.print(f"Question: {question}")
    console.print()
    
    # Step 1: Select relevant files
    console.print("[dim]Selecting relevant files...[/dim]")
    selection = select_relevant_files(question, brain, client)
    
    console.print(f"[dim]Selected {len(selection.files)} files:[/dim]")
    for f in selection.files:
        console.print(f"  - {f}")
    console.print()

    if not selection.files and not auto_enrich:
        return "I couldn't find any relevant information in the brain."
        
    # Step 2: Generate answer
    result = None
    if selection.files:
        console.print("[dim]Generating answer...[/dim]")
        result = answer_from_brain(question, brain, selection.files, client)
    
    # Active Learning / Auto-Enrichment Loop
    # Trigger if no files found OR low confidence
    processed_enrichment = False
    
    current_confidence = result.confidence if result else Confidence.NONE
    if auto_enrich and current_confidence in [Confidence.LOW, Confidence.NONE]:
        console.print("[dim]Low confidence answer. Checking skipped chapters (Active Learning)...[/dim]")
        
        manager = EnrichmentManager(brain_name, brains_dir)
        should_enrich, chapters = manager.evaluate_gap(question, provider, model)
        
        if should_enrich:
            console.print(f"[bold yellow]Gap Detected![/bold yellow] The answer seems likely to be in {len(chapters)} skipped chapters.")
            
            # Cost Guardrail
            proceed = True
            if len(chapters) > 5:
                # If running non-interactively, this might hang or fail. 
                # Ideally CLI handles this, but logic is here.
                # using console.input works if attached to TTY.
                response = console.input(f"[bold red]Warning:[/bold red] Auto-enrichment targets {len(chapters)} chapters. Proceed? [y/N] ")
                if response.lower() != 'y':
                    proceed = False
            
            if proceed:
                console.print("[bold cyan]Triggering Auto-Enrichment...[/bold cyan]")
                manager.enrich(question, provider, model)
                processed_enrichment = True
                
                # Re-Index (implicit in file system) & Re-Select
                console.print("[bold blue]Retrying query with expanded knowledge base...[/bold blue]")
                selection = select_relevant_files(question, brain, client)
                if selection.files:
                    result = answer_from_brain(question, brain, selection.files, client)
        else:
             console.print("[dim]Gap Detector: Skipped chapters are unlikely to contain the answer.[/dim]")

    if result is None:
        return "I couldn't find any relevant information in the brain, even after checking skipped chapters."
        
    console.print()
    console.print("[bold]Answer:[/bold]")
    console.print(result.answer)
    console.print()
    console.print(f"[dim]Confidence: {result.confidence.value}[/dim]")
    console.print(f"[dim]Sources: {', '.join(result.sources)}[/dim]")
    
    return result.answer


def select_relevant_files(
    question: str,
    brain: Brain,
    client: LLMClient
) -> FileSelection:
    """
    Use LLM to select which brain files are relevant to the question.
    
    Args:
        question: The user's question
        brain: The brain to query
        client: LLM client
        
    Returns:
        FileSelection with relevant file paths
    """
    system_prompt = """You are a knowledge navigator. Given a question and a brain structure, 
select which files would be most relevant to answer the question.

Only select files that are likely to contain relevant information.
You can select up to 10 files."""

    brain_structure = brain.get_structure()
    all_files = brain.list_files()
    
    # Group files by directory for better context
    files_by_dir: dict[str, list[str]] = {}
    for f in all_files:
        dir_name = f.split("/")[0] if "/" in f else "root"
        if dir_name not in files_by_dir:
            files_by_dir[dir_name] = []
        files_by_dir[dir_name].append(f)
    
    file_list = ""
    for dir_name, files in sorted(files_by_dir.items()):
        file_list += f"\n### {dir_name}/\n"
        for f in files:
            file_list += f"- {f}\n"
    
    user_prompt = f"""## Question
{question}

## Available Files
{file_list}

Which files should I read to answer this question?
"""

    return client.generate(
        response_model=FileSelection,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.3
    )


def expand_selection_with_graph(
    brain: Brain,
    initial_files: list[str],
    max_depth: int = 1
) -> list[str]:
    """
    Expand the initial file selection by following 'related' links in the knowledge graph.
    
    Args:
        brain: The brain
        initial_files: List of file paths selected by the LLM
        max_depth: How many hops to follow (default 1 to prevent explosion)
        
    Returns:
        Expanded list of file paths (unique)
    """
    from .viz import extract_related_links  # Reuse parser
    
    expanded = set(initial_files)
    frontier = list(initial_files)
    
    for _ in range(max_depth):
        new_frontier = []
        for file_path in frontier:
            content = brain.read_file(file_path)
            if not content:
                continue
                
            # Extract links
            links = extract_related_links(content)
            
            # Resolve and add links
            # We need a way to resolve paths similar to viz.py if they are partial
            # But for now assume agent follows instruction to put full paths or relative valid paths
            all_files = brain.list_files()
            
            for link in links:
                # Basic resolution: check if exists, or check if matches stem
                if link in all_files:
                    if link not in expanded:
                        expanded.add(link)
                        new_frontier.append(link)
                else:
                    # Try to match partials
                    # (Simple linear scan for robustness)
                    for f in all_files:
                        if Path(f).name == Path(link).name or Path(f).stem == Path(link).stem:
                            if f not in expanded:
                                expanded.add(f)
                                new_frontier.append(f)
                            break
                            
        frontier = new_frontier
        if not frontier:
            break
            
    return sorted(list(expanded))


def answer_from_brain(
    question: str,
    brain: Brain,
    selected_files: list[str],
    client: LLMClient
) -> QueryResult:
    """
    Generate an answer using the selected brain files.
    
    Args:
        question: The user's question
        brain: The brain
        selected_files: Files to read
        client: LLM client
        
    Returns:
        QueryResult with the answer
    """
    # Expand selection using Knowledge Graph
    expanded_files = expand_selection_with_graph(brain, selected_files)
    
    if len(expanded_files) > len(selected_files):
        console.print(f"[dim]Graph expansion added {len(expanded_files) - len(selected_files)} related files[/dim]")
        
    system_prompt = get_system_prompt("query")
    
    # Read the selected files
    file_contents = ""
    for file_path in expanded_files:
        content = brain.read_file(file_path)
        if content:
            file_contents += f"\n### {file_path}\n{content}\n"
    
    # Also include the objective response for context
    response = brain.get_response()
    
    user_prompt = f"""## Question
{question}

## Relevant Knowledge Base Files
{file_contents}

## Original Objective Response (for context)
{response}

---

Please answer the question using the information from these files.
"""

    return client.generate(
        response_model=QueryResult,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.5
    )




def interactive_query(
    brain_name: str,
    provider: str = "anthropic",
    model: str | None = None,
    brains_dir: str = "brains"
) -> None:
    """
    Start an interactive query session with a brain.
    
    Args:
        brain_name: Name of the brain
        provider: LLM provider
        model: Optional model override
        brains_dir: Directory containing brains
    """
    brain = Brain(name=brain_name, base_path=brains_dir)
    
    if not brain.exists():
        console.print(f"[red]Brain '{brain_name}' not found![/red]")
        return
    
    client = get_client(provider=provider, model=model)
    
    console.print(f"[bold blue]Interactive Query Mode - Brain: {brain_name}[/bold blue]")
    console.print("Type 'quit' or 'exit' to end the session.")
    console.print("Type 'structure' to see the brain structure.")
    console.print()
    
    # Show the objective
    objective = brain.get_objective()
    console.print(f"[dim]Original objective: {objective}[/dim]")
    console.print()
    
    while True:
        try:
            question = console.input("[bold]Question:[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        
        if not question:
            continue
        
        if question.lower() in ("quit", "exit", "q"):
            break
        
        if question.lower() == "structure":
            console.print(brain.get_structure())
            console.print()
            continue
        
        # Select relevant files
        selection = select_relevant_files(question, brain, client)
        
        # Generate answer
        result = answer_from_brain(question, brain, selection.files, client)
        
        console.print()
        console.print(result.answer)
        console.print()
        console.print(f"[dim]Sources: {', '.join(result.sources)}[/dim]")
        console.print()
    
    console.print("[dim]Session ended.[/dim]")
