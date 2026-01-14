import React, { useEffect, useState, useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

interface GraphNode {
    id: string;
    label: string;
    group: string;
    color?: string;
    val?: number;
}

interface GraphLink {
    source: string;
    target: string;
    label: string;
}

interface GraphData {
    nodes: GraphNode[];
    links: GraphLink[];
}

const GraphViewer: React.FC = () => {
    const params = new URLSearchParams(window.location.search);
    const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const fgRef = useRef<any>(null);

    const entity = params.get('entity');
    const kbId = params.get('kb_id');
    const backend = params.get('backend') || 'neo4j';
    const mode = params.get('mode') || 'entity'; // 'entity' | 'schema'

    const [showLabels, setShowLabels] = useState(false);
    const [isSchemaMode, setIsSchemaMode] = useState(mode === 'schema');
    const [showEntityRelationsOnly, setShowEntityRelationsOnly] = useState(false);
    const [repulsion, setRepulsion] = useState(400); // Default repulsion strength

    const [backendType, setBackendType] = useState(backend); // State to hold verified backend
    const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(new Set());
    const [hoveredLink, setHoveredLink] = useState<any>(null);

    // Helper to detect chunk nodes (UUID_section patterns or explicit Chunk group)
    const isChunkNode = useCallback((node: any) => {
        if (node.group === 'Chunk') return true;
        if (node.id.startsWith('b')) return true; // blank nodes
        // UUID_section pattern: matches anywhere in ID (for full URIs like http://rag.local/source/...)
        const uuidSectionPattern = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_section/i;
        if (uuidSectionPattern.test(node.id)) return true;
        if (node.label && uuidSectionPattern.test(node.label)) return true;
        // Also catch IDs containing 'source/' (Fuseki chunk storage path)
        if (node.id.includes('/source/')) return true;
        return false;
    }, []);


    // Helper to apply styles to a node based on its state
    const processNodeStyle = useCallback((node: any, isFocus: boolean, isRoot: boolean = false) => {
        let color = '#44ff88'; // Vibrant Green for Entities
        let val = 12;
        const isChunk = isChunkNode(node);
        const isClass = node.group === 'Class';
        const isInstance = node.group === 'Instance';

        if (isClass) {
            color = '#ff9933'; // Orange for Class nodes (schema view)
            val = 15;
        } else if (isInstance) {
            color = '#88cc88'; // Light Green for Instance nodes (schema view expansion)
            val = 10;
        } else if (isRoot) {
            color = '#ff4444'; // Vibrant Red for Root
            val = 100; // Increased even more (approx 2x radius of Focus nodes)
        } else if (isFocus) {
            color = '#ff4444'; // Vibrant Red for Target/Focused
            val = 20; // Small focused nodes
        } else if (isChunk) {
            color = '#4488ff'; // Vibrant Blue for Chunk nodes
        }

        return {
            ...node,
            label: isChunk ? '[chunk]' : node.label,
            val: val,
            color: color,
            isChunk: isChunk, // Mark for filtering
            isClass: isClass,
            isInstance: isInstance
        };
    }, [isChunkNode]);
    // Helper to calculate curvature for links sharing the same node pair
    const processLinksCurvature = useCallback((links: any[]) => {
        const linkMap = new Map<string, any[]>();

        links.forEach(link => {
            // Handle both string IDs and object references (force-graph transforms them)
            const s = typeof link.source === 'object' ? link.source.id : link.source;
            const t = typeof link.target === 'object' ? link.target.id : link.target;

            // Sort IDs to group A->B and B->A together
            const key = [s, t].sort().join('-');

            if (!linkMap.has(key)) {
                linkMap.set(key, []);
            }
            linkMap.get(key)?.push(link);
        });

        const newLinks = [...links]; // Shallow copy to avoid mutating original recklessly if needed

        linkMap.forEach((groupLinks) => {
            const len = groupLinks.length;
            // If more than 1 link between same nodes, curve them
            // If more than 1 link between same nodes, curve them
            if (len > 0) { // Changed to > 0 to allow processing even single links if needed, but really we care about multiple
                groupLinks.forEach((link, idx) => {
                    const curvatureScale = 0.7; // Increased from 0.5 for wider separation

                    // If len is 1, curvature is 0.
                    // If len > 1, we spread them out.
                    let c = 0;
                    if (len > 1) {
                        c = (idx - (len - 1) / 2) * curvatureScale;
                    }

                    const s = typeof link.source === 'object' ? link.source.id : link.source;
                    const t = typeof link.target === 'object' ? link.target.id : link.target;

                    if (s > t) {
                        c = -c;
                    }

                    link.curvature = c;
                });
            }
        });

        return newLinks;
    }, []);



    useEffect(() => {
        // For schema mode, we don't need entity parameter
        if (mode === 'schema') {
            if (!kbId) {
                setError("Missing required parameter: kb_id");
                setLoading(false);
                return;
            }
            setIsSchemaMode(true);
            setShowLabels(true); // Auto-enable labels in schema mode
            setRepulsion(600); // Wider spacing for class hierarchy
        } else {
            if (!entity || !kbId) {
                setError("Missing required parameters: entity, kb_id");
                setLoading(false);
                return;
            }
            setIsSchemaMode(false);
        }

        const fetchData = async () => {
            setLoading(true);
            try {
                // 1. Resolve Backend Type
                // Priority: URL Param > KB Metadata > Default (ontology)
                let resolvedBackend = backend || 'ontology';

                if (!backend) {
                    try {
                        const kbResp = await fetch(`/api/knowledge-bases/${kbId}`);
                        if (kbResp.ok) {
                            const kbData = await kbResp.json();
                            if (kbData.graph_backend) {
                                resolvedBackend = kbData.graph_backend;
                            }
                        }
                    } catch (e) {
                        console.warn("Failed to fetch KB details, using default backend:", e);
                    }
                }

                setBackendType(resolvedBackend);

                // 2. Fetch Graph Data
                let response;
                // Use mode directly as isSchemaMode state might not be updated yet
                if (mode === 'schema') {
                    // Fetch schema data
                    response = await fetch(`/api/retrieval/graph/schema?kb_id=${kbId}&backend=${resolvedBackend}`);
                } else {
                    // Fetch entity expansion data
                    response = await fetch(`/api/retrieval/graph/expand?kb_id=${kbId}&entity=${encodeURIComponent(entity || '')}&backend=${resolvedBackend}`);
                }

                if (!response.ok) {
                    const text = await response.text();
                    throw new Error(`API Error (${response.status}): ${text}`);
                }

                const contentType = response.headers.get("content-type");
                if (!contentType || !contentType.includes("application/json")) {
                    const text = await response.text();
                    throw new Error(`Received non-JSON response from server: ${text.substring(0, 100)}...`);
                }

                const data = await response.json();

                const processedNodes = data.nodes.map((n: any) => {
                    if (mode === 'schema') {
                        return processNodeStyle(n, false, false);
                    }
                    const isTarget = n.id === entity || n.label === entity ||
                        (n.id.includes('/') && decodeURIComponent(n.id.split('/').pop() || '') === entity);

                    if (isTarget) {
                        setExpandedNodeIds(prev => new Set(prev).add(n.id));
                    }
                    // Pass isTarget as BOTH 2nd (isFocus) and 3rd (isRoot) arguments
                    return processNodeStyle(n, isTarget, isTarget);
                });

                setGraphData({
                    nodes: processedNodes,
                    links: processLinksCurvature(data.links)
                });

            } catch (err: any) {
                console.error(err);
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, [entity, kbId, backend, mode, processNodeStyle, processLinksCurvature]);

    // Compute visible data based on filters
    const visibleGraphData = React.useMemo(() => {
        if (!showEntityRelationsOnly) {
            return graphData;
        }

        const visibleNodes = graphData.nodes.filter(n =>
            !(n as any).isChunk
        );

        const visibleNodeIds = new Set(visibleNodes.map(n => n.id));

        const visibleLinks = graphData.links.filter(l => {
            const sourceId = typeof l.source === 'object' ? (l.source as any).id : l.source;
            const targetId = typeof l.target === 'object' ? (l.target as any).id : l.target;
            return visibleNodeIds.has(sourceId) && visibleNodeIds.has(targetId);
        });

        return { nodes: visibleNodes, links: visibleLinks };
    }, [graphData, showEntityRelationsOnly]);

    useEffect(() => {
        if (fgRef.current && visibleGraphData.nodes.length > 0) {
            const fg = fgRef.current;
            const chargeForce = fg.d3Force('charge');
            if (chargeForce) {
                chargeForce.strength(-repulsion).distanceMax(repulsion * 2);
            }
            const linkDistance = Math.max(20, repulsion / 4);
            const linkForce = fg.d3Force('link');
            if (linkForce) {
                linkForce.distance(linkDistance);
            }
            try {
                fg.cooldownTime(Infinity);
                fg.d3ReheatSimulation();
                setTimeout(() => {
                    fg.cooldownTime(15000);
                }, 100);
            } catch (e) {
                fg.d3ReheatSimulation();
            }
        }
    }, [visibleGraphData, repulsion]);



    const handleNodeClick = useCallback(async (node: any) => {
        // 1. Center and Zoom
        fgRef.current?.centerAt(node.x, node.y, 1000);
        fgRef.current?.zoom(3, 2000);

        if (!kbId) return;

        // Determine if this node is the root entity
        const isNodeRoot = node.id === entity || node.label === entity ||
            (node.id.includes('/') && decodeURIComponent(node.id.split('/').pop() || '') === entity);

        // CHECK TOGGLE: If already expanded, try to COLLAPSE
        if (expandedNodeIds.has(node.id)) {
            // Prevent collapsing the root entity (initial search target)
            if (isNodeRoot) {
                console.log("Blocking collapse for root node:", node.label);
                return;
            }

            // Collapse Logic: Remove leaf nodes connected ONLY to this node
            setGraphData(prev => {
                // Find neighbors of the clicked node
                const neighbors = new Set<string>();
                (prev.links as any[]).forEach(l => {
                    const s = typeof l.source === 'object' ? l.source.id : l.source;
                    const t = typeof l.target === 'object' ? l.target.id : l.target;
                    if (s === node.id) neighbors.add(t);
                    if (t === node.id) neighbors.add(s);
                });

                // For each neighbor, check if it has connections to ANYONE ELSE but the clicked node
                const nodesToRemove = new Set<string>();

                neighbors.forEach(neighborId => {
                    // Start assuming it's removable
                    let isRemovable = true;

                    // Look through ALL links
                    for (const l of prev.links as any[]) {
                        const s = typeof l.source === 'object' ? l.source.id : l.source;
                        const t = typeof l.target === 'object' ? l.target.id : l.target;

                        // If this link involves the neighbor
                        if (s === neighborId || t === neighborId) {
                            const other = (s === neighborId) ? t : s;
                            // If connected to someone who is NOT the clicked node, then we can't delete this neighbor
                            if (other !== node.id) {
                                isRemovable = false;
                                break;
                            }
                        }
                    }

                    if (isRemovable) {
                        nodesToRemove.add(neighborId);
                    }
                });

                console.log(`Collapsing node ${node.label}. Removing ${nodesToRemove.size} neighbors.`);

                const newNodes = prev.nodes.filter(n => !nodesToRemove.has(n.id));
                // Remove any links connected to removed nodes
                const newLinks = (prev.links as any[]).filter(l => {
                    const s = typeof l.source === 'object' ? l.source.id : l.source;
                    const t = typeof l.target === 'object' ? l.target.id : l.target;
                    return !nodesToRemove.has(s) && !nodesToRemove.has(t);
                });

                // Revert style of current node (remove Focus)
                const currentNode = newNodes.find(n => n.id === node.id);
                if (currentNode) {
                    // Keep root status in mind if needed, but collapse usually implies reverting to default unless it's root (which is blocked above)
                    Object.assign(currentNode, processNodeStyle(currentNode, false, isNodeRoot));
                }

                return {
                    nodes: newNodes,
                    links: processLinksCurvature(newLinks)
                };
            });

            setExpandedNodeIds(prev => {
                const next = new Set(prev);
                next.delete(node.id);
                return next;
            });
            return;
        }

        // EXPAND LOGIC (If not already expanded)
        try {
            let apiUrl: string;

            // In schema mode, clicking a class node fetches its instances
            if (isSchemaMode && node.isClass) {
                apiUrl = `/api/retrieval/graph/schema/instances?kb_id=${kbId}&class_uri=${encodeURIComponent(node.id)}&limit=20`;
            } else {
                // Normal entity expansion
                apiUrl = `/api/retrieval/graph/expand?kb_id=${kbId}&entity=${encodeURIComponent(node.label)}&backend=${backendType}`;
            }

            const response = await fetch(apiUrl);

            if (!response.ok) {
                const text = await response.text();
                console.error("Expansion API Error:", text);
                return;
            }

            const contentType = response.headers.get("content-type");
            if (!contentType || !contentType.includes("application/json")) {
                const text = await response.text();
                console.error("Received non-JSON response:", text);
                return;
            }

            const data = await response.json();

            setGraphData(prev => {
                const existingNodesMap = new Map(prev.nodes.map(n => [n.id, n]));
                const existingLinksSet = new Set(prev.links.map(l => {
                    const s = (typeof l.source === 'object') ? (l.source as any).id : l.source;
                    const t = (typeof l.target === 'object') ? (l.target as any).id : l.target;
                    return `${s}-${t}-${l.label}`;
                }));

                // Update clicked node style to "Focus"
                const currentClicked = existingNodesMap.get(node.id);
                if (currentClicked) {
                    Object.assign(currentClicked, processNodeStyle(currentClicked, true, isNodeRoot));
                }
                setExpandedNodeIds(prev => new Set(prev).add(node.id));

                // Merge New Nodes
                const newNodes = [...prev.nodes];
                data.nodes.forEach((n: any) => {
                    if (!existingNodesMap.has(n.id)) {
                        // Check if new node is accidentally the root (unlikely but safe)
                        const nIsRoot = n.id === entity || n.label === entity ||
                            (n.id.includes('/') && decodeURIComponent(n.id.split('/').pop() || '') === entity);
                        newNodes.push(processNodeStyle(n, false, nIsRoot));
                        existingNodesMap.set(n.id, n);
                    }
                });

                // Merge New Links
                const mergedLinks = [...prev.links];
                data.links.forEach((l: any) => {
                    const linkId = `${l.source}-${l.target}-${l.label}`;
                    if (!existingLinksSet.has(linkId)) {
                        mergedLinks.push(l);
                        existingLinksSet.add(linkId);
                    }
                });

                // Recalculate curvature for ALL links (existing + new)
                const curvedLinks = processLinksCurvature(mergedLinks);

                return { nodes: newNodes, links: curvedLinks };
            });

        } catch (e) {
            console.error("Expansion failed", e);
        }
    }, [kbId, backendType, entity, expandedNodeIds, processNodeStyle, processLinksCurvature]);

    if (loading) return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#111', color: '#fff' }}>Loading Graph...</div>;
    if (error) return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#111', color: '#ff4444' }}>Error: {error}</div>;

    return (
        <div style={{ width: '100vw', height: '100vh', background: '#000011' }}>
            <style>{`
                .graph-tooltip {
                    font-size: 24px !important;
                    background: rgba(0, 0, 0, 0.9) !important;
                    border: 1px solid #4488ff !important;
                    border-radius: 4px !important;
                    padding: 8px 12px !important;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.5) !important;
                }
            `}</style>
            <div style={{ position: 'absolute', top: 20, left: 20, zIndex: 100, color: '#fff', background: 'rgba(0,0,0,0.7)', padding: '10px', borderRadius: '5px' }}>
                <h2 style={{ margin: 0 }}>{isSchemaMode ? 'Schema View' : entity}</h2>
                <small>Source: {backendType}</small>
            </div>

            <div style={{ position: 'absolute', top: 20, right: 20, zIndex: 100, color: '#fff', background: 'rgba(0,0,0,0.7)', padding: '12px', borderRadius: '5px', display: 'flex', flexDirection: 'column', gap: '12px', minWidth: '180px' }}>
                {/* Repulsion Slider */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <label style={{ fontSize: '0.85rem', opacity: 0.8 }}>Repulsion: {repulsion}</label>
                    <input
                        type="range"
                        min="80"
                        max="1000"
                        step="50"
                        value={repulsion}
                        onChange={(e) => setRepulsion(Number(e.target.value))}
                        style={{ cursor: 'pointer', width: '100%' }}
                    />
                </div>

                {/* Show Labels Checkbox */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <input
                        type="checkbox"
                        id="showLabels"
                        checked={showLabels}
                        onChange={(e) => setShowLabels(e.target.checked)}
                        style={{ cursor: 'pointer' }}
                    />
                    <label htmlFor="showLabels" style={{ cursor: 'pointer', fontSize: '0.9rem' }}>Show Labels</label>
                </div>

                {/* Show Entity Relations Only Checkbox */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <input
                        type="checkbox"
                        id="showEntityRelations"
                        checked={showEntityRelationsOnly}
                        onChange={(e) => setShowEntityRelationsOnly(e.target.checked)}
                        style={{ cursor: 'pointer' }}
                    />
                    <label htmlFor="showEntityRelations" style={{ cursor: 'pointer', fontSize: '0.9rem' }}>Entities Only</label>
                </div>
            </div>

            <ForceGraph2D
                ref={fgRef}
                graphData={visibleGraphData}
                nodeLabel="label"
                nodeColor="color"
                nodeRelSize={8}

                nodeCanvasObject={(node: any, ctx, globalScale) => {
                    const label = node.label;
                    const fontSize = 16 / globalScale; // Increased to 16 as requested
                    const r = node.val ? Math.sqrt(node.val) * 2 : 4;  // rough approximation of nodeRelSize logic

                    // Draw Node
                    ctx.beginPath();
                    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
                    ctx.fillStyle = node.color || '#fff';
                    ctx.fill();

                    // Selection glow could go here

                    // Draw Label if enabled
                    if (showLabels) {
                        ctx.font = `${fontSize}px Sans-Serif`;
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'middle';
                        ctx.fillStyle = 'white';
                        // Draw below the node
                        ctx.fillText(label, node.x, node.y + r + fontSize);
                    }
                }}
                nodeCanvasObjectMode={() => 'replace'} // We draw everything ourselves

                linkLabel={link => (link as any).label}
                linkDirectionalArrowLength={Math.max(6, repulsion / 50)}
                linkDirectionalArrowRelPos={0.85}
                linkWidth={2}

                linkCurvature="curvature"
                linkColor={() => 'rgba(255,255,255,0.4)'}

                onLinkHover={setHoveredLink}
                linkHoverPrecision={10}
                linkCanvasObjectMode={() => 'after'}
                linkCanvasObject={(link: any, ctx, globalScale) => {
                    if (hoveredLink !== link) return;
                    const isHovered = true; // Since we returned if not hovered
                    const start = link.source;
                    const end = link.target;

                    // Validate coordinates
                    if (typeof start !== 'object' || typeof end !== 'object') return;
                    if (!Number.isFinite(start.x) || !Number.isFinite(start.y) || !Number.isFinite(end.x) || !Number.isFinite(end.y)) return;

                    // Calculate Text Position (Midpoint of Bezier Curve t=0.5)
                    const midX = (start.x + end.x) / 2;
                    const midY = (start.y + end.y) / 2;

                    let textX = midX;
                    let textY = midY;

                    if (link.curvature) {
                        const dx = end.x - start.x;
                        const dy = end.y - start.y;
                        const cpX = midX + link.curvature * dy;
                        const cpY = midY - link.curvature * dx;

                        textX = (start.x + 2 * cpX + end.x) / 4;
                        textY = (start.y + 2 * cpY + end.y) / 4;
                    }

                    // Draw Label Box
                    const label = link.label || '';
                    const fontSize = 18 / globalScale; // Base size for always-on labels
                    ctx.font = `bold ${fontSize}px Sans-Serif`;
                    const textWidth = ctx.measureText(label).width;
                    const bckgDimensions = [textWidth + 10 / globalScale, fontSize + 8 / globalScale];

                    // Draw Background (Rounded Rect)
                    ctx.save();
                    ctx.translate(textX, textY);

                    ctx.fillStyle = 'rgba(0, 0, 0, 0.95)';
                    ctx.strokeStyle = '#4488ff';
                    ctx.lineWidth = 1.5 / globalScale;

                    ctx.beginPath();
                    const r = 6 / globalScale; // radius adjusted for size 18
                    const w = bckgDimensions[0];
                    const h = bckgDimensions[1];
                    const x = -w / 2;
                    const y = -h / 2;

                    ctx.moveTo(x + r, y);
                    ctx.lineTo(x + w - r, y);
                    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
                    ctx.lineTo(x + w, y + h - r);
                    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
                    ctx.lineTo(x + r, y + h);
                    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
                    ctx.lineTo(x, y + r);
                    ctx.quadraticCurveTo(x, y, x + r, y);
                    ctx.closePath();

                    ctx.fill();
                    ctx.stroke();

                    // Draw Text
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillStyle = '#ffffff';
                    ctx.fillText(label, 0, 0);

                    ctx.restore();
                }}

                onNodeClick={handleNodeClick}
                backgroundColor="#000011"
                d3AlphaDecay={0.02}
                d3VelocityDecay={0.3}
                cooldownTicks={100}
                onEngineStop={() => fgRef.current?.zoomToFit(400)}
            />
        </div>
    );
};

export default GraphViewer;
