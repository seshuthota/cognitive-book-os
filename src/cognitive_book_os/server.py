"""FastAPI Backend for Cognitive Book OS."""

from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import time
import json
import logging
import sqlite3
from threading import RLock, Lock

from .brain import Brain
from .gardener import run_gardener_for_brain
from .gardener_scheduler import GardenerScheduler, discover_brain_names, parse_interval_seconds
from .claim_store import (
    ClaimStore,
    claims_versioning_enabled,
    query_audit_endpoints_enabled,
    provenance_enforcement_mode,
)
from .orchestration import (
    BrainNotFoundError,
    MultiBrainInputError,
    orchestrate_multi_brain_query,
)
from .query import select_relevant_files, answer_from_brain, answer_from_brain_with_audit
from .llm import get_client
from .models import (
    ClaimStatus,
    MultiBrainQueryRequest,
    MultiBrainQueryResult,
    QueryAuditResult,
    QueryResult,
)

load_dotenv()

app = FastAPI(title="Cognitive Book OS API", version="1.0.0")

def _get_cors_origins() -> list[str]:
    """Read CORS origins from env, with safe local-development defaults."""
    raw = os.getenv("CORS_ALLOW_ORIGINS")
    if not raw:
        return [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8501",
            "http://127.0.0.1:8501",
        ]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BRAINS_DIR = os.getenv("BRAINS_DIR", "brains")
