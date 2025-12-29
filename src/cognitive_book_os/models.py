"""Pydantic models for Cognitive Book OS."""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from enum import Enum
from datetime import datetime


class Confidence(str, Enum):
    """Confidence level for extracted information."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCERTAIN = "uncertain"
    NONE = "none"  # Used when no answer could be generated


class FileOperation(BaseModel):
    """Represents a file operation the LLM wants to perform."""
    action: str = Field(..., description="One of: 'create', 'update', or 'delete'")
    path: str = Field(..., description="Relative path within the brain, e.g., 'characters/steve_jobs.md'")
    content: str = Field(
        ..., 
        description="REQUIRED: The full markdown content to write to the file. Must include YAML frontmatter and detailed content. For delete operations, use empty string."
    )
    reason: str = Field(..., description="Brief explanation of why this operation is needed")


class ExtractionResult(BaseModel):
    """Result of extracting information from a chapter."""
    file_operations: list[FileOperation] = Field(
        default_factory=list,
        description="List of file operations to perform"
    )
    summary: str = Field(..., description="Brief summary of what was extracted")
    key_entities: list[str] = Field(
        default_factory=list,
        description="Key entities (people, places, concepts) found"
    )


class ObjectiveSynthesis(BaseModel):
    """Result of synthesizing toward the user's objective."""
    new_insights: str = Field(..., description="New insights relevant to the objective from this chapter")
    updated_response: str = Field(..., description="Updated full response to the objective")
    confidence: Confidence = Field(..., description="Confidence in the current response")
    open_questions: list[str] = Field(
        default_factory=list,
        description="Questions that remain unanswered"
    )

    @field_validator("open_questions", mode="before")
    @classmethod
    def parse_open_questions(cls, v):
        """Handle case where LLM returns a string instead of a list."""
        if isinstance(v, str):
            questions = []
            for line in v.split('\n'):
                line = line.strip()
                if line:
                    # Remove "1. ", "- ", etc
                    if line[0].isdigit() and '. ' in line:
                        line = line.split('. ', 1)[1]
                    elif line.startswith('- '):
                        line = line[2:]
                    questions.append(line)
            return questions
        return v


class QueryResult(BaseModel):
    """Result of answering a query against the brain."""
    answer: str = Field(..., description="The answer to the question")
    sources: list[str] = Field(
        default_factory=list,
        description="Files in the brain that were used to answer"
    )
    confidence: Confidence = Field(..., description="Confidence in the answer")


class FileSelection(BaseModel):
    """LLM's selection of relevant files for a query."""
    files: list[str] = Field(..., description="List of file paths to read")
    reasoning: str = Field(..., description="Why these files are relevant")


class AnchorState(BaseModel):
    """Global anchor state for dynamic context."""
    narrator_reliability: float = Field(default=1.0, ge=0.0, le=1.0)
    current_timeline: str = Field(default="present")
    world_context: str = Field(default="real_world")
    confirmed_facts: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    custom_anchors: dict[str, float] = Field(default_factory=dict)



class ChapterStatus(str, Enum):
    """Status of a chapter in the processing pipeline."""
    EXTRACTED = "extracted"  # Fully processed and extracted
    SKIPPED = "skipped"      # Skipped by triage/filter
    PENDING = "pending"      # Not yet processed


class ChapterState(BaseModel):
    """State of a single chapter."""
    chapter_num: int
    status: ChapterStatus
    reason: Optional[str] = None  # e.g., "Skipped: Irrelevant to objective"
    timestamp: datetime = Field(default_factory=datetime.now)
    source_objective: Optional[str] = Field(None, description="The objective that triggered this chapter's extraction")


class ProcessingLog(BaseModel):
    """Tracks processing progress."""
    book_path: str
    objective: Optional[str] = None
    secondary_objectives: list[str] = Field(default_factory=list)
    
    # Legacy fields (for backward compatibility, though chapter_map is preferred)
    chapters_processed: int = 0
    total_chapters: Optional[int] = None
    last_processed_chapter: Optional[int] = None
    status: str = "in_progress"

    # New State Map
    chapter_map: dict[str, ChapterState] = Field(default_factory=dict) # Keys are stringified chapter indices "0", "1"...

