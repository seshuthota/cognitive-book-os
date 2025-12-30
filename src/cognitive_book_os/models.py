from __future__ import annotations
"""Pydantic models for Cognitive Book OS."""


from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Union
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
        description="REQUIRED: The full markdown content to write. MUST include YAML frontmatter. IMPORTANT: For every fact/claim, you MUST include a direct quote: > \"Quote\" (Source: Chapter X)."
    )
    reason: str = Field(..., description="Brief explanation of why this operation is needed")


class ExtractionResult(BaseModel):
    """Result of extracting information from a chapter."""
    file_operations: List[FileOperation] = Field(
        default_factory=list,
        description="List of file operations to perform"
    )
    summary: str = Field(..., description="Brief summary of what was extracted")
    key_entities: List[str] = Field(
        default_factory=list,
        description="Key entities (people, places, concepts) found"
    )


class ObjectiveSynthesis(BaseModel):
    """Result of synthesizing toward the user's objective."""
    new_insights: str = Field(..., description="New insights relevant to the objective from this chapter")
    updated_response: str = Field(..., description="Updated full response to the objective")
    confidence: Confidence = Field(..., description="Confidence in the current response")
    open_questions: List[str] = Field(
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
    sources: List[str] = Field(
        default_factory=list,
        description="Files in the brain that were used to answer"
    )
    confidence: Confidence = Field(..., description="Confidence in the answer")


class FileSelection(BaseModel):
    """LLM's selection of relevant files for a query."""
    files: List[str] = Field(..., description="List of file paths to read")
    reasoning: str = Field(..., description="Why these files are relevant")


class AnchorState(BaseModel):
    """Global anchor state for dynamic context."""
    narrator_reliability: float = Field(default=1.0, ge=0.0, le=1.0)
    current_timeline: str = Field(default="present")
    world_context: str = Field(default="real_world")
    confirmed_facts: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    custom_anchors: Dict[str, float] = Field(default_factory=dict)



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
    secondary_objectives: List[str] = Field(default_factory=list)
    
    # Legacy fields (for backward compatibility, though chapter_map is preferred)
    chapters_processed: int = 0
    total_chapters: Optional[int] = None
    last_processed_chapter: Optional[int] = None
    status: str = "in_progress"

    # New State Map
    chapter_map: Dict[str, ChapterState] = Field(default_factory=dict) # Keys are stringified chapter indices "0", "1"...


class Evidence(BaseModel):
    """A piece of evidence supporting or refuting a claim."""
    file_path: str = Field(..., description="Path to the file containing the evidence")
    quote: str = Field(..., description="Direct quote from the text")
    context: str = Field(..., description="Context or explanation of how this supports/refutes the claim")
    source_chapter: Optional[str] = Field(None, description="Original source chapter if known")


class VerificationResult(BaseModel):
    """Result of a verification request."""
    claim: str = Field(..., description="The claim being verified")
    # Simplified structure to avoid instructor Partial[List[Model]] issues
    # Each item should be a string like "Quote (Source) - Context"
    supporting_points: List[str] = Field(default_factory=list, description="List of supporting evidence strings")
    conflicting_points: List[str] = Field(default_factory=list, description="List of conflicting evidence strings")
    verdict: str = Field(..., description="Final verdict: Confirmed, Refuted, Ambiguous, or Unverified")
    reasoning: Optional[str] = Field(None, description="Explanation of the verdict")
