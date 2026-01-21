import React, { useState } from 'react';
import { X, Loader2 } from 'lucide-react';
import { docApi } from '../services/api';
import { Grid, GridColumn } from '@progress/kendo-react-grid';
import ChunkDetailModal from './ChunkDetailModal';

interface Chunk {
    chunk_id: string;
    content: string;
    metadata?: any;
    parent_id?: string;
    children?: Chunk[];
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

export default function ChunksModal({ isOpen, onClose, document, chunks, isLoading, kbId, onChunkUpdated, isGraphEnabled = false }: ChunksModalProps) {
    const [selectedChunk, setSelectedChunk] = useState<{ id: string; content: string } | null>(null);
    const [skip, setSkip] = useState(0);
    const [take, setTake] = useState(10);

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
                        <h2 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700, color: '#1e293b' }}>Document Chunks</h2>
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
                <div style={{ flex: 1, overflow: 'hidden' }}>
                    {isLoading ? (
                        <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                            <Loader2 size={40} className="spin" color="#3b82f6" />
                            <p style={{ marginTop: '1rem', color: '#64748b' }}>Loading chunks...</p>
                        </div>
                    ) : (
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
