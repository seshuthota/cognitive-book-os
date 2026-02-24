"""Graph data extraction logic.

Separates graph construction from visualization to allow API usage.
"""

from pathlib import Path
import yaml
import re

from .brain import Brain

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

def build_graph_data(brain_name: str, brains_dir: str = "brains") -> dict:
    """
    Build graph data (nodes and edges) for a brain.
    
    Returns:
        Dict with 'nodes' and 'links' compatible with force-graph libraries.
    """
    brain = Brain(name=brain_name, base_path=brains_dir)
    if not brain.exists():
        return {"nodes": [], "links": []}
        
    files = brain.list_files()
    nodes = []
    links = []
    
    # Track node IDs to ensure valid links
    node_ids = set()
    
    # 1. Add Nodes
    for f in files:
        if f.startswith("meta/") or f.startswith("_"):
            continue
            
        group = f.split("/")[0] if "/" in f else "root"
        label = Path(f).stem.replace("_", " ").title()
        
        # Color nodes by group (frontend can also handle this, but providing group is key)
        node = {
            "id": f,
            "label": label,
            "group": group,
            "val": 1  # Default size
        }
        nodes.append(node)
        node_ids.add(f)
        
    # 2. Add Edges
    for f in files:
        if f.startswith("meta/") or f.startswith("_"):
            continue
            
        content = brain.read_file(f)
        if not content:
            continue
            
        # Extract explicit 'related' from frontmatter
        related_links = extract_related_links(content)
        for target in related_links:
            target_path = resolve_path(target, files)
            if target_path and target_path != f and target_path in node_ids:
                links.append({
                    "source": f,
                    "target": target_path,
                    "type": "related"
                })
                
        # Extract wiki-links [[...]]
        wiki_links = extract_wiki_links(content)
        for target in wiki_links:
            target_path = resolve_path(target, files)
            if target_path and target_path != f and target_path in node_ids:
                links.append({
                    "source": f,
                    "target": target_path,
                    "type": "wiki-link"
                })

    return {"nodes": nodes, "links": links}
