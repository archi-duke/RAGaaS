import React from 'react';
import { X, Check, AlertCircle } from 'lucide-react';

interface Triple {
    subject: string;
    predicate: string;
    object: string;
    source_node_id?: string;
}

interface ExtractionPreviewModalProps {
    isOpen: boolean;
    onClose: () => void;
    previewId: string;
    triples: Triple[];
    nodeCount: number;
    isLoading?: boolean;
    onConfirm: () => void;
    onDiscard: () => void;
}

export default function ExtractionPreviewModal({
    isOpen,
    onClose,
    previewId,
    triples,
    nodeCount,
    isLoading = false,
    onConfirm,
    onDiscard
}: ExtractionPreviewModalProps) {
    if (!isOpen) return null;

    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 60
        }}>
            <div
                className="card"
                style={{
                    width: '100%',
                    maxWidth: '800px',
                    maxHeight: '85vh',
                    overflow: 'hidden',
                    display: 'flex',
                    flexDirection: 'column'
                }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: '1rem',
                    borderBottom: '1px solid var(--border)',
                    paddingBottom: '1rem'
                }}>
                    <div>
                        <h2 style={{ margin: 0, fontSize: '1.25rem' }}>추출 미리보기</h2>
                        <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                            {nodeCount}개 노드에서 {triples.length}개 트리플 추출됨
                        </p>
                    </div>
                    <button className="btn" onClick={onClose} style={{ padding: '0.5rem' }}>
                        <X size={20} />
                    </button>
                </div>

                {/* Triples Table */}
                <div style={{
                    flex: 1,
                    overflow: 'auto',
                    marginBottom: '1rem',
                    border: '1px solid var(--border)',
                    borderRadius: '8px'
                }}>
                    {triples.length === 0 ? (
                        <div style={{
                            padding: '2rem',
                            textAlign: 'center',
                            color: 'var(--text-secondary)'
                        }}>
                            <AlertCircle size={32} style={{ marginBottom: '0.5rem', opacity: 0.5 }} />
                            <p>추출된 트리플이 없습니다.</p>
                        </div>
                    ) : (
                        <table style={{
                            width: '100%',
                            borderCollapse: 'collapse',
                            fontSize: '0.9rem'
                        }}>
                            <thead>
                                <tr style={{
                                    backgroundColor: '#eff6ff',
                                    position: 'sticky',
                                    top: 0
                                }}>
                                    <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>#</th>
                                    <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>주어 (Subject)</th>
                                    <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>관계 (Predicate)</th>
                                    <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>목적어 (Object)</th>
                                </tr>
                            </thead>
                            <tbody>
                                {triples.map((triple, idx) => (
                                    <tr key={idx} style={{
                                        borderBottom: '1px solid var(--border)',
                                        backgroundColor: idx % 2 === 0 ? '#fff' : '#fafafa'
                                    }}>
                                        <td style={{ padding: '0.5rem 0.75rem', color: 'var(--text-secondary)' }}>{idx + 1}</td>
                                        <td style={{ padding: '0.5rem 0.75rem', fontWeight: 500 }}>{triple.subject}</td>
                                        <td style={{ padding: '0.5rem 0.75rem', color: '#3b82f6' }}>{triple.predicate}</td>
                                        <td style={{ padding: '0.5rem 0.75rem', fontWeight: 500 }}>{triple.object}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>

                {/* Footer Actions */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'flex-end',
                    gap: '1rem',
                    borderTop: '1px solid var(--border)',
                    paddingTop: '1rem'
                }}>
                    <button
                        className="btn"
                        onClick={onDiscard}
                        disabled={isLoading}
                        style={{ minWidth: '100px' }}
                    >
                        취소
                    </button>
                    <button
                        className="btn btn-primary"
                        onClick={onConfirm}
                        disabled={isLoading || triples.length === 0}
                        style={{
                            minWidth: '100px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '0.5rem'
                        }}
                    >
                        {isLoading ? '저장 중...' : (
                            <>
                                <Check size={16} />
                                저장
                            </>
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
}
