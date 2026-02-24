import { useEffect, useState, useRef, useMemo, lazy, Suspense } from 'react';
import { Network, X, ZoomIn, ZoomOut, Maximize, Cuboid, Search, Filter, ChevronRight } from 'lucide-react';
import { api } from '../api/client';
import ReactMarkdown from 'react-markdown';
import type { ForceGraphMethods as ForceGraph2DMethods } from 'react-force-graph-2d';
import type { ForceGraphMethods as ForceGraph3DMethods } from 'react-force-graph-3d';

const ForceGraph2D = lazy(() => import('react-force-graph-2d'));
const ForceGraph3D = lazy(() => import('react-force-graph-3d'));

interface VisualizerProps {
    brainName: string;
    onClose: () => void;
}

type NodeId = string | number;

interface GraphNode {
    id: NodeId;
    label: string;
    group: string;
    x?: number;
    y?: number;
    z?: number;
}

interface GraphLink {
    source: NodeId | GraphNode;
    target: NodeId | GraphNode;
}

interface GraphData {
    nodes: GraphNode[];
    links: GraphLink[];
}

interface NodeDetail {
    path: string;
    content: string;
}

interface SpriteTextInstance {
    color: string;
    textHeight: number;
    padding: number;
}

type SpriteTextCtor = new (text: string) => SpriteTextInstance;

const numberOrUndefined = (value: unknown): number | undefined =>
    typeof value === 'number' && Number.isFinite(value) ? value : undefined;

const normalizeNode = (raw: Record<string, unknown>): GraphNode | null => {
    const id = raw.id;
    if (typeof id !== 'string' && typeof id !== 'number') {
        return null;
    }

    const group = typeof raw.group === 'string' ? raw.group : 'facts';
    const label = typeof raw.label === 'string' ? raw.label : String(id);

    return {
        id,
        label,
        group,
        x: numberOrUndefined(raw.x),
        y: numberOrUndefined(raw.y),
        z: numberOrUndefined(raw.z),
    };
};

const normalizeEndpoint = (value: unknown): NodeId | GraphNode | null => {
    if (typeof value === 'string' || typeof value === 'number') return value;

    if (value && typeof value === 'object') {
        const maybeNode = normalizeNode(value as Record<string, unknown>);
        return maybeNode;
    }

    return null;
};

const endpointId = (endpoint: NodeId | GraphNode): NodeId =>
    typeof endpoint === 'object' ? endpoint.id : endpoint;

const toGraphNode = (value: unknown): GraphNode | null => {
    if (!value || typeof value !== 'object') return null;
    return normalizeNode(value as Record<string, unknown>);
};

const normalizeGraphData = (payload: {
    nodes: Array<Record<string, unknown>>;
    links: Array<Record<string, unknown>>;
}): GraphData => {
    const nodes = payload.nodes
        .map(normalizeNode)
        .filter((node): node is GraphNode => Boolean(node));

    const links = payload.links
        .map(item => {
            const source = normalizeEndpoint(item.source);
            const target = normalizeEndpoint(item.target);
            if (!source || !target) return null;
            return { source, target } as GraphLink;
        })
        .filter((link): link is GraphLink => Boolean(link));

    return { nodes, links };
};

