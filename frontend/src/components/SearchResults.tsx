import React, { useState } from 'react';
import AgenticReasoningCard from './AgenticScratchpad';

interface SearchResultsProps {
    chunks: any[];
    kbId?: string;
    graphBackend?: string;
    logs?: string[];
    pipeline?: any;
}

// Chunk popup modal component
function ChunkPopup({ triple, chunks, onClose }: { triple: any; chunks: any[]; onClose: () => void }) {
    const sourceStart = triple.source_start;
    const sourceEnd = triple.source_end;

    // 1. Priority: Direct match if chunk_id exists
    // 2. Fallback: Text-based match (subject OR object - OR instead of AND)
    let relatedChunks = [];

    // If chunk_id exists in triple (mapping stored by backend)
    if (triple.chunk_ids && triple.chunk_ids.length > 0) {
        relatedChunks = chunks.filter(c => triple.chunk_ids.includes(c.chunk_id));
    }

    // Text-based fallback if no chunk_id match (more permissive)
    if (relatedChunks.length === 0) {
        const subj = (triple.subject || '').toLowerCase();
        const obj = (triple.object || '').toLowerCase();

        relatedChunks = chunks.filter(c => {
            const content = (c.content || '').toLowerCase();
            // OR condition: Matches if either subject or object is included
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

    // 추론 내용(reasoning)이 있는 메타데이터를 우선 — 정렬 후 빈 메타데이터 청크가 앞에 올 수 있다
    const withReasoning = chunks.find((c: any) => c.graph_metadata?.reasoning && Object.keys(c.graph_metadata.reasoning).length);
    if (withReasoning) graphMetadata = withReasoning.graph_metadata;
    for (const chunk of chunks) {
        if (!graphMetadata && chunk.graph_metadata && Object.keys(chunk.graph_metadata).length) {
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
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '100%', flex: 1 }}>
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
                        <span style={{
                            color: (graphMetadata && (graphMetadata.sparql_query === 'Error' || graphMetadata.sparql_query === 'Generation Failed' || !graphMetadata.sparql_query))
                                ? 'tomato'
                                : 'inherit'
                        }}>
                            🔍 Retrieval Details
                        </span>
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
                    <div style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '1rem',
                        padding: '1rem',
                        width: '100%',
                        boxSizing: 'border-box'
                    }}>
                        {sortedChunks.map((chunk, idx) => {
                            const isGraph = chunk.metadata?.source === 'graph' || chunk.metadata?.source === 'graph_fallback';
                            return (
                                <div
                                    key={idx}
                                    className="card"
                                    style={{
                                        width: '100%',
                                        boxSizing: 'border-box',
                                        padding: '1.25rem',
                                        background: isGraph ? '#eff6ff' : '#f8fafc',
                                        borderRadius: '8px',
                                        border: isGraph ? '1px solid #93c5fd' : '1px solid var(--border)',
                                        borderLeft: isGraph ? '4px solid #1e40af' : '4px solid var(--primary)',
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
                                                background: isGraph ? '#dbeafe' : 'transparent',
                                                color: isGraph ? '#1e3a8a' : 'inherit',
                                                padding: isGraph ? '0.2rem 0.6rem' : '0',
                                                borderRadius: isGraph ? '20px' : '0',
                                                border: isGraph ? '1px solid #bfdbfe' : 'none',
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
                                                <span className="badge" style={{ fontSize: '0.65rem', backgroundColor: '#dbeafe', color: '#1e40af' }}>
                                                    Graph
                                                </span>
                                            )}

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
                                        whiteSpace: 'pre-wrap',
                                        wordBreak: 'break-word',
                                        width: '100%',
                                        display: 'block'
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
                                        graphMetadata.extracted_entities.map((entity: string, idx: number) => {
                                            // clickable_entities 가 있으면 그 목록에 있는 엔티티만 그래프 노드로 존재(live).
                                            // 필드가 없으면(구 백엔드) 하위호환으로 전부 clickable 로 취급.
                                            const liveList: string[] | undefined = graphMetadata.clickable_entities;
                                            const isLive = !liveList || liveList.includes(entity);
                                            const clickable = !!kbId && isLive;
                                            return (
                                            <button
                                                key={idx}
                                                className="badge"
                                                disabled={!clickable}
                                                onClick={() => {
                                                    if (clickable) {
                                                        window.open(`${import.meta.env.BASE_URL}graph-viewer?kb_id=${kbId}&entity=${encodeURIComponent(entity)}&backend=${graphBackend || 'neo4j'}`, '_blank');
                                                    }
                                                }}
                                                style={{
                                                    fontSize: '0.8rem',
                                                    background: clickable ? 'white' : '#f1f5f9',
                                                    border: clickable ? '1px solid #bae6fd' : '1px dashed #cbd5e1',
                                                    color: clickable ? '#0369a1' : '#94a3b8',
                                                    cursor: clickable ? 'pointer' : 'not-allowed',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '4px'
                                                }}
                                                title={clickable ? "Visualize Graph" : "이 엔티티는 그래프에 노드가 없어 확장할 수 없습니다"}
                                            >
                                                {clickable && <span>🕸️</span>}
                                                {entity}
                                            </button>
                                            );
                                        })
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

                        {/* Agentic 을 건너뛴 경우 — 스크래치패드가 없는 이유 */}
                        {graphMetadata?.reasoning?.agentic_skipped && (
                            <div style={{ fontSize: '0.8rem', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '6px', padding: '0.45rem 0.7rem' }}>
                                <b>Agentic 건너뜀</b> (mode {graphMetadata.reasoning.agentic_skipped.mode}) — {graphMetadata.reasoning.agentic_skipped.reason}
                            </div>
                        )}
                        {/* Agentic 스크래치패드 — 결과 탭에서도 바로 보이게 (전체 과정은 Logs 탭) */}
                        {graphMetadata?.reasoning?.agentic && (
                            <AgenticReasoningCard agentic={graphMetadata.reasoning.agentic} compact />
                        )}

                        {/* Graph Detail Tabs */}
                        {graphMetadata && (
                            <GraphDetailsTabs graphMetadata={graphMetadata} chunks={sortedChunks} />
                        )}
                    </div>
                )}

                {/* Logs Tab */}
                {activeTab === 'logs' && logs && (
                    <div style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '1rem',
                        padding: '1rem',
                        width: '100%',
                        boxSizing: 'border-box'
                    }}>
                        {/* 그래프 추론 과정 (관계 타게팅 리포트) */}
                        {graphMetadata?.reasoning && (graphMetadata.reasoning.agentic
                            ? <AgenticReasoningCard agentic={graphMetadata.reasoning.agentic} />
                            : <GraphReasoningCard reasoning={graphMetadata.reasoning} />)}

                        {/* Execution Logs */}
                        <div className="card" style={{ padding: '1rem', width: '100%', boxSizing: 'border-box' }}>
                            <div style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>
                                Execution Trace
                            </div>
                            <div style={{
                                background: '#1e293b',
                                color: '#a5b4fc',
                                padding: '1rem',
                                borderRadius: '6px',
                                fontSize: '0.75rem',
                                fontFamily: 'monospace',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '4px',
                                width: '100%',
                                boxSizing: 'border-box',
                                overflowX: 'auto',
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word'
                            }}>
                                {logs.map((log, idx) => (
                                    <div key={idx} style={{
                                        borderBottom: '1px solid #334155',
                                        paddingBottom: '4px',
                                        lineHeight: '1.4'
                                    }}>
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

// 그래프 추론 과정 카드: 질문 분석 → 엔티티 링킹 → 관계 타게팅 → 선택 트리플 → 근거 청크
// (docs/design/graph/design-graph-relation-targeting.md)
const MODE_LABELS: Record<string, string> = {
    A: 'A · 결정적 매칭',
    B: 'B · LLM 경로 선택',
    C: 'C · LLM SPARQL 생성',
    overview: '개요 이웃 조회',
    pair: '두 엔티티 직접 관계',
    none: '일치 관계 없음',
    P: 'P · 질의 계획 (유형 수준)',
};
const ROLE_LABELS: Record<string, string> = { filter: '필터', aggregate: '집계', return: '반환' };
const ROLE_COLORS: Record<string, [string, string]> = {
    filter: ['#dbeafe', '#1e40af'], aggregate: ['#fae8ff', '#86198f'], return: ['#dcfce7', '#166534'],
};
const TIER_LABELS: Record<number, string> = { 1: '완전일치', 2: '어간일치', 3: '토큰포함' };
const shortChunk = (cid: string) => (cid && cid.includes('::') ? cid.split('::').pop() : cid);

function GraphReasoningCard({ reasoning }: { reasoning: any }) {
    const [showSparql, setShowSparql] = React.useState(false);
    const an = reasoning.analysis || {};
    const tg = reasoning.targeting || {};
    const triples: any[] = reasoning.triples || [];
    const chunks: any[] = reasoning.chunks || [];
    const roles = an.entity_roles || {};

    const step = (no: number, title: string, body: React.ReactNode) => (
        <div style={{ display: 'flex', gap: '0.75rem', padding: '0.5rem 0', borderBottom: '1px solid var(--border, #e2e8f0)' }}>
            <div style={{
                flex: '0 0 1.6rem', height: '1.6rem', borderRadius: '50%', background: '#6366f1', color: 'white',
                fontSize: '0.75rem', fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center'
            }}>{no}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.25rem' }}>{title}</div>
                <div style={{ fontSize: '0.8rem', lineHeight: 1.5, wordBreak: 'break-word' }}>{body}</div>
            </div>
        </div>
    );
    const chip = (text: string, color = '#e0e7ff', fg = '#3730a3') => (
        <span style={{ display: 'inline-block', background: color, color: fg, borderRadius: '4px', padding: '0 6px', margin: '0 4px 4px 0', fontSize: '0.75rem' }}>{text}</span>
    );

    return (
        <div className="card" style={{ padding: '1rem', width: '100%', boxSizing: 'border-box' }}>
            <div style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Graph Reasoning</div>
            {step(1, '질문 분석', <>
                <div>intent: <b>{an.intent || '-'}</b>{an.target_class ? <> · 대상 유형 <b>{an.target_class}</b></> : null}{an.model ? <span style={{ opacity: 0.7 }}> · 모델 {an.model}</span> : null}</div>
                <div>엔티티: {(an.entities || []).map((e: string) => chip(roles[e] ? `${e} (${roles[e]})` : e))}</div>
                <div>관계어: {(an.relation_aliases || []).length ? an.relation_aliases.map((a: string) => chip(a, '#fef3c7', '#92400e')) : '(없음)'}</div>
                {an.llm_issue && <div style={{ color: 'tomato' }}>⚠ 질의 분석 LLM 호출 불가 — spaCy 토큰으로 대체: {an.llm_issue}</div>}
            </>)}
            {step(2, '엔티티 링킹', <>
                {(reasoning.linking || []).length
                    ? (reasoning.linking || []).map((l: any) => <div key={l.uri}>'{l.entity}' → <code>inst:{decodeURIComponent(String(l.uri).split('/').pop() || '')}</code>{l.value_node && <span style={{ opacity: 0.7 }}> (값 노드 — 조건 값으로 사용)</span>}</div>)
                    : <div>그래프 노드에 연결된 엔티티 없음</div>}
                {(tg.kinds || []).map((k: any) => (
                    <div key={k.name} style={{ opacity: 0.8 }}>유형 {k.name} ({k.typed ? 'rdf:type' : '경로 시그니처 추론'}, 멤버 {k.members}개: {(k.examples || []).join(', ')})</div>
                ))}
            </>)}
            {step(3, `관계 타게팅 — ${MODE_LABELS[tg.mode] || tg.mode || '-'}`, <>
                {(tg.matches || []).map((m: any, i: number) => (
                    <div key={i}>'{m.alias}' = <code>{m.matched}</code>{m.expanded ? ' (하위 경로 전체)' : ''} · {TIER_LABELS[m.tier] || ''}{m.inverse ? ' · 역관계' : ''}</div>
                ))}
                {tg.catalog_size != null && <div style={{ opacity: 0.8 }}>후보 경로 {tg.catalog_size}개 중 {(tg.selected_paths || []).length}개 선택</div>}
                {(tg.selected_paths || []).length > 0 && <div>{tg.selected_paths.map((sp: string) => chip(sp, '#dcfce7', '#166534'))}</div>}
                {tg.plan && (
                    <div style={{ margin: '0.25rem 0' }}>
                        {(tg.plan.filters || []).map((f: string) => chip(`필터 ${f}`, ...ROLE_COLORS.filter))}
                        {tg.plan.aggregate && chip(`집계 ${tg.plan.aggregate}`, ...ROLE_COLORS.aggregate)}
                        {(tg.plan.returns || []).map((r: string) => chip(`반환 ${r}`, ...ROLE_COLORS.return))}
                        {(tg.plan.value_matches || []).length > 0 && <div style={{ opacity: 0.7 }}>값 매칭: {tg.plan.value_matches.join('; ')}</div>}
                    </div>
                )}
                {(tg.equivalences || []).map((e: string, i: number) => <div key={`eq${i}`}>{chip('≡ 동치', '#ede9fe', '#5b21b6')}{e}</div>)}
                {(tg.adjustments || []).map((a: string, i: number) => <div key={i} style={{ opacity: 0.7 }}>조정: {a}</div>)}
                {(tg.warnings || []).map((w: string, i: number) => <div key={`w${i}`} style={{ color: '#b45309' }}>⚠ {w}</div>)}
                {tg.mode === 'P' && tg.result_entities && <div>결과 엔티티 {tg.result_entities.length}개{tg.truncated ? ' (상한 초과)' : ''}: <b>{tg.result_entities.join(', ')}</b></div>}
                {tg.reason && <div style={{ opacity: 0.8 }}>근거: {tg.reason}</div>}
                {reasoning.sparql && (
                    <div>
                        <button onClick={() => setShowSparql(!showSparql)} style={{ fontSize: '0.75rem', background: 'none', border: 'none', color: '#6366f1', cursor: 'pointer', padding: 0 }}>
                            {showSparql ? '▾ 실행한 SPARQL 숨기기' : '▸ 실행한 SPARQL 보기'}
                        </button>
                        {showSparql && <pre style={{ background: '#1e293b', color: '#e2e8f0', padding: '0.5rem', borderRadius: '4px', fontSize: '0.7rem', overflowX: 'auto' }}>{reasoning.sparql}</pre>}
                    </div>
                )}
            </>)}
            {step(4, `선택 트리플 ${triples.length}건`, triples.length ? (
                <ol style={{ margin: 0, paddingLeft: '1.2rem' }}>
                    {triples.slice(0, 30).map((t: any, i: number) => (
                        <li key={i}>
                            {t.entity && (i === 0 || triples[i - 1].entity !== t.entity) && <div style={{ fontWeight: 600, marginTop: '0.25rem' }}>▸ {t.entity}</div>}
                            {t.role && chip(ROLE_LABELS[t.role] || t.role, ...(ROLE_COLORS[t.role] || ['#e0e7ff', '#3730a3']))}
                            {t.subject} <b>—{t.predicate}→</b> {String(t.object)}
                            {(t.chunk_ids || []).length > 0 && <span style={{ opacity: 0.6 }}> ⟵ {(t.chunk_ids || []).map(shortChunk).join(', ')}</span>}
                        </li>
                    ))}
                    {triples.length > 30 && <li style={{ listStyle: 'none', opacity: 0.6 }}>… 외 {triples.length - 30}건</li>}
                </ol>
            ) : '선택된 트리플 없음 (Strict Mode: 빈 결과)')}
            {step(5, `근거 청크 ${chunks.length}건 (${reasoning.chunk_order_label || '트리플 연결 순'})`, chunks.length ? (
                chunks.map((c: any, i: number) => (
                    <div key={i}>
                        #{i + 1} <code>{shortChunk(c.chunk_id)}</code>
                        {(c.triple_idx || []).length > 0 && <span> ⟵ 트리플 {(c.triple_idx || []).join(', ')}</span>}
                        {c.kind === 'edge' && <span style={{ opacity: 0.6 }}> (구조 간선)</span>}
                        {c.missing && <span style={{ color: 'tomato' }}> — 벡터 저장소에 본문 없음</span>}
                    </div>
                ))
            ) : '근거 청크 없음')}
        </div>
    );
}

// Sub-component for Graph Tabs to keep code clean
function GraphDetailsTabs({ graphMetadata, chunks }: { graphMetadata: any, chunks: any[] }) {
    const [subTab, setSubTab] = React.useState<'triples' | 'query'>('triples');
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
                    <span style={{
                        color: (graphMetadata.sparql_query === 'Error' || graphMetadata.sparql_query === 'Generation Failed' || !graphMetadata.sparql_query)
                            ? 'tomato'
                            : (subTab === 'query' ? '#0369a1' : '#64748b')
                    }}>
                        {graphMetadata.graph_backend === 'neo4j' ? 'Cypher Query' : 'SPARQL Query'}
                    </span>
                </div>
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
                                    color: (graphMetadata.sparql_query === 'Error' || graphMetadata.sparql_query === 'Generation Failed') ? 'tomato' : '#e2e8f0',
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
