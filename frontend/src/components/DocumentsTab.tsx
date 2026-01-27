import React, { useState } from 'react';
import { Upload, FileText, Trash2, Database, Book, Check, X as XIcon } from 'lucide-react';
import UploadDocumentModal from './UploadDocumentModal';
import EntityDictionaryModal from './EntityDictionaryModal';
import ExtractionPreviewModal from './ExtractionPreviewModal';
import { docApi, extractionApi } from '../services/api';

interface Document {
    id: string;
    filename: string;
    file_type: string;
    status: string;
    created_at: string;
    updated_at: string;
    extractor_type?: string;
    max_paths?: number;
    enable_text_cleaning?: boolean;
    enable_subject_restoration?: boolean;
    enable_inference?: boolean;
    generate_inverse?: boolean;
    extraction_examples?: string;
    custom_prompt?: string;
    // Entity Normalization Settings
    enable_entity_normalization?: boolean;
    max_sample_size?: number;
    // Pipeline Persistence
    pipeline_status?: string;
    pipeline_metadata?: any;
    file_path?: string;
}

interface DocumentsTabProps {
    kbId: string;
    documents: Document[];
    onRefresh: () => void;
    onDeleteDocument: (docId: string) => void;
    onViewChunks: (doc: Document) => void;
    isOntology?: boolean;
}

