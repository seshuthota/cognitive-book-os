"""Tests for Pydantic models in cognitive_book_os.models."""

import pytest
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cognitive_book_os.models import (
    Confidence,
    FileOperation,
    ExtractionResult,
    ObjectiveSynthesis,
    QueryResult,
    FileSelection,
    AnchorState,
    ChapterStatus,
    ChapterState,
    ProcessingLog,
    Evidence,
    VerificationResult,
)


class TestConfidence:
    """Tests for Confidence enum."""

    def test_confidence_values(self):
        """Test that all confidence levels exist."""
        assert Confidence.HIGH == "high"
        assert Confidence.MEDIUM == "medium"
        assert Confidence.LOW == "low"
        assert Confidence.UNCERTAIN == "uncertain"
        assert Confidence.NONE == "none"

    def test_confidence_from_string(self):
        """Test creating confidence from string."""
        assert Confidence("high") == Confidence.HIGH
        assert Confidence("low") == Confidence.LOW


class TestFileOperation:
    """Tests for FileOperation model."""

    def test_create_file_operation(self):
        """Test creating a valid file operation."""
        op = FileOperation(
            action="create",
            path="characters/test.md",
            content="# Test",
            reason="Testing"
        )
        assert op.action == "create"
        assert op.path == "characters/test.md"
        assert op.content == "# Test"
        assert op.reason == "Testing"

    def test_file_operation_missing_action(self):
        """Test that action is required."""
        with pytest.raises(Exception):
            FileOperation(
                path="characters/test.md",
                content="# Test",
                reason="Testing"
            )

    def test_file_operation_default_values(self):
        """Test that content has description in Field."""
        op = FileOperation(
            action="update",
            path="characters/test.md",
            content="# Updated content",
            reason="Updating"
        )
        # The description should be present
        assert "content" in FileOperation.model_fields


class TestExtractionResult:
    """Tests for ExtractionResult model."""

    def test_create_extraction_result(self):
        """Test creating an extraction result."""
        result = ExtractionResult(
            file_operations=[],
            summary="Test summary",
            key_entities=["entity1", "entity2"]
        )
        assert result.summary == "Test summary"
        assert result.key_entities == ["entity1", "entity2"]
        assert result.file_operations == []

    def test_extraction_result_with_operations(self, sample_file_operation):
        """Test extraction result with file operations."""
        op = FileOperation(**sample_file_operation)
        result = ExtractionResult(
            file_operations=[op],
            summary="Extracted one file",
            key_entities=["Test Entity"]
        )
        assert len(result.file_operations) == 1
        assert result.file_operations[0].path == "characters/sarah_chen.md"


class TestObjectiveSynthesis:
    """Tests for ObjectiveSynthesis model."""

    def test_create_objective_synthesis(self):
        """Test creating an objective synthesis."""
        synthesis = ObjectiveSynthesis(
            new_insights="New insight",
            updated_response="Updated response",
            confidence=Confidence.HIGH,
            open_questions=["Question 1", "Question 2"]
        )
        assert synthesis.new_insights == "New insight"
        assert synthesis.confidence == Confidence.HIGH
        assert len(synthesis.open_questions) == 2

    def test_parse_open_questions_from_string(self):
        """Test parsing open questions from string format."""
        synthesis = ObjectiveSynthesis(
            new_insights="Test",
            updated_response="Test",
            confidence=Confidence.MEDIUM,
            open_questions="1. First question\n2. Second question\n3. Third question"
        )
        assert synthesis.open_questions == ["First question", "Second question", "Third question"]

    def test_parse_open_questions_with_dashes(self):
        """Test parsing open questions with dash prefix."""
        synthesis = ObjectiveSynthesis(
            new_insights="Test",
            updated_response="Test",
            confidence=Confidence.LOW,
            open_questions="- Question one\n- Question two"
        )
        assert synthesis.open_questions == ["Question one", "Question two"]


class TestQueryResult:
    """Tests for QueryResult model."""

    def test_create_query_result(self):
        """Test creating a query result."""
        result = QueryResult(
            answer="The answer is 42",
            sources=["characters/test.md", "timeline/test.md"],
            confidence=Confidence.HIGH
        )
        assert result.answer == "The answer is 42"
        assert len(result.sources) == 2
        assert result.confidence == Confidence.HIGH

    def test_query_result_default_sources(self):
        """Test that sources defaults to empty list."""
        result = QueryResult(
            answer="Test answer",
            confidence=Confidence.MEDIUM
        )
        assert result.sources == []


