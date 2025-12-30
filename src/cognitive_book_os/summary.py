"""Summary system - generate lightweight maps of knowledge."""

import yaml
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from .brain import Brain

console = Console()

def summarize_topic(
    brain_name: str,
    topic: str,
    brains_dir: str = "brains"
) -> None:
    """
    Generate a map/summary of a specific topic directory (e.g. 'characters', 'themes').
    
    Args:
        brain_name: Name of the brain
        topic: Subdirectory to summarize (characters, themes, timeline, facts)
        brains_dir: brains directory
    """
    brain = Brain(name=brain_name, base_path=brains_dir)
    
    if not brain.exists():
        console.print(f"[red]Brain '{brain_name}' not found![/red]")
        return
        
    # validate topic
    valid_topics = ["characters", "themes", "timeline", "facts", "notes"]
    if topic not in valid_topics:
        # fuzzy match or default
        console.print(f"[yellow]Topic '{topic}' not one of standard types {valid_topics}. Checking root...[/yellow]")
        search_dir = topic
    else:
        search_dir = topic
        
    files = brain.list_files(directory=search_dir)
    if not files:
        console.print(f"[yellow]No files found in '{search_dir}'.[/yellow]")
        return

    console.print(f"[bold blue]Knowledge Map: {topic.capitalize()} ({len(files)} files)[/bold blue]")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("File / Entity")
    table.add_column("Synopsis", width=50)
    table.add_column("Related To", style="dim")
    
    for relative_path in files:
        if not relative_path.endswith(".md"):
            continue
            
        content = brain.read_file(relative_path)
        if not content:
            continue
            
        # Parse Frontmatter
        frontmatter = {}
        synopsis = "No synopsis."
        related = []
        
        try:
            if content.startswith("---"):
                _, fm_text, body = content.split("---", 2)
                frontmatter = yaml.safe_load(fm_text) or {}
                
                # Get Synopsis from frontmatter OR content
                synopsis = frontmatter.get("summary")
                if not synopsis:
                    # heuristic: look for **Synopsis**: in body
                    if "**Synopsis**:" in body:
                        parts = body.split("**Synopsis**:", 1)[1]
                        synopsis = parts.split("\n", 1)[0].strip()
                    elif "**Summary**:" in body:
                        parts = body.split("**Summary**:", 1)[1]
                        synopsis = parts.split("\n", 1)[0].strip()
                    else:
                        # First non-empty line after title
                        lines = [l.strip() for l in body.split("\n") if l.strip() and not l.strip().startswith("#")]
                        if lines:
                            synopsis = lines[0][:100] + "..."
                            
                related = frontmatter.get("related", [])
        except Exception:
            synopsis = "[Error parsing frontmatter]"
            
        # Format "Related"
        related_str = ""
        if related:
            # Clean up paths to just names
            names = [Path(p).stem.replace("_", " ").title() for p in related]
            related_str = ", ".join(names[:3]) # Top 3
            if len(names) > 3:
                related_str += f" (+{len(names)-3})"
        
        name = Path(relative_path).stem.replace("_", " ").title()
        table.add_row(name, synopsis, related_str)
        
    console.print(table)