DEFAULT_QUERY_PROVIDER = os.getenv("DEFAULT_QUERY_PROVIDER", "anthropic")
REQUIRE_API_KEY = os.getenv("REQUIRE_API_KEY", "")
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "0"))
MAX_JOB_HISTORY = int(os.getenv("MAX_JOB_HISTORY", "200"))
JOB_STORE_PATH = Path(os.getenv("JOB_STORE_PATH", "dist/job_store.json"))
JOB_STORE_BACKEND = os.getenv("JOB_STORE_BACKEND", "json").strip().lower()
JOB_STORE_SQLITE_PATH = Path(os.getenv("JOB_STORE_SQLITE_PATH", "dist/job_store.db"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "dist/uploads"))
INGEST_TIMEOUT_SEC = int(os.getenv("INGEST_TIMEOUT_SEC", "7200"))
ENABLE_METRICS = os.getenv("ENABLE_METRICS", "1").lower() in {"1", "true", "yes", "on"}
METRICS_API_KEY = os.getenv("METRICS_API_KEY", "")
METRICS_MAX_PATHS = int(os.getenv("METRICS_MAX_PATHS", "200"))
REQUEST_LOG_JSON = os.getenv("REQUEST_LOG_JSON", "1").lower() in {"1", "true", "yes", "on"}
REQUEST_LOG_LEVEL = os.getenv("REQUEST_LOG_LEVEL", "INFO").upper()
ENABLE_CLAIM_VERSIONING = claims_versioning_enabled()
ENABLE_QUERY_AUDIT_ENDPOINTS = query_audit_endpoints_enabled()
PROVENANCE_ENFORCEMENT = provenance_enforcement_mode()
ENABLE_MULTI_BRAIN_QUERY = os.getenv("ENABLE_MULTI_BRAIN_QUERY", "0").strip().lower() in {"1", "true", "yes", "on"}
MULTI_BRAIN_MAX_BRAINS = max(int(os.getenv("MULTI_BRAIN_MAX_BRAINS", "5")), 1)
MULTI_BRAIN_MAX_FILES_PER_BRAIN = max(int(os.getenv("MULTI_BRAIN_MAX_FILES_PER_BRAIN", "12")), 1)
GARDENER_ENABLED = os.getenv("GARDENER_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
GARDENER_INTERVAL = os.getenv("GARDENER_INTERVAL", "weekly").strip().lower()
GARDENER_DRY_RUN = os.getenv("GARDENER_DRY_RUN", "1").strip().lower() in {"1", "true", "yes", "on"}
GARDENER_BRAIN_EXCLUDE = tuple(
    part.strip()
    for part in os.getenv("GARDENER_BRAIN_EXCLUDE", "").split(",")
    if part.strip()
)
GARDENER_REPORT_RETENTION = max(int(os.getenv("GARDENER_REPORT_RETENTION", "20")), 1)
GARDENER_PROVIDER = os.getenv("GARDENER_PROVIDER", DEFAULT_QUERY_PROVIDER).strip() or DEFAULT_QUERY_PROVIDER
GARDENER_MODEL = (os.getenv("GARDENER_MODEL", "") or "").strip() or None
MAX_GARDENER_HISTORY = int(os.getenv("MAX_GARDENER_HISTORY", "200"))

# Job status tracking for ingestion tasks
from datetime import datetime
from typing import Dict, Any
import uuid

ingestion_jobs: Dict[str, Dict[str, Any]] = {}
enrichment_jobs: Dict[str, Dict[str, Any]] = {}
gardener_runs: Dict[str, Dict[str, Any]] = {}
rate_limit_store: Dict[str, Dict[str, int | float]] = {}
_rate_limit_last_pruned_window: int = -1
_job_store_lock = RLock()
_metrics_lock = RLock()
_gardener_scheduler_lock = RLock()
_gardener_execution_lock = Lock()
_gardener_scheduler: Optional[GardenerScheduler] = None
_operational_metrics: Dict[str, Any] = {
    "started_at": datetime.now().isoformat(),
    "requests_total": 0,
    "responses_by_status": {},
    "requests_by_method": {},
    "requests_by_path": {},
    "auth_failures": 0,
    "rate_limited": 0,
    "latency_ms": {"count": 0, "sum": 0.0, "max": 0.0},
}
logger = logging.getLogger("cognitive_book_os.server")
logger.setLevel(getattr(logging, REQUEST_LOG_LEVEL, logging.INFO))


def _trim_job_history(store: Dict[str, Dict[str, Any]], max_items: int = MAX_JOB_HISTORY) -> None:
    """Keep only the most recent job entries to bound in-memory growth."""
    if max_items <= 0:
        return
    if len(store) <= max_items:
        return

    # Sort by started_at (ISO strings sort chronologically) and drop oldest.
    ordered = sorted(
        store.items(),
        key=lambda item: item[1].get("started_at", ""),
    )
    to_remove = len(store) - max_items
    for job_id, _ in ordered[:to_remove]:
        store.pop(job_id, None)


def _job_store_backend() -> str:
    """Return a validated job-store backend."""
    return "sqlite" if JOB_STORE_BACKEND == "sqlite" else "json"


def _save_job_store_json_locked() -> None:
    """Persist job state atomically to JSON."""
    JOB_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ingestion_jobs": ingestion_jobs,
        "enrichment_jobs": enrichment_jobs,
        "gardener_runs": gardener_runs,
    }
    temp_path = JOB_STORE_PATH.with_suffix(f"{JOB_STORE_PATH.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    temp_path.replace(JOB_STORE_PATH)


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_store (
            kind TEXT NOT NULL,
            job_id TEXT NOT NULL,
            started_at TEXT,
            payload TEXT NOT NULL,
            PRIMARY KEY (kind, job_id)
        )
        """
    )


def _save_job_store_sqlite_locked() -> None:
    """Persist full in-memory job state into SQLite."""
    JOB_STORE_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(JOB_STORE_SQLITE_PATH) as conn:
        _ensure_sqlite_schema(conn)
        conn.execute("DELETE FROM job_store")
        ingestion_rows = [
            (
                "ingestion",
                job_id,
                str(payload.get("started_at", "")),
                json.dumps(payload, ensure_ascii=True),
            )
            for job_id, payload in ingestion_jobs.items()
        ]
        enrichment_rows = [
            (
                "enrichment",
                job_id,
                str(payload.get("started_at", "")),
                json.dumps(payload, ensure_ascii=True),
            )
            for job_id, payload in enrichment_jobs.items()
        ]
        gardener_rows = [
            (
                "gardener",
                job_id,
                str(payload.get("started_at", "")),
                json.dumps(payload, ensure_ascii=True),
            )
            for job_id, payload in gardener_runs.items()
        ]
        conn.executemany(
            "INSERT INTO job_store (kind, job_id, started_at, payload) VALUES (?, ?, ?, ?)",
            ingestion_rows + enrichment_rows + gardener_rows,
        )


def _persist_job_store_locked() -> None:
    """Persist job state using configured backend. Caller must hold _job_store_lock."""
    if _job_store_backend() == "sqlite":
        _save_job_store_sqlite_locked()
    else:
        _save_job_store_json_locked()


def _save_job_store() -> None:
    """Persist job state so status survives process restarts."""
    with _job_store_lock:
        _persist_job_store_locked()


def _load_job_store() -> None:
    """Load persisted job state if available."""
    with _job_store_lock:
        loaded_ingestion: Dict[str, Dict[str, Any]] = {}
        loaded_enrichment: Dict[str, Dict[str, Any]] = {}
        loaded_gardener: Dict[str, Dict[str, Any]] = {}

        if _job_store_backend() == "sqlite":
            if not JOB_STORE_SQLITE_PATH.exists():
                return
            try:
                with sqlite3.connect(JOB_STORE_SQLITE_PATH) as conn:
                    _ensure_sqlite_schema(conn)
                    rows = conn.execute(
                        "SELECT kind, payload FROM job_store ORDER BY started_at ASC"
                    ).fetchall()
            except sqlite3.Error:
                return

            for kind, payload_raw in rows:
                try:
                    payload = json.loads(payload_raw)
                except ValueError:
                    continue
                if not isinstance(payload, dict):
                    continue
                job_id = str(payload.get("job_id", ""))
                if not job_id:
                    continue
                if kind == "ingestion":
                    loaded_ingestion[job_id] = payload
                elif kind == "enrichment":
                    loaded_enrichment[job_id] = payload
                elif kind == "gardener":
                    loaded_gardener[job_id] = payload
        else:
            if not JOB_STORE_PATH.exists():
                return
            try:
                data = json.loads(JOB_STORE_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Ignore corrupt store and continue with empty in-memory state.
                return
            maybe_ingestion = data.get("ingestion_jobs", {})
            maybe_enrichment = data.get("enrichment_jobs", {})
            maybe_gardener = data.get("gardener_runs", {})
            if isinstance(maybe_ingestion, dict):
                loaded_ingestion = maybe_ingestion
            if isinstance(maybe_enrichment, dict):
                loaded_enrichment = maybe_enrichment
            if isinstance(maybe_gardener, dict):
                loaded_gardener = maybe_gardener

        ingestion_jobs.clear()
        ingestion_jobs.update(loaded_ingestion)
        enrichment_jobs.clear()
        enrichment_jobs.update(loaded_enrichment)
        gardener_runs.clear()
        gardener_runs.update(loaded_gardener)
        _trim_job_history(ingestion_jobs)
        _trim_job_history(enrichment_jobs)
        _trim_job_history(gardener_runs, max_items=MAX_GARDENER_HISTORY)


def _upsert_job(store: Dict[str, Dict[str, Any]], job_id: str, updates: Dict[str, Any]) -> None:
    """Thread-safe update helper that also persists job state."""
    with _job_store_lock:
        current = store.get(job_id, {})
        current.update(updates)
        store[job_id] = current
        max_items = MAX_GARDENER_HISTORY if store is gardener_runs else MAX_JOB_HISTORY
        _trim_job_history(store, max_items=max_items)
        _persist_job_store_locked()


def _provider_api_key_env(provider: str) -> Optional[str]:
    mapping = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "minimax": "MINIMAX_API_KEY",
    }
    return mapping.get((provider or "").strip().lower())


def _provider_is_configured(provider: str) -> tuple[bool, str]:
    env_var = _provider_api_key_env(provider)
    if not env_var:
        return False, f"Unknown provider '{provider}'."
    if not os.getenv(env_var):
        return False, f"Missing {env_var}."
    return True, ""


def _resolved_gardener_interval_seconds() -> int:
    """Return configured interval, falling back to weekly on invalid values."""
    try:
        return parse_interval_seconds(GARDENER_INTERVAL)
    except ValueError:
        return 7 * 24 * 60 * 60


def _render_gardener_report_markdown(report: Dict[str, Any]) -> str:
    summary = report.get("summary_counts", {})
    llm_steps = report.get("llm_steps", {})
    issues = report.get("issues", [])
    recommendations = report.get("recommendations", [])
    clusters = report.get("clusters", [])

    lines: list[str] = [
        "# Gardener Report",
        "",
        f"- Run ID: `{report.get('run_id', '')}`",
        f"- Brain: `{report.get('brain_id', '')}`",
        f"- Timestamp: `{report.get('timestamp', '')}`",
        f"- Mode: `{report.get('mode', 'dry_run')}`",
        "",
        "## Summary Counts",
        f"- Files reviewed: {summary.get('files_reviewed', 0)}",
        f"- Duplicate clusters: {summary.get('duplicate_clusters', 0)}",
        f"- Files in clusters: {summary.get('files_in_clusters', 0)}",
        f"- Merges proposed: {summary.get('merges_proposed', 0)}",
        f"- Merges applied: {summary.get('merges_applied', 0)}",
        "",
        "## LLM Steps",
        f"- Status: {llm_steps.get('status', 'skipped')}",
        f"- Executed: {bool(llm_steps.get('executed', False))}",
    ]
    reason = llm_steps.get("reason")
    if reason:
        lines.append(f"- Reason: {reason}")

    lines.extend(["", "## Duplicate Clusters"])
    if not clusters:
        lines.append("- None")
    else:
        for cluster in clusters:
            lines.append(f"- {', '.join(cluster.get('files', []))}")

    lines.extend(["", "## Issues"])
    if not issues:
        lines.append("- None")
    else:
        for issue in issues:
            lines.append(f"- {issue}")

    lines.extend(["", "## Recommendations"])
    if not recommendations:
        lines.append("- None")
    else:
        for recommendation in recommendations:
            lines.append(f"- {recommendation}")

    lines.append("")
    return "\n".join(lines)


def _prune_brain_reports(brain: Brain, keep_last: int) -> None:
    report_dir = brain.path / "meta" / "reports"
    if not report_dir.exists():
        return

    json_reports = sorted(report_dir.glob("gardener_*.json"))
    if keep_last <= 0 or len(json_reports) <= keep_last:
        return

    to_remove = json_reports[: len(json_reports) - keep_last]
    for json_path in to_remove:
        md_path = json_path.with_suffix(".md")
        try:
            json_path.unlink(missing_ok=True)
            md_path.unlink(missing_ok=True)
        except OSError:
            continue


def _list_target_brains(explicit_brains: Optional[list[str]] = None) -> list[str]:
    if explicit_brains:
        brain_names = [name.strip() for name in explicit_brains if name.strip()]
    else:
        brain_names = discover_brain_names(BRAINS_DIR)
        excluded = set(GARDENER_BRAIN_EXCLUDE)
        brain_names = [name for name in brain_names if name not in excluded]
    return sorted(set(brain_names))


def _create_gardener_run_record(
    *,
    brain_names: list[str],
    dry_run: bool,
    trigger: str,
) -> str:
    run_id = f"gardener_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    _upsert_job(
        gardener_runs,
        run_id,
        {
            "run_id": run_id,
            "status": "processing",
            "trigger": trigger,
            "provider": GARDENER_PROVIDER,
            "model": GARDENER_MODEL,
            "mode": "dry_run" if dry_run else "apply",
            "dry_run": dry_run,
            "brains": brain_names,
            "brains_total": len(brain_names),
            "brains_succeeded": 0,
            "brains_failed": 0,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "issues": [],
            "reports": {},
            "artifacts_root": "meta/reports",
        },
    )
    return run_id


def _execute_gardener_run(run_id: str) -> None:
    if not _gardener_execution_lock.acquire(blocking=False):
        _upsert_job(
            gardener_runs,
            run_id,
            {
                "status": "skipped",
                "completed_at": datetime.now().isoformat(),
                "issues": ["Another gardener run is currently active."],
            },
        )
        return

    try:
        run = dict(gardener_runs.get(run_id, {}))
        brain_names = run.get("brains", []) if isinstance(run.get("brains", []), list) else []
        dry_run = bool(run.get("dry_run", True))
        provider = str(run.get("provider", GARDENER_PROVIDER))
        model = run.get("model")
        timestamp = datetime.now().isoformat()
        report_index: Dict[str, Dict[str, Any]] = {}
        run_issues: list[str] = []
        brains_failed = 0
        brains_succeeded = 0

        provider_ready, provider_reason = _provider_is_configured(provider)
        skip_llm = not provider_ready

        for brain_name in brain_names:
            brain = Brain(name=brain_name, base_path=BRAINS_DIR)
            if not brain.exists():
                brains_failed += 1
                run_issues.append(f"Brain not found: {brain_name}")
                continue

            try:
                report = run_gardener_for_brain(
                    brain,
                    dry_run=dry_run or skip_llm,
                    provider=provider,
                    model=model,
                )
                if skip_llm and not dry_run:
                    report["mode"] = "apply"
                    report["llm_steps"] = {
                        "status": "skipped",
                        "executed": False,
                        "reason": provider_reason,
                    }
                    if provider_reason not in report.get("issues", []):
                        report.setdefault("issues", []).append(provider_reason)

                report["run_id"] = run_id
                report["brain_id"] = brain_name
                report["timestamp"] = timestamp

                json_rel = f"meta/reports/gardener_{run_id}.json"
                md_rel = f"meta/reports/gardener_{run_id}.md"
                brain.write_file(json_rel, json.dumps(report, ensure_ascii=True, indent=2))
                brain.write_file(md_rel, _render_gardener_report_markdown(report))
                _prune_brain_reports(brain, keep_last=GARDENER_REPORT_RETENTION)

                report_index[brain_name] = {
                    "json_path": json_rel,
                    "markdown_path": md_rel,
                    "issues": report.get("issues", []),
                    "duplicate_clusters": report.get("summary_counts", {}).get("duplicate_clusters", 0),
                }
                if report.get("issues"):
                    brains_failed += 1
                    run_issues.extend(report.get("issues", []))
                else:
                    brains_succeeded += 1
            except Exception as exc:
                brains_failed += 1
                run_issues.append(f"{brain_name}: {exc}")

        if not brain_names:
            run_issues.append("No brains selected for this run.")

        if brains_failed == 0:
            final_status = "completed"
        elif brains_succeeded == 0:
            final_status = "failed"
        else:
            final_status = "completed_with_errors"

        _upsert_job(
            gardener_runs,
            run_id,
            {
                "status": final_status,
                "brains_succeeded": brains_succeeded,
                "brains_failed": brains_failed,
                "reports": report_index,
                "issues": run_issues,
                "completed_at": datetime.now().isoformat(),
            },
        )
    finally:
        _gardener_execution_lock.release()


def _trigger_gardener_run(
    *,
    dry_run: Optional[bool] = None,
    explicit_brains: Optional[list[str]] = None,
    trigger: str = "manual",
    execute_async: bool = True,
    background_tasks: Optional[BackgroundTasks] = None,
) -> str:
    selected = _list_target_brains(explicit_brains)
    run_id = _create_gardener_run_record(
        brain_names=selected,
        dry_run=GARDENER_DRY_RUN if dry_run is None else dry_run,
        trigger=trigger,
    )
    if execute_async:
        if background_tasks:
            background_tasks.add_task(_execute_gardener_run, run_id)
        else:
            from threading import Thread

            Thread(target=_execute_gardener_run, args=(run_id,), daemon=True).start()
    else:
        _execute_gardener_run(run_id)
    return run_id


def _scheduled_gardener_callback() -> Optional[str]:
    return _trigger_gardener_run(
        dry_run=GARDENER_DRY_RUN,
        explicit_brains=None,
        trigger="scheduled",
        execute_async=False,
        background_tasks=None,
    )


def _start_gardener_scheduler_if_enabled() -> None:
    global _gardener_scheduler
    if not GARDENER_ENABLED:
        return

    with _gardener_scheduler_lock:
        if _gardener_scheduler and _gardener_scheduler.is_running():
            return
        interval_seconds = _resolved_gardener_interval_seconds()
        _gardener_scheduler = GardenerScheduler(
            interval_seconds=interval_seconds,
            run_callback=_scheduled_gardener_callback,
        )
        _gardener_scheduler.start()


def _stop_gardener_scheduler() -> None:
    global _gardener_scheduler
    with _gardener_scheduler_lock:
        scheduler = _gardener_scheduler
        _gardener_scheduler = None
    if scheduler:
        scheduler.stop()


def _record_request_metrics(request: Request, status_code: int, duration_ms: float) -> None:
    """Track bounded in-memory operational metrics."""
    if not ENABLE_METRICS:
        return

    method = request.method
    path = request.url.path

    with _metrics_lock:
        _operational_metrics["requests_total"] += 1

        by_status = _operational_metrics["responses_by_status"]
        status_key = str(status_code)
        by_status[status_key] = int(by_status.get(status_key, 0)) + 1

        by_method = _operational_metrics["requests_by_method"]
        by_method[method] = int(by_method.get(method, 0)) + 1

        by_path = _operational_metrics["requests_by_path"]
        if path not in by_path and len(by_path) >= max(METRICS_MAX_PATHS, 1):
            path = "__other__"
        by_path[path] = int(by_path.get(path, 0)) + 1

        lat = _operational_metrics["latency_ms"]
        lat["count"] = int(lat.get("count", 0)) + 1
        lat["sum"] = float(lat.get("sum", 0.0)) + duration_ms
        lat["max"] = max(float(lat.get("max", 0.0)), duration_ms)


def _log_request(request: Request, status_code: int, duration_ms: float, request_id: str) -> None:
    """Emit structured request logs for production debugging and tracing."""
    payload = {
        "event": "http_request",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 3),
        "client_ip": request.client.host if request.client else "unknown",
    }
    if REQUEST_LOG_JSON:
        logger.info(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    else:
        logger.info(
            "%s %s %s %.3fms id=%s",
            payload["method"],
            payload["path"],
            payload["status_code"],
            payload["duration_ms"],
            payload["request_id"],
        )


_load_job_store()


@app.on_event("startup")
def startup_gardener_scheduler() -> None:
    """Start optional in-process gardener scheduler."""
    _start_gardener_scheduler_if_enabled()


@app.on_event("shutdown")
def shutdown_gardener_scheduler() -> None:
    """Stop gardener scheduler thread cleanly."""
    _stop_gardener_scheduler()


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Optional API key auth and request rate limiting for production."""
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id", uuid.uuid4().hex)

    # Optional API-key authentication
    if REQUIRE_API_KEY:
        api_key = request.headers.get("x-api-key", "")
        if api_key != REQUIRE_API_KEY:
            with _metrics_lock:
                _operational_metrics["auth_failures"] = int(_operational_metrics.get("auth_failures", 0)) + 1
            duration_ms = (time.perf_counter() - started) * 1000.0
            _record_request_metrics(request, 401, duration_ms)
            _log_request(request, 401, duration_ms, request_id)
            return Response("Unauthorized", status_code=401, headers={"X-Request-ID": request_id})

    # Optional simple in-memory rate limiting (per client IP, per minute)
    if RATE_LIMIT_PER_MINUTE > 0:
        global _rate_limit_last_pruned_window
        client_host = request.client.host if request.client else "unknown"
        now = int(time.time())
        current_window = now // 60

        # Prune stale buckets once per window to avoid unbounded growth.
        if _rate_limit_last_pruned_window != current_window:
            stale_hosts = [
                host for host, bucket in rate_limit_store.items()
                if int(bucket.get("window", -1)) < current_window
            ]
            for host in stale_hosts:
                rate_limit_store.pop(host, None)
            _rate_limit_last_pruned_window = current_window

        bucket = rate_limit_store.get(client_host)

        if not bucket or int(bucket["window"]) != current_window:
            rate_limit_store[client_host] = {"window": current_window, "count": 1}
        else:
            if int(bucket["count"]) >= RATE_LIMIT_PER_MINUTE:
                with _metrics_lock:
                    _operational_metrics["rate_limited"] = int(_operational_metrics.get("rate_limited", 0)) + 1
                duration_ms = (time.perf_counter() - started) * 1000.0
                _record_request_metrics(request, 429, duration_ms)
                _log_request(request, 429, duration_ms, request_id)
                return Response("Too Many Requests", status_code=429, headers={"X-Request-ID": request_id})
            bucket["count"] = int(bucket["count"]) + 1

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - started) * 1000.0
        _record_request_metrics(request, 500, duration_ms)
        _log_request(request, 500, duration_ms, request_id)
        raise

    duration_ms = (time.perf_counter() - started) * 1000.0
    _record_request_metrics(request, response.status_code, duration_ms)
    _log_request(request, response.status_code, duration_ms, request_id)
    response.headers["X-Request-ID"] = request_id
    return response

