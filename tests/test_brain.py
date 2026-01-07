"""Tests for Brain knowledge base operations."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cognitive_book_os.brain import Brain


class TestBrainFileOperations:
    """Tests for basic brain file read/write operations."""

    def test_write_and_read_file(self):
        """Test that users can write and read files from brain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            # Write a file
            content = "# Test Character\n\nThis is a test character."
            file_path = brain.write_file("characters/john-doe.md", content)
            
            # Verify file was created
            assert file_path.exists()
            
            # Read it back
            read_content = brain.read_file("characters/john-doe.md")
            assert read_content == content

    def test_read_nonexistent_file_returns_none(self):
        """Test that reading missing file returns None instead of error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            result = brain.read_file("nonexistent/file.md")
            assert result is None

    def test_delete_file(self):
        """Test that users can delete files from brain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            # Create a file
            brain.write_file("themes/test-theme.md", "Test content")
            
            # Delete it
            deleted = brain.delete_file("themes/test-theme.md")
            assert deleted is True
            
            # Verify it's gone
            assert brain.read_file("themes/test-theme.md") is None

    def test_delete_nonexistent_file_returns_false(self):
        """Test deleting missing file returns False gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            deleted = brain.delete_file("nonexistent.md")
            assert deleted is False

    def test_list_files_in_brain(self):
        """Test listing all files in brain directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            # Create several files
            brain.write_file("characters/alice.md", "Alice")
            brain.write_file("characters/bob.md", "Bob")
            brain.write_file("themes/friendship.md", "Friendship")
            brain.write_file("_objective.md", "Objective")
            
            # List all files
            files = brain.list_files()
            
            # Should have all created files
            assert len(files) >= 4
            assert "characters/alice.md" in files
            assert "characters/bob.md" in files
            assert "themes/friendship.md" in files
            assert "_objective.md" in files

    def test_list_files_in_subdirectory(self):
        """Test listing files in specific brain subdirectory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            # Create files in different directories
            brain.write_file("characters/alice.md", "Alice")
            brain.write_file("themes/friendship.md", "Friendship")
            
            # List only characters
            char_files = brain.list_files("characters")
            
            assert len(char_files) == 1
            assert "characters/alice.md" in char_files
            assert "themes/friendship.md" not in char_files

    def test_brain_exists_check(self):
        """Test checking if brain directory exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            # Should not exist initially
            assert brain.exists() is False
            
            # Create the brain directory
            brain.path.mkdir(parents=True)
            
            # Now it should exist
            assert brain.exists() is True
