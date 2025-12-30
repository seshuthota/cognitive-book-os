import json
import fcntl
import contextlib
from pathlib import Path
from typing import Optional
from .models import AnchorState, ProcessingLog


class Brain:
    """
    Manages the file-based knowledge structure.
    
    A brain is a folder containing organized markdown files
    that represent the LLM's understanding of a document.
    """
    
    def __init__(self, name: str, base_path: Path | str = "brains"):
        """
        Initialize a brain.
        
        Args:
            name: Name of the brain (used as folder name)
            base_path: Base directory for all brains
        """
        self.name = name
        self.base_path = Path(base_path)
        self.path = self.base_path / name
        
    @contextlib.contextmanager
    def _lock_log(self):
        """Exclusive lock for processing log operations."""
        lock_file_path = self.path / "meta/processing_log.lock"
        # Ensure directory exists
        lock_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(lock_file_path, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        
    def exists(self) -> bool:
        """Check if this brain already exists."""
        return self.path.exists()
    
    def initialize(self, objective: str) -> None:
        """
        Initialize a new brain with the base structure.
        
        Args:
            objective: The user's objective/question for this document
        """
        # Create directory structure
        directories = [
            "characters",
            "timeline", 
            "themes",
            "facts",
            "notes",
            "meta"
        ]
        
        for dir_name in directories:
            (self.path / dir_name).mkdir(parents=True, exist_ok=True)
        
        # Create objective file
        self.write_file("_objective.md", f"# Objective\n\n{objective}\n")
        
        # Create empty response file
        self.write_file("_response.md", "# Response\n\n*Processing not yet started.*\n")
        
        # Create index file
        index_content = """# Brain Index

This file tracks the structure of the knowledge base.

## Directories

- `characters/` - People and entities
- `timeline/` - Chronological events
- `themes/` - Recurring patterns and extracts
- `facts/` - Standalone facts, quotes, data
- `notes/` - User observations and overrides

## Files

*Updated as processing continues...*
"""
        self.write_file("_index.md", index_content)
        
        # Initialize anchor state
        anchor = AnchorState()
        self.write_file("meta/anchor_state.json", anchor.model_dump_json(indent=2))
        
        # Initialize processing log
        log = ProcessingLog(book_path="", objective=objective)
        self.write_file("meta/processing_log.json", log.model_dump_json(indent=2))
    
    def write_file(self, relative_path: str, content: str) -> Path:
        """
        Write content to a file in the brain.
        
        Args:
            relative_path: Path relative to brain root
            content: Content to write
            
        Returns:
            Absolute path to the file
        """
        file_path = self.path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return file_path
    
    def read_file(self, relative_path: str) -> Optional[str]:
        """
        Read content from a file in the brain.
        
        Args:
            relative_path: Path relative to brain root
            
        Returns:
            File content or None if not found
        """
        file_path = self.path / relative_path
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
        return None
    
    def delete_file(self, relative_path: str) -> bool:
        """
        Delete a file from the brain.
        
        Args:
            relative_path: Path relative to brain root
            
        Returns:
            True if deleted, False if not found
        """
        file_path = self.path / relative_path
        if file_path.exists():
            file_path.unlink()
            return True
        return False
    
    def list_files(self, directory: str = "") -> list[str]:
        """
        List all files in the brain or a subdirectory.
        
        Args:
            directory: Subdirectory to list (empty for root)
            
        Returns:
            List of relative file paths
        """
        search_path = self.path / directory if directory else self.path
        if not search_path.exists():
            return []
        
        files = []
        for file_path in search_path.rglob("*"):
            if file_path.is_file():
                files.append(str(file_path.relative_to(self.path)))
        return sorted(files)
    
    def get_structure(self) -> str:
        """
        Get a text representation of the brain structure.
        
        Returns:
            Tree-like representation of files and folders
        """
        lines = [f"Brain: {self.name}", "=" * 40]
        
        for file_path in sorted(self.list_files()):
            depth = file_path.count("/")
            indent = "  " * depth
            name = file_path.split("/")[-1]
            lines.append(f"{indent}├── {name}")
        
        return "\n".join(lines)
    
    def get_anchor_state(self) -> AnchorState:
        """Get the current anchor state."""
        content = self.read_file("meta/anchor_state.json")
        if content:
            return AnchorState.model_validate_json(content)
        return AnchorState()
    
    def update_anchor_state(self, **kwargs) -> AnchorState:
        """Update anchor state with new values."""
        anchor = self.get_anchor_state()
        for key, value in kwargs.items():
            if hasattr(anchor, key):
                setattr(anchor, key, value)
        self.write_file("meta/anchor_state.json", anchor.model_dump_json(indent=2))
        return anchor
    
    def get_processing_log(self) -> ProcessingLog:
        """Get the processing log."""
        content = self.read_file("meta/processing_log.json")
        if content:
            return ProcessingLog.model_validate_json(content)
        return ProcessingLog(book_path="", objective="")
    
    def update_processing_log(self, **kwargs) -> ProcessingLog:
        """Update processing log with new values."""
        with self._lock_log():
            log = self.get_processing_log()
            for key, value in kwargs.items():
                if hasattr(log, key):
                    setattr(log, key, value)
            self.write_file("meta/processing_log.json", log.model_dump_json(indent=2))
            return log
    
    def get_objective(self) -> str:
        """Get the objective for this brain."""
        content = self.read_file("_objective.md")
        if content:
            # Extract just the objective text (skip header)
            lines = content.strip().split("\n")
            return "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
        return ""
    
    def get_response(self) -> str:
        """Get the current response to the objective."""
        return self.read_file("_response.md") or ""
    
    def update_response(self, content: str) -> None:
        """Update the response file."""
        self.write_file("_response.md", content)
    
    def get_index(self) -> str:
        """Get the brain index."""
        return self.read_file("_index.md") or ""
    
    def update_index(self, content: str) -> None:
        """Update the index file."""
        self.write_file("_index.md", content)
