export interface Brain {
    name: string;
    objective: string;
    file_count: number;
}

export interface BrainContent {
    characters: FileNode[];
    timeline: FileNode[];
    themes: FileNode[];
    facts: FileNode[];
}

export interface FileNode {
    id: string;
    name: string;
    summary: string;
    tags: string[];
}

export interface ClaimTraceItem {
    claim_id: string;
    file_path: string;
    claim_text: string;
    evidence_quote: string;
    source_locator: string;
    confidence: string;
    user_override: boolean;
}

export interface QueryTraceCompleteness {
    total_statements: number;
    linked_statements: number;
    completeness_ratio: number;
}

export interface QueryResult {
    answer: string;
    sources: string[];
    confidence: string;
    claim_trace: ClaimTraceItem[];
    trace_completeness: QueryTraceCompleteness;
    query_run_id: string | null;
    trace_degraded: boolean;
    warnings: string[];
    mode: 'audit' | 'standard';
}

export interface QueryApiResponse {
    result: QueryResult;
    enrichmentJobId: string | null;
}

export interface EvidenceSnapshot {
    question: string;
    answer: string;
    confidence: string;
    sources: string[];
    claimTrace: ClaimTraceItem[];
    traceCompleteness: QueryTraceCompleteness;
    queryRunId: string | null;
    traceDegraded: boolean;
    warnings: string[];
    mode: 'audit' | 'standard';
    timestamp: string;
}

export interface EnrichmentJob {
    job_id: string;
    brain_name: string;
    question: string;
    status: 'processing' | 'completed' | 'failed';
    started_at: string;
    completed_at: string | null;
    error: string | null;
}

export interface IngestionJob {
    job_id?: string;
    brain_name: string;
    status: 'processing' | 'completed' | 'failed';
    started_at: string;
    completed_at: string | null;
    error: string | null;
    filename: string;
}

export interface LogEntry {
    book_path: string;
    status: string;
    chapters_processed: number;
}
