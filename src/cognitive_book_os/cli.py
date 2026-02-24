"""CLI for Cognitive Book OS."""

import json
import os
import typer
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv

from .brain import Brain
from .claim_store import ClaimStore, claims_versioning_enabled
from .ingest import process_document, final_synthesis
from .llm import get_client
from .models import ClaimStatus
from .orchestration import (
    BrainNotFoundError,
    MultiBrainInputError,
    multi_brain_query_enabled,
    orchestrate_multi_brain_query,
)
from .query import (
    answer_from_brain_with_audit,
    interactive_query,
    query_brain,
    select_relevant_files,
)
from .gardener import optimize_brain
from .viz import generate_graph

load_dotenv()

app = typer.Typer(
    name="cognitive-book-os",
    help="A structured knowledge extraction system for documents.",
    add_completion=False
)
claims_app = typer.Typer(help="Inspect claim-level audit metadata.")
gardener_app = typer.Typer(help="Operate scheduled gardener maintenance.")
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


def _api_base_url(override: Optional[str] = None) -> str:
    raw = override or os.getenv("BOOKOS_API_URL", "http://127.0.0.1:8000")
    return raw.rstrip("/")


def _api_request(method: str, path: str, payload: Optional[dict] = None, api_url: Optional[str] = None) -> dict:
    base = _api_base_url(api_url)
    url = f"{base}{path}"
    body = None
    headers = {"accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers["content-type"] = "application/json"

    req = Request(url=url, method=method.upper(), data=body, headers=headers)
    try:
        with urlopen(req, timeout=60) as response:
            content = response.read().decode("utf-8")
            return json.loads(content) if content else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        message = detail.strip() or f"HTTP {exc.code}"
        raise RuntimeError(message) from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach API at {base}: {exc.reason}") from exc


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


@app.command(name="query-trace")
def query_trace(
    brain: str = typer.Argument(..., help="Name of the brain to query"),
    question: str = typer.Option(..., "--question", "-q", help="Question to answer with claim trace"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use"),
):
    """
    Query a brain and print claim-level traceability details.
    """
    if not claims_versioning_enabled():
        console.print("[yellow]Claim versioning is disabled. Set ENABLE_CLAIM_VERSIONING=1.[/yellow]")
        raise typer.Exit(1)

    b = Brain(name=brain)
    if not b.exists():
        console.print(f"[red]Brain '{brain}' not found![/red]")
        raise typer.Exit(1)

    actual_provider = provider or auto_detect_provider()
    client = get_client(provider=actual_provider, model=model)
    selection = select_relevant_files(question, b, client)

    if not selection.files:
        console.print("[yellow]No relevant files were selected for this question.[/yellow]")
        return

    audit = answer_from_brain_with_audit(
        question=question,
        brain=b,
        selected_files=selection.files,
        client=client,
    )

    console.print()
    console.print("[bold]Answer:[/bold]")
    console.print(audit.answer)
    console.print()
    console.print(f"[dim]Confidence: {audit.confidence.value}[/dim]")
    console.print(f"[dim]Trace completeness: {audit.trace_completeness.completeness_ratio:.2%}[/dim]")
    console.print(f"[dim]Query Run ID: {audit.query_run_id}[/dim]")

    table = Table(title="Claim Trace")
    table.add_column("Claim ID", style="cyan")
    table.add_column("File", style="green")
    table.add_column("Claim", max_width=50)
    table.add_column("Source", style="dim")

    for item in audit.claim_trace:
        table.add_row(
            item.claim_id,
            item.file_path,
            item.claim_text,
            item.source_locator,
        )
    console.print(table)


@app.command(name="multi-query")
def multi_query(
    brains: str = typer.Option(..., "--brains", help="Comma-separated brain names"),
    question: str = typer.Option(..., "--question", "-q", help="Question to ask across brains"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use"),
    max_brains: int = typer.Option(5, "--max-brains", help="Maximum brains to include"),
    max_files_per_brain: int = typer.Option(12, "--max-files-per-brain", help="Max files per brain"),
    include_claim_trace: bool = typer.Option(True, "--include-claim-trace/--no-claim-trace", help="Include claim traces in output"),
    include_conflicts: bool = typer.Option(True, "--include-conflicts/--no-conflicts", help="Run conflict classification"),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output"),
):
    """
    Query multiple brains and return a unified answer with conflicts.
    """
    if not multi_brain_query_enabled():
        console.print("[yellow]Multi-brain query is disabled. Set ENABLE_MULTI_BRAIN_QUERY=1.[/yellow]")
        raise typer.Exit(1)

    brain_names = [part.strip() for part in brains.split(",") if part.strip()]
    if not brain_names:
        console.print("[red]No brain names provided in --brains.[/red]")
        raise typer.Exit(1)

    actual_provider = provider or auto_detect_provider()

    try:
        result = orchestrate_multi_brain_query(
            question=question,
            brain_names=brain_names,
            provider=actual_provider,
            model=model,
            include_claim_trace=include_claim_trace,
            include_conflicts=include_conflicts,
            max_brains=max(1, max_brains),
            max_files_per_brain=max(1, max_files_per_brain),
            brains_dir="brains",
        )
    except BrainNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    except MultiBrainInputError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if json_output:
        console.print_json(json.dumps(result.model_dump(), ensure_ascii=True))
        return

    console.print("[bold blue]Unified Answer[/bold blue]")
    console.print(result.answer)
    console.print()
    console.print(f"[dim]Confidence: {result.confidence.value}[/dim]")
    console.print(f"[dim]Run ID: {result.query_run_id}[/dim]")
    console.print(
        f"[dim]Traceability: {result.traceability.overall_completeness_ratio:.2%} "
        f"(claims: {result.traceability.brains_with_claims}, degraded: {result.traceability.brains_without_claims})[/dim]"
    )

    if result.warnings:
        console.print()
        for warning in result.warnings:
            console.print(f"[yellow]- {warning}[/yellow]")

    sections = Table(title="Per-Brain Sections")
    sections.add_column("Brain", style="cyan")
    sections.add_column("Confidence")
    sections.add_column("Sources", justify="right")
    sections.add_column("Trace")
    sections.add_column("Excerpt", max_width=56)
    for item in result.per_brain:
        sections.add_row(
            item.brain_name,
            item.confidence.value,
            str(len(item.sources)),
            "degraded" if item.trace_degraded else f"{item.trace_completeness_ratio:.2%}",
            item.answer_excerpt,
        )
    console.print()
    console.print(sections)

    if include_conflicts:
        conflict_table = Table(title="Conflict Analysis")
        conflict_table.add_column("Topic", max_width=44)
        conflict_table.add_column("Brains", style="cyan")
        conflict_table.add_column("Class")
        conflict_table.add_column("Evidence", max_width=44)

        if not result.conflicts:
            conflict_table.add_row("None detected", "-", "-", "-")
        else:
            for item in result.conflicts:
                conflict_table.add_row(
                    item.topic,
                    ", ".join(item.brains_involved),
                    item.classification,
                    ", ".join(item.evidence),
                )
        console.print()
        console.print(conflict_table)


@claims_app.command("list")
def claims_list(
    brain: str = typer.Argument(..., help="Name of the brain"),
    file: Optional[str] = typer.Option(None, "--file", help="Filter by file path"),
    status: str = typer.Option("active", "--status", help="Filter by status: active|superseded|deleted"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Filter by tag"),
    search: Optional[str] = typer.Option(None, "--search", help="Text search"),
    limit: int = typer.Option(50, "--limit", help="Maximum number of claims"),
):
    """
    List claims tracked for a brain.
    """
    if not claims_versioning_enabled():
        console.print("[yellow]Claim versioning is disabled. Set ENABLE_CLAIM_VERSIONING=1.[/yellow]")
        raise typer.Exit(1)

    b = Brain(name=brain)
    if not b.exists():
        console.print(f"[red]Brain '{brain}' not found![/red]")
        raise typer.Exit(1)

    try:
        parsed_status = ClaimStatus(status)
    except ValueError:
        console.print("[red]Invalid status. Use active, superseded, or deleted.[/red]")
        raise typer.Exit(1)

    store = ClaimStore(b)
    claims = store.list_claims(
        file_path=file,
        status=parsed_status,
        tag=tag,
        q=search,
        limit=limit,
        offset=0,
    )

    if not claims:
        console.print("[yellow]No claims found for the given filters.[/yellow]")
        return

    table = Table(title=f"Claims ({len(claims)})")
    table.add_column("Claim ID", style="cyan")
    table.add_column("File", style="green")
    table.add_column("Status")
    table.add_column("Claim", max_width=60)

    for claim in claims:
        table.add_row(
            claim.claim_id,
            claim.file_path,
            claim.status.value,
            claim.claim_text,
        )
    console.print(table)


@claims_app.command("show")
def claims_show(
    brain: str = typer.Argument(..., help="Name of the brain"),
    claim_id: str = typer.Argument(..., help="Claim ID"),
):
    """
    Show latest claim snapshot details.
    """
    if not claims_versioning_enabled():
        console.print("[yellow]Claim versioning is disabled. Set ENABLE_CLAIM_VERSIONING=1.[/yellow]")
        raise typer.Exit(1)

    b = Brain(name=brain)
    if not b.exists():
        console.print(f"[red]Brain '{brain}' not found![/red]")
        raise typer.Exit(1)

    store = ClaimStore(b)
    claim = store.get_claim(claim_id)
    if not claim:
        console.print(f"[red]Claim not found: {claim_id}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Claim ID:[/bold] {claim.claim_id}")
    console.print(f"[bold]File:[/bold] {claim.file_path}")
    console.print(f"[bold]Status:[/bold] {claim.status.value}")
    console.print(f"[bold]Claim:[/bold] {claim.claim_text}")
    console.print(f"[bold]Evidence:[/bold] {claim.evidence_quote or '(missing)'}")
    console.print(f"[bold]Source:[/bold] {claim.source_locator}")
    console.print(f"[bold]Created:[/bold] {claim.created_at} ({claim.created_by_run})")
    console.print(f"[bold]Updated:[/bold] {claim.updated_at} ({claim.updated_by_run})")


@claims_app.command("history")
def claims_history(
    brain: str = typer.Argument(..., help="Name of the brain"),
    claim_id: str = typer.Argument(..., help="Claim ID"),
):
    """
    Show lifecycle event history for a claim.
    """
    if not claims_versioning_enabled():
        console.print("[yellow]Claim versioning is disabled. Set ENABLE_CLAIM_VERSIONING=1.[/yellow]")
        raise typer.Exit(1)

    b = Brain(name=brain)
    if not b.exists():
        console.print(f"[red]Brain '{brain}' not found![/red]")
        raise typer.Exit(1)

    store = ClaimStore(b)
    history = store.get_claim_history(claim_id)
    if not history:
        console.print(f"[yellow]No history found for {claim_id}.[/yellow]")
        return

    table = Table(title=f"Claim History: {claim_id}")
    table.add_column("Timestamp", style="dim")
    table.add_column("Event")
    table.add_column("Run ID", style="cyan")

    for event in history:
        table.add_row(event.timestamp, event.event_type, event.run_id)
    console.print(table)


app.add_typer(claims_app, name="claims")


@gardener_app.command("status")
def gardener_status(
    api_url: Optional[str] = typer.Option(None, "--api-url", help="Server base URL (default: BOOKOS_API_URL or http://127.0.0.1:8000)"),
):
    """
    Show gardener scheduler state and defaults.
    """
    try:
        payload = _api_request("GET", "/gardener/status", api_url=api_url)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    defaults = payload.get("defaults", {})
    scheduler = payload.get("scheduler", {})

    console.print(f"[bold]Enabled:[/bold] {payload.get('enabled', False)}")
    console.print(f"[bold]Active Run:[/bold] {payload.get('active_run_id') or 'none'}")
    console.print(f"[bold]Interval:[/bold] {defaults.get('interval', 'weekly')} ({scheduler.get('interval_seconds', 0)}s)")
    console.print(f"[bold]Default Mode:[/bold] {'dry_run' if defaults.get('dry_run', True) else 'apply'}")
    console.print(f"[bold]Excluded Brains:[/bold] {', '.join(defaults.get('exclude_brains', [])) or 'none'}")
    console.print(f"[bold]Provider:[/bold] {defaults.get('provider', '')}")
    console.print(f"[bold]Model:[/bold] {defaults.get('model') or '(provider default)'}")
    console.print(f"[bold]Scheduler Running:[/bold] {scheduler.get('running', False)}")
    console.print(f"[bold]Next Run:[/bold] {scheduler.get('next_run_at') or 'n/a'}")
    if scheduler.get("last_error"):
        console.print(f"[yellow]Last scheduler error: {scheduler['last_error']}[/yellow]")


@gardener_app.command("trigger")
def gardener_trigger(
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="Run in dry-run mode or apply merges."),
    brain: Optional[list[str]] = typer.Option(None, "--brain", help="Optional brain to target (repeat flag)."),
    async_run: bool = typer.Option(True, "--async/--sync", help="Run asynchronously or wait for completion."),
    api_url: Optional[str] = typer.Option(None, "--api-url", help="Server base URL"),
):
    """
    Trigger an immediate gardener run.
    """
    payload = {
        "dry_run": dry_run,
        "brain_ids": brain or None,
        "async_run": async_run,
    }
    try:
        response = _api_request("POST", "/gardener/trigger", payload=payload, api_url=api_url)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Run {response.get('run_id', '')} {response.get('status', '')}.[/green]")
    console.print(f"Mode: {response.get('mode', 'dry_run')}")
    console.print(f"Brains: {', '.join(response.get('brains', [])) or 'none'}")


@gardener_app.command("history")
def gardener_history(
    limit: int = typer.Option(20, "--limit", min=1, max=200, help="Number of recent runs to show."),
    api_url: Optional[str] = typer.Option(None, "--api-url", help="Server base URL"),
):
    """
    Show recent gardener run history.
    """
    try:
        payload = _api_request("GET", f"/gardener/history?limit={limit}", api_url=api_url)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    runs = payload.get("runs", [])
    if not runs:
        console.print("[yellow]No gardener runs found.[/yellow]")
        return

    table = Table(title=f"Gardener History ({len(runs)})")
    table.add_column("Run ID", style="cyan")
    table.add_column("Status")
    table.add_column("Mode")
    table.add_column("Brains", justify="right")
    table.add_column("Started", style="dim")

    for item in runs:
        table.add_row(
            item.get("run_id", ""),
            item.get("status", ""),
            item.get("mode", ""),
            str(item.get("brains_total", 0)),
            item.get("started_at", ""),
        )
    console.print(table)


app.add_typer(gardener_app, name="gardener")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
