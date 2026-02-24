"""Tests for FastAPI server endpoints and production-safety behaviors."""

import sys
import io
import subprocess
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import cognitive_book_os.server as server_module
import cognitive_book_os.enrichment as enrichment_module
from cognitive_book_os.brain import Brain
from cognitive_book_os.claim_store import ClaimStore
from cognitive_book_os.models import (
    FileSelection,
    MultiBrainQueryResult,
    QueryAuditResult,
    TraceabilitySummary,
)


def _make_test_client(tmp_path, monkeypatch) -> TestClient:
    """Create a test client with isolated storage and clean job state."""
    if server_module._gardener_scheduler is not None:
        server_module._gardener_scheduler.stop()
        server_module._gardener_scheduler = None

    monkeypatch.setattr(server_module, "BRAINS_DIR", str(tmp_path))
    monkeypatch.setattr(server_module, "REQUIRE_API_KEY", "")
    monkeypatch.setattr(server_module, "RATE_LIMIT_PER_MINUTE", 0)
    monkeypatch.setattr(server_module, "JOB_STORE_BACKEND", "json")
    monkeypatch.setattr(server_module, "JOB_STORE_PATH", tmp_path / "job_store_test.json")
    monkeypatch.setattr(server_module, "JOB_STORE_SQLITE_PATH", tmp_path / "job_store_test.db")
    monkeypatch.setattr(server_module, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(server_module, "INGEST_TIMEOUT_SEC", 30)
    monkeypatch.setattr(server_module, "ENABLE_METRICS", True)
    monkeypatch.setattr(server_module, "METRICS_API_KEY", "")
    monkeypatch.setattr(server_module, "METRICS_MAX_PATHS", 200)
    monkeypatch.setattr(server_module, "GARDENER_ENABLED", False)
    monkeypatch.setattr(server_module, "GARDENER_DRY_RUN", True)
    monkeypatch.setattr(server_module, "GARDENER_INTERVAL", "weekly")
    monkeypatch.setattr(server_module, "GARDENER_BRAIN_EXCLUDE", tuple())
    monkeypatch.setattr(server_module, "GARDENER_REPORT_RETENTION", 20)
    monkeypatch.setattr(server_module, "GARDENER_PROVIDER", "minimax")
    monkeypatch.setattr(server_module, "GARDENER_MODEL", None)

    server_module.ingestion_jobs.clear()
    server_module.enrichment_jobs.clear()
    server_module.gardener_runs.clear()
    server_module.rate_limit_store.clear()
    with server_module._metrics_lock:
        server_module._operational_metrics.clear()
        server_module._operational_metrics.update({
            "started_at": "2026-01-01T00:00:00",
            "requests_total": 0,
            "responses_by_status": {},
            "requests_by_method": {},
            "requests_by_path": {},
            "auth_failures": 0,
            "rate_limited": 0,
            "latency_ms": {"count": 0, "sum": 0.0, "max": 0.0},
        })
    return TestClient(server_module.app)


def test_health_check(tmp_path, monkeypatch):
    """Health endpoint should be available for probes."""
    client = _make_test_client(tmp_path, monkeypatch)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers.get("x-request-id")


def test_readiness_check_ok(tmp_path, monkeypatch):
    """Readiness endpoint should report ok when storage dependencies are healthy."""
    client = _make_test_client(tmp_path, monkeypatch)
    response = client.get("/health/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["brains_dir"]["ok"] is True
    assert payload["checks"]["job_store"]["ok"] is True
    assert response.headers.get("x-request-id")


def test_readiness_check_reports_degraded_when_sqlite_unavailable(tmp_path, monkeypatch):
    """Readiness endpoint should return 503 when sqlite backend cannot initialize."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "JOB_STORE_BACKEND", "sqlite")

    def _failing_connect(*args, **kwargs):
        raise sqlite3.Error("sqlite unavailable")

    monkeypatch.setattr(server_module.sqlite3, "connect", _failing_connect)
    response = client.get("/health/ready")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["checks"]["job_store"]["ok"] is False


def test_metrics_endpoint_tracks_requests(tmp_path, monkeypatch):
    """Metrics endpoint should expose aggregated request/latency counters."""
    client = _make_test_client(tmp_path, monkeypatch)
    client.get("/health")
    client.get("/health")

    response = client.get("/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["requests_total"] >= 2
    assert payload["responses_by_status"].get("200", 0) >= 2
    assert payload["requests_by_method"].get("GET", 0) >= 2
    assert payload["latency_ms"]["count"] >= 2


def test_metrics_endpoint_requires_metrics_key_when_configured(tmp_path, monkeypatch):
    """Metrics endpoint should require x-metrics-key when METRICS_API_KEY is set."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "METRICS_API_KEY", "metrics-secret")

    unauthorized = client.get("/metrics")
    assert unauthorized.status_code == 401

    authorized = client.get("/metrics", headers={"x-metrics-key": "metrics-secret"})
    assert authorized.status_code == 200


def test_metrics_endpoint_can_be_disabled(tmp_path, monkeypatch):
    """Metrics endpoint should return 404 when disabled."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "ENABLE_METRICS", False)

    response = client.get("/metrics")
    assert response.status_code == 404


def test_gardener_status_endpoint_returns_defaults(tmp_path, monkeypatch):
    """Gardener status endpoint should return scheduler/config defaults."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "GARDENER_ENABLED", False)
    monkeypatch.setattr(server_module, "GARDENER_INTERVAL", "weekly")

    response = client.get("/gardener/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["defaults"]["interval"] == "weekly"
    assert "scheduler" in payload
    assert "active_run_id" in payload


def test_gardener_trigger_sync_generates_reports_and_history(tmp_path, monkeypatch):
    """Manual gardener trigger should create run history and report artifacts."""
    client = _make_test_client(tmp_path, monkeypatch)
    brain = Brain("gardener-brain", base_path=tmp_path)
    brain.initialize("keep this clean")

    monkeypatch.setattr(
        server_module,
        "run_gardener_for_brain",
        lambda brain, dry_run, provider, model: {
            "mode": "dry_run",
            "summary_counts": {
                "files_reviewed": 5,
                "duplicate_clusters": 1,
                "files_in_clusters": 2,
                "merges_proposed": 1,
                "merges_applied": 0,
            },
            "llm_steps": {"status": "skipped", "executed": False, "reason": "dry_run"},
            "issues": [],
            "recommendations": ["ok"],
            "clusters": [{"anchor": "facts/a.md", "files": ["facts/a.md", "facts/a_1.md"]}],
        },
    )

    response = client.post(
        "/gardener/trigger",
        json={"dry_run": True, "async_run": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    run_id = payload["run_id"]

    history = client.get("/gardener/history")
    assert history.status_code == 200
    runs = history.json()["runs"]
    assert len(runs) >= 1
    assert runs[0]["run_id"] == run_id
    assert runs[0]["status"] == "completed"

    json_report = brain.path / "meta" / "reports" / f"gardener_{run_id}.json"
    md_report = brain.path / "meta" / "reports" / f"gardener_{run_id}.md"
    assert json_report.exists()
    assert md_report.exists()


def test_gardener_trigger_rejects_missing_brain(tmp_path, monkeypatch):
    """Manual trigger with explicit unknown brain should return 404."""
    client = _make_test_client(tmp_path, monkeypatch)
    response = client.post(
        "/gardener/trigger",
        json={"dry_run": True, "brain_ids": ["does-not-exist"], "async_run": False},
    )
    assert response.status_code == 404


def test_gardener_report_retention_prunes_older_runs(tmp_path, monkeypatch):
    """Gardener reports should retain only configured number per brain."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "GARDENER_REPORT_RETENTION", 2)

    brain = Brain("retention-brain", base_path=tmp_path)
    brain.initialize("retention objective")

    monkeypatch.setattr(
        server_module,
        "run_gardener_for_brain",
        lambda brain, dry_run, provider, model: {
            "mode": "dry_run",
            "summary_counts": {
                "files_reviewed": 1,
                "duplicate_clusters": 0,
                "files_in_clusters": 0,
                "merges_proposed": 0,
                "merges_applied": 0,
            },
            "llm_steps": {"status": "skipped", "executed": False, "reason": "dry_run"},
            "issues": [],
            "recommendations": ["none"],
            "clusters": [],
        },
    )

    for _ in range(3):
        response = client.post("/gardener/trigger", json={"dry_run": True, "async_run": False})
        assert response.status_code == 200

    report_dir = brain.path / "meta" / "reports"
    assert len(list(report_dir.glob("gardener_*.json"))) == 2
    assert len(list(report_dir.glob("gardener_*.md"))) == 2


def test_middleware_emits_structured_request_log(tmp_path, monkeypatch, caplog):
    """Request middleware should emit a structured request log entry."""
    client = _make_test_client(tmp_path, monkeypatch)
    caplog.set_level("INFO", logger="cognitive_book_os.server")

    response = client.get("/health")
    assert response.status_code == 200
    assert any(
        "\"event\": \"http_request\"" in record.message and "\"path\": \"/health\"" in record.message
        for record in caplog.records
    )


def test_api_key_middleware_blocks_unauthorized(tmp_path, monkeypatch):
    """When configured, API key middleware should reject missing/invalid keys."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "REQUIRE_API_KEY", "secret-key")

    unauthorized = client.get("/health")
    assert unauthorized.status_code == 401
    assert unauthorized.headers.get("x-request-id")

    authorized = client.get("/health", headers={"x-api-key": "secret-key"})
    assert authorized.status_code == 200


def test_rate_limit_middleware_enforces_limit(tmp_path, monkeypatch):
    """Rate limiter should return 429 after exceeding configured per-minute budget."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "RATE_LIMIT_PER_MINUTE", 2)

    first = client.get("/health")
    second = client.get("/health")
    third = client.get("/health")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers.get("x-request-id")


def test_trim_job_history_keeps_recent_entries():
    """Job store should be capped to configured history size."""
    store = {
        "j1": {"started_at": "2026-01-01T00:00:00"},
        "j2": {"started_at": "2026-01-01T00:00:01"},
        "j3": {"started_at": "2026-01-01T00:00:02"},
    }
    server_module._trim_job_history(store, max_items=2)
    assert len(store) == 2
    assert "j1" not in store
    assert "j2" in store and "j3" in store


def test_job_store_persists_and_loads(tmp_path, monkeypatch):
    """Job store should be saved to disk and restored correctly."""
    store_path = tmp_path / "persisted_jobs.json"
    monkeypatch.setattr(server_module, "JOB_STORE_BACKEND", "json")
    monkeypatch.setattr(server_module, "JOB_STORE_PATH", store_path)

    server_module.ingestion_jobs.clear()
    server_module.enrichment_jobs.clear()

    server_module._upsert_job(
        server_module.ingestion_jobs,
        "ingest_1",
        {"job_id": "ingest_1", "status": "processing"},
    )
    server_module._upsert_job(
        server_module.enrichment_jobs,
        "enrich_1",
        {"job_id": "enrich_1", "status": "completed"},
    )
    assert store_path.exists()

    server_module.ingestion_jobs.clear()
    server_module.enrichment_jobs.clear()
    server_module._load_job_store()

    assert server_module.ingestion_jobs["ingest_1"]["status"] == "processing"
    assert server_module.enrichment_jobs["enrich_1"]["status"] == "completed"


def test_job_store_sqlite_persists_and_loads(tmp_path, monkeypatch):
    """SQLite job store should save and restore ingestion/enrichment jobs."""
    db_path = tmp_path / "persisted_jobs.db"
    monkeypatch.setattr(server_module, "JOB_STORE_BACKEND", "sqlite")
    monkeypatch.setattr(server_module, "JOB_STORE_SQLITE_PATH", db_path)

    server_module.ingestion_jobs.clear()
    server_module.enrichment_jobs.clear()

    server_module._upsert_job(
        server_module.ingestion_jobs,
        "ingest_sql_1",
        {"job_id": "ingest_sql_1", "status": "processing"},
    )
    server_module._upsert_job(
        server_module.enrichment_jobs,
        "enrich_sql_1",
        {"job_id": "enrich_sql_1", "status": "completed"},
    )
    assert db_path.exists()

    server_module.ingestion_jobs.clear()
    server_module.enrichment_jobs.clear()
    server_module._load_job_store()

    assert server_module.ingestion_jobs["ingest_sql_1"]["status"] == "processing"
    assert server_module.enrichment_jobs["enrich_sql_1"]["status"] == "completed"


def test_get_file_rejects_path_traversal(tmp_path, monkeypatch):
    """Path traversal attempts should be rejected with 400."""
    client = _make_test_client(tmp_path, monkeypatch)
    brain = Brain("secure-brain", base_path=tmp_path)
    brain.initialize("test objective")
    brain.write_file("notes/a.md", "hello")

    response = client.get(f"/brains/{brain.name}/files/..%2Fmeta%2Fprocessing_log.json")
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid file path"


def test_query_auto_enrich_schedules_background_job(tmp_path, monkeypatch):
    """Auto-enrichment should schedule a background job when async_enrich is enabled."""
    client = _make_test_client(tmp_path, monkeypatch)
    brain = Brain("query-brain", base_path=tmp_path)
    brain.initialize("test objective")

    # Avoid external calls and force "no initial answer -> enrich needed" path.
    monkeypatch.setattr(server_module, "get_client", lambda provider, model: object())
    monkeypatch.setattr(
        server_module,
        "select_relevant_files",
        lambda question, brain, llm_client: FileSelection(files=[], reasoning="none"),
    )
    monkeypatch.setattr(enrichment_module.EnrichmentManager, "evaluate_gap", lambda self, q, p, m: (True, [1]))
    monkeypatch.setattr(enrichment_module.EnrichmentManager, "enrich", lambda self, q, p, m: None)

    response = client.post(
        f"/brains/{brain.name}/query",
        json={
            "question": "Where is the missing fact?",
            "auto_enrich": True,
            "async_enrich": True,
            "provider": "anthropic",
        },
    )

    assert response.status_code == 200
    assert response.json()["confidence"] == "none"

    job_id = response.headers.get("X-Enrichment-Job-ID")
    assert job_id is not None

    status_response = client.get(f"/enrichment-jobs/{job_id}")
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["brain_name"] == brain.name
    assert payload["status"] in ("processing", "completed")


def test_claim_endpoints_list_show_history(tmp_path, monkeypatch):
    """Claim endpoints should expose snapshots and lifecycle history when enabled."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "ENABLE_CLAIM_VERSIONING", True)

    brain = Brain("claim-api-brain", base_path=tmp_path)
    brain.initialize("claim api objective")
    store = ClaimStore(brain)
    store.track_file_claims(
        file_path="facts/a.md",
        run_id="ingest_claim_api_1",
        content="""---
source: chapter_1
---

# Facts

- The reactor starts at dawn.
> "The reactor starts at dawn." (Source: Chapter 1)
""",
    )

    list_response = client.get(f"/brains/{brain.name}/claims")
    assert list_response.status_code == 200
    claims = list_response.json()["claims"]
    assert len(claims) >= 1

    claim_id = claims[0]["claim_id"]
    show_response = client.get(f"/brains/{brain.name}/claims/{claim_id}")
    assert show_response.status_code == 200
    assert show_response.json()["claim_id"] == claim_id

    history_response = client.get(f"/brains/{brain.name}/claims/{claim_id}/history")
    assert history_response.status_code == 200
    assert any(event["event_type"] == "claim_created" for event in history_response.json()["events"])


def test_query_audit_endpoint_returns_trace(tmp_path, monkeypatch):
    """Audited query endpoint should return answer + claim trace payload."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "ENABLE_CLAIM_VERSIONING", True)
    monkeypatch.setattr(server_module, "ENABLE_QUERY_AUDIT_ENDPOINTS", True)

    brain = Brain("audit-api-brain", base_path=tmp_path)
    brain.initialize("audit objective")

    monkeypatch.setattr(server_module, "get_client", lambda provider, model: object())
    monkeypatch.setattr(
        server_module,
        "select_relevant_files",
        lambda question, brain, llm_client: FileSelection(files=["facts/a.md"], reasoning="test"),
    )
    monkeypatch.setattr(
        server_module,
        "answer_from_brain_with_audit",
        lambda question, brain, selected_files, client: QueryAuditResult(
            answer="Audited answer [facts/a.md].",
            sources=["facts/a.md"],
            confidence="high",
            claim_trace=[],
            trace_completeness={"total_statements": 1, "linked_statements": 1, "completeness_ratio": 1.0},
            query_run_id="query_audit_1",
        ),
    )

    response = client.post(
        f"/brains/{brain.name}/query/audit",
        json={"question": "What happened?", "provider": "anthropic"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query_run_id"] == "query_audit_1"
    assert payload["sources"] == ["facts/a.md"]


def test_multi_brain_query_endpoint_requires_feature_flag(tmp_path, monkeypatch):
    """Multi-brain endpoint should return 404 when feature is disabled."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "ENABLE_MULTI_BRAIN_QUERY", False)

    response = client.post(
        "/multi-brain/query",
        json={
            "question": "What happened?",
            "brains": ["a", "b"],
            "provider": "anthropic",
        },
    )
    assert response.status_code == 404


def test_multi_brain_query_endpoint_success_and_limits(tmp_path, monkeypatch):
    """Multi-brain endpoint should forward clamped limits to orchestration."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "ENABLE_MULTI_BRAIN_QUERY", True)
    monkeypatch.setattr(server_module, "MULTI_BRAIN_MAX_BRAINS", 5)
    monkeypatch.setattr(server_module, "MULTI_BRAIN_MAX_FILES_PER_BRAIN", 12)

    captured = {}

    def _fake_orchestrate(**kwargs):
        captured.update(kwargs)
        return MultiBrainQueryResult(
            answer="global",
            confidence="high",
            per_brain=[],
            conflicts=[],
            sources=[],
            traceability=TraceabilitySummary(),
            query_run_id="multi_1",
            warnings=[],
        )

    monkeypatch.setattr(server_module, "orchestrate_multi_brain_query", _fake_orchestrate)

    response = client.post(
        "/multi-brain/query",
        json={
            "question": "Cross compare",
            "brains": ["a", "b", "c", "d", "e", "f"],
            "provider": "anthropic",
            "max_brains": 999,
            "max_files_per_brain": 999,
            "include_conflicts": True,
            "include_claim_trace": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["query_run_id"] == "multi_1"
    assert captured["max_brains"] == 5
    assert captured["max_files_per_brain"] == 12


def test_ingest_rejects_non_pdf_upload(tmp_path, monkeypatch):
    """Ingestion endpoint should reject non-PDF content."""
    client = _make_test_client(tmp_path, monkeypatch)

    response = client.post(
        "/ingest",
        files={"file": ("notes.txt", b"not a pdf", "text/plain")},
        data={"brain_name": "x", "strategy": "standard"},
    )

    assert response.status_code == 400
    assert "Only PDF uploads are supported" in response.json()["detail"]


def test_ingest_rejects_oversized_upload(tmp_path, monkeypatch):
    """Ingestion endpoint should enforce configured max upload size."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "MAX_UPLOAD_MB", 1)

    content = io.BytesIO(b"x" * (2 * 1024 * 1024))
    response = client.post(
        "/ingest",
        files={"file": ("book.pdf", content, "application/pdf")},
        data={"brain_name": "x", "strategy": "standard"},
    )

    assert response.status_code == 413
    assert "MAX_UPLOAD_MB=1" in response.json()["detail"]


def test_ingest_uses_configured_subprocess_timeout(tmp_path, monkeypatch):
    """Background ingestion should pass configured timeout into subprocess.run."""
    client = _make_test_client(tmp_path, monkeypatch)
    monkeypatch.setattr(server_module, "INGEST_TIMEOUT_SEC", 7)

    captured = {}

    def _fake_run(cmd, capture_output, text, timeout):
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    response = client.post(
        "/ingest",
        files={"file": ("book.pdf", b"%PDF-1.7\nx", "application/pdf")},
        data={"brain_name": "x", "strategy": "standard"},
    )
    assert response.status_code == 200
    assert captured["timeout"] == 7


def test_ingest_keeps_uploaded_pdf_for_future_enrichment(tmp_path, monkeypatch):
    """Successful ingestion should preserve uploaded PDF for later enrichment runs."""
    client = _make_test_client(tmp_path, monkeypatch)

    def _fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    response = client.post(
        "/ingest",
        files={"file": ("book.pdf", b"%PDF-1.7\nx", "application/pdf")},
        data={"brain_name": "x", "strategy": "standard"},
    )
    assert response.status_code == 200

    upload_dir = tmp_path / "uploads"
    assert upload_dir.exists()
    uploaded_files = list(upload_dir.iterdir())
    assert len(uploaded_files) == 1
    assert uploaded_files[0].suffix.lower() == ".pdf"


def test_ingest_failure_cleans_uploaded_pdf(tmp_path, monkeypatch):
    """Failed ingestion should clean uploaded PDF to avoid stale failed artifacts."""
    client = _make_test_client(tmp_path, monkeypatch)

    def _fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="failed")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    response = client.post(
        "/ingest",
        files={"file": ("book.pdf", b"%PDF-1.7\nx", "application/pdf")},
        data={"brain_name": "x", "strategy": "standard"},
    )
    assert response.status_code == 200

    upload_dir = tmp_path / "uploads"
    assert upload_dir.exists()
    assert list(upload_dir.iterdir()) == []