class BrainInfo(BaseModel):
    name: str
    objective: str
    file_count: int

class QueryRequest(BaseModel):
    question: str
    provider: str = DEFAULT_QUERY_PROVIDER
    model: Optional[str] = None
    auto_enrich: bool = False
    async_enrich: bool = True


class QueryAuditRequest(BaseModel):
    question: str
    provider: str = DEFAULT_QUERY_PROVIDER
    model: Optional[str] = None
    include_claim_trace: bool = True


class NoteRequest(BaseModel):
    path: str
    content: str


class GardenerTriggerRequest(BaseModel):
    dry_run: Optional[bool] = None
    brain_ids: Optional[list[str]] = None
    async_run: bool = True


def get_brain_or_404(name: str) -> Brain:
    brain = Brain(name=name, base_path=BRAINS_DIR)
    if not brain.exists():
        raise HTTPException(status_code=404, detail=f"Brain '{name}' not found")
    return brain


def _require_claim_features() -> None:
    if not ENABLE_CLAIM_VERSIONING:
        raise HTTPException(status_code=404, detail="Claim versioning is disabled.")


def _require_query_audit_features() -> None:
    if not ENABLE_QUERY_AUDIT_ENDPOINTS:
        raise HTTPException(status_code=404, detail="Query audit endpoints are disabled.")


