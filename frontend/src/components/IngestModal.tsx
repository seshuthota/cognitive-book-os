import { useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, FileText, Loader2, Upload, X } from 'lucide-react';
import { api } from '../api/client';

interface IngestModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

export const IngestModal: React.FC<IngestModalProps> = ({ isOpen, onClose, onSuccess }) => {
    const [file, setFile] = useState<File | null>(null);
    const [brainName, setBrainName] = useState('');
    const [objective, setObjective] = useState('');
    const [strategy, setStrategy] = useState<'standard' | 'triage'>('standard');
    const [status, setStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
    const [errorMsg, setErrorMsg] = useState('');
    const [jobId, setJobId] = useState<string | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    if (!isOpen) return null;

    const resetForm = () => {
        setFile(null);
        setBrainName('');
        setObjective('');
        setStrategy('standard');
        setStatus('idle');
        setErrorMsg('');
        setJobId(null);
    };

    const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const selected = event.target.files?.[0] || null;
        if (!selected) return;

        if (selected.type !== 'application/pdf') {
            setStatus('error');
            setErrorMsg('Only PDF files are supported.');
            return;
        }

        setStatus('idle');
        setErrorMsg('');
        setFile(selected);

        if (!brainName) {
            const normalized = selected.name.replace(/\.pdf$/i, '').replace(/[^a-zA-Z0-9_-]/g, '_');
            setBrainName(normalized);
        }
    };

    const handleSubmit = async () => {
        if (!file || !brainName.trim()) {
            setStatus('error');
            setErrorMsg('Select a PDF and provide a brain name.');
            return;
        }

        if (strategy === 'triage' && !objective.trim()) {
            setStatus('error');
            setErrorMsg('Triage strategy requires an objective.');
            return;
        }

        setStatus('uploading');
        setErrorMsg('');

        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('brain_name', brainName.trim());
            formData.append('strategy', strategy);
            formData.append(
                'objective',
                objective.trim() || 'General Comprehensive Knowledge Extraction',
            );

            const response = await fetch(`${api.getApiUrl()}/ingest`, {
                method: 'POST',
                headers: api.getRequestHeaders(),
                body: formData,
            });

            if (!response.ok) {
                const detail = await response.text();
                throw new Error(detail || `HTTP ${response.status}`);
            }

            const payload = await response.json();
            setJobId(payload.job_id || null);
            setStatus('success');

            await onSuccess();
        } catch (error) {
            setStatus('error');
            setErrorMsg((error as Error).message || 'Failed to start ingestion.');
        }
    };

    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal-card" onClick={event => event.stopPropagation()} role="dialog" aria-modal="true">
                <header className="modal-card__header">
                    <div>
                        <p className="rail-kicker">Ingestion</p>
                        <h3 className="rail-title">Create a New Brain</h3>
                    </div>
                    <button type="button" className="icon-button" onClick={onClose}>
                        <X size={14} />
                    </button>
                </header>

                <div className="modal-card__body">
                    {status === 'success' && (
                        <div className="modal-status modal-status--success">
                            <CheckCircle2 size={16} />
                            <div>
                                <p>Ingestion accepted and running in background.</p>
                                {jobId && <small>Job ID: {jobId}</small>}
                            </div>
                        </div>
                    )}

                    {status === 'error' && (
                        <div className="modal-status modal-status--error">
                            <AlertCircle size={16} />
                            <p>{errorMsg}</p>
                        </div>
                    )}

                    <section className="form-group">
                        <label>PDF Document</label>
                        <button
                            type="button"
                            className={`upload-drop ${file ? 'is-selected' : ''}`}
                            onClick={() => fileInputRef.current?.click()}
                        >
                            {file ? (
                                <span>
                                    <FileText size={16} /> {file.name}
                                </span>
                            ) : (
                                <span>
                                    <Upload size={16} /> Click to choose a PDF
                                </span>
                            )}
                        </button>
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".pdf"
                            onChange={handleFileChange}
                            className="hidden"
                        />
                    </section>

                    <section className="form-group">
                        <label>Brain Name</label>
                        <input
                            type="text"
                            value={brainName}
                            onChange={event => setBrainName(event.target.value.replace(/[^a-zA-Z0-9_-]/g, '_'))}
                            placeholder="journeys_book_1"
                        />
                    </section>

                    <section className="form-group">
                        <label>Extraction Strategy</label>
                        <div className="segmented-control">
                            <button
                                type="button"
                                className={strategy === 'standard' ? 'is-active' : ''}
                                onClick={() => setStrategy('standard')}
                            >
                                Standard
                            </button>
                            <button
                                type="button"
                                className={strategy === 'triage' ? 'is-active' : ''}
                                onClick={() => setStrategy('triage')}
                            >
                                Triage
                            </button>
                        </div>
                        <p className="form-hint">
                            {strategy === 'standard'
                                ? 'Comprehensive extraction across all major chapters.'
                                : 'Objective-driven extraction focused on your question.'}
                        </p>
                    </section>

                    <section className="form-group">
                        <label>Objective {strategy === 'triage' ? '(Required)' : '(Optional)'}</label>
                        <textarea
                            rows={4}
                            value={objective}
                            onChange={event => setObjective(event.target.value)}
                            placeholder="What should this brain prove, compare, or extract?"
                        />
                    </section>
                </div>

                <footer className="modal-card__footer">
                    <button
                        type="button"
                        className="button button--ghost"
                        onClick={() => {
                            resetForm();
                            onClose();
                        }}
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        className="button button--solid"
                        onClick={() => void handleSubmit()}
                        disabled={status === 'uploading'}
                    >
                        {status === 'uploading' ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                        Start Ingestion
                    </button>
                </footer>
            </div>
        </div>
    );
};
