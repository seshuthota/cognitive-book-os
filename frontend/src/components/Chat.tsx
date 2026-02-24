import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    AlertTriangle,
    BadgeCheck,
    Bot,
    BookOpen,
    Loader2,
    MessageSquare,
    Send,
    Sparkles,
    Target,
    Telescope,
} from 'lucide-react';
import { api } from '../api/client';
import type { EvidenceSnapshot, QueryResult } from '../types';

interface ChatProps {
    brainName: string;
    onEvidenceUpdate: (evidence: EvidenceSnapshot) => void;
    onOpenInspector: () => void;
}

interface ChatMessage {
    id: string;
    role: 'user' | 'assistant';
    kind: 'user' | 'system' | 'answer';
    content: string;
    question?: string;
    result?: QueryResult;
    timestamp: string;
}

const lowConfidence = (confidence: string): boolean => confidence === 'low' || confidence === 'none';

const createMessageId = (): string => {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    return `${Date.now()}_${Math.random().toString(16).slice(2)}`;
};

const confidenceTone = (confidence: string): string => {
    if (confidence === 'high') return 'text-emerald-300 border-emerald-400/30 bg-emerald-400/10';
    if (confidence === 'medium') return 'text-sky-300 border-sky-400/30 bg-sky-400/10';
    if (confidence === 'low') return 'text-amber-200 border-amber-400/30 bg-amber-300/10';
    return 'text-rose-200 border-rose-400/30 bg-rose-300/10';
};

