"""Claim versioning and audit storage for Cognitive Book OS."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

from .brain import Brain
from .models import (
    ClaimEvent,
    ClaimSnapshot,
    ClaimStatus,
    ClaimTraceItem,
    Confidence,
    QueryAuditResult,
    QueryResult,
    QueryTraceCompleteness,
    RunRecord,
)

CLAIMS_EVENTS_FILE = "meta/claims_events.jsonl"
CLAIMS_CURRENT_FILE = "meta/claims_current.json"
CLAIMS_RUNS_FILE = "meta/runs.jsonl"
CLAIMS_LOCK_FILE = "meta/claims.lock"


TRUE_VALUES = {"1", "true", "yes", "on"}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _make_short_hash(*parts: str) -> str:
    joined = "|".join(_normalize_text(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in TRUE_VALUES


def claims_versioning_enabled() -> bool:
    """Whether claim versioning should run on writes."""
    return _truthy_env("ENABLE_CLAIM_VERSIONING", "0")


def query_audit_endpoints_enabled() -> bool:
    """Whether audited query endpoints are enabled."""
    return _truthy_env("ENABLE_QUERY_AUDIT_ENDPOINTS", "0")


def provenance_enforcement_mode() -> str:
    """Get provenance enforcement mode: warn|strict|off."""
    mode = os.getenv("PROVENANCE_ENFORCEMENT", "warn").strip().lower()
    return mode if mode in {"warn", "strict", "off"} else "warn"


def generate_run_id(run_type: str, brain_name: str) -> str:
    """Generate a stable run identifier prefix for audit records."""
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    suffix = _make_short_hash(run_type, brain_name, stamp)
    return f"{run_type}_{brain_name}_{suffix}"


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter_raw = parts[1]
    body = parts[2]
    try:
        frontmatter = yaml.safe_load(frontmatter_raw) or {}
    except yaml.YAMLError:
        frontmatter = {}
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, body


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(t) >= 4}


def _extract_quotes(body: str) -> list[tuple[str, str]]:
    quotes: list[tuple[str, str]] = []
    source_pattern = re.compile(r"\(Source:\s*([^)]+)\)", re.IGNORECASE)

    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith(">"):
            continue

        quote_text = stripped.lstrip(">").strip()
        source = ""
        source_match = source_pattern.search(quote_text)
        if source_match:
            source = source_match.group(1).strip()
            quote_text = source_pattern.sub("", quote_text).strip()

        quote_text = quote_text.strip('"').strip()
        if quote_text:
            quotes.append((quote_text, source))

    return quotes


def _extract_claim_lines(body: str) -> list[str]:
    claims: list[str] = []
    current_section = ""

    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("#"):
            current_section = stripped.lstrip("#").strip().lower()
            continue

        match = re.match(r"^(?:-|\*|\d+\.)\s+(.+)$", stripped)
        if match:
            text = match.group(1).strip()
            if text.lower().startswith("[["):
                continue
            if current_section.startswith("related"):
                continue
            if len(text) >= 8:
                claims.append(text)
            continue

        if stripped.lower().startswith("**claim**"):
            claim_text = stripped.split(":", 1)[-1].strip()
            if len(claim_text) >= 8:
                claims.append(claim_text)

    if claims:
        # Preserve order while de-duplicating.
        return list(dict.fromkeys(claims))

    fallback_lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ">", "-", "*")):
            continue
        fallback_lines.extend(re.split(r"(?<=[.!?])\s+", stripped))

    filtered = [s.strip() for s in fallback_lines if len(s.strip().split()) >= 6]
    return list(dict.fromkeys(filtered[:5]))


def _choose_quote_for_claim(claim_text: str, quotes: list[tuple[str, str]]) -> tuple[str, str]:
    if not quotes:
        return "", ""

    claim_tokens = _tokenize(claim_text)
    best = ("", "")
    best_score = -1

    for quote_text, source in quotes:
        quote_tokens = _tokenize(quote_text)
        score = len(claim_tokens & quote_tokens)
        if score > best_score:
            best = (quote_text, source)
            best_score = score

    return best


def _safe_confidence(value: Any) -> Confidence:
    if isinstance(value, Confidence):
        return value
    if isinstance(value, str):
        try:
            return Confidence(value.strip().lower())
        except ValueError:
            return Confidence.MEDIUM
    return Confidence.MEDIUM


class ClaimStore:
    """Persistent claim audit storage attached to a brain."""

    def __init__(self, brain: Brain):
        self.brain = brain

    @contextlib.contextmanager
    def _lock(self):
        lock_path = self.brain.path / CLAIMS_LOCK_FILE
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _read_json(self, relative_path: str) -> dict[str, Any]:
        raw = self.brain.read_file(relative_path)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}

    def _write_json(self, relative_path: str, payload: dict[str, Any]) -> None:
        self.brain.write_file(relative_path, json.dumps(payload, ensure_ascii=True, indent=2))

    def _append_jsonl(self, relative_path: str, payload: dict[str, Any]) -> None:
        target = self.brain.path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def _load_events(self) -> list[ClaimEvent]:
        events_path = self.brain.path / CLAIMS_EVENTS_FILE
        if not events_path.exists():
            return []

        events: list[ClaimEvent] = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = ClaimEvent.model_validate_json(line)
                events.append(event)
            except ValueError:
                continue
        return events

    def _emit_event(
        self,
        *,
        event_type: str,
        run_id: str,
        claim_id: str | None = None,
        revision_id: str | None = None,
        file_path: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event = ClaimEvent(
            event_id=f"evt_{_make_short_hash(event_type, run_id, _now_iso(), claim_id or '')}",
            event_type=event_type,
            timestamp=_now_iso(),
            brain_name=self.brain.name,
            run_id=run_id,
            claim_id=claim_id,
            revision_id=revision_id,
            file_path=file_path,
            payload=payload or {},
        )
        self._append_jsonl(CLAIMS_EVENTS_FILE, event.model_dump())

    def load_current_claims(self) -> dict[str, ClaimSnapshot]:
        payload = self._read_json(CLAIMS_CURRENT_FILE)
        raw_claims = payload.get("claims", {})
        if not isinstance(raw_claims, dict):
            return {}

        claims: dict[str, ClaimSnapshot] = {}
        for claim_id, raw in raw_claims.items():
            try:
                claims[claim_id] = ClaimSnapshot.model_validate(raw)
            except ValueError:
                continue
        return claims

    def _save_current_claims(self, claims: dict[str, ClaimSnapshot]) -> None:
        payload = {
            "updated_at": _now_iso(),
            "claims": {cid: claim.model_dump() for cid, claim in claims.items()},
        }
        self._write_json(CLAIMS_CURRENT_FILE, payload)

    def list_claims(
        self,
        *,
        file_path: str | None = None,
        status: ClaimStatus | None = None,
        tag: str | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ClaimSnapshot]:
        claims = list(self.load_current_claims().values())

        if file_path:
            claims = [c for c in claims if c.file_path == file_path]
        if status:
            claims = [c for c in claims if c.status == status]
        if tag:
            claims = [c for c in claims if tag in c.tags]
        if q:
            term = q.lower()
            claims = [
                c for c in claims
                if term in c.claim_text.lower() or term in c.evidence_quote.lower()
            ]

        claims.sort(key=lambda c: c.updated_at, reverse=True)
        return claims[offset:offset + max(limit, 0)]

    def get_claim(self, claim_id: str) -> ClaimSnapshot | None:
        return self.load_current_claims().get(claim_id)

    def get_claim_history(self, claim_id: str) -> list[ClaimEvent]:
        history = [event for event in self._load_events() if event.claim_id == claim_id]
        history.sort(key=lambda event: event.timestamp)
        return history

    def _extract_claim_snapshots(
        self,
        *,
        file_path: str,
        content: str,
        run_id: str,
    ) -> tuple[list[ClaimSnapshot], list[str]]:
        frontmatter, body = _split_frontmatter(content)
        source_default = str(frontmatter.get("source", "")).strip()
        tags = frontmatter.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        confidence = _safe_confidence(frontmatter.get("confidence", "medium"))

        quotes = _extract_quotes(body)
        claim_lines = _extract_claim_lines(body)

        warnings: list[str] = []
        snapshots: list[ClaimSnapshot] = []
        now = _now_iso()

        for claim_text in claim_lines:
            evidence_quote, quote_source = _choose_quote_for_claim(claim_text, quotes)
            source_locator = (quote_source or source_default or "unknown").strip()

            if not evidence_quote:
                warnings.append(f"Missing direct quote for claim: {claim_text[:120]}")
            if source_locator == "unknown":
                warnings.append(f"Missing source locator for claim: {claim_text[:120]}")

            claim_id = f"clm_{_make_short_hash(self.brain.name, file_path, claim_text, evidence_quote, source_locator)}"
            revision_id = f"rev_{_make_short_hash(claim_id, run_id, now)}"

            snapshots.append(
                ClaimSnapshot(
                    claim_id=claim_id,
                    revision_id=revision_id,
                    status=ClaimStatus.ACTIVE,
                    brain_name=self.brain.name,
                    file_path=file_path,
                    claim_text=claim_text,
                    evidence_quote=evidence_quote,
                    source_locator=source_locator,
                    confidence=confidence,
                    tags=[str(t) for t in tags],
                    related_claim_ids=[],
                    created_at=now,
                    updated_at=now,
                    created_by_run=run_id,
                    updated_by_run=run_id,
                    supersedes_revision_id=None,
                    user_override=file_path.startswith("notes/"),
                )
            )

        if not snapshots:
            warnings.append("No claim candidates extracted from file content.")

        return snapshots, warnings

    def track_file_claims(
        self,
        *,
        file_path: str,
        content: str,
        run_id: str,
    ) -> dict[str, int]:
        """Create/refresh claim snapshots for a file and persist lifecycle events."""
        enforcement = provenance_enforcement_mode()

        with self._lock():
            current = self.load_current_claims()
            active_for_file = {
                cid: claim
                for cid, claim in current.items()
                if claim.file_path == file_path and claim.status == ClaimStatus.ACTIVE
            }

            extracted, warnings = self._extract_claim_snapshots(
                file_path=file_path,
                content=content,
                run_id=run_id,
            )

            created = 0
            unchanged = 0
            superseded = 0
            now = _now_iso()
            new_ids = {claim.claim_id for claim in extracted}

            for claim in extracted:
                existing = current.get(claim.claim_id)
                if existing and existing.status == ClaimStatus.ACTIVE:
                    claim.revision_id = existing.revision_id
                    claim.created_at = existing.created_at
                    claim.created_by_run = existing.created_by_run
                    claim.updated_at = now
                    claim.updated_by_run = run_id
                    current[claim.claim_id] = claim
                    unchanged += 1
                    continue

                current[claim.claim_id] = claim
                created += 1
                self._emit_event(
                    event_type="claim_created",
                    run_id=run_id,
                    claim_id=claim.claim_id,
                    revision_id=claim.revision_id,
                    file_path=file_path,
                    payload={
                        "claim_text": claim.claim_text,
                        "source_locator": claim.source_locator,
                        "user_override": claim.user_override,
                    },
                )

            for old_id, old_claim in active_for_file.items():
                if old_id in new_ids:
                    continue

                old_claim.status = ClaimStatus.SUPERSEDED
                old_claim.updated_at = now
                old_claim.updated_by_run = run_id
                current[old_id] = old_claim
                superseded += 1
                self._emit_event(
                    event_type="claim_superseded",
                    run_id=run_id,
                    claim_id=old_id,
                    revision_id=old_claim.revision_id,
                    file_path=file_path,
                    payload={"reason": "not_present_in_latest_file_revision"},
                )

            warning_count = 0
            if enforcement != "off":
                for warning in warnings:
                    warning_count += 1
                    self._emit_event(
                        event_type="provenance_warning",
                        run_id=run_id,
                        file_path=file_path,
                        payload={"message": warning},
                    )

            self._save_current_claims(current)

            if warnings and enforcement == "strict":
                raise ValueError(warnings[0])

            return {
                "created": created,
                "unchanged": unchanged,
                "superseded": superseded,
                "warnings": warning_count,
            }

    def start_run(
        self,
        *,
        run_type: str,
        objective: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        run_id = generate_run_id(run_type, self.brain.name)
        record = RunRecord(
            run_id=run_id,
            run_type=run_type,
            brain_name=self.brain.name,
            objective=objective,
            provider=provider,
            model=model,
            started_at=_now_iso(),
            metadata=metadata or {},
        )
        with self._lock():
            self._append_jsonl(CLAIMS_RUNS_FILE, record.model_dump())
        return run_id

    def finish_run(self, *, run_id: str, run_type: str, status: str, error: str | None = None) -> None:
        record = RunRecord(
            run_id=run_id,
            run_type=run_type,
            brain_name=self.brain.name,
            started_at=_now_iso(),
            finished_at=_now_iso(),
            status=status,
            error=error,
        )
        with self._lock():
            self._append_jsonl(CLAIMS_RUNS_FILE, record.model_dump())

    def _active_claims_for_files(self, files: Iterable[str]) -> list[ClaimSnapshot]:
        wanted = set(files)
        claims = self.load_current_claims().values()
        return [
            claim for claim in claims
            if claim.status == ClaimStatus.ACTIVE and claim.file_path in wanted
        ]

    def build_query_audit(
        self,
        *,
        question: str,
        result: QueryResult,
        default_sources: list[str],
        run_id: str,
    ) -> QueryAuditResult:
        sources = result.sources or default_sources
        active_claims = self._active_claims_for_files(sources)

        question_tokens = _tokenize(question)
        answer_tokens = _tokenize(result.answer)

        scored: list[tuple[int, ClaimSnapshot]] = []
        for claim in active_claims:
            claim_tokens = _tokenize(claim.claim_text + " " + claim.evidence_quote)
            score = len(claim_tokens & question_tokens) * 2 + len(claim_tokens & answer_tokens)
            scored.append((score, claim))

        scored.sort(key=lambda item: item[0], reverse=True)

        trace_items: list[ClaimTraceItem] = []
        seen_ids: set[str] = set()
        per_file_counts: dict[str, int] = {}

        for _, claim in scored:
            count = per_file_counts.get(claim.file_path, 0)
            if count >= 3:
                continue
            if claim.claim_id in seen_ids:
                continue

            trace_items.append(
                ClaimTraceItem(
                    claim_id=claim.claim_id,
                    file_path=claim.file_path,
                    claim_text=claim.claim_text,
                    evidence_quote=claim.evidence_quote,
                    source_locator=claim.source_locator,
                    confidence=claim.confidence,
                    user_override=claim.user_override,
                )
            )
            seen_ids.add(claim.claim_id)
            per_file_counts[claim.file_path] = count + 1

        with self._lock():
            for item in trace_items:
                self._emit_event(
                    event_type="claim_cited_in_answer",
                    run_id=run_id,
                    claim_id=item.claim_id,
                    file_path=item.file_path,
                    payload={
                        "question": question,
                        "source_locator": item.source_locator,
                    },
                )

        statements = [
            stmt.strip()
            for stmt in re.split(r"[\n.!?]+", result.answer)
            if stmt.strip()
        ]
        linked_by_file = {item.file_path for item in trace_items}

        linked_statements = 0
        if statements:
            citation_pattern = re.compile(r"\[([^\]]+\.md)\]")
            for statement in statements:
                matches = citation_pattern.findall(statement)
                if matches:
                    if any(match in linked_by_file for match in matches):
                        linked_statements += 1
                elif trace_items:
                    linked_statements += 1

        total_statements = len(statements)
        completeness_ratio = 0.0
        if total_statements > 0:
            completeness_ratio = round(linked_statements / total_statements, 4)

        completeness = QueryTraceCompleteness(
            total_statements=total_statements,
            linked_statements=linked_statements,
            completeness_ratio=completeness_ratio,
        )

        return QueryAuditResult(
            answer=result.answer,
            sources=sources,
            confidence=result.confidence,
            claim_trace=trace_items,
            trace_completeness=completeness,
            query_run_id=run_id,
        )