export const Visualizer: React.FC<VisualizerProps> = ({ brainName, onClose }) => {
    const [data, setData] = useState<GraphData>({ nodes: [], links: [] });
    const [loading, setLoading] = useState(true);
    const [dimensions, setDimensions] = useState({ width: window.innerWidth * 0.8, height: window.innerHeight * 0.8 });
    const graph2DRef = useRef<ForceGraph2DMethods<Record<string, unknown>, Record<string, unknown>> | undefined>(undefined);
    const graph3DRef = useRef<ForceGraph3DMethods<Record<string, unknown>, Record<string, unknown>> | undefined>(undefined);

    // Feature states
    const [is3D, setIs3D] = useState(false);
    const [show3DLabels, setShow3DLabels] = useState(false);
    const [spriteTextClass, setSpriteTextClass] = useState<SpriteTextCtor | null>(null);
    const [searchTerm, setSearchTerm] = useState('');
    const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
    const [nodeDetail, setNodeDetail] = useState<NodeDetail | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);

    // Filtering
    const [hiddenGroups, setHiddenGroups] = useState<Set<string>>(new Set());

    useEffect(() => {
        setLoading(true);
        api.getBrainGraph(brainName)
            .then(graphData => {
                setData(normalizeGraphData(graphData));
            })
            .catch(err => console.error('Failed to load graph:', err))
            .finally(() => setLoading(false));

        const handleResize = () => {
            setDimensions({
                width: window.innerWidth * 0.8,
                height: window.innerHeight * 0.8,
            });
        };

        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, [brainName]);

    useEffect(() => {
        if (!is3D || !show3DLabels || spriteTextClass) return;
        import('three-spritetext')
            .then(mod => setSpriteTextClass(() => mod.default as SpriteTextCtor))
            .catch(err => console.error('Failed to load three-spritetext:', err));
    }, [is3D, show3DLabels, spriteTextClass]);

    useEffect(() => {
        if (!selectedNode) {
            setNodeDetail(null);
            return;
        }

        setDetailLoading(true);
        api.getFileContent(brainName, String(selectedNode.id))
            .then(detail => setNodeDetail(detail))
            .catch(err => console.error(err))
            .finally(() => setDetailLoading(false));
    }, [selectedNode, brainName]);

    const handleZoomIn = () => {
        if (is3D) {
            const camera = graph3DRef.current?.camera();
            if (camera) {
                graph3DRef.current?.cameraPosition({ z: camera.position.z * 0.8 }, undefined, 400);
            }
            return;
        }

        const currentZoom = graph2DRef.current?.zoom();
        if (typeof currentZoom === 'number') {
            graph2DRef.current?.zoom(currentZoom * 1.2, 400);
        }
    };

    const handleZoomOut = () => {
        if (is3D) {
            const camera = graph3DRef.current?.camera();
            if (camera) {
                graph3DRef.current?.cameraPosition({ z: camera.position.z * 1.2 }, undefined, 400);
            }
            return;
        }

        const currentZoom = graph2DRef.current?.zoom();
        if (typeof currentZoom === 'number') {
            graph2DRef.current?.zoom(currentZoom / 1.2, 400);
        }
    };

    const handleZoomFit = () => {
        if (is3D) {
            graph3DRef.current?.zoomToFit(400);
            return;
        }
        graph2DRef.current?.zoomToFit(400);
    };

    const toggleGroup = (group: string) => {
        const next = new Set(hiddenGroups);
        if (next.has(group)) next.delete(group);
        else next.add(group);
        setHiddenGroups(next);
    };

    const visibleData = useMemo(() => {
        const search = searchTerm.toLowerCase();
        const nodes = data.nodes.filter(node => !hiddenGroups.has(node.group)
            && (search === '' || node.label.toLowerCase().includes(search)));

        const nodeIds = new Set(nodes.map(node => node.id));
        const links = data.links.filter(link => {
            const sourceId = endpointId(link.source);
            const targetId = endpointId(link.target);
            return nodeIds.has(sourceId) && nodeIds.has(targetId);
        });

        return { nodes, links };
    }, [data, hiddenGroups, searchTerm]);

    const groups = useMemo(() => {
        const set = new Set(data.nodes.map(node => node.group));
        return Array.from(set);
    }, [data]);

    const colors: Record<string, string> = {
        characters: '#f87171',
        timeline: '#60a5fa',
        themes: '#c084fc',
        facts: '#4ade80',
        locations: '#facc15',
        root: '#e2e8f0',
    };

    return (
        <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center animate-in fade-in duration-200" onClick={onClose}>
            <div className="bg-slate-950 border border-slate-700 rounded-xl w-[90vw] h-[90vh] shadow-2xl relative flex flex-col overflow-hidden" onClick={e => e.stopPropagation()}>
                <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-slate-900 z-10 shrink-0">
                    <div className="flex items-center gap-3">
                        <Network size={20} className="text-blue-400" />
                        <h3 className="text-lg font-bold text-white">Knowledge Graph</h3>
                        <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
                            {brainName}
                        </span>

                        <div className="relative ml-4">
                            <Search size={14} className="absolute left-2.5 top-1.5 text-slate-500" />
                            <input
                                type="text"
                                placeholder="Search nodes..."
                                className="bg-slate-800 border border-slate-700 rounded-full pl-8 pr-3 py-1 text-xs text-white focus:outline-none focus:border-blue-500 w-48 transition-all"
                                value={searchTerm}
                                onChange={e => setSearchTerm(e.target.value)}
                            />
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setIs3D(!is3D)}
                            className={`p-1.5 rounded-lg flex items-center gap-2 text-xs font-medium transition-colors border ${is3D ? 'bg-blue-600 border-blue-500 text-white' : 'bg-slate-800 border-slate-700 text-slate-400 hover:text-white'}`}
                        >
                            <Cuboid size={16} />
                            {is3D ? '3D Mode' : '2D Mode'}
                        </button>

                        {is3D && (
                            <button
                                onClick={() => setShow3DLabels(!show3DLabels)}
                                className={`p-1.5 rounded-lg text-xs font-medium transition-colors border ${show3DLabels ? 'bg-indigo-600 border-indigo-500 text-white' : 'bg-slate-800 border-slate-700 text-slate-400 hover:text-white'}`}
                            >
                                {show3DLabels ? '3D Labels: On' : '3D Labels: Off'}
                            </button>
                        )}

                        <div className="flex bg-slate-800 rounded-lg mx-2 border border-slate-700">
                            <button onClick={handleZoomOut} className="p-1.5 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors" title="Zoom Out">
                                <ZoomOut size={16} />
                            </button>
                            <button onClick={handleZoomFit} className="p-1.5 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors border-l border-r border-slate-700" title="Fit to Screen">
                                <Maximize size={16} />
                            </button>
                            <button onClick={handleZoomIn} className="p-1.5 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors" title="Zoom In">
                                <ZoomIn size={16} />
                            </button>
                        </div>

                        <button onClick={onClose} className="text-slate-500 hover:text-white p-2 hover:bg-slate-800 rounded-lg transition-colors">
                            <X size={20} />
                        </button>
                    </div>
                </div>

                <div className="flex flex-1 overflow-hidden relative">
                    <div className="flex-1 bg-slate-950 relative cursor-move">
                        {loading ? (
                            <div className="absolute inset-0 flex items-center justify-center text-slate-500 flex-col gap-2">
                                <div className="w-8 h-8 md-2 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                                <p className="text-sm font-medium">Tracing neural pathways...</p>
                            </div>
                        ) : (data.nodes.length === 0) ? (
                            <div className="absolute inset-0 flex items-center justify-center text-slate-500">
                                <p className="text-lg">No graph data available for this brain.</p>
                            </div>
                        ) : (
                            <Suspense
                                fallback={
                                    <div className="absolute inset-0 flex items-center justify-center text-slate-500">
                                        <p className="text-sm">Loading graph renderer...</p>
                                    </div>
                                }
                            >
                                {is3D ? (
                                    <ForceGraph3D
                                        ref={graph3DRef}
                                        width={dimensions.width}
                                        height={dimensions.height}
                                        graphData={visibleData}
                                        nodeLabel="label"
                                        nodeColor={node => colors[(node as GraphNode).group] || '#94a3b8'}
                                        nodeRelSize={4}
                                        {...(show3DLabels && spriteTextClass
                                            ? {
                                                nodeThreeObject: (node: GraphNode) => {
                                                    const sprite = new spriteTextClass(node.label);
                                                    sprite.color = colors[node.group] || '#94a3b8';
                                                    sprite.textHeight = 1.5;
                                                    sprite.padding = 1;
                                                    return sprite;
                                                },
                                                nodeThreeObjectExtend: true,
                                            }
                                            : {})}
                                        linkColor={() => '#334155'}
                                        linkWidth={1}
                                        backgroundColor="#020617"
                                        onNodeClick={rawNode => {
                                            const node = toGraphNode(rawNode);
                                            if (!node) return;
                                            setSelectedNode(node);

                                            const distance = 40;
                                            const nodeX = node.x ?? 0;
                                            const nodeY = node.y ?? 0;
                                            const nodeZ = node.z ?? 0;
                                            const hyp = Math.hypot(nodeX, nodeY, nodeZ) || 1;
                                            const distRatio = 1 + distance / hyp;

                                            graph3DRef.current?.cameraPosition(
                                                { x: nodeX * distRatio, y: nodeY * distRatio, z: nodeZ * distRatio },
                                                { x: nodeX, y: nodeY, z: nodeZ },
                                                3000,
                                            );
                                        }}
                                    />
                                ) : (
                                    <ForceGraph2D
                                        ref={graph2DRef}
                                        width={dimensions.width}
                                        height={dimensions.height}
                                        graphData={visibleData}
                                        nodeCanvasObject={(rawNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
                                            const node = toGraphNode(rawNode);
                                            if (!node) return;
                                            const label = node.label;
                                            const fontSize = 12 / globalScale;
                                            ctx.font = `${fontSize}px Sans-Serif`;

                                            const color = colors[node.group] || '#94a3b8';
                                            const x = node.x ?? 0;
                                            const y = node.y ?? 0;

                                            ctx.beginPath();
                                            ctx.arc(x, y, 5, 0, 2 * Math.PI, false);
                                            ctx.fillStyle = color;
                                            ctx.fill();

                                            if (selectedNode && selectedNode.id === node.id) {
                                                ctx.beginPath();
                                                ctx.arc(x, y, 8, 0, 2 * Math.PI, false);
                                                ctx.strokeStyle = '#60a5fa';
                                                ctx.lineWidth = 2 / globalScale;
                                                ctx.stroke();
                                            }

                                            if (globalScale > 0.5) {
                                                ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
                                                ctx.textAlign = 'center';
                                                ctx.textBaseline = 'middle';
                                                ctx.fillText(label, x, y + 8);
                                            }
                                        }}
                                        onNodeClick={rawNode => {
                                            const node = toGraphNode(rawNode);
                                            if (!node) return;
                                            setSelectedNode(node);
                                            if (typeof node.x === 'number' && typeof node.y === 'number') {
                                                graph2DRef.current?.centerAt(node.x, node.y, 1000);
                                                graph2DRef.current?.zoom(2.5, 1000);
                                            }
                                        }}
                                        linkColor={() => '#334155'}
                                        linkWidth={1.5}
                                        backgroundColor="#020617"
                                    />
                                )}
                            </Suspense>
                        )}

                        <div className="absolute bottom-4 left-4 bg-slate-900/90 backdrop-blur border border-slate-700 p-3 rounded-lg z-10 text-xs shadow-xl">
                            <div className="flex items-center justify-between mb-2">
                                <h4 className="font-bold text-slate-400 uppercase tracking-wider text-[10px]">Filter Groups</h4>
                                <Filter size={10} className="text-slate-500" />
                            </div>
                            <div className="space-y-1.5">
                                {groups.map(group => (
                                    <div
                                        key={group}
                                        onClick={() => toggleGroup(group)}
                                        className={`flex items-center gap-2 cursor-pointer transition-opacity ${hiddenGroups.has(group) ? 'opacity-40 grayscale' : 'opacity-100'}`}
                                    >
                                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: colors[group] || '#94a3b8' }}></span>
                                        <span className="text-slate-300 capitalize">{group}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    {selectedNode && (
                        <div className="w-[600px] bg-slate-900 border-l border-slate-800 flex flex-col animate-in slide-in-from-right duration-300 z-20 shadow-xl">
                            <div className="p-4 border-b border-slate-800 flex items-start justify-between bg-slate-800/50">
                                <div>
                                    <h4 className="font-bold text-white text-lg leading-tight">{selectedNode.label}</h4>
                                    <span className="text-xs text-slate-400 capitalize inline-block mt-1">{selectedNode.group}</span>
                                </div>
                                <button onClick={() => setSelectedNode(null)} className="text-slate-500 hover:text-white transition-colors">
                                    <X size={16} />
                                </button>
                            </div>

                            <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                                {detailLoading ? (
                                    <div className="flex items-center justify-center py-8">
                                        <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                                    </div>
                                ) : nodeDetail ? (
                                    <div className="prose prose-invert prose-sm max-w-none">
                                        <ReactMarkdown>{nodeDetail.content}</ReactMarkdown>
                                    </div>
                                ) : (
                                    <p className="text-slate-500 italic">No details found.</p>
                                )}
                            </div>

                            <div className="p-3 border-t border-slate-800 bg-slate-800/30 text-center">
                                <button className="text-xs text-blue-400 hover:text-blue-300 font-medium flex items-center justify-center gap-1 w-full py-1">
                                    Full Inspector <ChevronRight size={12} />
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