def _require_multi_brain_features() -> None:
    if not ENABLE_MULTI_BRAIN_QUERY:
        raise HTTPException(status_code=404, detail="Multi-brain query is disabled.")


@app.get("/health")
def health_check():
    """Basic health endpoint for probes."""
    return {"status": "ok"}


@app.get("/health/ready")
def readiness_check(response: Response):
    """Readiness probe that validates storage dependencies."""
    checks: Dict[str, Any] = {}
    ready = True

    # Brains directory should be creatable/accessible.
    try:
        Path(BRAINS_DIR).mkdir(parents=True, exist_ok=True)
        checks["brains_dir"] = {"ok": True, "path": str(BRAINS_DIR)}
    except OSError as e:
        ready = False
        checks["brains_dir"] = {"ok": False, "error": str(e)}

    # Job store backend should be usable.
    backend = _job_store_backend()
    if backend == "sqlite":
        try:
            JOB_STORE_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(JOB_STORE_SQLITE_PATH) as conn:
                _ensure_sqlite_schema(conn)
            checks["job_store"] = {"ok": True, "backend": "sqlite", "path": str(JOB_STORE_SQLITE_PATH)}
        except sqlite3.Error as e:
            ready = False
            checks["job_store"] = {"ok": False, "backend": "sqlite", "error": str(e)}
    else:
        try:
            JOB_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            checks["job_store"] = {"ok": True, "backend": "json", "path": str(JOB_STORE_PATH)}
        except OSError as e:
            ready = False
            checks["job_store"] = {"ok": False, "backend": "json", "error": str(e)}

    if not ready:
        response.status_code = 503
        return {"status": "degraded", "checks": checks}
    return {"status": "ok", "checks": checks}


