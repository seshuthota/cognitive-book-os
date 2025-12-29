"""Visualization module for the Knowledge Graph.

Scans the brain for links and generates an interactive HTML graph.
"""

from pathlib import Path
from rich.console import Console
import yaml
import re

from .brain import Brain

console = Console()

def extract_related_links(content: str) -> list[str]:
    """Extract related links from YAML frontmatter."""
    try:
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                frontmatter = content[3:end]
                data = yaml.safe_load(frontmatter)
                if data and "related" in data:
                    related = data["related"]
                    if isinstance(related, list):
                        return related
                    elif isinstance(related, str):
                        # Handle basic list strings if LLM messed up YAML
                        return [r.strip() for r in related.strip("[]").split(",")]
    except Exception:
        pass
    return []

def extract_wiki_links(content: str) -> list[str]:
    """Extract [[wiki-links]] from markdown content."""
    # Matches [[link]] or [[link|alias]]
    matches = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", content)
    return matches

def generate_graph(brain_name: str, output_file: str = "graph.html"):
    """
    Generate an interactive network graph of the knowledge base.
    """
    try:
        from pyvis.network import Network
    except ImportError:
        console.print("[red]pyvis not installed. Please install it: uv pip install pyvis[/red]")
        return
        
    brain = Brain(name=brain_name)
    if not brain.exists():
        console.print(f"[red]Brain {brain_name} not found.[/red]")
        return
        
    console.print(f"[bold blue]Visualizing Brain: {brain_name}[/bold blue]")
    
    files = brain.list_files()
    net = Network(height="750px", width="100%", bgcolor="#222222", font_color="white", select_menu=True)
    
    # 1. Add Nodes
    for f in files:
        if f.startswith("meta/") or f.startswith("_"):
            continue
            
        group = f.split("/")[0] if "/" in f else "root"
        label = Path(f).stem.replace("_", " ").title()
        
        # Color nodes by group
        color_map = {
            "characters": "#ff9999", # Red
            "timeline": "#99ccff",   # Blue
            "themes": "#cc99ff",     # Purple
            "facts": "#99ff99",      # Green
            "locations": "#ffff99"   # Yellow
        }
        color = color_map.get(group, "#cccccc")
        
        net.add_node(f, label=label, title=f, group=group, color=color)
        
    # 2. Add Edges
    edge_count = 0
    for f in files:
        if f.startswith("meta/") or f.startswith("_"):
            continue
            
        content = brain.read_file(f)
        if not content:
            continue
            
        # Extract explicit 'related' from frontmatter
        related_links = extract_related_links(content)
        for target in related_links:
            # target might be just "steve_jobs.md" or "characters/steve_jobs.md"
            # We need to find the full path if possible
            target_path = resolve_path(target, files)
            if target_path and target_path != f:
                net.add_edge(f, target_path, title="related", color="#555555")
                edge_count += 1
                
        # Extract wiki-links [[...]]
        wiki_links = extract_wiki_links(content)
        for target in wiki_links:
            target_path = resolve_path(target, files)
            if target_path and target_path != f:
                net.add_edge(f, target_path, title="wiki-link", color="#777777")
                edge_count += 1

    console.print(f"Nodes: {len(net.nodes)}")
    console.print(f"Edges: {edge_count}")
    
    # Save graph
    output_path = brain.path / output_file
    net.save_graph(str(output_path))
    console.print(f"[green]Graph saved to:[/green] {output_path}")

def resolve_path(target: str, all_files: list[str]) -> str | None:
    """Resolve a partial path/name to a full file path."""
    target = target.strip()
    if not target:
        return None
        
    # Exact match
    if target in all_files:
        return target
        
    # Name match (steve_jobs matching characters/steve_jobs.md)
    # Check with and without .md
    target_stem = Path(target).stem.lower()
    
    for f in all_files:
        if Path(f).stem.lower() == target_stem:
            return f
            
    return None
