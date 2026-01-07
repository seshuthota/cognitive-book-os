"""Tests for document parsing utilities."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cognitive_book_os.parser import split_into_chunks


class TestSplitIntoChunks:
    """Tests for text chunking functionality."""

    def test_split_small_text_returns_single_chunk(self):
        """Test that text smaller than chunk size returns single chunk."""
        text = "This is a short text that fits in one chunk."
        chunks = split_into_chunks(text, chunk_size=100)
        
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_split_large_text_creates_multiple_chunks(self):
        """Test that large text is split into multiple overlapping chunks."""
        # Create text that requires multiple chunks
        text = "Sentence. " * 500  # ~5000 characters
        chunks = split_into_chunks(text, chunk_size=1000, overlap=100)
        
        # Should create multiple chunks
        assert len(chunks) > 1
        
        # Each chunk should not exceed chunk_size significantly
        for chunk in chunks:
            assert len(chunk) <= 1200  # Allow some overage for sentence breaks

    def test_split_respects_paragraph_boundaries(self):
        """Test that chunking prefers paragraph breaks when possible."""
        # Create text with clear paragraph boundaries
        paragraphs = ["Paragraph one." * 50, "Paragraph two." * 50, "Paragraph three." * 50]
        text = "\n\n".join(paragraphs)
        
        chunks = split_into_chunks(text, chunk_size=500, overlap=50)
        
        # Should have created chunks
        assert len(chunks) > 0
        
        # First chunk should contain first paragraph
        assert "Paragraph one" in chunks[0]

    def test_split_respects_sentence_boundaries(self):
        """Test that chunking breaks at sentences when no paragraphs found."""
        # Create long text without paragraph breaks but with sentences
        sentences = [f"This is sentence number {i}. " for i in range(100)]
        text = "".join(sentences)
        
        chunks = split_into_chunks(text, chunk_size=500, overlap=50)
        
        # Should create multiple chunks
        assert len(chunks) > 1
        
        # Chunks should end at sentence boundaries (with ". ")
        for chunk in chunks[:-1]:  # All but last chunk
            # Should either end with period-space or be the natural end
            assert chunk.endswith(".") or ". " in chunk

    def test_chunk_overlap_provides_context(self):
        """Test that overlapping chunks share content for context continuity."""
        text = "A" * 2000  # Simple repeated character for easy testing
        chunks = split_into_chunks(text, chunk_size=1000, overlap=200)
        
        # Should have multiple chunks with overlap
        assert len(chunks) >= 2
        
        # Check that chunks overlap (end of chunk N shares with start of chunk N+1)
        if len(chunks) >= 2:
            # Due to overlap, chunk sizes should be close to chunk_size
            assert 800 <= len(chunks[0]) <= 1000
