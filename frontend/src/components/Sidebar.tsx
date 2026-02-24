import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, FileText, Filter, Search } from 'lucide-react';
import type { Brain, BrainContent, FileNode } from '../types';

interface SidebarProps {
    brain: Brain | null;
    content: BrainContent | null;
    onSelectFile: (file: FileNode) => void;
    selectedFileId: string | null;
    loading: boolean;
}

const CATEGORY_ORDER: Array<keyof BrainContent> = ['characters', 'themes', 'timeline', 'facts'];

export const Sidebar: React.FC<SidebarProps> = ({ brain, content, onSelectFile, selectedFileId, loading }) => {
    const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>({
        characters: true,
        themes: true,
        timeline: false,
        facts: false,
    });
    const [searchQuery, setSearchQuery] = useState('');

    const filteredContent = useMemo(() => {
        if (!content) {
            return {
                characters: [],
                themes: [],
                timeline: [],
                facts: [],
            } as BrainContent;
        }

        const q = searchQuery.trim().toLowerCase();
        if (!q) return content;

        const filterItems = (items: FileNode[]) =>
            items.filter(item => {
                const haystack = `${item.name} ${item.summary} ${(item.tags || []).join(' ')}`.toLowerCase();
                return haystack.includes(q);
            });

        return {
            characters: filterItems(content.characters),
            themes: filterItems(content.themes),
            timeline: filterItems(content.timeline),
            facts: filterItems(content.facts),
        };
    }, [content, searchQuery]);

    const totalFiles = useMemo(
        () => CATEGORY_ORDER.reduce((acc, key) => acc + (filteredContent[key]?.length || 0), 0),
        [filteredContent],
    );

    if (loading) {
        return (
            <aside className="workspace-rail workspace-rail--left">
                <div className="rail-skeleton" />
                <div className="rail-skeleton rail-skeleton--tall" />
                <div className="rail-skeleton rail-skeleton--tall" />
            </aside>
        );
    }

    return (
        <aside className="workspace-rail workspace-rail--left">
            <section className="rail-block">
                <p className="rail-kicker">Current brain</p>
                <h1 className="rail-title">{brain?.name || 'No brain selected'}</h1>
                <p className="rail-subtitle">{brain?.objective || 'Select or ingest a brain to begin.'}</p>
            </section>

            <section className="rail-block">
                <div className="rail-search">
                    <Search size={14} />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={event => setSearchQuery(event.target.value)}
                        placeholder="Filter nodes"
                    />
                </div>
                <div className="rail-metric-row">
                    <span>{totalFiles} visible</span>
                    <span className="rail-metric-pill">
                        <Filter size={12} />
                        {searchQuery ? 'Filtered' : 'All'}
                    </span>
                </div>
            </section>

            <nav className="rail-nav" aria-label="Knowledge folders">
                {CATEGORY_ORDER.map(category => {
                    const files = filteredContent[category] || [];
                    const isOpen = expandedFolders[category];

                    return (
                        <section key={category} className="rail-folder">
                            <button
                                type="button"
                                className="rail-folder__toggle"
                                onClick={() =>
                                    setExpandedFolders(prev => ({
                                        ...prev,
                                        [category]: !prev[category],
                                    }))
                                }
                            >
                                {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                <span>{category}</span>
                                <small>{files.length}</small>
                            </button>

                            {isOpen && (
                                <div className="rail-folder__items" role="list">
                                    {files.length === 0 ? (
                                        <p className="rail-folder__empty">No matches in {category}</p>
                                    ) : (
                                        files.map(file => (
                                            <button
                                                key={file.id}
                                                type="button"
                                                className={`rail-file ${selectedFileId === file.id ? 'is-active' : ''}`}
                                                onClick={() => onSelectFile(file)}
                                            >
                                                <FileText size={13} />
                                                <span>{file.name}</span>
                                            </button>
                                        ))
                                    )}
                                </div>
                            )}
                        </section>
                    );
                })}
            </nav>
        </aside>
    );
};
