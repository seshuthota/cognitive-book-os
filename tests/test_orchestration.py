"""Tests for multi-brain orchestration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from cognitive_book_os.brain import Brain
from cognitive_book_os.models import (
    ClaimTraceItem,
    ConflictItem,
    FileSelection,
    QueryAuditResult,
    QueryResult,
)
import cognitive_book_os.orchestration as orchestration


@pytest.fixture
def prepared_brains(tmp_path):
    a = Brain("brain_a", base_path=tmp_path)
    b = Brain("brain_b", base_path=tmp_path)
    a.initialize("obj a")
    b.initialize("obj b")
    a.write_file("facts/a.md", "# A\n\n- Fact A")
    b.write_file("facts/b.md", "# B\n\n- Fact B")
    return tmp_path, a, b


def test_orchestrate_multi_brain_query_with_claims(monkeypatch, prepared_brains):
    base, a, b = prepared_brains

    monkeypatch.setattr(orchestration, "get_client", lambda provider, model: object())
    monkeypatch.setattr(
        orchestration,
        "select_relevant_files",
        lambda question, brain, client: FileSelection(files=["facts/a.md", "facts/x.md"], reasoning="test"),
    )
    monkeypatch.setattr(orchestration, "claims_versioning_enabled", lambda: True)
    monkeypatch.setattr(orchestration.ClaimStore, "list_claims", lambda self, **kwargs: [1])

    def _audit(question, brain, selected_files, client):
        return QueryAuditResult(
            answer=f"answer from {brain.name}",
            sources=[selected_files[0]],
            confidence="high",
            claim_trace=[
                ClaimTraceItem(
                    claim_id=f"clm_{brain.name}",
                    file_path=selected_files[0],
                    claim_text="Policy iteration converges with theorem constraints.",
                    evidence_quote="Policy iteration converges.",
                    source_locator="chapter_1",
                    confidence="high",
                    user_override=False,
                )
            ],
            trace_completeness={"total_statements": 1, "linked_statements": 1, "completeness_ratio": 1.0},
            query_run_id=f"query_{brain.name}",
        )

    monkeypatch.setattr(orchestration, "answer_from_brain_with_audit", _audit)
    monkeypatch.setattr(
        orchestration,
        "_synthesize_global_answer",
        lambda **kwargs: type("Synth", (), {"answer": "global answer", "confidence": "high"})(),
    )
    monkeypatch.setattr(
        orchestration,
        "_classify_conflicts",
        lambda **kwargs: [
            ConflictItem(
                topic="policy convergence",
                brains_involved=["brain_a", "brain_b"],
                classification="support",
                evidence=["brain_a:clm_brain_a", "brain_b:clm_brain_b"],
            )
        ],
    )

    result = orchestration.orchestrate_multi_brain_query(
        question="How does convergence work?",
        brain_names=[a.name, b.name],
        provider="anthropic",
        model=None,
        include_claim_trace=True,
        include_conflicts=True,
        max_brains=5,
        max_files_per_brain=1,
        brains_dir=str(base),
    )

    assert result.answer == "global answer"
    assert len(result.per_brain) == 2
    assert len(result.conflicts) == 1
    assert any("truncated" in warning for warning in result.warnings)
    assert result.traceability.brains_with_claims == 2


def test_orchestrate_multi_brain_query_missing_brain(prepared_brains):
    base, _, _ = prepared_brains

    with pytest.raises(orchestration.BrainNotFoundError):
        orchestration.orchestrate_multi_brain_query(
            question="test",
            brain_names=["missing_brain"],
            provider="anthropic",
            model=None,
            include_claim_trace=True,
            include_conflicts=True,
            max_brains=5,
            max_files_per_brain=12,
            brains_dir=str(base),
        )


def test_orchestrate_multi_brain_query_degraded_without_claims(monkeypatch, prepared_brains):
    base, a, _ = prepared_brains

    monkeypatch.setattr(orchestration, "get_client", lambda provider, model: object())
    monkeypatch.setattr(
        orchestration,
        "select_relevant_files",
        lambda question, brain, client: FileSelection(files=["facts/a.md"], reasoning="test"),
    )
    monkeypatch.setattr(orchestration, "claims_versioning_enabled", lambda: False)
    monkeypatch.setattr(
        orchestration,
        "answer_from_brain",
        lambda question, brain, selected_files, client: QueryResult(
            answer="fallback answer",
            sources=selected_files,
            confidence="medium",
        ),
    )
    monkeypatch.setattr(
        orchestration,
        "_synthesize_global_answer",
        lambda **kwargs: type("Synth", (), {"answer": "global", "confidence": "medium"})(),
    )
    monkeypatch.setattr(orchestration, "_classify_conflicts", lambda **kwargs: [])

    result = orchestration.orchestrate_multi_brain_query(
        question="test",
        brain_names=[a.name],
        provider="anthropic",
        model=None,
        include_claim_trace=True,
        include_conflicts=True,
        max_brains=5,
        max_files_per_brain=12,
        brains_dir=str(base),
    )

    assert len(result.per_brain) == 1
    assert result.per_brain[0].trace_degraded is True
    assert result.per_brain[0].claim_trace == []
    assert result.traceability.brains_without_claims == 1
