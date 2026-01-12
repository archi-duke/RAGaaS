import React, { useState } from 'react';

interface SearchResultsProps {
    chunks: any[];
    kbId?: string;
    graphBackend?: string;
}

export default function SearchResults({ chunks, kbId, graphBackend }: SearchResultsProps) {
    const [activeTab, setActiveTab] = useState<'graph' | 'chunks'>('chunks');

    // Reset tab to chunks when new results arrive
    React.useEffect(() => {
        setActiveTab('chunks');
    }, [chunks]);

    if (!chunks || chunks.length === 0) {
        return (
            <div style={{
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--text-secondary)',
                border: '1px dashed var(--border)',
                borderRadius: '8px',
                padding: '2rem',
                textAlign: 'center'
            }}>
                <p>Retrieved chunks and graph details will appear here after your search.</p>
            </div>
        );
    }

    // Search ALL chunks for metadata (not just the first one)
    // This is needed because chunks may be filtered/reordered after API response
    let graphMetadata = null;
    let extractedKeywords = null;

    for (const chunk of chunks) {
        if (!graphMetadata && chunk.graph_metadata) {
            graphMetadata = chunk.graph_metadata;
        }
        if (!extractedKeywords && chunk.metadata?.extracted_keywords && chunk.metadata.extracted_keywords.length > 0) {
            extractedKeywords = chunk.metadata.extracted_keywords;
        }
        // Stop early if both are found
        if (graphMetadata && extractedKeywords) break;
    }

    // Debug: Log the data to verify it's being received correctly
    console.log('[SearchResults] chunks count:', chunks.length);
    console.log('[SearchResults] graphMetadata:', graphMetadata);
    console.log('[SearchResults] extractedKeywords:', extractedKeywords);
    console.log('[SearchResults] Show Retrieval Tab:', graphMetadata || (extractedKeywords && extractedKeywords.length > 0));

    // Tab styles
    const tabStyle = (isActive: boolean) => ({
        padding: '0.75rem 1.5rem',
        cursor: 'pointer',
        borderBottom: isActive ? '3px solid var(--primary)' : '3px solid transparent',
        fontWeight: isActive ? 600 : 400,
        color: isActive ? 'var(--primary)' : 'var(--text-secondary)',
        transition: 'all 0.2s',
        background: isActive ? 'var(--bg-secondary)' : 'transparent'
    });

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Tab Headers */}
            <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: '1rem' }}>
                <div
                    style={tabStyle(activeTab === 'chunks')}
                    onClick={() => setActiveTab('chunks')}
                >
                    📄 Retrieved Chunks ({chunks.length})
                </div>
                {(graphMetadata || (extractedKeywords && extractedKeywords.length > 0)) && (
                    <div
                        style={tabStyle(activeTab === 'graph')}
                        onClick={() => setActiveTab('graph')}
                    >
                        🔍 Retrieval Details
                    </div>
                )}
            </div>

            {/* Tab Content */}
            <div style={{ flex: 1, overflowY: 'auto' }}>
                {/* Chunks Tab */}
                {activeTab === 'chunks' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                        {chunks.map((chunk, idx) => {
                            const isGraph = chunk.metadata?.source === 'graph' || chunk.metadata?.source === 'graph_fallback';
                            return (
                                <div
                                    key={idx}
                                    className="card"
                                    style={{
                                        padding: '1rem',
                                        background: isGraph ? '#f0fdf4' : '#f8fafc',
                                        borderRadius: '8px',
                                        border: isGraph ? '1px solid #86efac' : '1px solid var(--border)',
                                        borderLeft: isGraph ? '4px solid #166534' : '4px solid var(--primary)',
                                        position: 'relative'
                                    }}
                                >
                                    <div style={{
                                        display: 'flex',
                                        justifyContent: 'space-between',
                                        marginBottom: '0.5rem',
                                        fontSize: '0.75rem',
                                        color: 'var(--text-secondary)'
                                    }}>
                                        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                            <span style={{
                                                fontWeight: 600,
                                                background: isGraph ? '#dcfce7' : 'transparent',
                                                color: isGraph ? '#14532d' : 'inherit',
                                                padding: isGraph ? '0.2rem 0.6rem' : '0',
                                                borderRadius: isGraph ? '20px' : '0',
                                                border: isGraph ? '1px solid #bbf7d0' : 'none',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '4px'
                                            }}>
                                                {isGraph && <span>🕸️</span>}
                                                Chunk {idx + 1}
                                            </span>
                                            {chunk.chunk_id && (
                                                <span className="badge" style={{ fontSize: '0.65rem', backgroundColor: '#f1f5f9', color: '#475569' }}>
                                                    ID: {chunk.chunk_id}
                                                </span>
                                            )}
                                        </div>
                                        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                            {isGraph && (
                                                <span className="badge" style={{ fontSize: '0.65rem', backgroundColor: '#dcfce7', color: '#166534' }}>
                                                    Graph
                                                </span>
                                            )}
                                            <span className="badge badge-secondary" style={{ fontSize: '0.7rem' }}>
                                                Score: {chunk.score?.toFixed(4)}
                                                {chunk.l2_score != null && ` (L2: ${chunk.l2_score.toFixed(4)})`}
                                            </span>
                                        </div>
                                    </div>
                                    <div style={{
                                        fontSize: '0.9rem',
                                        lineHeight: '1.6',
                                        color: 'var(--text-primary)',
                                        whiteSpace: 'pre-wrap'
                                    }}>
                                        {chunk.content ? chunk.content.replace(/\n\s*\n/g, '\n').trim() : ''}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}

                {/* Retrieval Details Tab (Graph + Keyword) */}
                {activeTab === 'graph' && (graphMetadata || (extractedKeywords && extractedKeywords.length > 0)) && (
                    <div className="card" style={{
                        background: '#f0f9ff',
                        borderLeft: '4px solid var(--primary)',
                        padding: '1rem'
                    }}>
                        {graphMetadata ? (
                            <div style={{ marginBottom: '1.5rem' }}>
                                <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-primary)' }}>
                                    🔑 Extracted Entities (Graph):
                                </div>
                                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    {graphMetadata.extracted_entities && graphMetadata.extracted_entities.length > 0 ? (
                                        graphMetadata.extracted_entities.map((entity: string, idx: number) => (
                                            <button
                                                key={idx}
                                                className="badge"
                                                onClick={() => {
                                                    if (kbId) {
                                                        window.open(`/graph-viewer?kb_id=${kbId}&entity=${encodeURIComponent(entity)}&backend=${graphBackend || 'neo4j'}`, '_blank');
                                                    }
                                                }}
                                                style={{
                                                    fontSize: '0.8rem',
                                                    background: 'white',
                                                    border: '1px solid #bae6fd',
                                                    color: '#0369a1',
                                                    cursor: kbId ? 'pointer' : 'default',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '4px'
                                                }}
                                                title={kbId ? "Visualize Graph" : undefined}
                                            >
                                                {kbId && <span>🕸️</span>}
                                                {entity}
                                            </button>
                                        ))
                                    ) : (
                                        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>None detected</span>
                                    )}
                                </div>
                            </div>
                        ) : (
                            extractedKeywords && extractedKeywords.length > 0 && (
                                <div style={{ marginBottom: '1.5rem' }}>
                                    <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-primary)' }}>
                                        🔑 Extracted Keywords (Hybrid/BM25):
                                    </div>
                                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                        {extractedKeywords.map((kw: string, idx: number) => (
                                            <span key={idx} className="badge" style={{ fontSize: '0.8rem', background: '#fffbeb', border: '1px solid #fcd34d', color: '#b45309' }}>
                                                {kw}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )
                        )}

                        {/* Graph Detail Tabs */}
                        {graphMetadata && (
                            <GraphDetailsTabs graphMetadata={graphMetadata} chunks={chunks} />
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}

// Sub-component for Graph Tabs to keep code clean
function GraphDetailsTabs({ graphMetadata, chunks }: { graphMetadata: any, chunks: any[] }) {
    const [subTab, setSubTab] = React.useState<'triples' | 'query' | 'log'>('triples');

    const subTabStyle = (isActive: boolean) => ({
        padding: '0.5rem 1rem',
        cursor: 'pointer',
        fontSize: '0.8rem',
        fontWeight: isActive ? 600 : 400,
        color: isActive ? '#0369a1' : '#64748b',
        borderBottom: isActive ? '2px solid #0369a1' : '2px solid transparent',
        background: isActive ? '#e0f2fe' : 'transparent',
        borderRadius: '4px 4px 0 0',
        transition: 'all 0.1s'
    });

    return (
        <div>
            <div style={{ display: 'flex', borderBottom: '1px solid #bfdbfe', marginBottom: '1rem', gap: '0.5rem' }}>
                <div style={subTabStyle(subTab === 'triples')} onClick={() => setSubTab('triples')}>
                    Knowledge Graph Triples
                </div>
                <div style={subTabStyle(subTab === 'query')} onClick={() => setSubTab('query')}>
                    {graphMetadata.graph_backend === 'neo4j' ? 'Cypher Query' : 'SPARQL Query'}
                </div>
                {graphMetadata.trace_logs && graphMetadata.trace_logs.length > 0 && (
                    <div style={subTabStyle(subTab === 'log')} onClick={() => setSubTab('log')}>
                        Log & Analysis
                    </div>
                )}
            </div>

            <div style={{ minHeight: '200px' }}>
                {/* 1. Triples Tab */}
                {subTab === 'triples' && (
                    <div>
                        {graphMetadata.triples && graphMetadata.triples.length > 0 ? (
                            <>
                                <div style={{ fontSize: '0.75rem', color: '#64748b', marginBottom: '0.5rem' }}>
                                    Found {graphMetadata.triples.length} triples related to your query.
                                </div>
                                <div style={{
                                    maxHeight: '300px',
                                    overflowY: 'auto',
                                    background: 'white',
                                    padding: '0.75rem',
                                    borderRadius: '6px',
                                    fontSize: '0.8rem',
                                    border: '1px solid #e0f2fe'
                                }}>
                                    {graphMetadata.triples.map((triple: any, idx: number) => {
                                        // Reuse logic for Triple rendering
                                        let s = 'Unknown', p = 'Unknown', o = 'Unknown';

                                        if (typeof triple === 'string') {
                                            const match = triple.match(/\((.*?)\)\s-\[(.*?)\]->\s\((.*?)\)/);
                                            if (match) { s = match[1]; p = match[2]; o = match[3]; }
                                            else { s = triple; p = ''; o = ''; }
                                        } else {
                                            s = triple.subject; p = triple.predicate; o = triple.object;
                                        }

                                        const formatValue = (val: string) => {
                                            try {
                                                if (!val) return '';
                                                let text = val;
                                                if (text.startsWith('http')) {
                                                    const parts = text.split('/');
                                                    text = parts[parts.length - 1];
                                                }
                                                return decodeURIComponent(text).replace(/_/g, ' ');
                                            } catch (e) {
                                                return val;
                                            }
                                        };

                                        return (
                                            <div key={idx} style={{
                                                padding: '0.5rem',
                                                marginBottom: '0.5rem',
                                                background: '#f8fafc',
                                                borderRadius: '4px',
                                                fontFamily: 'monospace',
                                                display: 'flex',
                                                alignItems: 'center',
                                                flexWrap: 'wrap',
                                                gap: '0.25rem'
                                            }}>
                                                <span style={{ color: '#0284c7', fontWeight: 600 }}>{formatValue(s)}</span>
                                                {p && (
                                                    <>
                                                        <span style={{ color: '#94a3b8' }}>→</span>
                                                        <span style={{ color: '#7c3aed' }}>{formatValue(p)}</span>
                                                        <span style={{ color: '#94a3b8' }}>→</span>
                                                        <span style={{ color: '#0284c7', fontWeight: 600 }}>{formatValue(o)}</span>
                                                    </>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </>
                        ) : (
                            <div style={{ color: '#94a3b8', fontStyle: 'italic', padding: '1rem', textAlign: 'center' }}>
                                No triples found from graph search.
                            </div>
                        )}
                    </div>
                )}

                {/* 2. Query Tab */}
                {subTab === 'query' && (
                    <div>
                        {graphMetadata.sparql_query ? (
                            <div style={{ padding: '0', background: '#1e293b', borderRadius: '8px', border: '1px solid #cbd5e1', overflow: 'hidden' }}>
                                <pre style={{
                                    color: '#e2e8f0',
                                    padding: '1rem',
                                    margin: 0,
                                    overflow: 'auto',
                                    fontSize: '0.75rem',
                                    lineHeight: 1.5,
                                    whiteSpace: 'pre-wrap',
                                    wordBreak: 'break-word',
                                    maxHeight: '400px'
                                }}>
                                    {graphMetadata.sparql_query}
                                </pre>
                            </div>
                        ) : (
                            <div style={{ color: '#94a3b8', fontStyle: 'italic', padding: '1rem', textAlign: 'center' }}>
                                No query generated.
                            </div>
                        )}
                    </div>
                )}

                {/* 3. Log Tab */}
                {subTab === 'log' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                        {/* Query Understanding Log */}
                        {graphMetadata.rewritten_query && (
                            <div style={{ padding: '0.75rem', background: '#fffbeb', borderRadius: '6px', border: '1px solid #fcd34d' }}>
                                <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem', color: '#92400e' }}>
                                    Query Understanding
                                </div>
                                <div style={{ fontSize: '0.75rem', color: '#78350f', display: 'grid', gap: '0.5rem' }}>
                                    <div><strong>Rewritten:</strong> {graphMetadata.rewritten_query.rewritten_query_text || 'N/A'}</div>
                                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                                        {graphMetadata.rewritten_query.query_type && <span className="badge badge-secondary">Type: {graphMetadata.rewritten_query.query_type}</span>}
                                        {graphMetadata.rewritten_query.hops && <span className="badge badge-secondary">Hops: {graphMetadata.rewritten_query.hops}</span>}
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Search Stats Log */}
                        {graphMetadata.total_chunks_found !== undefined && (
                            <div style={{ padding: '0.75rem', background: '#f0fdf4', borderRadius: '6px', border: '1px solid #bbf7d0' }}>
                                <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem', color: '#166534' }}>
                                    Search Execution Stats
                                </div>
                                <ul style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '0.75rem', color: '#15803d' }}>
                                    <li>Total Chunks Found in Graph: <strong>{graphMetadata.total_chunks_found}</strong></li>
                                    <li>Graph Backend: <strong>{graphMetadata.graph_backend || 'ontology'}</strong></li>
                                </ul>


                            </div>
                        )}

                        {/* Process Trace Logs */}
                        {graphMetadata.trace_logs && graphMetadata.trace_logs.length > 0 && (
                            <div style={{ marginTop: '1rem', padding: '0.75rem', background: '#f8fafc', borderRadius: '6px', border: '1px solid #e2e8f0' }}>
                                <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem', color: '#475569' }}>
                                    🛠️ Process Trace Logs
                                </div>
                                <div style={{
                                    fontFamily: 'monospace',
                                    fontSize: '0.7rem',
                                    color: '#334155',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '0.2rem',
                                    maxHeight: '200px',
                                    overflowY: 'auto'
                                }}>
                                    {graphMetadata.trace_logs.map((log: string, idx: number) => (
                                        <div key={idx} style={{ borderBottom: '1px solid #f1f5f9', paddingBottom: '2px' }}>
                                            {log}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* 3. Raw JSON Logs (Full Debug Dump) */}
                        <div style={{ marginTop: '1rem' }}>
                            <div style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                marginBottom: '0.5rem'
                            }}>
                                <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#334155' }}>
                                    📋 Raw JSON Logs (for Debugging)
                                </div>
                                <button
                                    onClick={() => navigator.clipboard.writeText(JSON.stringify(graphMetadata, null, 2))}
                                    style={{
                                        fontSize: '0.7rem',
                                        padding: '0.2rem 0.6rem',
                                        background: 'white',
                                        border: '1px solid #cbd5e1',
                                        borderRadius: '4px',
                                        cursor: 'pointer',
                                        color: '#475569'
                                    }}
                                >
                                    Copy JSON
                                </button>
                            </div>
                            <pre style={{
                                background: '#1e293b',
                                color: '#a5b4fc',
                                padding: '1rem',
                                borderRadius: '6px',
                                overflow: 'auto',
                                fontSize: '0.7rem',
                                lineHeight: '1.4',
                                margin: 0,
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word',
                                maxHeight: '300px',
                                fontFamily: 'Menlo, Monaco, Consolas, "Courier New", monospace'
                            }}>
                                {JSON.stringify(graphMetadata, null, 2)}
                            </pre>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