@app.get("/metrics")
def get_metrics(request: Request):
    """Operational in-memory metrics for basic production observability."""
    if not ENABLE_METRICS:
        raise HTTPException(status_code=404, detail="Metrics are disabled.")

    if METRICS_API_KEY:
        metrics_key = request.headers.get("x-metrics-key", "")
        if metrics_key != METRICS_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

    with _metrics_lock:
        started_at = _operational_metrics.get("started_at")
        latency = dict(_operational_metrics.get("latency_ms", {}))
        count = int(latency.get("count", 0))
        avg_ms = float(latency.get("sum", 0.0)) / count if count else 0.0
        snapshot = {
            "started_at": started_at,
            "uptime_seconds": int(
                max(0.0, datetime.now().timestamp() - datetime.fromisoformat(started_at).timestamp())
            ) if isinstance(started_at, str) else 0,
            "requests_total": int(_operational_metrics.get("requests_total", 0)),
            "responses_by_status": dict(_operational_metrics.get("responses_by_status", {})),
            "requests_by_method": dict(_operational_metrics.get("requests_by_method", {})),
            "requests_by_path": dict(_operational_metrics.get("requests_by_path", {})),
            "auth_failures": int(_operational_metrics.get("auth_failures", 0)),
            "rate_limited": int(_operational_metrics.get("rate_limited", 0)),
            "latency_ms": {
                "count": count,
                "avg": round(avg_ms, 3),
                "max": round(float(latency.get("max", 0.0)), 3),
            },
        }
    return snapshot


