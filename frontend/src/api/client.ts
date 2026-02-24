import axios from 'axios';
import type {
    Brain,
    BrainContent,
    QueryResult,
    LogEntry,
    QueryApiResponse,
    EnrichmentJob,
    IngestionJob,
    ClaimTraceItem,
    QueryTraceCompleteness,
} from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001';
const DEFAULT_PROVIDER = import.meta.env.VITE_PROVIDER || 'anthropic';
const API_KEY = import.meta.env.VITE_API_KEY || '';
const REQUEST_HEADERS: Record<string, string> = API_KEY ? { 'x-api-key': API_KEY } : {};

const EMPTY_TRACE: QueryTraceCompleteness = {
    total_statements: 0,
    linked_statements: 0,
    completeness_ratio: 0,
};

const normalizeStandardResult = (
    payload: { answer: string; sources?: string[]; confidence?: string },
    warnings: string[] = [],
): QueryResult => ({
    answer: payload.answer,
    sources: payload.sources || [],
    confidence: payload.confidence || 'none',
    claim_trace: [],
    trace_completeness: { ...EMPTY_TRACE },
    query_run_id: null,
    trace_degraded: true,
    warnings,
    mode: 'standard',
});

const normalizeAuditResult = (payload: {
    answer: string;
    sources?: string[];
    confidence: string;
    claim_trace?: ClaimTraceItem[];
    trace_completeness?: QueryTraceCompleteness;
    query_run_id: string;
}): QueryResult => ({
    answer: payload.answer,
    sources: payload.sources || [],
    confidence: payload.confidence,
    claim_trace: payload.claim_trace || [],
    trace_completeness: payload.trace_completeness || { ...EMPTY_TRACE },
    query_run_id: payload.query_run_id || null,
    trace_degraded: false,
    warnings: [],
    mode: 'audit',
});

export const api = {
    getApiUrl: (): string => API_URL,

    getRequestHeaders: (): Record<string, string> => ({ ...REQUEST_HEADERS }),

    getBrains: async (): Promise<Brain[]> => {
        const res = await axios.get(`${API_URL}/brains`, { headers: REQUEST_HEADERS });
        return res.data;
    },

    getBrainContent: async (name: string): Promise<BrainContent> => {
        const res = await axios.get(`${API_URL}/brains/${name}/content`, { headers: REQUEST_HEADERS });
        return res.data;
    },

    getBrainLog: async (name: string): Promise<LogEntry> => {
        const res = await axios.get(`${API_URL}/brains/${name}/log`, { headers: REQUEST_HEADERS });
        return res.data;
    },

    queryBrainStandard: async (
        name: string,
        question: string,
        autoEnrich: boolean = false,
        warnings: string[] = [],
    ): Promise<QueryApiResponse> => {
        const res = await axios.post(
            `${API_URL}/brains/${name}/query`,
            {
                question,
                provider: DEFAULT_PROVIDER,
                auto_enrich: autoEnrich,
                async_enrich: true,
            },
            { headers: REQUEST_HEADERS },
        );

        return {
            result: normalizeStandardResult(res.data, warnings),
            enrichmentJobId: (res.headers['x-enrichment-job-id'] as string | undefined) || null,
        };
    },

    queryBrainAudit: async (name: string, question: string): Promise<QueryApiResponse> => {
        const res = await axios.post(
            `${API_URL}/brains/${name}/query/audit`,
            {
                question,
                provider: DEFAULT_PROVIDER,
                include_claim_trace: true,
            },
            { headers: REQUEST_HEADERS },
        );

        return {
            result: normalizeAuditResult(res.data),
            enrichmentJobId: null,
        };
    },

    queryBrainPreferred: async (name: string, question: string): Promise<QueryApiResponse> => {
        try {
            return await api.queryBrainAudit(name, question);
        } catch (error) {
            if (axios.isAxiosError(error) && error.response?.status === 404) {
                return api.queryBrainStandard(name, question, false, [
                    'Audit trace is disabled on this backend. Showing standard query output.',
                ]);
            }
            throw error;
        }
    },

    triggerEnrichment: async (name: string, question: string): Promise<QueryApiResponse> => {
        return api.queryBrainStandard(name, question, true, [
            'Enrichment trigger sent. A background job will run if a knowledge gap is detected.',
        ]);
    },

    getEnrichmentJob: async (jobId: string): Promise<EnrichmentJob> => {
        const res = await axios.get(`${API_URL}/enrichment-jobs/${jobId}`, { headers: REQUEST_HEADERS });
        return res.data;
    },

    getEnrichmentJobs: async (): Promise<EnrichmentJob[]> => {
        const res = await axios.get(`${API_URL}/enrichment-jobs`, { headers: REQUEST_HEADERS });
        return res.data;
    },

    getIngestionJobs: async (): Promise<IngestionJob[]> => {
        const res = await axios.get(`${API_URL}/jobs`, { headers: REQUEST_HEADERS });
        return res.data;
    },

    getBrainGraph: async (
        name: string,
    ): Promise<{ nodes: Array<Record<string, unknown>>; links: Array<Record<string, unknown>> }> => {
        const res = await axios.get(`${API_URL}/brains/${name}/graph`, { headers: REQUEST_HEADERS });
        return res.data;
    },

    getFileContent: async (brainName: string, path: string): Promise<{ path: string; content: string }> => {
        const res = await axios.get(`${API_URL}/brains/${brainName}/files/${path}`, { headers: REQUEST_HEADERS });
        return res.data;
    },
};
