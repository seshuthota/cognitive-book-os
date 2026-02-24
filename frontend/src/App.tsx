import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, AlertCircle, BookOpen, CheckCircle2, Loader2, Sparkles, XCircle } from 'lucide-react';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { Chat } from './components/Chat';
import { FileInspector, type InspectorTab } from './components/FileInspector';
import { IngestModal } from './components/IngestModal';
import { api } from './api/client';
import type { Brain, BrainContent, EvidenceSnapshot, FileNode, EnrichmentJob, IngestionJob } from './types';

function App() {
  const [brains, setBrains] = useState<Brain[]>([]);
  const [selectedBrain, setSelectedBrain] = useState<Brain | null>(null);
  const [brainContent, setBrainContent] = useState<BrainContent | null>(null);
  const [selectedFile, setSelectedFile] = useState<FileNode | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<EvidenceSnapshot | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('evidence');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showIngest, setShowIngest] = useState(false);
  const [showJobsDrawer, setShowJobsDrawer] = useState(false);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [enrichmentJobs, setEnrichmentJobs] = useState<EnrichmentJob[]>([]);

  const loadBrainContent = useCallback(async (brain: Brain) => {
    setLoading(true);
    setSelectedBrain(brain);
    setSelectedFile(null);
    setInspectorTab('evidence');

    try {
      const content = await api.getBrainContent(brain.name);
      setBrainContent(content);
      setError(null);
    } catch (err) {
      setError(`Failed to load brain content: ${(err as Error).message}`);
      setBrainContent(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshBrains = useCallback(async () => {
    const brainList = await api.getBrains();
    setBrains(brainList);

    if (brainList.length === 0) {
      setSelectedBrain(null);
      setBrainContent(null);
      setLoading(false);
      return;
    }

    if (!selectedBrain) {
      await loadBrainContent(brainList[0]);
      return;
    }

    const updatedSelection = brainList.find(item => item.name === selectedBrain.name);
    if (!updatedSelection) {
      await loadBrainContent(brainList[0]);
      return;
    }

    if (
      updatedSelection.file_count !== selectedBrain.file_count ||
      updatedSelection.objective !== selectedBrain.objective
    ) {
      setSelectedBrain(updatedSelection);
    }
  }, [loadBrainContent, selectedBrain]);

  const refreshJobs = useCallback(async () => {
    const [ingestion, enrichment] = await Promise.all([api.getIngestionJobs(), api.getEnrichmentJobs()]);
    setJobs(ingestion);
    setEnrichmentJobs(enrichment);
  }, []);

  const openEvidenceInspector = useCallback(() => {
    setInspectorTab('evidence');
  }, []);

  useEffect(() => {
    const initialize = async () => {
      try {
        await Promise.all([refreshBrains(), refreshJobs()]);
      } catch (err) {
        setError(`Failed to connect to Cognitive Core: ${(err as Error).message}`);
        setLoading(false);
      }
    };

    void initialize();

    const interval = setInterval(() => {
      void refreshJobs().catch(fetchError => {
        console.error('Failed to poll jobs', fetchError);
      });
    }, 4000);

    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleIngestSuccess = useCallback(async () => {
    await Promise.all([refreshBrains(), refreshJobs()]);
  }, [refreshBrains, refreshJobs]);

  const handleRefresh = useCallback(async () => {
    await Promise.all([refreshBrains(), refreshJobs()]);
  }, [refreshBrains, refreshJobs]);

  const pendingJobs = jobs.filter(job => job.status === 'processing').length;
  const pendingEnrichmentJobs = enrichmentJobs.filter(job => job.status === 'processing').length;
  const totalPendingJobs = pendingJobs + pendingEnrichmentJobs;

  const recentIngestion = useMemo(() => jobs.slice().reverse().slice(0, 6), [jobs]);
  const recentEnrichment = useMemo(() => enrichmentJobs.slice().reverse().slice(0, 6), [enrichmentJobs]);

  if (error) {
    return (
      <div className="h-screen bg-slate-950 text-slate-100">
        <div className="mx-auto flex h-full max-w-xl flex-col items-center justify-center gap-4 px-6 text-center">
          <XCircle size={32} className="text-rose-300" />
          <h2 className="text-xl font-semibold">Cognitive Core Unreachable</h2>
          <p className="text-sm text-slate-300">{error}</p>
          <button
            type="button"
            className="button button--solid"
            onClick={() => window.location.reload()}
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Sidebar
        brain={selectedBrain}
        content={brainContent}
        onSelectFile={file => {
          setSelectedFile(file);
          setInspectorTab('file');
        }}
        selectedFileId={selectedFile?.id || null}
        loading={loading && Boolean(selectedBrain)}
      />

      <main className="workspace-main">
        <Header
          brain={selectedBrain}
          brains={brains}
          pendingJobs={totalPendingJobs}
          onSelectBrain={brain => {
            void loadBrainContent(brain);
          }}
          onIngestClick={() => setShowIngest(true)}
          onToggleJobs={() => setShowJobsDrawer(current => !current)}
          onRefresh={handleRefresh}
        />

        {selectedBrain ? (
          <Chat
            brainName={selectedBrain.name}
            onEvidenceUpdate={evidence => {
              setActiveEvidence(evidence);
              setInspectorTab('evidence');
            }}
            onOpenInspector={openEvidenceInspector}
          />
        ) : (
          <section className="workspace-empty">
            <div className="workspace-empty__card">
              <BookOpen size={24} />
              <h2>No brains yet</h2>
              <p>
                Start by ingesting your first document. The system will build a structured brain you can query,
                inspect, and enrich.
              </p>
              <button type="button" className="button button--solid" onClick={() => setShowIngest(true)}>
                <Sparkles size={14} />
                Ingest First Brain
              </button>
            </div>
          </section>
        )}
      </main>

      <FileInspector
        brainName={selectedBrain?.name || ''}
        file={selectedFile}
        evidence={activeEvidence}
        tab={inspectorTab}
        onTabChange={setInspectorTab}
        onClearFile={() => setSelectedFile(null)}
      />

      {showJobsDrawer && (
        <aside className="jobs-drawer" aria-label="Operations drawer">
          <header>
            <div>
              <p className="rail-kicker">Operations</p>
              <h3 className="rail-title">Ingestion & Enrichment</h3>
            </div>
            <button type="button" className="icon-button" onClick={() => setShowJobsDrawer(false)}>
              <XCircle size={14} />
            </button>
          </header>

          <section className="jobs-section">
            <h4>
              <Activity size={14} /> Active
            </h4>
            {totalPendingJobs === 0 ? (
              <p className="jobs-empty">No active jobs.</p>
            ) : (
              <ul>
                {jobs
                  .filter(job => job.status === 'processing')
                  .map(job => (
                    <li key={`ingest_${job.job_id || job.started_at}`}>
                      <Loader2 size={12} className="animate-spin" />
                      <span>Ingesting {job.brain_name}</span>
                    </li>
                  ))}
                {enrichmentJobs
                  .filter(job => job.status === 'processing')
                  .map(job => (
                    <li key={`enrich_${job.job_id}`}>
                      <Loader2 size={12} className="animate-spin" />
                      <span>Enriching {job.brain_name}</span>
                    </li>
                  ))}
              </ul>
            )}
          </section>

          <section className="jobs-section">
            <h4>Recent ingestion runs</h4>
            {recentIngestion.length === 0 ? (
              <p className="jobs-empty">No ingestion history yet.</p>
            ) : (
              <ul>
                {recentIngestion.map(job => (
                  <li key={`recent_${job.job_id || job.started_at}`}>
                    {job.status === 'completed' ? (
                      <CheckCircle2 size={12} className="text-emerald-300" />
                    ) : job.status === 'failed' ? (
                      <AlertCircle size={12} className="text-rose-300" />
                    ) : (
                      <Loader2 size={12} className="animate-spin" />
                    )}
                    <span>{job.brain_name}</span>
                    <small>{job.status}</small>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="jobs-section">
            <h4>Recent enrichment runs</h4>
            {recentEnrichment.length === 0 ? (
              <p className="jobs-empty">No enrichment runs yet.</p>
            ) : (
              <ul>
                {recentEnrichment.map(job => (
                  <li key={`recent_enrich_${job.job_id}`}>
                    {job.status === 'completed' ? (
                      <CheckCircle2 size={12} className="text-emerald-300" />
                    ) : job.status === 'failed' ? (
                      <AlertCircle size={12} className="text-rose-300" />
                    ) : (
                      <Loader2 size={12} className="animate-spin" />
                    )}
                    <span>{job.brain_name}</span>
                    <small>{job.status}</small>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      )}

      <IngestModal
        isOpen={showIngest}
        onClose={() => setShowIngest(false)}
        onSuccess={handleIngestSuccess}
      />
    </div>
  );
}

export default App;
