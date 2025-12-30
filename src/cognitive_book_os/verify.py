"""Verification system - test hypotheses against the brain."""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .brain import Brain
from .llm import LLMClient, get_client
from .models import VerificationResult, Evidence
from .query import select_relevant_files

console = Console()

def verify_claim(
    brain_name: str,
    claim: str,
    provider: str = "anthropic",
    model: str | None = None,
    brains_dir: str = "brains"
) -> None:
    """
    Verify a claim against the brain using a dual-pass search (Pro vs Con).
    
    Args:
        brain_name: Name of the brain
        claim: The hypothesis/claim to test
        provider: LLM provider
        model: Optional model override
        brains_dir: Directory containing brains
    """
    brain = Brain(name=brain_name, base_path=brains_dir)
    
    if not brain.exists():
        console.print(f"[red]Brain '{brain_name}' not found![/red]")
        return
    
    client = get_client(provider=provider, model=model)
    
    console.print(f"[bold blue]Testing Hypothesis against Brain: {brain_name}[/bold blue]")
    console.print(Panel(f"[bold]{claim}[/bold]", title="Claim/Hypothesis"))
    console.print()
    
    # Pass 1: Supporting Evidence
    console.print("[dim]Pass 1: Hunting for SUPPORTING evidence...[/dim]")
    support_query = f"Find evidence that SUPPORTS the claim: '{claim}'"
    support_files = select_relevant_files(support_query, brain, client).files
    
    # Pass 2: Conflicting Evidence
    console.print("[dim]Pass 2: Hunting for CONFLICTING evidence...[/dim]")
    refute_query = f"Find evidence that REFUTES or CONTRADICTS the claim: '{claim}'"
    refute_files = select_relevant_files(refute_query, brain, client).files
    
    # Combine unique files
    all_files = sorted(list(set(support_files + refute_files)))
    
    if not all_files:
        console.print("[yellow]No relevant files found for either side of the argument.[/yellow]")
        return

    console.print(f"[dim]Analyzing {len(all_files)} unique files...[/dim]")
    
    # Read content
    context = ""
    for f in all_files:
        content = brain.read_file(f)
        if content:
            context += f"\n### File: {f}\n{content}\n"
            
    # Synthesis
    system_prompt = """You are a rigorous Fact-Checker and Analyst.
Your job is to verify a specific User Claim against the provided Evidence Context.

## Rules
1. **Be Neutral**: Look objectively at the evidence.
2. **Quote Everything**: Every piece of evidence MUST have a direct quote from the text.
3. **Check User Notes**: If a file is in `notes/`, it overrides the book content.
4. **Verdict**:
   - `Confirmed`: The evidence overwhelmingly supports the claim.
   - `Refuted`: The evidence explicitly contradicts the claim.
   - `Ambiguous`: There is conflicting evidence or insufficient data.
   - `Unverified`: No relevant evidence found.
"""

    user_prompt = f"""## Claim to Verify
"{claim}"

## Evidence Context
{context}

---

Analyze the evidence. List supporting points, conflicting points, and provide a final verdict.
"""

    result = client.generate(
        response_model=VerificationResult,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.0 # Strict analysis
    )
    
    # Display Results
    console.print()
    if result.verdict == "Confirmed":
        color = "green"
    elif result.verdict == "Refuted":
        color = "red"
    else:
        color = "yellow"
        
    console.print(f"[bold {color}]Verdict: {result.verdict}[/bold {color}]")
    console.print(f"[italic]{result.reasoning}[/italic]")
    console.print()
    
    # Evidence Table
    table = Table(title="Evidence Analysis", show_lines=True)
    table.add_column("Type", style="bold")
    table.add_column("Evidence & Context")
    table.add_column("Source", style="dim")
    
    for point in result.supporting_points:
        table.add_row(
            "[green]Support[/green]",
            point,
            "-"
        )
        
    for point in result.conflicting_points:
        table.add_row(
            "[red]Refute[/red]",
            point,
            "-"
        )
        
    if not result.supporting_points and not result.conflicting_points:
        table.add_row("None", "No direct evidence found.", "-")
        
    console.print(table)
