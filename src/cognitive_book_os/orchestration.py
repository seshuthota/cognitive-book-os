"""Multi-brain query orchestration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from pydantic import BaseModel, Field

from .brain import Brain
from .claim_store import ClaimStore, claims_versioning_enabled, generate_run_id
from .llm import LLMClient, get_client
from .models import (
    ClaimTraceItem,
    Confidence,
    ConflictItem,
    MultiBrainQueryResult,
    PerBrainResult,
    QueryAuditResult,
    QueryResult,
    TraceabilitySummary,
)
from .query import answer_from_brain, answer_from_brain_with_audit, select_relevant_files

TRUE_VALUES = {"1", "true", "yes", "on"}


class MultiBrainInputError(ValueError):
    """Raised for invalid multi-brain orchestration request arguments."""


class BrainNotFoundError(ValueError):
    """Raised when one or more requested brains do not exist."""

    def __init__(self, missing_brains: list[str]):
        self.missing_brains = missing_brains
        super().__init__(f"Brains not found: {', '.join(missing_brains)}")


class _GlobalSynthesis(BaseModel):
    """Internal model for global synthesis pass."""

    answer: str
    confidence: Confidence


class _ConflictDecision(BaseModel):
    """Internal conflict classification item."""

    pair_id: str
    topic: str
    classification: str = Field(..., description="support|refute|ambiguous")
    rationale: str = ""


class _ConflictDecisionBatch(BaseModel):
    """Internal model for conflict batch classification."""

    items: list[_ConflictDecision] = Field(default_factory=list)


@dataclass
class _InternalPerBrain:
    """Internal per-brain execution bundle with audit context."""

    result: PerBrainResult
    claim_trace_for_conflicts: list[ClaimTraceItem]


def multi_brain_query_enabled() -> bool:
    """Feature flag for multi-brain query orchestration."""

    return os.getenv("ENABLE_MULTI_BRAIN_QUERY", "0").strip().lower() in TRUE_VALUES


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(token) >= 4}


def _brain_has_claim_metadata(brain: Brain) -> bool:
    if not claims_versioning_enabled():
        return False
    store = ClaimStore(brain)
    return len(store.list_claims(limit=1)) > 0


def _collect_per_brain(
    *,
    question: str,
    brains: list[Brain],
    client: LLMClient,
    max_files_per_brain: int,
    warnings: list[str],
) -> list[_InternalPerBrain]:
    internal: list[_InternalPerBrain] = []

    for brain in brains:
        selection = select_relevant_files(question, brain, client)
        selected_files = list(selection.files)
        if len(selected_files) > max_files_per_brain:
            warnings.append(
                f"Brain '{brain.name}' selected {len(selected_files)} files; truncated to {max_files_per_brain}."
            )
            selected_files = selected_files[:max_files_per_brain]

        has_claims = _brain_has_claim_metadata(brain)

        if not selected_files:
            internal.append(
                _InternalPerBrain(
                    result=PerBrainResult(
                        brain_name=brain.name,
                        answer_excerpt="No relevant files found for this brain.",
                        confidence=Confidence.NONE,
                        sources=[],
                        claim_trace=[],
                        trace_degraded=not has_claims,
                        trace_completeness_ratio=0.0,
                    ),
                    claim_trace_for_conflicts=[],
                )
            )
            continue

        if has_claims:
            audit = answer_from_brain_with_audit(
                question=question,
                brain=brain,
                selected_files=selected_files,
                client=client,
            )
            prefixed_sources = [f"{brain.name}:{source}" for source in audit.sources]
            internal.append(
                _InternalPerBrain(
                    result=PerBrainResult(
                        brain_name=brain.name,
                        answer_excerpt=audit.answer,
                        confidence=audit.confidence,
                        sources=prefixed_sources,
                        claim_trace=audit.claim_trace,
                        trace_degraded=False,
                        trace_completeness_ratio=audit.trace_completeness.completeness_ratio,
                    ),
                    claim_trace_for_conflicts=audit.claim_trace,
                )
            )
            continue

        result = answer_from_brain(
            question=question,
            brain=brain,
            selected_files=selected_files,
            client=client,
        )
        source_paths = result.sources or selected_files
        internal.append(
            _InternalPerBrain(
                result=PerBrainResult(
                    brain_name=brain.name,
                    answer_excerpt=result.answer,
                    confidence=result.confidence,
                    sources=[f"{brain.name}:{source}" for source in source_paths],
                    claim_trace=[],
                    trace_degraded=True,
                    trace_completeness_ratio=0.0,
                ),
                claim_trace_for_conflicts=[],
            )
        )

    return internal


def _synthesize_global_answer(
    *,
    question: str,
    per_brain: list[PerBrainResult],
    client: LLMClient,
) -> _GlobalSynthesis:
    if not per_brain:
        return _GlobalSynthesis(
            answer="I couldn't find relevant information across the selected brains.",
            confidence=Confidence.NONE,
        )

    context_parts: list[str] = []
    for item in per_brain:
        context_parts.append(
            (
                f"## Brain: {item.brain_name}\n"
                f"Confidence: {item.confidence.value}\n"
                f"Sources: {', '.join(item.sources) or 'none'}\n"
                f"Answer: {item.answer_excerpt}\n"
            )
        )

    system_prompt = (
        "You are a rigorous synthesis engine. Combine the per-brain findings into one coherent answer. "
        "Cite where claims come from using brain names and preserve uncertainty when evidence is weak."
    )
    user_prompt = (
        f"Question: {question}\n\n"
        "Per-brain findings:\n"
        + "\n".join(context_parts)
        + "\n\nProvide a unified answer and confidence."
    )

    return client.generate(
        response_model=_GlobalSynthesis,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.2,
    )


def _build_conflict_candidates(
    per_brain_internal: list[_InternalPerBrain],
    max_pairs_per_brain_combo: int = 2,
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []

    for first, second in combinations(per_brain_internal, 2):
        claims_a = first.claim_trace_for_conflicts[:8]
        claims_b = second.claim_trace_for_conflicts[:8]

        if not claims_a or not claims_b:
            continue

        scored: list[tuple[int, ClaimTraceItem, ClaimTraceItem]] = []
        for claim_a in claims_a:
            tokens_a = _tokenize(claim_a.claim_text)
            for claim_b in claims_b:
                if claim_a.claim_id == claim_b.claim_id:
                    continue
                tokens_b = _tokenize(claim_b.claim_text)
                overlap = len(tokens_a & tokens_b)
                if overlap < 2:
                    continue
                if claim_a.claim_text.strip().lower() == claim_b.claim_text.strip().lower():
                    continue
                scored.append((overlap, claim_a, claim_b))

        scored.sort(key=lambda item: item[0], reverse=True)
        for idx, (_, claim_a, claim_b) in enumerate(scored[:max_pairs_per_brain_combo], start=1):
            pair_id = (
                f"{first.result.brain_name}__{second.result.brain_name}__{idx}"
            )
            candidates.append(
                {
                    "pair_id": pair_id,
                    "brain_a": first.result.brain_name,
                    "brain_b": second.result.brain_name,
                    "claim_a": claim_a,
                    "claim_b": claim_b,
                }
            )

    return candidates


def _classify_conflicts(
    *,
    question: str,
    per_brain_internal: list[_InternalPerBrain],
    client: LLMClient,
) -> list[ConflictItem]:
    candidates = _build_conflict_candidates(per_brain_internal)
    if not candidates:
        return []

    lines = []
    for candidate in candidates:
        claim_a = candidate["claim_a"]
        claim_b = candidate["claim_b"]
        lines.append(
            (
                f"PAIR_ID: {candidate['pair_id']}\n"
                f"BRAIN_A: {candidate['brain_a']}\n"
                f"CLAIM_A: {claim_a.claim_text}\n"
                f"EVIDENCE_A: {claim_a.evidence_quote}\n"
                f"BRAIN_B: {candidate['brain_b']}\n"
                f"CLAIM_B: {claim_b.claim_text}\n"
                f"EVIDENCE_B: {claim_b.evidence_quote}\n"
            )
        )

    system_prompt = (
        "You are a contradiction classifier for multi-source knowledge. "
        "Classify each claim pair as support, refute, or ambiguous."
    )
    user_prompt = (
        f"Question: {question}\n\n"
        "Classify these claim pairs:\n\n"
        + "\n".join(lines)
        + "\nRespond with topic and classification for each pair."
    )

    try:
        decisions = client.generate(
            response_model=_ConflictDecisionBatch,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
        )
    except Exception:
        return []

    by_pair = {str(item["pair_id"]): item for item in candidates}
    conflicts: list[ConflictItem] = []
    for decision in decisions.items:
        pair = by_pair.get(decision.pair_id)
        if not pair:
            continue

        normalized = decision.classification.strip().lower()
        if normalized not in {"support", "refute", "ambiguous"}:
            normalized = "ambiguous"

        claim_a = pair["claim_a"]
        claim_b = pair["claim_b"]
        conflicts.append(
            ConflictItem(
                topic=decision.topic or "Cross-brain claim comparison",
                brains_involved=[str(pair["brain_a"]), str(pair["brain_b"])],
                classification=normalized,
                evidence=[
                    f"{pair['brain_a']}:{claim_a.claim_id}",
                    f"{pair['brain_b']}:{claim_b.claim_id}",
                ],
            )
        )

    return conflicts


def _summarize_traceability(per_brain: Iterable[PerBrainResult]) -> TraceabilitySummary:
    per_brain_list = list(per_brain)
    with_claims = [item for item in per_brain_list if not item.trace_degraded]
    degraded = [item.brain_name for item in per_brain_list if item.trace_degraded]

    ratio = 0.0
    if per_brain_list:
        ratio = round(
            sum(item.trace_completeness_ratio for item in per_brain_list) / len(per_brain_list),
            4,
        )

    return TraceabilitySummary(
        brains_with_claims=len(with_claims),
        brains_without_claims=len(degraded),
        overall_completeness_ratio=ratio,
        degraded_brains=degraded,
    )


def orchestrate_multi_brain_query(
    *,
    question: str,
    brain_names: list[str],
    provider: str,
    model: str | None,
    include_claim_trace: bool,
    include_conflicts: bool,
    max_brains: int,
    max_files_per_brain: int,
    brains_dir: str = "brains",
) -> MultiBrainQueryResult:
    """Run a synchronous multi-brain query with conflict analysis."""

    if not question.strip():
        raise MultiBrainInputError("Question is required.")
    if not brain_names:
        raise MultiBrainInputError("At least one brain name is required.")
    if max_brains <= 0 or max_files_per_brain <= 0:
        raise MultiBrainInputError("max_brains and max_files_per_brain must be > 0.")

    warnings: list[str] = []

    deduped = list(dict.fromkeys(name.strip() for name in brain_names if name.strip()))
    if not deduped:
        raise MultiBrainInputError("No valid brain names provided.")

    if len(deduped) > max_brains:
        warnings.append(
            f"Received {len(deduped)} brains; truncated to max_brains={max_brains}."
        )
        deduped = deduped[:max_brains]

    brains = [Brain(name=name, base_path=brains_dir) for name in deduped]
    missing = [brain.name for brain in brains if not brain.exists()]
    if missing:
        raise BrainNotFoundError(missing)

    client = get_client(provider=provider, model=model)

    per_internal = _collect_per_brain(
        question=question,
        brains=brains,
        client=client,
        max_files_per_brain=max_files_per_brain,
        warnings=warnings,
    )
    per_brain = [item.result for item in per_internal]

    global_synthesis = _synthesize_global_answer(
        question=question,
        per_brain=per_brain,
        client=client,
    )

    conflicts = []
    if include_conflicts:
        conflicts = _classify_conflicts(
            question=question,
            per_brain_internal=per_internal,
            client=client,
        )

    if not include_claim_trace:
        for item in per_brain:
            item.claim_trace = []
            item.trace_completeness_ratio = 0.0

    unique_sources: list[str] = []
    seen_sources: set[str] = set()
    for item in per_brain:
        for source in item.sources:
            if source not in seen_sources:
                unique_sources.append(source)
                seen_sources.add(source)

    run_id = generate_run_id("multiquery", "_".join(deduped[:3]))

    return MultiBrainQueryResult(
        answer=global_synthesis.answer,
        confidence=global_synthesis.confidence,
        per_brain=per_brain,
        conflicts=conflicts,
        sources=unique_sources,
        traceability=_summarize_traceability(per_brain),
        query_run_id=run_id,
        warnings=warnings,
    )