class TestFileSelection:
    """Tests for FileSelection model."""

    def test_create_file_selection(self):
        """Test creating a file selection."""
        selection = FileSelection(
            files=["characters/a.md", "timeline/b.md"],
            reasoning="These files contain relevant information"
        )
        assert selection.files == ["characters/a.md", "timeline/b.md"]
        assert "relevant" in selection.reasoning


class TestAnchorState:
    """Tests for AnchorState model."""

    def test_create_anchor_state(self):
        """Test creating an anchor state."""
        state = AnchorState()
        assert state.narrator_reliability == 1.0
        assert state.current_timeline == "present"
        assert state.world_context == "real_world"
        assert state.confirmed_facts == []
        assert state.open_questions == []
        assert state.custom_anchors == {}

    def test_anchor_state_custom_values(self):
        """Test anchor state with custom values."""
        state = AnchorState(
            narrator_reliability=0.8,
            current_timeline="past",
            world_context="fictional",
            confirmed_facts=["fact1"],
            open_questions=["q1"],
            custom_anchors={"key": 0.5}
        )
        assert state.narrator_reliability == 0.8
        assert state.current_timeline == "past"
        assert state.custom_anchors == {"key": 0.5}

    def test_anchor_state_reliability_bounds(self):
        """Test that narrator_reliability is bounded 0-1."""
        with pytest.raises(ValueError):
            AnchorState(narrator_reliability=1.5)
        with pytest.raises(ValueError):
            AnchorState(narrator_reliability=-0.1)


class TestChapterState:
    """Tests for ChapterState model."""

    def test_create_chapter_state(self):
        """Test creating a chapter state."""
        state = ChapterState(
            chapter_num=5,
            status=ChapterStatus.EXTRACTED
        )
        assert state.chapter_num == 5
        assert state.status == ChapterStatus.EXTRACTED

    def test_chapter_state_with_reason(self):
        """Test chapter state with skip reason."""
        state = ChapterState(
            chapter_num=3,
            status=ChapterStatus.SKIPPED,
            reason="Irrelevant to objective"
        )
        assert state.reason == "Irrelevant to objective"


class TestProcessingLog:
    """Tests for ProcessingLog model."""

    def test_create_processing_log(self):
        """Test creating a processing log."""
        log = ProcessingLog(
            book_path="/path/to/book.pdf"
        )
        assert log.book_path == "/path/to/book.pdf"
        assert log.status == "in_progress"
        assert log.chapters_processed == 0
        assert log.chapter_map == {}

    def test_processing_log_with_chapters(self):
        """Test processing log with chapter states."""
        log = ProcessingLog(
            book_path="/path/to/book.pdf",
            total_chapters=10
        )
        log.chapter_map["0"] = ChapterState(
            chapter_num=0,
            status=ChapterStatus.EXTRACTED
        )
        log.chapter_map["5"] = ChapterState(
            chapter_num=5,
            status=ChapterStatus.SKIPPED,
            reason="Irrelevant"
        )
        assert len(log.chapter_map) == 2
        assert log.chapter_map["0"].status == ChapterStatus.EXTRACTED


class TestEvidence:
    """Tests for Evidence model."""

    def test_create_evidence(self):
        """Test creating evidence."""
        evidence = Evidence(
            file_path="characters/test.md",
            quote="Test quote",
            context="This supports the claim",
            source_chapter="chapter_3"
        )
        assert evidence.file_path == "characters/test.md"
        assert evidence.quote == "Test quote"
        assert evidence.source_chapter == "chapter_3"


class TestVerificationResult:
    """Tests for VerificationResult model."""

    def test_create_verification_result(self):
        """Test creating a verification result."""
        result = VerificationResult(
            claim="Test claim",
            supporting_points=["Point 1", "Point 2"],
            conflicting_points=[],
            verdict="Confirmed",
            reasoning="Evidence supports the claim"
        )
        assert result.claim == "Test claim"
        assert result.verdict == "Confirmed"
        assert len(result.supporting_points) == 2
        assert len(result.conflicting_points) == 0

    def test_verification_result_all_verdict_types(self):
        """Test all possible verdict types."""
        for verdict in ["Confirmed", "Refuted", "Ambiguous", "Unverified"]:
            result = VerificationResult(
                claim="Test",
                supporting_points=[],
                conflicting_points=[],
                verdict=verdict
            )
            assert result.verdict == verdict
