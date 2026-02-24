import { lazy, Suspense, useMemo, useState } from 'react';
import {
    Activity,
    Brain as BrainIcon,
    ChevronDown,
    Loader2,
    Maximize2,
    Plus,
    RefreshCw,
    Search,
} from 'lucide-react';
import type { Brain } from '../types';

const Visualizer = lazy(async () => {
    const module = await import('./Visualizer');
    return { default: module.Visualizer };
});

interface HeaderProps {
    brain: Brain | null;
    brains: Brain[];
    pendingJobs: number;
    onSelectBrain: (brain: Brain) => void;
    onIngestClick: () => void;
    onToggleJobs: () => void;
    onRefresh: () => Promise<void>;
}

export const Header: React.FC<HeaderProps> = ({
    brain,
    brains,
    pendingJobs,
    onSelectBrain,
    onIngestClick,
    onToggleJobs,
    onRefresh,
}) => {
    const [showDropdown, setShowDropdown] = useState(false);
    const [showVisualizer, setShowVisualizer] = useState(false);
    const [search, setSearch] = useState('');
    const [refreshing, setRefreshing] = useState(false);

    const filteredBrains = useMemo(() => {
        const q = search.trim().toLowerCase();
        if (!q) return brains;
        return brains.filter(item => item.name.toLowerCase().includes(q) || item.objective.toLowerCase().includes(q));
    }, [brains, search]);

    return (
        <>
            <header className="workspace-header">
                <div className="workspace-header__left">
                    <span className="workspace-header__label">Knowledge Workspace</span>

                    <div className="brain-switcher">
                        <button
                            type="button"
                            onClick={() => setShowDropdown(current => !current)}
                            className="brain-switcher__trigger"
                            aria-expanded={showDropdown}
                        >
                            <BrainIcon size={15} />
                            <span>{brain ? brain.name : 'Select Brain'}</span>
                            <ChevronDown size={14} className={showDropdown ? 'rotate-180 transition-transform' : 'transition-transform'} />
                        </button>

                        {showDropdown && (
                            <div className="brain-switcher__menu" role="menu">
                                <div className="brain-switcher__search">
                                    <Search size={13} />
                                    <input
                                        type="text"
                                        placeholder="Find brain"
                                        value={search}
                                        onChange={event => setSearch(event.target.value)}
                                        autoFocus
                                    />
                                </div>

                                <div className="brain-switcher__list">
                                    {filteredBrains.length === 0 ? (
                                        <p className="brain-switcher__empty">No matching brains</p>
                                    ) : (
                                        filteredBrains.map(item => (
                                            <button
                                                key={item.name}
                                                type="button"
                                                className={`brain-switcher__option ${brain?.name === item.name ? 'is-active' : ''}`}
                                                onClick={() => {
                                                    onSelectBrain(item);
                                                    setShowDropdown(false);
                                                }}
                                            >
                                                <span>{item.name}</span>
                                                <small>{item.file_count} files</small>
                                            </button>
                                        ))
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                <div className="workspace-header__actions">
                    <button type="button" className="button button--ghost" onClick={onToggleJobs}>
                        <Activity size={14} />
                        Ops
                        {pendingJobs > 0 && <span className="button__badge">{pendingJobs}</span>}
                    </button>

                    <button
                        type="button"
                        className="button button--ghost"
                        onClick={async () => {
                            setRefreshing(true);
                            try {
                                await onRefresh();
                            } finally {
                                setRefreshing(false);
                            }
                        }}
                        disabled={refreshing}
                    >
                        {refreshing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                        Refresh
                    </button>

                    <button type="button" className="button button--solid" onClick={onIngestClick}>
                        <Plus size={14} />
                        Ingest
                    </button>

                    <button
                        type="button"
                        className="button button--accent"
                        onClick={() => setShowVisualizer(true)}
                        disabled={!brain}
                    >
                        <Maximize2 size={14} />
                        Visualizer
                    </button>
                </div>

                {showDropdown && <div className="brain-switcher__backdrop" onClick={() => setShowDropdown(false)} />}
            </header>

            {showVisualizer && brain && (
                <Suspense
                    fallback={
                        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 text-slate-200">
                            <Loader2 size={18} className="animate-spin" />
                            <span className="ml-2 text-sm">Loading visualizer...</span>
                        </div>
                    }
                >
                    <Visualizer brainName={brain.name} onClose={() => setShowVisualizer(false)} />
                </Suspense>
            )}
        </>
    );
};