@app.get("/gardener/status")
def gardener_status():
    """Return gardener scheduler and configuration status."""
    scheduler_status: Dict[str, Any] = {
        "running": False,
        "started_at": None,
        "last_run_at": None,
        "next_run_at": None,
        "last_run_id": None,
        "last_error": None,
        "interval_seconds": _resolved_gardener_interval_seconds(),
    }
    with _gardener_scheduler_lock:
        if _gardener_scheduler:
            snapshot = _gardener_scheduler.get_status()
            scheduler_status = {
                "running": snapshot.running,
                "started_at": snapshot.started_at,
                "last_run_at": snapshot.last_run_at,
                "next_run_at": snapshot.next_run_at,
                "last_run_id": snapshot.last_run_id,
                "last_error": snapshot.last_error,
                "interval_seconds": snapshot.interval_seconds,
            }

    with _job_store_lock:
        active_runs = [item for item in gardener_runs.values() if item.get("status") == "processing"]
    active_runs = sorted(active_runs, key=lambda item: item.get("started_at", ""), reverse=True)
    active_run_id = active_runs[0].get("run_id") if active_runs else None

    return {
        "enabled": GARDENER_ENABLED,
        "defaults": {
            "interval": GARDENER_INTERVAL,
            "dry_run": GARDENER_DRY_RUN,
            "exclude_brains": list(GARDENER_BRAIN_EXCLUDE),
            "provider": GARDENER_PROVIDER,
            "model": GARDENER_MODEL,
            "report_retention": GARDENER_REPORT_RETENTION,
        },
        "scheduler": scheduler_status,
        "active_run_id": active_run_id,
    }


@app.post("/gardener/trigger")
def trigger_gardener_run(
    request: GardenerTriggerRequest,
    background_tasks: BackgroundTasks,
):
    """Trigger an immediate gardener run."""
    explicit_brains = request.brain_ids or None
    if explicit_brains:
        for brain_name in explicit_brains:
            brain = Brain(name=brain_name, base_path=BRAINS_DIR)
            if not brain.exists():
                raise HTTPException(status_code=404, detail=f"Brain '{brain_name}' not found")

    run_id = _trigger_gardener_run(
        dry_run=request.dry_run,
        explicit_brains=explicit_brains,
        trigger="manual",
        execute_async=request.async_run,
        background_tasks=background_tasks,
    )
    return {
        "status": "accepted" if request.async_run else "completed",
        "run_id": run_id,
        "mode": "dry_run" if (request.dry_run if request.dry_run is not None else GARDENER_DRY_RUN) else "apply",
        "brains": _list_target_brains(explicit_brains),
        "async_run": request.async_run,
    }


@app.get("/gardener/history")
def gardener_history(limit: int = 20):
    """Return recent gardener run records."""
    safe_limit = max(1, min(limit, 200))
    with _job_store_lock:
        ordered = sorted(
            gardener_runs.values(),
            key=lambda item: item.get("started_at", ""),
            reverse=True,
        )
    return {"runs": ordered[:safe_limit]}


@app.get("/brains", response_model=List[BrainInfo])
def list_brains():
    """List all available brains."""
    brains = []
    base_path = Path(BRAINS_DIR)
    if base_path.exists():
        for d in base_path.iterdir():
            if d.is_dir() and (d / "_index.md").exists():
                brain = Brain(d.name, base_path=BRAINS_DIR)
                # Count files roughly
                count = len(brain.list_files())
                brains.append(BrainInfo(
                    name=d.name,
                    objective=brain.get_objective(),
                    file_count=count
                ))
    return brains

@app.get("/brains/{name}/structure")
def get_brain_structure(name: str):
    """Get the file structure of a brain."""
    brain = get_brain_or_404(name)
    return {"structure": brain.get_structure()}

