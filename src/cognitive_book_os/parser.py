"""Document parsing utilities."""

import fitz  # PyMuPDF
from pathlib import Path
from typing import Iterator
from dataclasses import dataclass


@dataclass
class Chapter:
    """Represents a chapter or section of a document."""
    number: int
    title: str
    content: str
    start_page: int
    end_page: int


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """
    Extract all text from a PDF file.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Full text content
    """
    doc = fitz.open(pdf_path)
    text_parts = []
    
    for page in doc:
        text_parts.append(page.get_text())
    
    doc.close()
    return "\n".join(text_parts)


def extract_pages_from_pdf(pdf_path: str | Path) -> list[tuple[int, str]]:
    """
    Extract text from each page of a PDF.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        List of (page_number, text) tuples (1-indexed)
    """
    doc = fitz.open(pdf_path)
    pages = []
    
    for i, page in enumerate(doc):
        pages.append((i + 1, page.get_text()))
    
    doc.close()
    return pages


def split_into_chunks(text: str, chunk_size: int = 32000, overlap: int = 500) -> list[str]:
    """
    Split text into overlapping chunks.
    
    Args:
        text: Full text to split
        chunk_size: Target size of each chunk in characters
        overlap: Overlap between chunks
        
    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # Try to break at a paragraph or sentence
        if end < len(text):
            # Look for paragraph break
            para_break = text.rfind("\n\n", start, end)
            if para_break > start + chunk_size // 2:
                end = para_break + 2
            else:
                # Look for sentence break
                sentence_break = text.rfind(". ", start, end)
                if sentence_break > start + chunk_size // 2:
                    end = sentence_break + 2
        
        chunks.append(text[start:end].strip())
        start = end - overlap
    
    return chunks


def detect_chapters(text: str) -> list[Chapter]:
    """
    Attempt to detect chapter boundaries in text.
    
    This is a heuristic-based approach. For better results,
    consider using LLM to identify chapter boundaries.
    
    Args:
        text: Full document text
        
    Returns:
        List of detected chapters
    """
    import re
    
    # Common chapter patterns
    patterns = [
        r"^Chapter\s+(\d+)[:\.\s]*(.*?)$",
        r"^CHAPTER\s+(\d+)[:\.\s]*(.*?)$",
        r"^Part\s+(\d+)[:\.\s]*(.*?)$",
        r"^PART\s+(\d+)[:\.\s]*(.*?)$",
        r"^(\d+)\.\s+(.+)$",
    ]
    
    combined_pattern = "|".join(f"({p})" for p in patterns)
    
    chapters = []
    lines = text.split("\n")
    current_chapter_start = 0
    current_chapter_num = 0
    current_chapter_title = "Introduction"
    
    for i, line in enumerate(lines):
        line = line.strip()
        for pattern in patterns:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                # Save previous chapter
                if i > current_chapter_start:
                    content = "\n".join(lines[current_chapter_start:i])
                    chapters.append(Chapter(
                        number=current_chapter_num,
                        title=current_chapter_title,
                        content=content.strip(),
                        start_page=0,  # Would need page mapping
                        end_page=0
                    ))
                
                # Start new chapter
                current_chapter_start = i
                groups = match.groups()
                current_chapter_num = int(groups[0]) if groups[0].isdigit() else len(chapters) + 1
                current_chapter_title = groups[1].strip() if len(groups) > 1 and groups[1] else f"Chapter {current_chapter_num}"
                break
    
    # Don't forget the last chapter
    if current_chapter_start < len(lines):
        content = "\n".join(lines[current_chapter_start:])
        chapters.append(Chapter(
            number=current_chapter_num,
            title=current_chapter_title,
            content=content.strip(),
            start_page=0,
            end_page=0
        ))
    
    # If no chapters detected, treat whole document as one
    if not chapters:
        chapters.append(Chapter(
            number=1,
            title="Full Document",
            content=text.strip(),
            start_page=0,
            end_page=0
        ))
    
    return chapters


def chunk_document(
    pdf_path: str | Path,
    chunk_size: int = 32000,
    use_chapters: bool = True
) -> Iterator[tuple[int, str, str]]:
    """
    Load a document and yield processable chunks.
    
    Args:
        pdf_path: Path to the PDF file
        chunk_size: Target chunk size if not using chapters
        use_chapters: Try to detect and use chapter boundaries
        
    Yields:
        (chunk_number, chunk_title, chunk_content) tuples
    """
    text = extract_text_from_pdf(pdf_path)
    
    if use_chapters:
        chapters = detect_chapters(text)
        for chapter in chapters:
            # If chapter is too long, split it
            if len(chapter.content) > chunk_size * 1.5:
                sub_chunks = split_into_chunks(chapter.content, chunk_size)
                for i, sub_chunk in enumerate(sub_chunks):
                    yield (
                        chapter.number,
                        f"{chapter.title} (Part {i+1})",
                        sub_chunk
                    )
            else:
                yield (chapter.number, chapter.title, chapter.content)
    else:
        chunks = split_into_chunks(text, chunk_size)
        for i, chunk in enumerate(chunks):
            yield (i + 1, f"Chunk {i + 1}", chunk)
