import React, { useState } from 'react';

interface SearchResultsProps {
    chunks: any[];
    kbId?: string;
    graphBackend?: string;
    logs?: string[];
    pipeline?: any;
}

// 청크 팝업 모달 컴포넌트
function ChunkPopup({ triple, chunks, onClose }: { triple: any; chunks: any[]; onClose: () => void }) {
    const sourceStart = triple.source_start;
    const sourceEnd = triple.source_end;

    // 1. 우선: chunk_id가 있으면 직접 매칭
    // 2. 폴백: 텍스트 기반 매칭 (subject OR object 포함 - AND 대신 OR 사용)
    let relatedChunks = [];

    // chunk_id가 트리플에 있는 경우 (백엔드에서 저장한 매핑)
    if (triple.chunk_ids && triple.chunk_ids.length > 0) {
        relatedChunks = chunks.filter(c => triple.chunk_ids.includes(c.chunk_id));
    }

    // chunk_id 매칭이 없으면 텍스트 기반 폴백 (더 관대한 매칭)
    if (relatedChunks.length === 0) {
        const subj = (triple.subject || '').toLowerCase();
        const obj = (triple.object || '').toLowerCase();

        relatedChunks = chunks.filter(c => {
            const content = (c.content || '').toLowerCase();
            // OR 조건: subject 또는 object 중 하나라도 포함되면 매칭
            return content.includes(subj) || content.includes(obj);
        });
    }

    relatedChunks = relatedChunks.slice(0, 3);

    return (
        <div style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000
        }} onClick={onClose}>
            <div style={{
                background: 'white',
                borderRadius: '12px',
                maxWidth: '600px',
                maxHeight: '80vh',
                overflow: 'auto',
                padding: '1.5rem',
                boxShadow: '0 10px 40px rgba(0,0,0,0.2)'
            }} onClick={e => e.stopPropagation()}>
                <div style={{ marginBottom: '1rem' }}>
                    <div style={{ fontSize: '0.8rem', color: '#64748b' }}>Source for Triple:</div>
                    <div style={{ fontSize: '1rem', fontWeight: 600, color: '#0369a1' }}>
                        {triple.subject} → {triple.predicate} → {triple.object}
                    </div>
                    {sourceStart != null && sourceEnd != null && (
                        <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '4px' }}>
                            📍 Character offset: {sourceStart} ~ {sourceEnd}
                        </div>
                    )}
                </div>

                {relatedChunks.length > 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                        {relatedChunks.map((chunk, idx) => (
                            <div key={idx} style={{
                                padding: '0.75rem',
                                background: '#f8fafc',
                                borderRadius: '8px',
                                border: '1px solid #e2e8f0',
                                fontSize: '0.85rem',
                                lineHeight: 1.6
                            }}>
                                <div style={{ fontSize: '0.7rem', color: '#64748b', marginBottom: '0.5rem' }}>
                                    Chunk {idx + 1}
                                </div>
                                {chunk.content?.substring(0, 300)}...
                            </div>
                        ))}
                    </div>
                ) : (
                    <div style={{ color: '#94a3b8', fontStyle: 'italic', textAlign: 'center', padding: '2rem' }}>
                        No matching chunks found in current results.
                    </div>
                )}

                <button onClick={onClose} style={{
                    marginTop: '1rem',
                    padding: '0.5rem 1rem',
                    background: '#0369a1',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    width: '100%'
                }}>Close</button>
            </div>
        </div>
    );
}

