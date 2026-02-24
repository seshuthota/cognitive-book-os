"""Tests for claim versioning and audit storage."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cognitive_book_os.brain import Brain
from cognitive_book_os.claim_store import ClaimStore
from cognitive_book_os.models import ClaimStatus, QueryResult


def _sample_content(claim_text: str, quote_text: str) -> str:
    return f"""---
source: chapter_1
confidence: high
tags: [test, claims]
---

# Facts

**Key Details**:
- {claim_text}

**Quotes**:
> \"{quote_text}\" (Source: Chapter 1)
"""


def test_track_file_claims_creates_snapshots_and_events(tmp_path):
    brain = Brain("claim-brain", base_path=tmp_path)
    brain.initialize("Track claims")

    store = ClaimStore(brain)
    run_id = "ingest_claim_brain_run1"

    summary = store.track_file_claims(
        file_path="facts/sample.md",
        content=_sample_content("The launch window opens at 0900 UTC.", "Launch window opens at 0900 UTC."),
        run_id=run_id,
    )

    assert summary["created"] >= 1

    claims = store.list_claims(status=ClaimStatus.ACTIVE)
    assert claims
    assert claims[0].file_path == "facts/sample.md"

    history = store.get_claim_history(claims[0].claim_id)
    assert any(event.event_type == "claim_created" for event in history)


def test_track_file_claims_supersedes_previous_claims(tmp_path):
    brain = Brain("claim-brain-2", base_path=tmp_path)
    brain.initialize("Track revisions")

    store = ClaimStore(brain)

    store.track_file_claims(
        file_path="facts/sample.md",
        content=_sample_content("Claim A includes timeline details.", "Quote A"),
        run_id="ingest_run_1",
    )
    first_active = store.list_claims(status=ClaimStatus.ACTIVE)
    assert len(first_active) == 1

    store.track_file_claims(
        file_path="facts/sample.md",
        content=_sample_content("Claim B includes timeline details.", "Quote B"),
        run_id="ingest_run_2",
    )

    active_claims = store.list_claims(status=ClaimStatus.ACTIVE)
    superseded_claims = store.list_claims(status=ClaimStatus.SUPERSEDED)

    assert len(active_claims) == 1
    assert active_claims[0].claim_text == "Claim B includes timeline details."
    assert len(superseded_claims) == 1
    assert superseded_claims[0].claim_text == "Claim A includes timeline details."


def test_build_query_audit_links_claim_trace(tmp_path):
    brain = Brain("claim-brain-3", base_path=tmp_path)
    brain.initialize("Audit query")

    store = ClaimStore(brain)
    store.track_file_claims(
        file_path="facts/sample.md",
        content=_sample_content("Mars mission launches in April.", "Mars mission launches in April."),
        run_id="ingest_run_audit",
    )

    query_result = QueryResult(
        answer="The mission launches in April [facts/sample.md].",
        sources=["facts/sample.md"],
        confidence="high",
    )

    audit = store.build_query_audit(
        question="When does the mission launch?",
        result=query_result,
        default_sources=["facts/sample.md"],
        run_id="query_run_audit",
    )

    assert audit.claim_trace
    assert audit.trace_completeness.completeness_ratio >= 0.0

    claim_id = audit.claim_trace[0].claim_id
    history = store.get_claim_history(claim_id)
    assert any(event.event_type == "claim_cited_in_answer" for event in history)
