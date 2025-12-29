"""The Gardener: Entropy Management Agent.

Responsible for cleaning, merging, and organizing the knowledge base to prevent
fragmentation and duplication.
"""

from pathlib import Path
from rich.console import Console
from difflib import SequenceMatcher
from pydantic import BaseModel, Field

from .brain import Brain
from .llm import LLMClient, get_client

console = Console()

class MergeDecision(BaseModel):
    """Decision on how to merge files."""
    should_merge: bool = Field(..., description="Whether these files should actually be merged.")
    target_filename: str = Field(..., description="The best filename for the merged content (e.g., 'steve_jobs.md').")
    reasoning: str = Field(..., description="Why should they be merged (or not)?")

class MergedContent(BaseModel):
    """The result of the merge operation."""
    content: str = Field(..., description="The comprehensive merged markdown content.")
    summary: str = Field(..., description="Brief summary of what was merged.")


def detect_duplicates(brain: Brain, threshold: float = 0.8) -> dict[str, list[str]]:
    """
    Detect potential duplicates based on filename similarity.
    
    Args:
        brain: The brain to inspect
        threshold: Similarity threshold (0.0 to 1.0)
        
    Returns:
        Dict mapping generic/shorter names to list of similar files
        Example: {'steve.md': ['steve_jobs.md', 'steve_wozniak.md']}
    """
    files = brain.list_files()
    
    # Filter for content directories only
    content_files = [
        f for f in files 
        if f.startswith(("characters/", "themes/", "locations/")) 
        and f.endswith(".md")
    ]
    
    clusters = {}
    processed = set()
    
    for i, f1 in enumerate(content_files):
        if f1 in processed:
            continue
            
        name1 = Path(f1).stem.lower().replace("_", " ")
        cluster = [f1]
        
        for f2 in content_files[i+1:]:
            if f2 in processed:
                continue
            
            # Don't compare across directories
            if Path(f1).parent != Path(f2).parent:
                continue
                
            name2 = Path(f2).stem.lower().replace("_", " ")
            
            # Check string similarity
            ratio = SequenceMatcher(None, name1, name2).ratio()
            
            # Special case: Substring match (e.g., "AI" vs "Alien AI")
            is_substring = (name1 in name2 or name2 in name1) and len(min(name1, name2)) > 3
            
            if ratio > threshold or is_substring:
                cluster.append(f2)
                processed.add(f2)
        
        if len(cluster) > 1:
            clusters[f1] = cluster
            processed.add(f1)
            
    return clusters


def merge_cluster(
    brain: Brain, 
    cluster: list[str], 
    client: LLMClient
) -> bool:
    """
    Merge a cluster of files into one.
    
    Args:
        brain: The brain
        cluster: List of relative file paths to merge
        client: LLM client
        
    Returns:
        True if merged, False if skipped
    """
    console.print(f"[bold]Analyzing cluster:[/bold] {cluster}")
    
    # 1. Read all content
    contents = {}
    for f in cluster:
        text = brain.read_file(f)
        if text:
            contents[f] = text
            
    if len(contents) < 2:
        console.print("[yellow]Skipping: Less than 2 readable files.[/yellow]")
        return False
        
    file_list = "\n".join(f"- {f}" for f in cluster)
    content_list = "\n".join(f"--- {f} ---\n{text[:200]}..." for f, text in contents.items())
    
    # 2. Ask LLM if they should be merged
    decision_prompt = f"""You are a knowledge base librarian. 
We have detected similar filenames that might refer to the same entity.

Files:
{file_list}

Content Previews:
{content_list}

Should these be merged into a single file? 
- YES if they refer to the SAME entity (e.g. "Steve" and "Steve Jobs"). 
- NO if they are distinct (e.g. "Steve Jobs" and "Steve Wozniak").

If YES, pick the best canonical filename (e.g. "steve_jobs.md").
"""
    try:
        decision = client.generate(
            response_model=MergeDecision,
            system_prompt="You are a librarian managing a knowledge base.",
            user_prompt=decision_prompt,
            temperature=0.0
        )
    except Exception as e:
        console.print(f"[red]Error deciding merge: {e}[/red]")
        return False
        
    if not decision.should_merge:
        console.print(f"[yellow]Skipping:[/yellow] {decision.reasoning}")
        return False
        
    console.print(f"[green]Merging into:[/green] {decision.target_filename}")
    console.print(f"[dim]Reason: {decision.reasoning}[/dim]")
    
    files_content = "\n".join(f"### {f}\n{text}\n" for f, text in contents.items())

    # 3. Perform Merge
    merge_prompt = f"""Merge the following markdown files into a single comprehensive profile for '{decision.target_filename}'.

Files to Merge:
{chr(10).join(cluster)}

---
{files_content}
---

## Instructions
1. Combine all information into a single structured markdown file.
2. PRESERVE detailed facts, quotes, and observations.
3. PRESERVE the `source` frontmatter: combine them into a list if multiple sources exist (e.g. `source: [chapter_1, chapter_5]`).
4. PRESERVE `tags`: allow unique tags from all files.
5. Create a clean narrative structure.
"""
    
    merged_result = client.generate(
        response_model=MergedContent,
        system_prompt="You are an expert editor merging knowledge base files.",
        user_prompt=merge_prompt,
        temperature=0.3
    )
    
    # 4. Write new file
    # Ensure we strictly use the filename part, in case LLM included dir
    target_path = Path(cluster[0]).parent / Path(decision.target_filename).name
    # Ensure extension
    if not target_path.name.endswith(".md"):
        target_path = target_path.with_suffix(".md")
        
    # target_path is already relative to the brain root (e.g. 'characters/steve_jobs.md')
    # precisely because cluster[0] came from list_files() which returns relative paths.
    brain.write_file(str(target_path), merged_result.content)
    
    final_relative_path = str(target_path)
    console.print(f"  [green]+ Written:[/green] {final_relative_path}")
    
    # 5. Soft Delete old files (Move to archive/)
    # Don't delete the new file if it was one of the old ones!
    for f in cluster:
        if f == final_relative_path:
            continue
            
        content = brain.read_file(f)
        if content:
            # Write to archive
            archive_path = f"archive/{f}"
            brain.write_file(archive_path, content)
            
            # Delete original
            brain.delete_file(f)
            console.print(f"  [red]- Archived:[/red] {f}")
            
    return True

def optimize_brain(brain_name: str, provider: str = "anthropic"):
    """
    Run the Gardener to optimize the brain.
    """
    brain = Brain(name=brain_name)
    if not brain.exists():
        console.print(f"[red]Brain {brain_name} not found.[/red]")
        return
        
    client = get_client(provider=provider)
    console.print(f"[bold blue]Gardener: Optimizing '{brain_name}'[/bold blue]")
    
    console.print("[dim]Detecting duplicates...[/dim]")
    clusters = detect_duplicates(brain)
    
    if not clusters:
        console.print("[green]No duplicates detected.[/green]")
        return
        
    console.print(f"[yellow]Found {len(clusters)} potential clusters.[/yellow]")
    
    for _, cluster in clusters.items():
        merge_cluster(brain, cluster, client)
        
    console.print("[bold green]Optimization complete.[/bold green]")
