import { useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle,
    BookText,
    ChevronRight,
    FileText,
    Gauge,
    Link as LinkIcon,
    NotebookPen,
    Orbit,
    X,
} from 'lucide-react';
import type { EvidenceSnapshot, FileNode } from '../types';
import { api } from '../api/client';

export type InspectorTab = 'evidence' | 'file' | 'run';

interface FileInspectorProps {
    brainName: string;
    file: FileNode | null;
    evidence: EvidenceSnapshot | null;
    tab: InspectorTab;
    onTabChange: (tab: InspectorTab) => void;
    onClearFile: () => void;
}

export const FileInspector: React.FC<FileInspectorProps> = ({
    brainName,
    file,
    evidence,
    tab,
    onTabChange,
    onClearFile,
}) => {
    const [contentCache, setContentCache] = useState<Record<string, string>>({});

    const cacheKey = file ? `${brainName}:${file.id}` : null;
    const content = cacheKey ? contentCache[cacheKey] : '';
    const loading = Boolean(cacheKey && contentCache[cacheKey] === undefined);

    useEffect(() => {
        if (!file || !brainName || !cacheKey || contentCache[cacheKey] !== undefined) return;
        api
            .getFileContent(brainName, file.id)
            .then(data => {
                setContentCache(prev => ({
                    ...prev,
                    [cacheKey]: data.content,
                }));
            })
            .catch(error => {
                setContentCache(prev => ({
                    ...prev,
                    [cacheKey]: `Error loading file: ${error}`,
                }));
            });
    }, [file, brainName, cacheKey, contentCache]);

    const tracePercent = useMemo(() => {
        if (!evidence) return 0;
        return Math.round((evidence.traceCompleteness.completeness_ratio || 0) * 100);
    }, [evidence]);

    return (
        <aside className="workspace-rail workspace-rail--right">
            <header className="inspector-header">
                <div>
                    <p className="rail-kicker">Inspector</p>
                    <h2 className="rail-title">Evidence & Context</h2>
                </div>
                {file ? (
                    <button type="button" className="icon-button" onClick={onClearFile}>
                        <X size={14} />
                    </button>
                ) : (
                    <ChevronRight size={14} className="text-slate-500" />
                )}
            </header>

            <div className="inspector-tabs" role="tablist" aria-label="Inspector tabs">
                <button
                    type="button"
                    role="tab"
                    aria-selected={tab === 'evidence'}
                    className={`inspector-tab ${tab === 'evidence' ? 'is-active' : ''}`}
                    onClick={() => onTabChange('evidence')}
                >
                    <Orbit size={13} /> Evidence
                </button>
                <button
                    type="button"
                    role="tab"
                    aria-selected={tab === 'file'}
                    className={`inspector-tab ${tab === 'file' ? 'is-active' : ''}`}
                    onClick={() => onTabChange('file')}
                >
                    <FileText size={13} /> File
                </button>
                <button
                    type="button"
                    role="tab"
                    aria-selected={tab === 'run'}
                    className={`inspector-tab ${tab === 'run' ? 'is-active' : ''}`}
                    onClick={() => onTabChange('run')}
                >
                    <Gauge size={13} /> Run
                </button>
            </div>

            <div className="inspector-body">
                {tab === 'evidence' && (
                    <section className="inspector-section">
                        {!evidence ? (
                            <p className="inspector-empty">No evidence selected yet. Ask a question in Synthesis and open evidence.</p>
                        ) : (
                            <>
                                <div className="inspector-card">
                                    <p className="inspector-label">Question</p>
                                    <p>{evidence.question}</p>
                                </div>
                                <div className="inspector-card">
                                    <p className="inspector-label">Answer</p>
                                    <p>{evidence.answer}</p>
                                </div>
                                <div className="inspector-card">
                                    <p className="inspector-label">Sources</p>
                                    {evidence.sources.length === 0 ? (
                                        <p className="inspector-empty-inline">No explicit sources returned.</p>
                                    ) : (
                                        <div className="source-chip-row">
                                            {evidence.sources.map(source => (
                                                <span key={source} className="source-chip">
                                                    {source}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </div>

                                <div className="inspector-card">
                                    <p className="inspector-label">Claim Trace</p>
                                    {evidence.claimTrace.length === 0 ? (
                                        <p className="inspector-empty-inline">Trace unavailable in this response mode.</p>
                                    ) : (
                                        <ul className="trace-list">
                                            {evidence.claimTrace.slice(0, 8).map(item => (
                                                <li key={`${item.claim_id}_${item.file_path}`}>
                                                    <p>{item.claim_text}</p>
                                                    <small>
                                                        <LinkIcon size={11} /> {item.source_locator}
                                                    </small>
                                                </li>
                                            ))}
                                        </ul>
                                    )}
                                </div>
                            </>
                        )}
                    </section>
                )}

                {tab === 'file' && (
                    <section className="inspector-section">
                        {!file ? (
                            <p className="inspector-empty">Select a file from the left rail to inspect source content.</p>
                        ) : (
                            <>
                                <div className="inspector-card">
                                    <p className="inspector-label">Selected file</p>
                                    <p>{file.name}</p>
                                    <small>{file.id}</small>
                                </div>
                                <div className="inspector-card">
                                    <p className="inspector-label">Summary</p>
                                    <p>{file.summary || 'No summary available.'}</p>
                                </div>
                                <div className="inspector-card">
                                    <p className="inspector-label">Raw content</p>
                                    <pre className="content-preview">{loading ? 'Loading content...' : content || 'No content.'}</pre>
                                </div>
                            </>
                        )}
                    </section>
                )}

                {tab === 'run' && (
                    <section className="inspector-section">
                        {!evidence ? (
                            <p className="inspector-empty">Run metadata appears after at least one answer.</p>
                        ) : (
                            <>
                                <div className="inspector-card">
                                    <p className="inspector-label">Run details</p>
                                    <ul className="meta-list">
                                        <li>
                                            <span>Mode</span>
                                            <strong>{evidence.mode}</strong>
                                        </li>
                                        <li>
                                            <span>Confidence</span>
                                            <strong>{evidence.confidence}</strong>
                                        </li>
                                        <li>
                                            <span>Trace completeness</span>
                                            <strong>{tracePercent}%</strong>
                                        </li>
                                        <li>
                                            <span>Query run id</span>
                                            <strong>{evidence.queryRunId || 'n/a'}</strong>
                                        </li>
                                    </ul>
                                </div>

                                {evidence.traceDegraded && (
                                    <div className="inspector-warning">
                                        <AlertTriangle size={14} />
                                        This response used standard mode. Run audit trace to inspect claim-level evidence.
                                    </div>
                                )}

                                {evidence.warnings.length > 0 && (
                                    <div className="inspector-card">
                                        <p className="inspector-label">Warnings</p>
                                        <ul className="warning-list">
                                            {evidence.warnings.map(warning => (
                                                <li key={warning}>
                                                    <NotebookPen size={12} />
                                                    <span>{warning}</span>
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )}

                                <div className="inspector-card">
                                    <p className="inspector-label">Timestamp</p>
                                    <p>
                                        <BookText size={13} className="inline-block mr-2" />
                                        {new Date(evidence.timestamp).toLocaleString()}
                                    </p>
                                </div>
                            </>
                        )}
                    </section>
                )}
            </div>
        </aside>
    );
};
