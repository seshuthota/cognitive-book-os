"""CLI for Cognitive Book OS."""

import os
import typer
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv

from .brain import Brain
from .ingest import process_document, final_synthesis
from .query import query_brain, interactive_query
from .gardener import optimize_brain
from .viz import generate_graph

load_dotenv()

app = typer.Typer(
    name="cognitive-book-os",
    help="A structured knowledge extraction system for documents.",
    add_completion=False
)
console = Console()


def auto_detect_provider() -> str:
    """Auto-detect the best available provider based on API keys."""
    # Check providers in order of preference
    if os.getenv("MINIMAX_API_KEY"):
        return "minimax"
    elif os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    elif os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    elif os.getenv("OPENAI_API_KEY"):
        return "openai"
    else:
        console.print("[yellow]Warning: No API keys found. Set MINIMAX_API_KEY, OPENROUTER_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY[/yellow]")
        return "openrouter"


@app.command()
def ingest(
    book: Path = typer.Argument(..., help="Path to the PDF document"),
    objective: Optional[str] = typer.Option(None, "--objective", "-o", help="Your objective/question (optional - defaults to general ingestion)"),
    brain: str = typer.Option(..., "--brain", "-b", help="Name for the brain (knowledge base)"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider (auto-detects from API keys, or specify: openai, anthropic, openrouter, minimax)"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use (defaults to provider's best)"),
    fast: bool = typer.Option(False, "--fast", "-f", help="Fast mode: skip per-chapter synthesis, only at end (~50% fewer calls)"),
    strategy: str = typer.Option("standard", "--strategy", "-s", help="Ingestion strategy: 'standard' or 'triage'")
):
    """
    Process a document and build a knowledge base.
    
    Example:
        python -m cognitive_book_os ingest book.pdf -o "How does Elon think?" -b elon
        python -m cognitive_book_os ingest book.pdf -o "..." -b name --fast  # Faster
    """
    if not book.exists():
        console.print(f"[red]File not found: {book}[/red]")
        raise typer.Exit(1)
    
    if not book.suffix.lower() == ".pdf":
        console.print(f"[yellow]Warning: Expected PDF file, got {book.suffix}[/yellow]")
    
    # Auto-detect provider if not specified
    actual_provider = provider or auto_detect_provider()
    
    process_document(
        document_path=book,
        objective=objective,
        brain_name=brain,
        provider=actual_provider,
        model=model,
        fast_mode=fast,
        strategy_name=strategy
    )


@app.command()
def query(
    brain: str = typer.Argument(..., help="Name of the brain to query"),
    question: str = typer.Option(None, "--question", "-q", help="Question to answer (omit for interactive mode)"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider (auto-detects from API keys, or specify: openai, anthropic, openrouter)"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use"),
    auto_enrich: bool = typer.Option(False, "--auto-enrich", help="Automatically enrich brain if answer is unknown")
):
    """
    Ask questions against an existing brain.
    
    Example:
        python -m cognitive_book_os query elon -q "What was SpaceX's first success?"
        python -m cognitive_book_os query elon  # Interactive mode
    """
    # Auto-detect provider if not specified
    actual_provider = provider or auto_detect_provider()
    
    if question:
        query_brain(
            brain_name=brain,
            question=question,
            provider=actual_provider,
            model=model,
            auto_enrich=auto_enrich
        )
    else:
        interactive_query(
            brain_name=brain,
            provider=actual_provider,
            model=model
        )