export default function DocumentsTab({ kbId, documents, onRefresh, onDeleteDocument, onViewChunks }: DocumentsTabProps) {
    const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
    const [resumeState, setResumeState] = useState<{
        docId?: string;
        filename?: string;
        filePath?: string;
        step?: 'ENTITY_EXTRACTED' | 'TRIPLE_EXTRACTED';
        data?: any;
    } | undefined>(undefined);

    // Result Modals State
    const [showPreviewModal, setShowPreviewModal] = useState(false);
    const [previewData, setPreviewData] = useState<any>(null);
    const [showDictionaryModal, setShowDictionaryModal] = useState(false);
    const [dictionaryData, setDictionaryData] = useState<any>(null);
    const [isLoadingResults, setIsLoadingResults] = useState(false);

    const handleViewEntities = async (docId: string, filename: string) => {
        setIsLoadingResults(true);
        try {
            const res = await docApi.getPipelineData(kbId, docId);
            if (res.data.dictionary) {
                setDictionaryData({
                    dictionary: res.data.dictionary,
                    entity_count: Object.keys(res.data.dictionary).length,
                    doc_id: docId
                });
                setShowDictionaryModal(true);
            } else {
                alert("No entity extraction data found.");
            }
        } catch (error) {
            console.error("Failed to fetch dictionary data:", error);
            alert("Failed to fetch data.");
        } finally {
            setIsLoadingResults(false);
        }
    };

    const handleViewTriples = async (docId: string, filename: string) => {
        setIsLoadingResults(true);
        try {
            const res = await docApi.getPipelineData(kbId, docId);
            if (res.data.triples) {
                setPreviewData({
                    preview_id: res.data.preview_id || 'saved',
                    doc_id: docId,
                    triples: res.data.triples,
                    node_count: res.data.node_count || 0
                });
                setShowPreviewModal(true);
            } else {
                alert("No triple extraction data found.");
            }
        } catch (error) {
            console.error("Failed to fetch triples data:", error);
            alert("Failed to fetch data.");
        } finally {
            setIsLoadingResults(false);
        }
    };

    const handlePreviewConfirm = async () => {
        if (!previewData || previewData.preview_id === 'saved') {
            setShowPreviewModal(false);
            return;
        }
        // If it's a re-confirm of a preview, we can handle it here, 
        // but usually for already saved docs, we just close.
        setShowPreviewModal(false);
    };


    const getStatusBadge = (status: string, pipeline_status?: string) => {
        const statusMap: Record<string, { class: string; label: string }> = {
            completed: { class: 'badge-success', label: 'Published' }, // Changed to Published
            processing: { class: 'badge-warning', label: 'Processing' },
            deleting: { class: 'badge-warning', label: 'Deleting...' },
            error: { class: 'badge-danger', label: 'Error' }
        };

        // Graph Pipeline Status Overrides
        if (status === 'processing' && pipeline_status) {
            switch (pipeline_status) {
                case 'EXTRACTING_ENTITIES':
                    return <span className="badge badge-warning" style={{ animation: 'pulse 2s infinite' }}>Entities...</span>;
                case 'ENTITY_EXTRACTED':
                    return <span className="badge badge-success" style={{ backgroundColor: '#0ea5e9', borderColor: '#0ea5e9' }}>Entities</span>;
                case 'EXTRACTING_TRIPLES':
                    return <span className="badge badge-warning" style={{ animation: 'pulse 2s infinite' }}>Triples...</span>;
                case 'TRIPLE_EXTRACTED':
                    return <span className="badge badge-success" style={{ backgroundColor: '#8b5cf6', borderColor: '#8b5cf6' }}>Triples</span>;
                case 'STORING':
                    return <span className="badge badge-warning" style={{ animation: 'pulse 2s infinite' }}>Storing</span>;
                case 'COMPLETED':
                    return <span className="badge badge-success">Published</span>;
                default:
                    // Fallback to standard processing
                    break;
            }
        }

        // Final Status Overrides
        if (status === 'completed') return <span className="badge badge-success">Published</span>;

        const config = statusMap[status] || { class: 'badge-secondary', label: status };
        return <span className={`badge ${config.class}`}>{config.label}</span>;
    };

    return (
        <>
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                <div style={{
                    padding: '1.5rem',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    borderBottom: '1px solid var(--border)'
                }}>
                    <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>Documents ({documents.length})</h3>
                    <button
                        className="btn btn-primary"
                        onClick={() => {
                            setResumeState(undefined); // Reset resume state for new upload
                            setIsUploadModalOpen(true);
                        }}
                        style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                    >
                        <Upload size={18} />
                        Upload Document
                    </button>
                </div>

                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                            <tr style={{ borderBottom: '1px solid var(--border)', backgroundColor: 'rgba(0,0,0,0.02)' }}>
                                <th style={{ padding: '1rem', textAlign: 'left', fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Filename</th>
                                <th style={{ padding: '1rem', textAlign: 'left', fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Type</th>
                                <th style={{ padding: '1rem', textAlign: 'left', fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Status</th>
                                <th style={{ padding: '1rem', textAlign: 'center', fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Paths</th>
                                <th style={{ padding: '1rem', textAlign: 'center', fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Sample</th>
                                <th style={{ padding: '1rem', textAlign: 'center', fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Clean</th>
                                <th style={{ padding: '1rem', textAlign: 'center', fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Subject</th>
                                {/* [REMOVED] Inverse column - inverse relations now inferred at query time */}
                                <th style={{ padding: '1rem', textAlign: 'left', fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Updated</th>
                                <th style={{ padding: '1rem', textAlign: 'center', fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {documents.length === 0 ? (
                                <tr>
                                    <td colSpan={8} style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                        <FileText size={48} style={{ margin: '0 auto 1rem', opacity: 0.2 }} />
                                        <p style={{ margin: 0 }}>No documents uploaded yet</p>
                                    </td>
                                </tr>
                            ) : (
                                documents.map((doc) => (
                                    <tr
                                        key={doc.id}
                                        onClick={() => {
                                            // [RESUME LOGIC] If processing, always show the upload/pipeline modal
                                            if (doc.status === 'processing') {
                                                console.log("Resuming document:", doc.id, doc.pipeline_status);
                                                setResumeState({
                                                    docId: doc.id,
                                                    filename: doc.filename,
                                                    filePath: doc.file_path,
                                                    step: doc.pipeline_status as any,
                                                    data: doc.pipeline_metadata
                                                });
                                                setIsUploadModalOpen(true);
                                            } else {
                                                // Default: View Chunks
                                                onViewChunks(doc);
                                            }
                                        }}
                                        style={{
                                            borderBottom: '1px solid var(--border)',
                                            cursor: 'pointer',
                                            transition: 'background-color 0.15s ease'
                                        }}
                                        className="hover:bg-gray-50"
                                        onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(0,0,0,0.02)'}
                                        onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                                    >
                                        <td style={{ padding: '1rem', fontWeight: 500 }}>{doc.filename}</td>
                                        <td style={{ padding: '1rem' }}>
                                            <span className="badge badge-secondary" style={{ fontSize: '0.75rem' }}>{doc.file_type.toUpperCase()}</span>
                                        </td>
                                        <td style={{ padding: '1rem' }}>{getStatusBadge(doc.status, doc.pipeline_status)}</td>
                                        <td style={{ padding: '1rem', textAlign: 'center', fontSize: '0.85rem' }}>{doc.max_paths === 1000 ? '∞' : (doc.max_paths || '-')}</td>
                                        <td style={{ padding: '1rem', textAlign: 'center', fontSize: '0.85rem' }}>{doc.max_sample_size ? `${doc.max_sample_size / 1000}k` : '-'}</td>
                                        <td style={{ padding: '1rem', textAlign: 'center' }}>
                                            {doc.enable_text_cleaning ? <Check size={16} color="#3b82f6" /> : <XIcon size={16} color="var(--text-tertiary)" />}
                                        </td>
                                        <td style={{ padding: '1rem', textAlign: 'center' }}>
                                            {doc.enable_subject_restoration ? <Check size={16} color="#3b82f6" /> : <XIcon size={16} color="var(--text-tertiary)" />}
                                        </td>
                                        {/* [REMOVED] Inverse column data */}
                                        <td style={{ padding: '1rem', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                                            {doc.updated_at ? new Date(doc.updated_at).toLocaleString() : '-'}
                                        </td>
                                        <td style={{ padding: '1rem', textAlign: 'center' }}>
                                            <div style={{ display: 'flex', justifyContent: 'center', gap: '0.5rem' }}>
                                                <button
                                                    className="btn btn-icon"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleViewEntities(doc.id, doc.filename);
                                                    }}
                                                    title="View Entity List"
                                                    disabled={isLoadingResults}
                                                    style={{ color: '#3b82f6' }}
                                                >
                                                    <Book size={18} />
                                                </button>
                                                <button
                                                    className="btn btn-icon"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleViewTriples(doc.id, doc.filename);
                                                    }}
                                                    title="View Triple List"
                                                    disabled={isLoadingResults}
                                                    style={{ color: '#3b82f6' }}
                                                >
                                                    <Database size={18} />
                                                </button>
                                                <button
                                                    className="btn btn-icon danger"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        onDeleteDocument(doc.id);
                                                    }}
                                                    title="Delete Document"
                                                    style={{
                                                        color: 'var(--error)',
                                                        opacity: 0.7
                                                    }}
                                                >
                                                    <Trash2 size={18} />
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            <UploadDocumentModal
                isOpen={isUploadModalOpen}
                onClose={() => {
                    setIsUploadModalOpen(false);
                    onRefresh();
                }}
                kbId={kbId}
                onUploadComplete={onRefresh}
                initialState={resumeState}
            />

            {dictionaryData && (
                <EntityDictionaryModal
                    isOpen={showDictionaryModal}
                    onClose={() => setShowDictionaryModal(false)}
                    dictionary={dictionaryData.dictionary}
                    entityCount={dictionaryData.entity_count}
                />
            )}

            {previewData && (
                <ExtractionPreviewModal
                    isOpen={showPreviewModal}
                    onClose={() => setShowPreviewModal(false)}
                    previewId={previewData.preview_id}
                    triples={previewData.triples}
                    nodeCount={previewData.node_count}
                    onConfirm={handlePreviewConfirm}
                    onDiscard={() => setShowPreviewModal(false)}
                    viewOnly={true}
                />
            )}
        </>
    );
}
