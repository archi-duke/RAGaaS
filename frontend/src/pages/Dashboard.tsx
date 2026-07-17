import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { kbApi } from '../services/api';
import { Plus, Database, Trash2, ArrowRight, FileText, HardDrive, Layers } from 'lucide-react';
import ConfirmDialog from '../components/ConfirmDialog';
import CreateKnowledgeBaseModal from '../components/CreateKnowledgeBaseModal';

interface KnowledgeBase {
    id: string;
    name: string;
    description: string;
    created_at: string;
    updated_at: string;
    chunking_strategy?: string;
    chunking_config?: any;
    document_count?: number;
    total_size?: number;
    graph_backend?: string;
    is_promoted?: boolean;
}

export default function Dashboard() {
    const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [isLoading, setIsLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);

    const [deleteKbId, setDeleteKbId] = useState<string | null>(null);

    useEffect(() => {
        loadKbs();
    }, []);

    const loadKbs = async () => {
        setIsLoading(true);
        setLoadError(null);
        try {
            const res = await kbApi.list();
            setKbs(Array.isArray(res.data) ? res.data : []);
        } catch (err: unknown) {
            const msg = err && typeof err === 'object' && 'response' in err
                ? (err as { response?: { status?: number; data?: unknown } }).response?.status === 404
                    ? 'API endpoint not found. Check backend URL.'
                    : `Failed to load: ${String((err as { response?: { data?: unknown } }).response?.data ?? (err instanceof Error ? err.message : err))}`
                : String(err);
            setLoadError(msg);
            console.error('KB list load error:', err);
            setKbs([]);
        } finally {
            setIsLoading(false);
        }
    };



    const handleDelete = (id: string, e: React.MouseEvent) => {
        e.preventDefault(); // Prevent navigation
        setDeleteKbId(id);
    };

    const confirmDeleteKb = async () => {
        if (!deleteKbId) return;
        try {
            await kbApi.delete(deleteKbId);
            loadKbs();
        } catch (err) {
            console.error(err);
        } finally {
            setDeleteKbId(null);
        }
    };

    return (
        <div className="container">
            <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', marginBottom: '2rem' }}>
                <button className="btn btn-primary" onClick={() => setIsModalOpen(true)}>
                    <Plus size={20} />
                    Create Knowledge Base
                </button>
            </div>

            {loadError && (
                <div style={{
                    padding: '1rem 1.5rem',
                    background: '#fef2f2',
                    color: '#b91c1c',
                    borderRadius: '8px',
                    marginBottom: '1.5rem',
                    fontSize: '0.875rem'
                }}>
                    {loadError}
                </div>
            )}
            {isLoading ? (
                <div style={{ color: 'var(--text-secondary)', padding: '2rem', textAlign: 'center' }}>
                    Loading...
                </div>
            ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))', gap: '1.5rem' }}>
                {kbs.map((kb) => (
                    <Link to={`/kb/${kb.id}`} key={kb.id} style={{ textDecoration: 'none', color: 'inherit' }}>
                        <div
                            className="card"
                            style={{
                                height: '100%',
                                display: 'flex',
                                flexDirection: 'column',
                                position: 'relative',
                                transition: 'all 0.2s',
                                cursor: 'pointer'
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.transform = 'translateY(-2px)';
                                e.currentTarget.style.boxShadow = '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.transform = 'translateY(0)';
                                e.currentTarget.style.boxShadow = '0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)';
                            }}
                        >
                            {/* Header with icon and delete button */}
                            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1rem' }}>
                                {/* Icon and title */}
                                <div style={{ display: 'flex', gap: '1rem', flex: 1 }}>
                                    <div style={{
                                        padding: '0.75rem',
                                        background: '#eff6ff',
                                        borderRadius: '8px',
                                        color: 'var(--primary)',
                                        flexShrink: 0,
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center'
                                    }}>
                                        <Database size={24} />
                                    </div>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1.125rem', fontWeight: 600 }}>
                                            {kb.name}
                                        </h3>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                            {/* Chunking strategy */}
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                                                <Database size={12} />

                                                {kb.graph_backend && kb.graph_backend !== 'none' && (
                                                    <span style={{
                                                        backgroundColor:
                                                            kb.graph_backend === 'ontology'
                                                                ? (kb.is_promoted ? '#1e40af' : '#bfdbfe')
                                                                : '#166534',
                                                        color: kb.graph_backend === 'ontology' && !kb.is_promoted ? '#1e40af' : 'white',
                                                        fontSize: '0.65rem',
                                                        padding: '1px 8px',
                                                        borderRadius: '12px',
                                                        fontWeight: 800,
                                                        lineHeight: 1.4,
                                                        boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                                                        textTransform: 'uppercase',
                                                        letterSpacing: '0.025em'
                                                    }}>
                                                        {kb.graph_backend === 'ontology' && kb.is_promoted
                                                            ? 'Ontology'
                                                            : 'Graph'}
                                                    </span>
                                                )}

                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', marginLeft: '2px' }}>
                                                    <Layers size={12} />
                                                    <span style={{ fontSize: '0.75rem' }}>
                                                        {(kb.chunking_strategy === 'size' || kb.chunking_strategy === 'fixed_size') && 'Fixed Size'}
                                                        {kb.chunking_strategy === 'parent_child' && 'Parent-Child'}
                                                        {kb.chunking_strategy === 'context_aware' && 'Context Aware'}
                                                        {!kb.chunking_strategy && 'N/A'}

                                                        {kb.chunking_config && (
                                                            <span style={{ marginLeft: '4px', opacity: 0.8 }}>
                                                                {kb.chunking_strategy === 'parent_child' ? (
                                                                    `(${kb.chunking_config.child_size || 0}/${kb.chunking_config.child_overlap || 0})`
                                                                ) : (
                                                                    `(${kb.chunking_config.chunk_size || 0}/${kb.chunking_config.chunk_overlap || 0})`
                                                                )}
                                                            </span>
                                                        )}
                                                    </span>
                                                </div>
                                            </div>
                                            {/* Document count and size */}
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                                                    <FileText size={12} />
                                                    <span>{kb.document_count ?? 0} docs</span>
                                                </div>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                                                    <HardDrive size={12} />
                                                    <span>
                                                        {kb.total_size
                                                            ? kb.total_size >= 1024 * 1024
                                                                ? `${(kb.total_size / (1024 * 1024)).toFixed(1)} MB`
                                                                : `${(kb.total_size / 1024).toFixed(1)} KB`
                                                            : '0 KB'
                                                        }
                                                    </span>
                                                </div>
                                            </div>
                                            {/* Updated timestamp */}
                                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                                                Updated: {kb.updated_at ? new Date(kb.updated_at).toLocaleString() : 'N/A'}
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                {/* Delete button */}
                                <button
                                    className="btn"
                                    style={{
                                        padding: '0.5rem',
                                        color: 'var(--text-secondary)',
                                        flexShrink: 0,
                                        background: 'transparent',
                                        border: 'none'
                                    }}
                                    onClick={(e) => handleDelete(kb.id, e)}
                                    onMouseEnter={(e) => {
                                        e.currentTarget.style.background = '#fee2e2';
                                        e.currentTarget.style.color = 'var(--danger)';
                                    }}
                                    onMouseLeave={(e) => {
                                        e.currentTarget.style.background = 'transparent';
                                        e.currentTarget.style.color = 'var(--text-secondary)';
                                    }}
                                >
                                    <Trash2 size={18} />
                                </button>
                            </div>

                            {/* Description */}
                            <p style={{
                                color: 'var(--text-secondary)',
                                margin: '0 0 1.5rem 0',
                                flex: 1,
                                fontSize: '0.875rem',
                                lineHeight: 1.5,
                                minHeight: '2.5rem',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                display: '-webkit-box',
                                WebkitLineClamp: 2,
                                WebkitBoxOrient: 'vertical'
                            }}>
                                {kb.description || 'No description'}
                            </p>

                            {/* View Details link */}
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                color: 'var(--primary)',
                                fontWeight: 500,
                                fontSize: '0.875rem',
                                gap: '0.5rem'
                            }}>
                                View Details
                                <ArrowRight size={16} />
                            </div>
                        </div>
                    </Link>
                ))}
            </div>
            )}

            <CreateKnowledgeBaseModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                onCreateComplete={loadKbs}
            />

            <ConfirmDialog
                isOpen={!!deleteKbId}
                title="Delete Knowledge Base"
                message="Are you sure you want to delete this Knowledge Base? This action cannot be undone."
                onConfirm={confirmDeleteKb}
                onCancel={() => setDeleteKbId(null)}
                confirmText="Delete"
                isDestructive={true}
            />
        </div>
    );
}
