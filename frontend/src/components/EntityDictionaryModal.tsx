import React from 'react';
import { X, Check, Book, AlertCircle } from 'lucide-react';

interface EntityDictionaryModalProps {
    isOpen: boolean;
    onClose: () => void;
    dictionary: Record<string, any>; // { "Canonical Name": { variants: [...], type: "..." } }
    entityCount: number;
    isLoading?: boolean;
}

export default function EntityDictionaryModal({
    isOpen,
    onClose,
    dictionary,
    entityCount,
    isLoading = false
}: EntityDictionaryModalProps) {
    if (!isOpen) return null;

    const entities = Object.entries(dictionary || {}).map(([name, data]) => ({
        name,
        type: data.type || 'Unknown',
        variants: data.variants || []
    }));

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
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <div style={{
                            width: '32px', height: '32px', borderRadius: '8px',
                            background: '#eff6ff', color: '#3b82f6',
                            display: 'flex', alignItems: 'center', justifyContent: 'center'
                        }}>
                            <Book size={18} />
                        </div>
                        <div>
                            <h2 style={{ margin: 0, fontSize: '1.25rem' }}>Entity Dictionary (Doc2Graph)</h2>
                            <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                {entityCount} canonical entities extracted from document
                            </p>
                        </div>
                    </div>
                    <button className="btn" onClick={onClose} style={{ padding: '0.5rem' }}>
                        <X size={20} />
                    </button>
                </div>

                {/* Dictionary Table */}
                <div style={{
                    flex: 1,
                    overflow: 'auto',
                    marginBottom: '1rem',
                    border: '1px solid var(--border)',
                    borderRadius: '8px'
                }}>
                    {entities.length === 0 ? (
                        <div style={{
                            padding: '3rem',
                            textAlign: 'center',
                            color: 'var(--text-secondary)'
                        }}>
                            <AlertCircle size={40} style={{ marginBottom: '1rem', opacity: 0.5, color: '#94a3b8' }} />
                            <p style={{ fontSize: '1.1rem', fontWeight: 500 }}>No entities found.</p>
                            <p style={{ fontSize: '0.9rem' }}>Try adjusting chunking or document content.</p>
                        </div>
                    ) : (
                        <table style={{
                            width: '100%',
                            borderCollapse: 'collapse',
                            fontSize: '0.9rem'
                        }}>
                            <thead>
                                <tr style={{
                                    backgroundColor: '#f8fafc',
                                    position: 'sticky',
                                    top: 0,
                                    zIndex: 10
                                }}>
                                    <th style={{ padding: '0.85rem', textAlign: 'left', borderBottom: '1px solid var(--border)', width: '60px' }}>#</th>
                                    <th style={{ padding: '0.85rem', textAlign: 'left', borderBottom: '1px solid var(--border)', width: '200px' }}>Canonical Name</th>
                                    <th style={{ padding: '0.85rem', textAlign: 'left', borderBottom: '1px solid var(--border)', width: '120px' }}>Type</th>
                                    <th style={{ padding: '0.85rem', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>Mapped Variants (Aliases)</th>
                                </tr>
                            </thead>
                            <tbody>
                                {entities.map((entity, idx) => (
                                    <tr key={idx} style={{
                                        borderBottom: '1px solid var(--border)',
                                        backgroundColor: idx % 2 === 0 ? '#fff' : '#fafafa'
                                    }}>
                                        <td style={{ padding: '0.75rem', color: 'var(--text-secondary)', textAlign: 'center' }}>{idx + 1}</td>
                                        <td style={{ padding: '0.75rem', fontWeight: 600, color: '#1e293b' }}>
                                            {entity.name}
                                        </td>
                                        <td style={{ padding: '0.75rem' }}>
                                            <span style={{
                                                display: 'inline-block',
                                                padding: '0.2rem 0.5rem',
                                                borderRadius: '4px',
                                                fontSize: '0.75rem',
                                                fontWeight: 500,
                                                backgroundColor: '#f1f5f9',
                                                color: '#475569',
                                                border: '1px solid #e2e8f0'
                                            }}>
                                                {entity.type}
                                            </span>
                                        </td>
                                        <td style={{ padding: '0.75rem', color: '#475569' }}>
                                            {entity.variants.length > 0 ? (
                                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                                                    {entity.variants.map((v: string, i: number) => (
                                                        <span key={i} style={{
                                                            fontSize: '0.8rem',
                                                            backgroundColor: '#eff6ff',
                                                            color: '#3b82f6',
                                                            padding: '0.1rem 0.4rem',
                                                            borderRadius: '4px'
                                                        }}>
                                                            {v}
                                                        </span>
                                                    ))}
                                                </div>
                                            ) : (
                                                <span style={{ color: '#cbd5e1', fontStyle: 'italic', fontSize: '0.8rem' }}>-</span>
                                            )}
                                        </td>
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
                        className="btn btn-primary"
                        onClick={onClose}
                        style={{ minWidth: '100px' }}
                    >
                        Close
                    </button>
                </div>
            </div>
        </div>
    );
}