export const Chat: React.FC<ChatProps> = ({ brainName, onEvidenceUpdate, onOpenInspector }) => {
    const providerLabel = (import.meta.env.VITE_PROVIDER || 'anthropic').toString();
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [activeTab, setActiveTab] = useState<'chat' | 'briefing'>('chat');
    const [autoEnrich, setAutoEnrich] = useState(true);
    const [enrichmentJobId, setEnrichmentJobId] = useState<string | null>(null);
    const [pendingEnrichmentQuestion, setPendingEnrichmentQuestion] = useState<string | null>(null);
    const [upgradingMessageId, setUpgradingMessageId] = useState<string | null>(null);
    const [enrichmentBusyQuestion, setEnrichmentBusyQuestion] = useState<string | null>(null);
    const scrollRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        setMessages([
            {
                id: createMessageId(),
                role: 'assistant',
                kind: 'system',
                content: `Brain '${brainName}' connected. Ask a question to synthesize evidence-backed answers.`,
                timestamp: new Date().toISOString(),
            },
        ]);
        setInput('');
        setEnrichmentJobId(null);
        setPendingEnrichmentQuestion(null);
        setUpgradingMessageId(null);
        setEnrichmentBusyQuestion(null);
        setActiveTab('chat');
    }, [brainName]);

    useEffect(() => {
        if (!scrollRef.current) return;
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }, [messages, loading, enrichmentJobId]);

    const pushSystem = useCallback((content: string) => {
        setMessages(prev => [
            ...prev,
            {
                id: createMessageId(),
                role: 'assistant',
                kind: 'system',
                content,
                timestamp: new Date().toISOString(),
            },
        ]);
    }, []);

    const emitEvidence = useCallback((question: string, result: QueryResult) => {
        onEvidenceUpdate({
            question,
            answer: result.answer,
            confidence: result.confidence,
            sources: result.sources,
            claimTrace: result.claim_trace,
            traceCompleteness: result.trace_completeness,
            queryRunId: result.query_run_id,
            traceDegraded: result.trace_degraded,
            warnings: result.warnings,
            mode: result.mode,
            timestamp: new Date().toISOString(),
        });
    }, [onEvidenceUpdate]);

    const triggerEnrichment = useCallback(async (question: string, announceIfNoJob: boolean) => {
        if (enrichmentBusyQuestion) return;
        setEnrichmentBusyQuestion(question);

        try {
            const { enrichmentJobId: newJobId } = await api.triggerEnrichment(brainName, question);

            if (newJobId) {
                setEnrichmentJobId(newJobId);
                setPendingEnrichmentQuestion(question);
                pushSystem('Enrichment job started. I will refresh this question when new context is integrated.');
            } else if (announceIfNoJob) {
                pushSystem('No enrichment job was scheduled. The system did not detect a retrievable gap for this question.');
            }
        } catch (error) {
            pushSystem(`Enrichment trigger failed: ${(error as Error).message}`);
        } finally {
            setEnrichmentBusyQuestion(null);
        }
    }, [brainName, enrichmentBusyQuestion, pushSystem]);

    useEffect(() => {
        if (!enrichmentJobId) return;

        const poll = async () => {
            try {
                const job = await api.getEnrichmentJob(enrichmentJobId);

                if (job.status === 'completed') {
                    setEnrichmentJobId(null);
                    pushSystem('Enrichment completed. Refreshing evidence snapshot now.');

                    if (pendingEnrichmentQuestion) {
                        try {
                            const refreshed = await api.queryBrainPreferred(brainName, pendingEnrichmentQuestion);
                            const refreshedMsg: ChatMessage = {
                                id: createMessageId(),
                                role: 'assistant',
                                kind: 'answer',
                                content: refreshed.result.answer,
                                question: pendingEnrichmentQuestion,
                                result: refreshed.result,
                                timestamp: new Date().toISOString(),
                            };
                            setMessages(prev => [...prev, refreshedMsg]);
                            emitEvidence(pendingEnrichmentQuestion, refreshed.result);
                            onOpenInspector();
                        } catch (refreshError) {
                            pushSystem(`Post-enrichment refresh failed: ${(refreshError as Error).message}`);
                        } finally {
                            setPendingEnrichmentQuestion(null);
                        }
                    }
                } else if (job.status === 'failed') {
                    setEnrichmentJobId(null);
                    setPendingEnrichmentQuestion(null);
                    pushSystem(`Enrichment failed: ${job.error || 'Unknown error'}`);
                }
            } catch (error) {
                setEnrichmentJobId(null);
                setPendingEnrichmentQuestion(null);
                pushSystem(`Lost enrichment job tracking: ${(error as Error).message}`);
            }
        };

        const interval = setInterval(poll, 2000);
        poll();
        return () => clearInterval(interval);
    }, [enrichmentJobId, pendingEnrichmentQuestion, brainName, emitEvidence, onOpenInspector, pushSystem]);

    const runQuery = async (question: string) => {
        setLoading(true);
        try {
            const { result } = await api.queryBrainPreferred(brainName, question);
            const responseMessage: ChatMessage = {
                id: createMessageId(),
                role: 'assistant',
                kind: 'answer',
                content: result.answer,
                question,
                result,
                timestamp: new Date().toISOString(),
            };
            setMessages(prev => [...prev, responseMessage]);
            emitEvidence(question, result);

            if (autoEnrich && lowConfidence(result.confidence)) {
                await triggerEnrichment(question, false);
            }
        } catch (error) {
            pushSystem(`Query failed: ${(error as Error).message}`);
        } finally {
            setLoading(false);
        }
    };

    const handleSend = async () => {
        const question = input.trim();
        if (!question || loading) return;

        setMessages(prev => [
            ...prev,
            {
                id: createMessageId(),
                role: 'user',
                kind: 'user',
                content: question,
                timestamp: new Date().toISOString(),
            },
        ]);
        setInput('');
        await runQuery(question);
    };

    const handleUpgradeToAudit = async (messageId: string) => {
        const target = messages.find(message => message.id === messageId);
        if (!target?.question) return;

        setUpgradingMessageId(messageId);
        try {
            const { result } = await api.queryBrainAudit(brainName, target.question);
            setMessages(prev =>
                prev.map(message =>
                    message.id === messageId
                        ? {
                            ...message,
                            content: result.answer,
                            result,
                            timestamp: new Date().toISOString(),
                        }
                        : message,
                ),
            );
            emitEvidence(target.question, result);
            onOpenInspector();
        } catch (error) {
            pushSystem(`Audit trace upgrade failed: ${(error as Error).message}`);
        } finally {
            setUpgradingMessageId(null);
        }
    };

    const briefingMessages = useMemo(
        () => messages.filter(message => message.kind === 'answer' && message.result),
        [messages],
    );

    return (
        <section className="flex h-full min-h-0 flex-col">
            <div className="workspace-tabs">
                <button
                    type="button"
                    className={`workspace-tab ${activeTab === 'chat' ? 'workspace-tab--active' : ''}`}
                    onClick={() => setActiveTab('chat')}
                >
                    <MessageSquare size={14} />
                    Synthesis
                </button>
                <button
                    type="button"
                    className={`workspace-tab ${activeTab === 'briefing' ? 'workspace-tab--active' : ''}`}
                    onClick={() => setActiveTab('briefing')}
                >
                    <BookOpen size={14} />
                    Briefing
                </button>
            </div>

            {activeTab === 'chat' ? (
                <>
                    <div className="flex-1 overflow-y-auto px-8 py-6" ref={scrollRef}>
                        <div className="mx-auto flex w-full max-w-4xl flex-col gap-5">
                            {messages.map(message => {
                                const result = message.result;
                                const isAnswer = message.kind === 'answer' && Boolean(result);

                                return (
                                    <article
                                        key={message.id}
                                        className={`chat-card ${
                                            message.role === 'user' ? 'chat-card--user' : message.kind === 'system' ? 'chat-card--system' : ''
                                        }`}
                                    >
                                        <header className="chat-card__meta">
                                            <span className="chat-card__author">
                                                {message.role === 'user' ? <Target size={12} /> : <Bot size={12} />}
                                                {message.role === 'user' ? 'You' : message.kind === 'system' ? 'System' : 'Cognitive Core'}
                                            </span>
                                            <time>{new Date(message.timestamp).toLocaleTimeString()}</time>
                                        </header>

                                        <div className="chat-card__content">
                                            {message.content.split('\n').map((line, index) => (
                                                <p key={`${message.id}_${index}`}>{line}</p>
                                            ))}
                                        </div>

                                        {isAnswer && result && (
                                            <div className="chat-card__evidence">
                                                <div className="chat-card__evidence-row">
                                                    <span className={`confidence-badge ${confidenceTone(result.confidence)}`}>
                                                        <BadgeCheck size={12} />
                                                        {result.confidence}
                                                    </span>
                                                    <span className="chat-card__trace-tag">
                                                        {result.trace_degraded ? 'Trace: degraded' : 'Trace: full'}
                                                    </span>
                                                </div>

                                                {result.sources.length > 0 && (
                                                    <div className="source-chip-row">
                                                        {result.sources.map(source => (
                                                            <span key={source} className="source-chip">
                                                                {source}
                                                            </span>
                                                        ))}
                                                    </div>
                                                )}

                                                <div className="chat-card__actions">
                                                    <button
                                                        type="button"
                                                        className="action-link"
                                                        onClick={() => {
                                                            emitEvidence(message.question || '', result);
                                                            onOpenInspector();
                                                        }}
                                                    >
                                                        <Telescope size={14} />
                                                        Open evidence panel
                                                    </button>

                                                    {result.trace_degraded && (
                                                        <button
                                                            type="button"
                                                            className="action-link"
                                                            onClick={() => handleUpgradeToAudit(message.id)}
                                                            disabled={upgradingMessageId === message.id}
                                                        >
                                                            {upgradingMessageId === message.id ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                                                            Run with audit trace
                                                        </button>
                                                    )}

                                                    {lowConfidence(result.confidence) && (
                                                        <button
                                                            type="button"
                                                            className="action-link action-link--warn"
                                                            onClick={() => triggerEnrichment(message.question || '', true)}
                                                            disabled={Boolean(enrichmentBusyQuestion)}
                                                        >
                                                            <AlertTriangle size={14} />
                                                            Enrich this gap
                                                        </button>
                                                    )}
                                                </div>

                                                {(result.warnings.length > 0 || result.trace_completeness.total_statements > 0) && (
                                                    <details className="explain-panel">
                                                        <summary>Why this confidence?</summary>
                                                        <ul>
                                                            <li>
                                                                Trace coverage: {result.trace_completeness.linked_statements}/
                                                                {result.trace_completeness.total_statements} (
                                                                {(result.trace_completeness.completeness_ratio * 100).toFixed(0)}%)
                                                            </li>
                                                            {result.warnings.map(warning => (
                                                                <li key={warning}>{warning}</li>
                                                            ))}
                                                        </ul>
                                                    </details>
                                                )}
                                            </div>
                                        )}
                                    </article>
                                );
                            })}

                            {(loading || enrichmentJobId) && (
                                <div className="status-strip">
                                    <Loader2 size={14} className="animate-spin" />
                                    {loading
                                        ? 'Synthesizing answer...'
                                        : 'Enrichment job running in background. Evidence will refresh when completed.'}
                                </div>
                            )}
                        </div>
                    </div>

                    <footer className="composer-shell">
                        <div className="mx-auto flex w-full max-w-4xl flex-col gap-3">
                            <label className="composer-label" htmlFor="query-input">
                                Ask a precise question
                            </label>
                            <div className="composer-row">
                                <input
                                    id="query-input"
                                    type="text"
                                    placeholder={`What should ${brainName} prove or explain?`}
                                    value={input}
                                    onChange={event => setInput(event.target.value)}
                                    onKeyDown={event => {
                                        if (event.key === 'Enter') {
                                            event.preventDefault();
                                            void handleSend();
                                        }
                                    }}
                                    disabled={loading}
                                />
                                <button type="button" onClick={() => void handleSend()} disabled={loading || !input.trim()}>
                                    {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                                    Send
                                </button>
                            </div>

                            <div className="composer-meta">
                                <label>
                                    <input
                                        type="checkbox"
                                        checked={autoEnrich}
                                        onChange={event => setAutoEnrich(event.target.checked)}
                                    />
                                    Auto-enrich when confidence is low
                                </label>
                                <span>Provider: {providerLabel}</span>
                            </div>
                        </div>
                    </footer>
                </>
            ) : (
                <div className="flex-1 overflow-y-auto px-8 py-6">
                    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
                        <h2 className="text-lg font-semibold text-slate-100">Research Briefing</h2>
                        {briefingMessages.length === 0 ? (
                            <div className="empty-briefing">
                                <BookOpen size={22} />
                                Ask questions in Synthesis mode to build a briefing timeline.
                            </div>
                        ) : (
                            briefingMessages.map((item, index) => (
                                <article key={item.id} className="briefing-card">
                                    <header>
                                        <span>Finding {index + 1}</span>
                                        <span className={`confidence-badge ${confidenceTone(item.result?.confidence || 'none')}`}>
                                            {(item.result?.confidence || 'none').toUpperCase()}
                                        </span>
                                    </header>
                                    <p>{item.content}</p>
                                    {item.result && item.result.sources.length > 0 && (
                                        <div className="source-chip-row">
                                            {item.result.sources.map(source => (
                                                <span key={`${item.id}_${source}`} className="source-chip">
                                                    {source}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </article>
                            ))
                        )}
                    </div>
                </div>
            )}
        </section>
    );
};