export default function SearchResults({ chunks, kbId, graphBackend, logs, pipeline }: SearchResultsProps) {
    const [activeTab, setActiveTab] = useState<'graph' | 'chunks' | 'logs'>('chunks');

    // Sort chunks by score (descending)
    const sortedChunks = React.useMemo(() => {
        if (!chunks) return [];
        return [...chunks].sort((a, b) => (b.score || 0) - (a.score || 0));
    }, [chunks]);

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
    let extractedKeywords: string[] | null = null;
    let tokenizerName: string | null = null;

    for (const chunk of chunks) {
        if (!graphMetadata && chunk.graph_metadata) {
            graphMetadata = chunk.graph_metadata;
        }
        if (!extractedKeywords && chunk.metadata?.extracted_keywords && chunk.metadata.extracted_keywords.length > 0) {
            extractedKeywords = chunk.metadata.extracted_keywords;
        }
        if (!tokenizerName && chunk.metadata?.tokenizer) {
            tokenizerName = chunk.metadata.tokenizer;
        }
        // Stop early if all are found
        if (graphMetadata && extractedKeywords && tokenizerName) break;
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
                    📄 Retrieved Chunks ({sortedChunks.length})
                </div>
                {(graphMetadata || (extractedKeywords && extractedKeywords.length > 0)) && (
                    <div
                        style={tabStyle(activeTab === 'graph')}
                        onClick={() => setActiveTab('graph')}
                    >
                        🔍 Retrieval Details
                    </div>
                )}
                {(logs && logs.length > 0) && (
                    <div
                        style={tabStyle(activeTab === 'logs')}
                        onClick={() => setActiveTab('logs')}
                    >
                        📝 Execution Log
                    </div>
                )}
            </div>

            {/* Tab Content */}
            <div style={{ flex: 1, overflowY: 'auto' }}>
                {/* Chunks Tab */}
                {activeTab === 'chunks' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                        {sortedChunks.map((chunk, idx) => {
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
                                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '2px' }}>
                                                <span className="badge badge-secondary" style={{ fontSize: '0.7rem' }}>
                                                    Final Score: {chunk.score?.toFixed(4)}
                                                    {chunk.l2_score != null && ` (L2: ${chunk.l2_score.toFixed(4)})`}
                                                </span>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Score History Display */}
                                    {chunk.metadata?.score_history && Object.keys(chunk.metadata.score_history).length > 0 && (
                                        <div style={{
                                            marginBottom: '0.5rem',
                                            padding: '0.4rem',
                                            background: '#f1f5f9',
                                            border: '1px dashed #cbd5e1',
                                            borderRadius: '4px',
                                            fontSize: '0.7rem',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.5rem',
                                            flexWrap: 'wrap'
                                        }}>
                                            <span style={{ fontWeight: 600, color: '#64748b' }}>Pipeline Scores:</span>
                                            {Object.entries(chunk.metadata.score_history).map(([stage, score], hIdx) => (
                                                <div key={stage} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                                    {hIdx > 0 && <span style={{ color: '#94a3b8' }}>→</span>}
                                                    <span style={{
                                                        background: '#e2e8f0',
                                                        padding: '1px 6px',
                                                        borderRadius: '4px',
                                                        color: '#334155',
                                                        border: '1px solid #cbd5e1'
                                                    }}>
                                                        {stage}: <b>{typeof score === 'number' ? score.toFixed(4) : String(score)}</b>
                                                    </span>
                                                </div>
                                            ))}
                                        </div>
                                    )}
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
                                    <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <span>🔑 Extracted Keywords (Hybrid/BM25):</span>
                                        {tokenizerName && (
                                            <span style={{ fontSize: '0.65rem', fontWeight: 400, color: '#64748b', background: '#f1f5f9', padding: '1px 6px', borderRadius: '4px', border: '1px solid #e2e8f0' }}>
                                                Tokenizer: {tokenizerName}
                                            </span>
                                        )}
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
                            <GraphDetailsTabs graphMetadata={graphMetadata} chunks={sortedChunks} />
                        )}
                    </div>
                )}

                {/* Logs Tab */}
                {activeTab === 'logs' && logs && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', padding: '1rem' }}>
                        {/* Pipeline Config */}
                        {pipeline && (
                            <div className="card" style={{ padding: '1rem' }}>
                                <div style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>
                                    Pipeline Configuration
                                </div>
                                <pre style={{
                                    background: '#1e293b',
                                    color: '#e2e8f0',
                                    padding: '1rem',
                                    borderRadius: '6px',
                                    overflow: 'auto',
                                    fontSize: '0.75rem',
                                    maxHeight: '200px'
                                }}>
                                    {JSON.stringify(pipeline, null, 2)}
                                </pre>
                            </div>
                        )}

                        {/* Execution Logs */}
                        <div className="card" style={{ padding: '1rem' }}>
                            <div style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>
                                Execution Trace
                            </div>
                            <div style={{
                                background: '#1e293b',
                                color: '#a5b4fc',
                                padding: '1rem',
                                borderRadius: '6px',
                                overflow: 'auto',
                                fontSize: '0.75rem',
                                fontFamily: 'monospace',
                                maxHeight: '400px',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '4px'
                            }}>
                                {logs.map((log, idx) => (
                                    <div key={idx} style={{ borderBottom: '1px solid #334155', paddingBottom: '2px' }}>
                                        {log}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

// Sub-component for Graph Tabs to keep code clean
function GraphDetailsTabs({ graphMetadata, chunks }: { graphMetadata: any, chunks: any[] }) {
    const [subTab, setSubTab] = React.useState<'triples' | 'query' | 'log'>('triples');
    const [selectedTriple, setSelectedTriple] = React.useState<any>(null);

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

                                        const hasOffset = triple.source_start != null && triple.source_end != null;

                                        return (
                                            <div key={idx} style={{
                                                padding: '0.5rem',
                                                marginBottom: '0.5rem',
                                                background: '#f8fafc',
                                                borderRadius: '4px',
                                                fontFamily: 'monospace',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'space-between',
                                                flexWrap: 'wrap',
                                                gap: '0.25rem'
                                            }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
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
                                                {hasOffset && (
                                                    <button
                                                        onClick={() => setSelectedTriple(triple)}
                                                        style={{
                                                            fontSize: '0.65rem',
                                                            padding: '0.2rem 0.5rem',
                                                            background: triple.is_inverse ? '#fff1f2' : '#e0f2fe',
                                                            border: `1px solid ${triple.is_inverse ? '#fda4af' : '#7dd3fc'}`,
                                                            borderRadius: '4px',
                                                            cursor: 'pointer',
                                                            color: triple.is_inverse ? '#e11d48' : '#0369a1',
                                                            whiteSpace: 'nowrap',
                                                            display: 'flex',
                                                            alignItems: 'center',
                                                            gap: '4px'
                                                        }}
                                                        title={`Source: ${triple.source_start}~${triple.source_end}${triple.is_inverse ? ' (Inverse Relation)' : ''}`}
                                                    >
                                                        <span>📄</span>
                                                        {triple.source_start}~{triple.source_end}
                                                    </button>
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

            {/* Chunk Popup Modal */}
            {selectedTriple && (
                <ChunkPopup
                    triple={selectedTriple}
                    chunks={chunks}
                    onClose={() => setSelectedTriple(null)}
                />
            )}
        </div>
    );
}
