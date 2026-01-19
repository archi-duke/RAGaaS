import React, { useEffect, useState } from 'react';
import { kbApi } from '../services/api';

interface Triple {
    subject: string;
    predicate: string;
    object: string;
    doc_id?: string;
    doc_filename?: string;
    chunk_id?: string;
    chunk_text?: string;  // 청크 원문 (트리플 출처)
    confidence?: number;
}

interface GraphDataTableProps {
    kbId: string;
    backend: string;
}

export default function GraphDataTable({ kbId, backend }: GraphDataTableProps) {
    const [triples, setTriples] = useState<Triple[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [hasChunkMappings, setHasChunkMappings] = useState(true);
    const [selectedChunk, setSelectedChunk] = useState<{ id: string; content: string } | null>(null);

    useEffect(() => {
        loadTriples();
    }, [kbId, backend]);

    const loadTriples = async () => {
        setIsLoading(true);
        try {
            const response = await kbApi.getTriples(kbId, backend);
            setTriples(response.data.triples || []);
            setHasChunkMappings(response.data.has_chunk_mappings ?? true);
        } catch (error) {
            console.error('Failed to load triples:', error);
        } finally {
            setIsLoading(false);
        }
    };

    // 청크 클릭 시 트리플 출처 원문 표시
    const handleChunkClick = async (triple: Triple) => {
        if (!triple.chunk_id) return;

        try {
            const response = await kbApi.getChunk(kbId, triple.chunk_id);
            setSelectedChunk({
                id: triple.chunk_id,
                content: response.data.content
            });
        } catch (error) {
            console.error('Failed to load chunk:', error);
            alert('Failed to load chunk content');
        }
    };

    if (isLoading) {
        return (
            <div style={{ padding: '2rem', textAlign: 'center' }}>
                <p>Loading triples...</p>
            </div>
        );
    }

    if (triples.length === 0) {
        return (
            <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
                <p>No triples found in this knowledge base.</p>
            </div>
        );
    }

    return (
        <div style={{ padding: '20px', height: '100%', overflow: 'auto' }}>
            <div style={{ marginBottom: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ margin: 0 }}>Extracted Triples ({triples.length})</h3>
                <button className="btn" onClick={loadTriples}>
                    Refresh
                </button>
            </div>

            {/* 매핑 없음 경고 */}
            {!hasChunkMappings && (
                <div style={{
                    padding: '0.75rem 1rem',
                    marginBottom: '1rem',
                    backgroundColor: '#fef3c7',
                    border: '1px solid #f59e0b',
                    borderRadius: '6px',
                    color: '#92400e',
                    fontSize: '0.85rem'
                }}>
                    ⚠️ 청크 매핑 정보가 없습니다. 트리플 출처를 확인하려면 문서를 재인덱싱하세요.
                </div>
            )}

            <table className="table" style={{ width: '100%', fontSize: '0.9rem', textAlign: 'center' }}>
                <thead>
                    <tr>
                        <th style={{ textAlign: 'center' }}>Subject</th>
                        <th style={{ textAlign: 'center' }}>Predicate</th>
                        <th style={{ textAlign: 'center' }}>Object</th>
                        <th style={{ textAlign: 'center' }}>Document</th>
                        <th style={{ textAlign: 'center' }}>Chunk</th>
                    </tr>
                </thead>
                <tbody>
                    {triples.map((triple, idx) => (
                        <tr key={idx}>
                            <td>{triple.subject}</td>
                            <td style={{ fontStyle: 'italic', color: '#3b82f6' }}>{triple.predicate}</td>
                            <td>{triple.object}</td>
                            <td style={{ fontSize: '0.85rem', color: '#64748b' }}>
                                {triple.doc_filename || triple.doc_id || '-'}
                            </td>
                            <td>
                                {triple.chunk_id ? (
                                    <button
                                        className="btn"
                                        onClick={() => handleChunkClick(triple)}
                                        style={{
                                            padding: '2px 8px',
                                            fontSize: '0.8rem',
                                            backgroundColor: '#f0f9ff',
                                            color: '#0284c7',
                                            border: '1px solid #bae6fd',
                                            cursor: 'pointer'
                                        }}
                                    >
                                        {triple.chunk_id.substring(0, 8)}...
                                    </button>
                                ) : (
                                    <span style={{ color: '#f59e0b' }}>⚠️ 없음</span>
                                )}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>

            {/* Chunk Preview Modal */}
            {selectedChunk && (
                <div
                    style={{
                        position: 'fixed',
                        top: 0,
                        left: 0,
                        right: 0,
                        bottom: 0,
                        backgroundColor: 'rgba(0,0,0,0.5)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        zIndex: 1000
                    }}
                    onClick={() => setSelectedChunk(null)}
                >
                    <div
                        className="card"
                        style={{ width: '90%', maxWidth: '700px', maxHeight: '80vh', overflow: 'auto' }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                            <h3 style={{ margin: 0 }}>📄 트리플 출처 (Chunk Content)</h3>
                            <button className="btn" onClick={() => setSelectedChunk(null)}>
                                Close
                            </button>
                        </div>
                        <div style={{ fontSize: '0.85rem', color: '#64748b', marginBottom: '0.5rem' }}>
                            Chunk ID: <code>{selectedChunk.id}</code>
                        </div>
                        <div
                            style={{
                                padding: '1rem',
                                backgroundColor: '#f8fafc',
                                borderRadius: '8px',
                                whiteSpace: 'pre-wrap',
                                lineHeight: 1.6,
                                border: '1px solid #e2e8f0'
                            }}
                        >
                            {selectedChunk.content}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
