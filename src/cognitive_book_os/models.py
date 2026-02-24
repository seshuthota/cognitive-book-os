from __future__ import annotations
"""Pydantic models for Cognitive Book OS."""


from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Union, Any
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


class ClaimStatus(str, Enum):
    """Lifecycle status for a claim snapshot."""
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class ClaimSnapshot(BaseModel):
    """Latest materialized state for a claim."""
    claim_id: str
    revision_id: str
    status: ClaimStatus = ClaimStatus.ACTIVE
    brain_name: str
    file_path: str
    claim_text: str
    evidence_quote: str
    source_locator: str
    confidence: Confidence = Confidence.MEDIUM
    tags: List[str] = Field(default_factory=list)
    related_claim_ids: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    created_by_run: str
    updated_by_run: str
    supersedes_revision_id: Optional[str] = None
    user_override: bool = False


class ClaimEvent(BaseModel):
    """Append-only event for claim lifecycle/audit."""
    event_id: str
    event_type: str
    timestamp: str
    brain_name: str
    run_id: str
    claim_id: Optional[str] = None
    revision_id: Optional[str] = None
    file_path: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class RunRecord(BaseModel):
    """Run metadata for ingestion/enrichment/query auditing."""
    run_id: str
    run_type: str
    brain_name: str
    objective: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    started_at: str
    finished_at: Optional[str] = None
    status: str = "started"
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QueryTraceCompleteness(BaseModel):
    """Coverage summary for claim traceability."""
    total_statements: int = 0
    linked_statements: int = 0
    completeness_ratio: float = 0.0


class ClaimTraceItem(BaseModel):
    """Claim-level evidence used in a query answer."""
    claim_id: str
    file_path: str
    claim_text: str
    evidence_quote: str
    source_locator: str
    confidence: Confidence = Confidence.MEDIUM
    user_override: bool = False


class QueryAuditResult(BaseModel):
    """Audited query result with claim-level traceability."""
    answer: str
    sources: List[str] = Field(default_factory=list)
    confidence: Confidence
    claim_trace: List[ClaimTraceItem] = Field(default_factory=list)
    trace_completeness: QueryTraceCompleteness = Field(default_factory=QueryTraceCompleteness)
    query_run_id: str


class PerBrainResult(BaseModel):
    """Per-brain section in a multi-brain query response."""
    brain_name: str
    answer_excerpt: str
    confidence: Confidence
    sources: List[str] = Field(default_factory=list)
    claim_trace: List[ClaimTraceItem] = Field(default_factory=list)
    trace_degraded: bool = False
    trace_completeness_ratio: float = 0.0


class ConflictItem(BaseModel):
    """Cross-brain claim comparison result."""
    topic: str
    brains_involved: List[str] = Field(default_factory=list)
    classification: str = Field(..., description="support|refute|ambiguous")
    evidence: List[str] = Field(default_factory=list)


class TraceabilitySummary(BaseModel):
    """Aggregate traceability status across selected brains."""
    brains_with_claims: int = 0
    brains_without_claims: int = 0
    overall_completeness_ratio: float = 0.0
    degraded_brains: List[str] = Field(default_factory=list)


class MultiBrainQueryRequest(BaseModel):
    """Request contract for cross-brain orchestration."""
    question: str
    brains: List[str] = Field(default_factory=list)
    provider: str = "anthropic"
    model: Optional[str] = None
    include_claim_trace: bool = True
    include_conflicts: bool = True
    max_brains: int = 5
    max_files_per_brain: int = 12


class MultiBrainQueryResult(BaseModel):
    """Unified response across multiple brains."""
    answer: str
    confidence: Confidence
    per_brain: List[PerBrainResult] = Field(default_factory=list)
    conflicts: List[ConflictItem] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    traceability: TraceabilitySummary = Field(default_factory=TraceabilitySummary)
    query_run_id: str
    warnings: List[str] = Field(default_factory=list)