@app.get("/brains/{name}/files/{path:path}")
def get_file_content(name: str, path: str):
    """Get content of a specific file."""
    brain = get_brain_or_404(name)
    try:
        content = brain.read_file(path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": path, "content": content}


@app.get("/brains/{name}/claims")
def list_claims(
    name: str,
    file: Optional[str] = None,
    status: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """List materialized claims for a brain."""
    _require_claim_features()
    brain = get_brain_or_404(name)
    store = ClaimStore(brain)

    parsed_status = None
    if status:
        try:
            parsed_status = ClaimStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid claim status")

    claims = store.list_claims(
        file_path=file,
        status=parsed_status,
        tag=tag,
        q=q,
        limit=limit,
        offset=offset,
    )
    return {"claims": [claim.model_dump() for claim in claims]}


@app.get("/brains/{name}/claims/{claim_id}")
def get_claim(name: str, claim_id: str):
    """Return the latest snapshot for a specific claim id."""
    _require_claim_features()
    brain = get_brain_or_404(name)
    store = ClaimStore(brain)
    claim = store.get_claim(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim.model_dump()


@app.get("/brains/{name}/claims/{claim_id}/history")
def get_claim_history(name: str, claim_id: str):
    """Return append-only lifecycle history for a specific claim."""
    _require_claim_features()
    brain = get_brain_or_404(name)
    store = ClaimStore(brain)
    events = store.get_claim_history(claim_id)
    return {"events": [event.model_dump() for event in events]}


def _run_auto_enrichment_task(
    job_id: str,
    brain_name: str,
    question: str,
    provider: str,
    model: Optional[str],
) -> None:
    """Run enrichment in a background task and track job status."""
    from .enrichment import EnrichmentManager

    try:
        manager = EnrichmentManager(brain_name, BRAINS_DIR)
        manager.enrich(question, provider, model)
        _upsert_job(
            enrichment_jobs,
            job_id,
            {"status": "completed", "completed_at": datetime.now().isoformat()},
        )
    except Exception as e:
        _upsert_job(
            enrichment_jobs,
            job_id,
            {
                "status": "failed",
                "error": str(e),
                "completed_at": datetime.now().isoformat(),
            },
        )


@app.post("/brains/{name}/query", response_model=QueryResult)
def query_brain_endpoint(
    name: str,
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    response: Response,
):
    """Query a brain."""
    brain = get_brain_or_404(name)
    client = get_client(provider=request.provider, model=request.model)
    
    # Select relevant files
    selection = select_relevant_files(request.question, brain, client)
    
    # Initial Answer Generation
    result = None
    if selection.files:
        result = answer_from_brain(request.question, brain, selection.files, client)
        
    # Check for Auto-Enrichment (Active Learning)
    from .enrichment import EnrichmentManager
    from .models import Confidence
    
    current_confidence = result.confidence if result else Confidence.NONE
    
    # If auto_enrich is requested AND confidence is low/none
    if request.auto_enrich and current_confidence in [Confidence.LOW, Confidence.NONE]:
        print(f"Auto-enrich triggered for {name}")
        manager = EnrichmentManager(name, BRAINS_DIR)
        
        # Check for gap
        should_enrich, chapters = manager.evaluate_gap(request.question, request.provider, request.model)
        
        if should_enrich:
            if request.async_enrich:
                job_id = f"enrich_{name}_{uuid.uuid4().hex[:8]}"
                _upsert_job(
                    enrichment_jobs,
                    job_id,
                    {
                        "job_id": job_id,
                        "brain_name": name,
                        "question": request.question,
                        "status": "processing",
                        "started_at": datetime.now().isoformat(),
                        "completed_at": None,
                        "error": None,
                    },
                )
                background_tasks.add_task(
                    _run_auto_enrichment_task,
                    job_id,
                    name,
                    request.question,
                    request.provider,
                    request.model,
                )
                response.headers["X-Enrichment-Job-ID"] = job_id
            else:
                # Synchronous fallback path
                manager.enrich(request.question, request.provider, request.model)
                
                # Re-select files with new knowledge
                selection = select_relevant_files(request.question, brain, client)
                if selection.files:
                    result = answer_from_brain(request.question, brain, selection.files, client)

    if not result:
         return QueryResult(
            answer="I couldn't find relevant information in the current brain. If auto-enrich was enabled, enrichment may still be running in the background.",
            sources=[],
            confidence="none"
        )
    
    return result


@app.post("/brains/{name}/query/audit", response_model=QueryAuditResult)
def query_brain_audit_endpoint(
    name: str,
    request: QueryAuditRequest,
):
    """Query a brain and return claim-level traceability data."""
    _require_query_audit_features()
    _require_claim_features()

    brain = get_brain_or_404(name)
    client = get_client(provider=request.provider, model=request.model)
    selection = select_relevant_files(request.question, brain, client)

    if not selection.files:
        return QueryAuditResult(
            answer="I couldn't find relevant information in the current brain.",
            sources=[],
            confidence="none",
            claim_trace=[],
            trace_completeness={"total_statements": 0, "linked_statements": 0, "completeness_ratio": 0.0},
            query_run_id=f"query_{name}_none",
        )

    audit_result = answer_from_brain_with_audit(
        question=request.question,
        brain=brain,
        selected_files=selection.files,
        client=client,
    )

    if not request.include_claim_trace:
        audit_result.claim_trace = []
        audit_result.trace_completeness.total_statements = 0
        audit_result.trace_completeness.linked_statements = 0
        audit_result.trace_completeness.completeness_ratio = 0.0

    return audit_result


@app.post("/multi-brain/query", response_model=MultiBrainQueryResult)
def multi_brain_query_endpoint(request: MultiBrainQueryRequest):
    """Run a synchronized query across multiple selected brains."""
    _require_multi_brain_features()

    if not request.brains:
        raise HTTPException(status_code=400, detail="At least one brain must be specified.")

    max_brains = min(max(request.max_brains, 1), MULTI_BRAIN_MAX_BRAINS)
    max_files_per_brain = min(
        max(request.max_files_per_brain, 1),
        MULTI_BRAIN_MAX_FILES_PER_BRAIN,
    )

    try:
        return orchestrate_multi_brain_query(
            question=request.question,
            brain_names=request.brains,
            provider=request.provider,
            model=request.model,
            include_claim_trace=request.include_claim_trace,
            include_conflicts=request.include_conflicts,
            max_brains=max_brains,
            max_files_per_brain=max_files_per_brain,
            brains_dir=BRAINS_DIR,
        )
    except BrainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MultiBrainInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/brains/{name}/notes")
def update_user_note(name: str, note: NoteRequest):
    """Create or update a user note."""
    brain = get_brain_or_404(name)
    
    # Ensure path is in notes/ directory
    if not note.path.startswith("notes/"):
        full_path = f"notes/{note.path}"
    else:
        full_path = note.path
        
    # Ensure extension
    if not full_path.endswith(".md"):
        full_path += ".md"
        
    brain.write_file(full_path, note.content)
    return {"status": "success", "path": full_path}

@app.get("/brains/{name}/graph")
def get_brain_graph(name: str):
    """Get graph data (nodes/edges) for the visualizer."""
    # Ensure brain exists
    get_brain_or_404(name)
    
    from .graph import build_graph_data
    return build_graph_data(name, BRAINS_DIR)

@app.get("/viz/{name}")
def get_visualization(name: str):
    """Legacy visualization endpoint."""
    return {"message": "Use /brains/{name}/graph for data or CLI 'viz' command."}

@app.get("/brains/{name}/content")
def get_brain_content(name: str):
    """Get structured content for the brain explorer (characters, themes, etc)."""
    brain = get_brain_or_404(name)
    
    structure = {
        "characters": [],
        "timeline": [],
        "themes": [],
        "facts": []
    }
    
    # Helper to parse frontmatter-like content simply for the list view
    # In a real app, we might use python-frontmatter, but let's stick to standard lib if possible
    # or just simple line parsing for the summary/tags.
    
    for category in structure.keys():
        files = brain.list_files(category)
        for f in files:
            # f is like "characters/tommy_nolan.md"
            full_content = brain.read_file(f)
            if not full_content:
                continue
                
            # Extract simple metadata
            lines = full_content.split('\n')
            title = f.split('/')[-1].replace('.md', '').replace('_', ' ').title()
            summary = "No summary available."
            tags = []
            
            # Very basic parsing for demo purposes
            # Assume first H1 is title
            for line in lines:
                if line.startswith('# '):
                    title = line[2:].strip()
                    break
            
            # Assume first non-header text is summary
            for line in lines:
                if not line.startswith('#') and line.strip() and not line.startswith('---'):
                    summary = line.strip()[:150] + "..."
                    break
                    
            structure[category].append({
                "id": f,
                "name": title,
                "summary": summary,
                "tags": [category.capitalize()] # Placeholder tags
            })
            
    return structure

@app.get("/brains/{name}/log")
def get_brain_log(name: str):
    """Get the processing log for the brain."""
    brain = get_brain_or_404(name)
    return brain.get_processing_log()

# --- Ingestion Support ---
from fastapi import File, UploadFile, Form
import shutil

@app.post("/ingest")
async def ingest_brain(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    brain_name: str = Form(...),
    objective: Optional[str] = Form(None),
    strategy: str = Form("standard"),
):
    """
    Upload a PDF and start ingestion in the background.
    """
    # 0. Validate Inputs
    safe_filename = Path(file.filename or "upload.pdf").name
    if not safe_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")

    file.file.seek(0, os.SEEK_END)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size <= 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if MAX_UPLOAD_MB > 0 and file_size > (MAX_UPLOAD_MB * 1024 * 1024):
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file exceeds MAX_UPLOAD_MB={MAX_UPLOAD_MB}.",
        )

    # If strategy is triage, objective is required
    final_objective = objective
    if strategy == "triage" and not final_objective:
        raise HTTPException(status_code=400, detail="Strategy 'triage' requires an objective.")
    
    if not final_objective:
        final_objective = "General Comprehensive Knowledge Extraction"

    # 1. Save uploaded file temporarily
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    
    file_path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{safe_filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    job_id = f"ingest_{brain_name}_{datetime.now().strftime('%H%M%S')}"
    
    # Track job status
    _upsert_job(
        ingestion_jobs,
        job_id,
        {
            "job_id": job_id,
            "brain_name": brain_name,
            "status": "processing",
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "error": None,
            "filename": safe_filename,
            "stored_filename": file_path.name,
        },
    )
        
    # 2. Define background task
    def run_ingestion_task(pdf_path: Path, b_name: str, obj: str, strat: str, jid: str):
        import subprocess
        keep_source_pdf = False
        
        cmd = [
            "uv", "run", "python", "-m", "src.cognitive_book_os", "ingest",
            str(pdf_path),
            "--brain", b_name,
            "--strategy", strat,
            "--objective", obj
        ]
        
        print(f"Starting ingestion for {b_name}...")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(INGEST_TIMEOUT_SEC, 1),
            )
            if result.returncode == 0:
                print(f"Ingestion for {b_name} completed successfully.")
                keep_source_pdf = True
                _upsert_job(
                    ingestion_jobs,
                    jid,
                    {
                        "status": "completed",
                        "completed_at": datetime.now().isoformat(),
                        "source_pdf_path": str(pdf_path),
                    },
                )
            else:
                print(f"Ingestion for {b_name} failed:\n{result.stderr}")
                _upsert_job(
                    ingestion_jobs,
                    jid,
                    {
                        "status": "failed",
                        "error": result.stderr[:500],
                        "completed_at": datetime.now().isoformat(),
                    },
                )
        except subprocess.TimeoutExpired:
            _upsert_job(
                ingestion_jobs,
                jid,
                {
                    "status": "failed",
                    "error": f"Ingestion timed out after {max(INGEST_TIMEOUT_SEC, 1)} seconds.",
                    "completed_at": datetime.now().isoformat(),
                },
            )
        except Exception as e:
            print(f"Ingestion error: {e}")
            _upsert_job(
                ingestion_jobs,
                jid,
                {
                    "status": "failed",
                    "error": str(e),
                    "completed_at": datetime.now().isoformat(),
                },
            )
        finally:
            if not keep_source_pdf:
                try:
                    pdf_path.unlink(missing_ok=True)
                except OSError:
                    pass
            
    # 3. Schedule task
    background_tasks.add_task(run_ingestion_task, file_path, brain_name, final_objective, strategy, job_id)
    
    return {
        "status": "accepted",
        "message": f"Ingestion started for brain '{brain_name}'. Check back in a few minutes.",
        "job_id": job_id 
    }

@app.get("/jobs")
def get_ingestion_jobs():
    """Get status of all ingestion jobs."""
    with _job_store_lock:
        return list(ingestion_jobs.values())

@app.get("/jobs/{job_id}")
def get_job_status(job_id: str):
    """Get status of a specific ingestion job."""
    with _job_store_lock:
        if job_id not in ingestion_jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        return ingestion_jobs[job_id]


@app.get("/enrichment-jobs")
def get_enrichment_jobs():
    """Get status of all auto-enrichment jobs."""
    with _job_store_lock:
        return list(enrichment_jobs.values())


@app.get("/enrichment-jobs/{job_id}")
def get_enrichment_job_status(job_id: str):
    """Get status of a specific auto-enrichment job."""
    with _job_store_lock:
        if job_id not in enrichment_jobs:
            raise HTTPException(status_code=404, detail="Enrichment job not found")
        return enrichment_jobs[job_id]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
