"""Tests for Brain knowledge base operations."""

import sys
import tempfile
from pathlib import Path
import pytest

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

    def test_write_file_rejects_path_traversal(self):
        """Test that write_file blocks paths escaping the brain root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            brain.initialize("Test objective")

            with pytest.raises(ValueError):
                brain.write_file("../outside.md", "bad")

    def test_read_file_rejects_path_traversal(self):
        """Test that read_file blocks paths escaping the brain root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            brain.initialize("Test objective")

            with pytest.raises(ValueError):
                brain.read_file("../../etc/passwd")


class TestBrainInitialization:
    """Tests for brain initialization and setup."""

    def test_initialize_creates_directory_structure(self):
        """Test that initialize creates the expected brain directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            objective = "Summarize the key themes in this document."
            brain.initialize(objective)
            
            # Verify directories were created
            assert (brain.path / "characters").exists()
            assert (brain.path / "timeline").exists()
            assert (brain.path / "themes").exists()
            assert (brain.path / "facts").exists()
            assert (brain.path / "notes").exists()
            assert (brain.path / "meta").exists()

    def test_initialize_creates_objective_file(self):
        """Test that initialize stores the user's objective."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            objective = "Extract all character relationships."
            brain.initialize(objective)
            
            # Verify objective file was created
            objective_content = brain.read_file("_objective.md")
            assert objective_content is not None
            assert objective in objective_content
            assert "# Objective" in objective_content

    def test_initialize_creates_response_file(self):
        """Test that initialize creates empty response placeholder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            brain.initialize("Test objective")
            
            # Verify response file exists
            response = brain.read_file("_response.md")
            assert response is not None
            assert "# Response" in response

    def test_initialize_creates_index_file(self):
        """Test that initialize creates brain index for navigation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            brain.initialize("Test objective")
            
            # Verify index file was created with structure info
            index = brain.read_file("_index.md")
            assert index is not None
            assert "# Brain Index" in index
            assert "characters/" in index
            assert "timeline/" in index


class TestBrainObjectiveAndResponse:
    """Tests for getting and updating brain objective and response."""

    def test_get_objective_returns_user_query(self):
        """Test that get_objective retrieves the user's original question from brain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            
            user_objective = "What are the main themes and character arcs in this novel?"
            brain.initialize(user_objective)
            
            # User should be able to retrieve their original objective
            retrieved = brain.get_objective()
            
            assert retrieved == user_objective

    def test_get_and_update_response_retrieves_answer(self):
        """Test that users can retrieve and update the brain's synthesized answer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = Brain("test-brain", base_path=tmpdir)
            brain.initialize("What is the main theme?")
            
            # After initialization, response exists with placeholder
            initial_response = brain.get_response()
            assert "# Response" in initial_response
            assert "Processing not yet started" in initial_response
            
            # System updates the response after ingestion
            synthesized_answer = """# Response

The main theme of this work is the struggle between ambition and morality.

## Key Evidence

- Chapter 3: "The protagonist faces a choice between success and integrity."
- Chapter 7: Resolution shows consequences of earlier choices.
"""
            brain.update_response(synthesized_answer)
            
            # User retrieves the synthesized answer
            final_response = brain.get_response()
            assert "ambition and morality" in final_response
            assert "Chapter 3" in final_response
