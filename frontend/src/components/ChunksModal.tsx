import React, { useState, useMemo } from 'react';
import { X, Loader2, ChevronDown, ChevronRight, FileText } from 'lucide-react';
import { docApi } from '../services/api';
import { Grid, GridColumn } from '@progress/kendo-react-grid';
import ChunkDetailModal from './ChunkDetailModal';

interface Chunk {
    chunk_id: string;
    content: string;
    metadata?: any;
}

interface ChunksModalProps {
    isOpen: boolean;
    onClose: () => void;
    document: {
        id: string;
        filename: string;
    } | null;
    chunks: Chunk[];
    isLoading: boolean;
    kbId: string;
    onChunkUpdated: () => void;
    isGraphEnabled?: boolean;
}

interface ParentGroup {
    parentId: string;
    parentIndex: number;
    parentContent: string;
    children: Chunk[];
}

export default function ChunksModal({ isOpen, onClose, document, chunks, isLoading, kbId, onChunkUpdated, isGraphEnabled = false }: ChunksModalProps) {
    const [selectedChunk, setSelectedChunk] = useState<{ id: string; content: string } | null>(null);
    const [skip, setSkip] = useState(0);
    const [take, setTake] = useState(10);

    // Accordion state
    const [expandedParents, setExpandedParents] = useState<Set<string>>(new Set());

    // Group chunks by parent if metadata exists
    const { isParentChild, groupedChunks } = useMemo(() => {
        if (!chunks || chunks.length === 0) return { isParentChild: false, groupedChunks: [] };

        // Check if first chunk has parent_id metadata
        const firstChunk = chunks[0];
        const hasParentMetadata = firstChunk.metadata && (firstChunk.metadata.parent_id !== undefined);

        if (!hasParentMetadata) return { isParentChild: false, groupedChunks: [] };

        const groups = new Map<string, ParentGroup>();

        chunks.forEach((chunk) => {
            const parentId = chunk.metadata?.parent_id || 'unknown';
            const parentIndex = chunk.metadata?.parent_index ?? -1;
            const parentContent = chunk.metadata?.parent_content || '(No parent content)';

            if (!groups.has(parentId)) {
                groups.set(parentId, {
                    parentId,
                    parentIndex,
                    parentContent,
                    children: []
                });
            }
            groups.get(parentId)?.children.push(chunk);
        });

        // Sort by parent index
        const sortedGroups = Array.from(groups.values()).sort((a, b) => a.parentIndex - b.parentIndex);

        return { isParentChild: true, groupedChunks: sortedGroups };
    }, [chunks]);

    // Initialize all expanded on load
    React.useEffect(() => {
        if (isParentChild && groupedChunks.length > 0) {
            // Default: Expand first 3
            setExpandedParents(new Set(groupedChunks.slice(0, 3).map(g => g.parentId)));
        }
    }, [isParentChild, groupedChunks]);


    if (!isOpen || !document) return null;

    const handleChunkClick = (chunk: Chunk) => {
        setSelectedChunk({
            id: chunk.chunk_id,
            content: chunk.content
        });
    };

    const handleSaveChunk = async (newContent: string) => {
        if (!selectedChunk) return;
        try {
            await docApi.updateChunk(kbId, document.id, selectedChunk.id, newContent);
            setSelectedChunk(prev => prev ? { ...prev, content: newContent } : null);
            onChunkUpdated(); // Refresh chunks in parent
            alert('Chunk updated successfully!');
        } catch (error) {
            console.error('Failed to update chunk:', error);
            throw error;
        }
    };

    const pageChange = (event: any) => {
        setSkip(event.page.skip);
        setTake(event.page.take);
    };

    const toggleParent = (parentId: string) => {
        const newExpanded = new Set(expandedParents);
        if (newExpanded.has(parentId)) {
            newExpanded.delete(parentId);
        } else {
            newExpanded.add(parentId);
        }
        setExpandedParents(newExpanded);
    };

    const ChunkIdCell = (props: any) => {
        return (
            <td style={{ textAlign: 'center' }}>
                <span
                    onClick={() => handleChunkClick(props.dataItem)}
                    style={{
                        color: '#3b82f6',
                        textDecoration: 'underline',
                        cursor: 'pointer',
                        fontWeight: 500
                    }}
                >
                    {props.dataItem.chunk_id.substring(0, 8)}...
                </span>
            </td>
        );
    };

    const ContentPreviewCell = (props: any) => {
        return (
            <td style={{ fontSize: '0.85rem', color: '#64748b' }}>
                <div style={{
                    maxHeight: '1.5em',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    cursor: 'pointer'
                }} onClick={() => handleChunkClick(props.dataItem)}>
                    {props.dataItem.content}
                </div>
            </td>
        );
    };

    const processedChunks = chunks.map((c, i) => ({ ...c, index: i + 1 }));
    const pagedChunks = processedChunks.slice(skip, skip + take);

    return (
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
            onClick={onClose}
        >
            <div
                className="card"
                style={{
                    width: '90%',
                    maxWidth: '1000px',
                    height: '80vh',
                    display: 'flex',
                    flexDirection: 'column',
                    padding: '24px',
                    backgroundColor: 'white',
                    borderRadius: '12px',
                    boxShadow: '0 20px 50px rgba(0,0,0,0.3)'
                }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', borderBottom: '1px solid #e2e8f0', paddingBottom: '1rem' }}>
                    <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <h2 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700, color: '#1e293b' }}>
                                Document Chunks
                            </h2>
                            {isParentChild && (
                                <span style={{
                                    backgroundColor: '#dbeafe',
                                    color: '#1e40af',
                                    fontSize: '0.75rem',
                                    padding: '2px 8px',
                                    borderRadius: '12px',
                                    fontWeight: 600
                                }}>
                                    Parent-Child View
                                </span>
                            )}
                        </div>
                        <p style={{ margin: '0.25rem 0 0 0', color: '#64748b', fontSize: '0.9rem' }}>
                            {document.filename} ({chunks.length} chunks)
                        </p>
                    </div>
                    <button
                        className="btn btn-icon"
                        onClick={onClose}
                        style={{ padding: '8px' }}
                    >
                        <X size={24} />
                    </button>
                </div>

                {/* Content */}
                <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                    {isLoading ? (
                        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                            <Loader2 size={40} className="spin" color="#3b82f6" />
                            <p style={{ marginTop: '1rem', color: '#64748b' }}>Loading chunks...</p>
                        </div>
                    ) : isParentChild ? (
                        // Parent-Child View
                        <div style={{ flex: 1, overflowY: 'auto', paddingRight: '8px' }}>
                            {groupedChunks.map((group) => {
                                const isExpanded = expandedParents.has(group.parentId);
                                return (
                                    <div key={group.parentId} style={{ marginBottom: '16px', border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden' }}>
                                        {/* Parent Header */}
                                        <div
                                            onClick={() => toggleParent(group.parentId)}
                                            style={{
                                                padding: '12px 16px',
                                                backgroundColor: '#f8fafc',
                                                cursor: 'pointer',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '10px',
                                                borderBottom: isExpanded ? '1px solid #e2e8f0' : 'none',
                                                transition: 'background-color 0.2s'
                                            }}
                                            onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#f1f5f9'}
                                            onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#f8fafc'}
                                        >
                                            {isExpanded ? <ChevronDown size={18} color="#64748b" /> : <ChevronRight size={18} color="#64748b" />}
                                            <div style={{ flex: 1 }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                                                    <span style={{ fontWeight: 600, fontSize: '0.9rem', color: '#334155' }}>
                                                        Parent Chunk {group.parentIndex + 1}
                                                    </span>
                                                    <span style={{ fontSize: '0.8rem', color: '#94a3b8', backgroundColor: '#f1f5f9', padding: '1px 6px', borderRadius: '4px' }}>
                                                        {group.children.length} children
                                                    </span>
                                                </div>
                                                <div style={{
                                                    fontSize: '0.85rem',
                                                    color: '#64748b',
                                                    whiteSpace: 'nowrap',
                                                    overflow: 'hidden',
                                                    textOverflow: 'ellipsis',
                                                    maxWidth: '600px'
                                                }}>
                                                    {group.parentContent.substring(0, 100)}...
                                                </div>
                                            </div>
                                        </div>

                                        {/* Children List */}
                                        {isExpanded && (
                                            <div style={{ backgroundColor: 'white' }}>
                                                {group.children.map((child, idx) => (
                                                    <div
                                                        key={child.chunk_id}
                                                        onClick={() => handleChunkClick(child)}
                                                        style={{
                                                            padding: '10px 16px 10px 44px',
                                                            borderBottom: idx === group.children.length - 1 ? 'none' : '1px solid #f1f5f9',
                                                            cursor: 'pointer',
                                                            display: 'flex',
                                                            alignItems: 'start',
                                                            gap: '8px'
                                                        }}
                                                        onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#f8fafc'}
                                                        onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'white'}
                                                    >
                                                        <FileText size={14} color="#94a3b8" style={{ marginTop: '3px' }} />
                                                        <div style={{ flex: 1 }}>
                                                            <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '2px', fontFamily: 'monospace' }}>
                                                                {child.chunk_id.substring(0, 8)}...
                                                            </div>
                                                            <div style={{ fontSize: '0.9rem', color: '#334155', lineHeight: '1.4' }}>
                                                                {child.content}
                                                            </div>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    ) : (
                        // Standard Grid View
                        <div style={{ height: '100%' }}>
                            <style>{`
                                .k-grid th {
                                    text-align: center !important;
                                    font-weight: bold !important;
                                    background-color: #f8fafc !important;
                                    font-size: 0.8rem !important;
                                }
                                .k-grid td {
                                    vertical-align: middle !important;
                                    padding: 12px !important;
                                }
                                .k-pager {
                                    font-size: 0.75rem !important;
                                }
                            `}</style>
                            <Grid
                                style={{ height: '100%' }}
                                data={pagedChunks}
                                skip={skip}
                                take={take}
                                total={processedChunks.length}
                                pageable={{
                                    buttonCount: 5,
                                    info: true,
                                    type: 'numeric',
                                    pageSizes: [10, 20, 50],
                                    previousNext: true
                                }}
                                onPageChange={pageChange}
                                resizable={true}
                            >
                                <GridColumn field="index" title="#" width="60px" />
                                <GridColumn field="chunk_id" title="Chunk ID" width="150px" cell={ChunkIdCell} />
                                <GridColumn field="content" title="Content Preview" cell={ContentPreviewCell} />
                            </Grid>
                        </div>
                    )}
                </div>
            </div>

            {/* Unified Detail Modal */}
            <ChunkDetailModal
                isOpen={!!selectedChunk}
                onClose={() => setSelectedChunk(null)}
                chunk={selectedChunk}
                title="Chunk Detail View"
                onSave={handleSaveChunk}
                isGraphEnabled={isGraphEnabled}
                kbId={kbId}
            />
        </div>
    );
}