@app.command()
def synthesize(
    brain: str = typer.Argument(..., help="Name of the brain to synthesize"),
    objective: str = typer.Option(..., "--objective", "-o", help="The objective/question to synthesize an answer for"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use")
):
    """
    Generate a synthesis/response for a specific objective using an existing brain.
    """
    b = Brain(name=brain)
    
    if not b.exists():
        console.print(f"[red]Brain '{brain}' not found![/red]")
        raise typer.Exit(1)
        
    # Update objective in brain if it was generic or different
    b.write_file("_objective.md", f"# Objective\n\n{objective}\n")
    
    # Auto-detect provider if not specified
    actual_provider = provider or auto_detect_provider()
    
    from .llm import get_client
    client = get_client(provider=actual_provider, model=model)
    
    console.print(f"[bold blue]Synthesizing Response[/bold blue]")
    console.print(f"Brain: {brain}")
    console.print(f"Objective: {objective}")
    console.print()
    
    final_synthesis(b, client)
    
    console.print(f"[green]Synthesis complete![/green]")
    console.print(f"Response saved to: {b.path}/_response.md")


@app.command(name="list")
def list_brains():
    """
    List all available brains.
    """
    brains_dir = Path("brains")
    
    if not brains_dir.exists():
        console.print("[yellow]No brains directory found.[/yellow]")
        return
    
    brains = [d for d in brains_dir.iterdir() if d.is_dir()]
    
    if not brains:
        console.print("[yellow]No brains found.[/yellow]")
        return
    
    table = Table(title="Available Brains")
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Chapters", justify="right")
    table.add_column("Objective", max_width=50)
    
    for brain_dir in sorted(brains):
        brain = Brain(name=brain_dir.name)
        if brain.exists():
            log = brain.get_processing_log()
            objective = brain.get_objective()[:50] + "..." if len(brain.get_objective()) > 50 else brain.get_objective()
            
            chapters = f"{log.chapters_processed}"
            if log.total_chapters:
                chapters += f"/{log.total_chapters}"
            
            table.add_row(
                brain.name,
                log.status,
                chapters,
                objective
            )
    
    console.print(table)


@app.command()
def inspect(
    brain: str = typer.Argument(..., help="Name of the brain to inspect")
):
    """
    View the structure of a brain.
    """
    b = Brain(name=brain)
    
    if not b.exists():
        console.print(f"[red]Brain '{brain}' not found![/red]")
        raise typer.Exit(1)
    
    console.print(b.get_structure())
    console.print()
    
    # Show objective
    console.print("[bold]Objective:[/bold]")
    console.print(b.get_objective())
    console.print()
    
    # Show processing status
    log = b.get_processing_log()
    console.print(f"[bold]Status:[/bold] {log.status}")
    console.print(f"[bold]Chapters:[/bold] {log.chapters_processed}/{log.total_chapters or '?'}")


@app.command()
def response(
    brain: str = typer.Argument(..., help="Name of the brain")
):
    """
    View the current response to the objective.
    """
    b = Brain(name=brain)
    
    if not b.exists():
        console.print(f"[red]Brain '{brain}' not found![/red]")
        raise typer.Exit(1)
    
    console.print(b.get_response())


@app.command()
def optimize(
    brain: str = typer.Argument(..., help="Name of the brain to optimize"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider")
):
    """
    Optimize a brain by merging duplicate files and cleaning up entropy.
    """
    actual_provider = provider or auto_detect_provider()
    optimize_brain(brain, provider=actual_provider)


@app.command()
def viz(
    brain: str = typer.Argument(..., help="Name of the brain to visualize"),
    output: str = typer.Option("graph.html", "--output", "-o", help="Output HTML file name")
):
    """
    Generate an interactive visualization of the brain's knowledge graph.
    """
    generate_graph(brain, output_file=output)



@app.command()
def enrich(
    brain: str = typer.Argument(..., help="Name of the brain to enrich"),
    objective: str = typer.Option(..., "--objective", "-o", help="New objective to scan for"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use")
):
    """
    Enrich an existing brain by scanning skipped chapters for a new objective.
    """
    actual_provider = provider or auto_detect_provider()
    from .enrichment import EnrichmentManager
    
    manager = EnrichmentManager(brain_name=brain)
    manager.enrich(new_objective=objective, provider=actual_provider, model=model)


@app.command()
def verify(
    brain: str = typer.Argument(..., help="Name of the brain to verify against"),
    claim: str = typer.Option(..., "--claim", "-c", help="The claim or hypothesis to value-test"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use")
):
    """
    Verify a claim or hypothesis using dual-pass evidence search (Pro vs Con).
    """
    actual_provider = provider or auto_detect_provider()
    from .verify import verify_claim
    
    verify_claim(
        brain_name=brain,
        claim=claim,
        provider=actual_provider,
        model=model,
        brains_dir="brains"
    )



@app.command()
def summary(
    brain: str = typer.Argument(..., help="Name of the brain"),
    topic: str = typer.Option("characters", "--topic", "-t", help="Topic to summarize (characters, themes, etc.)")
):
    """
    Generate a lightweight map/summary of a topic directory.
    """
    from .summary import summarize_topic
    summarize_topic(brain_name=brain, topic=topic, brains_dir="brains")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
