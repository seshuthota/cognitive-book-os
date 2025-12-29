"""Benchmark script for Cognitive Book OS (Golden Test).

Runs ingestion on a sample book and evaluates retrieval quality against ground truth questions.
"""

import typer
from rich.console import Console
from rich.table import Table
from pathlib import Path
import json

from cognitive_book_os.ingest import process_document
from cognitive_book_os.query import query_brain
from cognitive_book_os.llm import get_client
from cognitive_book_os.brain import Brain

app = typer.Typer()
console = Console()

# Ground Truth Data for "Chains of the Sea" (Introduction/First few chapters)
GROUND_TRUTH = [
    {
        "question": "What happens to the alien ships when the military fires on them?",
        "answer": "They do not react initially. Later, they open or dissolve, revealing the aliens/landing, but they are impervious to conventional weapons.",
        "type": "fact"
    },
    {
        "question": "Who is Tommy Nolan talking to in the woods?",
        "answer": "He is talking to the 'Other People' or aliens (Thants), and possibly an AI/machine intelligence.",
        "type": "multi-hop"
    },
    {
        "question": "What is the 'time anomaly' or 'variable time' mentioned?",
        "answer": "There is a discrepancy in time measurements between the alien ship's vicinity and the outside world (Time Dilation).",
        "type": "concept"
    }
]

def evaluate_answer(client, question: str, actual: str, expected: str) -> int:
    """Score the answer from 0 to 2 using LLM-as-a-Judge."""
    prompt = f"""You are an evaluator. Compare the Actual Answer to the Expected Answer.

Question: {question}

Expected Answer: {expected}

Actual Answer: {actual}

Score:
0: Wrong or "I don't know".
1: Partially correct but missing key details.
2: Correct and comprehensive.

Return ONLY the digit (0, 1, or 2).
"""
    try:
        response = client.generate_text(
            system_prompt="You are an impartial evaluator.",
            user_prompt=prompt
        )
        console.print(f"[dim]Evaluator Raw: {response}[/dim]")
        # Extract digit
        import re
        match = re.search(r"\b([0-2])\b", response)
        if match:
            return int(match.group(1))
        return 0
    except Exception as e:
        console.print(f"[red]Evaluator Error: {e}[/red]")
        return 0

@app.command()
def run(
    book: str = "books/Chains of the Sea.pdf",
    brain_name: str = "benchmark_brain",
    provider: str = "anthropic"
):
    """Run the benchmark."""
    console.print(f"[bold blue]Running Golden Test Benchmark[/bold blue]")
    console.print(f"Book: {book}")
    console.print(f"Brain: {brain_name}")
    
    # 1. Ingest (Fast Mode, Standard Strategy)
    # console.print("\n[bold]Step 1: Ingestion[/bold]")
    # process_document(
    #     document_path=book,
    #     brain_name=brain_name,
    #     objective="Comprehensive extraction for benchmark",
    #     provider=provider,
    #     fast_mode=True,
    #     strategy_name="standard"
    # )
    # assume brain exists for this test to save time, or uncomment above
    
    brain = Brain(name=brain_name)
    if not brain.exists():
        console.print("[yellow]Brain not found, running ingestion...[/yellow]")
        process_document(
            document_path=book,
            brain_name=brain_name,
            objective="Comprehensive extraction for benchmark",
            provider=provider,
            fast_mode=True,
            strategy_name="standard"
        )
    
    # 2. Evaluate
    console.print("\n[bold]Step 2: Evaluation[/bold]")
    client = get_client(provider=provider) # Use same provider for evaluation
    
    table = Table(title="Benchmark Results")
    table.add_column("Question", max_width=40)
    table.add_column("Score", style="magenta")
    table.add_column("Type", style="cyan")
    
    total_score = 0
    results = []
    
    for item in GROUND_TRUTH:
        q = item["question"]
        console.print(f"Asking: {q}")
        
        answer = query_brain(brain_name=brain_name, question=q, provider=provider)
        
        score = evaluate_answer(client, q, answer, item["answer"])
        console.print(f"-> Score: {score}/2")
        
        table.add_row(q, str(score), item["type"])
        total_score += score
        results.append({"q": q, "score": score, "answer": answer})
        
    console.print(table)
    
    avg_score = total_score / len(GROUND_TRUTH)
    console.print(f"\n[bold]Average Score: {avg_score:.2f} / 2.0[/bold]")
    
    if avg_score >= 1.5:
        console.print("[bold green]PASSED[/bold green]")
    else:
        console.print("[bold red]FAILED[/bold red]")

if __name__ == "__main__":
    app()
