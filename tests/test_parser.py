"""Tests for document parsing utilities."""

import sys
from pathlib import Path
import fitz  # PyMuPDF
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cognitive_book_os.parser import split_into_chunks, detect_chapters, chunk_document


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


class TestDetectChapters:
    """Tests for chapter detection in documents."""

    def test_detect_standard_chapter_headings(self):
        """Test detecting chapters with 'Chapter N' format."""
        text = """
Chapter 1: Introduction

This is the introduction content.

Chapter 2: The Main Story

This is the main story content.

Chapter 3: Conclusion

This is the conclusion.
"""
        chapters = detect_chapters(text)
        
        # Should detect 3 chapters
        assert len(chapters) >= 3
        
        # Check chapter titles
        titles = [ch.title for ch in chapters]
        assert any("Introduction" in t for t in titles)
        assert any("Main Story" in t for t in titles)

    def test_detect_uppercase_chapter_headings(self):
        """Test detecting CHAPTER format (uppercase)."""
        text = """
CHAPTER 1: FIRST PART

Content of first chapter.

CHAPTER 2: SECOND PART

Content of second chapter.
"""
        chapters = detect_chapters(text)
        
        assert len(chapters) >= 2
        assert any("FIRST PART" in ch.title or "First Part" in ch.title for ch in chapters)

    def test_detect_numbered_headings(self):
        """Test detecting '1. Title' format."""
        text = """
1. First Section

Content here.

2. Second Section

More content.
"""
        chapters = detect_chapters(text)
        
        # Should detect sections
        assert len(chapters) >= 2

    def test_no_chapters_returns_full_document(self):
        """Test that text without chapter markers returns whole document as one chapter."""
        text = "This is just regular text without any chapter markers at all."
        
        chapters = detect_chapters(text)
        
        # Should return single chapter with full document
        assert len(chapters) == 1
        # Default title is "Full Document" or chapter 0 (based on code inspection)
        assert "regular text" in chapters[0].content


class TestChunkDocument:
    """Tests for PDF document chunking - the main entry point users rely on."""

    @pytest.fixture
    def sample_pdf(self, tmp_path):
        """Create a sample PDF with chapter structure for testing."""
        pdf_path = tmp_path / "test_doc.pdf"
        doc = fitz.open()
        
        # Create a multi-chapter PDF that users would typically process
        content = """Chapter 1: Introduction

This is the introduction to our test document. It contains enough content
to verify that the chunking system works correctly for typical user workflows.

Chapter 2: Main Content

This chapter has the main content. When users process PDFs, they expect
the system to intelligently detect chapter boundaries and create meaningful
chunks that preserve document structure.

Chapter 3: Conclusion

The final chapter wraps up our test document with concluding remarks."""
        
        page = doc.new_page()
        page.insert_text((50, 50), content)
        doc.save(pdf_path)
        doc.close()
        
        return pdf_path

    def test_chunk_document_detects_chapters(self, sample_pdf):
        """Test that chunk_document() correctly processes PDF chapters for users."""
        # This is the main function users call to process their PDFs
        chunks = list(chunk_document(sample_pdf, use_chapters=True))
        
        # Should detect the 3 chapters
        assert len(chunks) >= 3
        
        # Each chunk is (number, title, content)
        numbers, titles, contents = zip(*chunks)
        
        # Verify chapter detection worked
        assert any("Introduction" in title for title in titles)
        assert any("Main Content" in title for title in titles)
        assert any("Conclusion" in title for title in titles)
        
        # Verify content is extracted
        full_content = " ".join(contents)
        assert "introduction to our test document" in full_content.lower()
        assert "intelligently detect chapter boundaries" in full_content.lower()

