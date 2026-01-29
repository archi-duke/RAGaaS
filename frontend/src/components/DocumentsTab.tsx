import React, { useState } from 'react';
import { Upload, FileText, Trash2, Database, Book, Check, X as XIcon, ChevronsRight } from 'lucide-react';

import UploadDocumentModal from './UploadDocumentModal';
import EntityDictionaryModal from './EntityDictionaryModal';
import ExtractionPreviewModal from './ExtractionPreviewModal';
import { docApi, extractionApi } from '../services/api';
import ConfirmDialog from './ConfirmDialog';

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
    pipeline_metadata?: {
        execution_mode?: 'batch' | 'step';
        [key: string]: any;
    };
    file_path?: string;
    chunking_strategy?: string;
    chunking_config?: any;
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
    // Defensive: Ensure documents is always an array
    const safeDocuments = Array.isArray(documents) ? documents : [];
    
    const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
    const [processingDocId, setProcessingDocId] = useState<string | null>(null);
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

    // Delete Confirmation State
    const [deleteConfirmState, setDeleteConfirmState] = useState<{ isOpen: boolean; docId: string | null }>({
        isOpen: false,
        docId: null
    });

    // Error Dialog State
    const [errorDialog, setErrorDialog] = useState<{ isOpen: boolean; title: string; message: string }>({
        isOpen: false,
        title: '',
        message: ''
    });

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

    const handleContinueProcessing = async (doc: Document) => {
        if (processingDocId) return;
        setProcessingDocId(doc.id);

        let currentStep = "INIT";

        try {
            // Determine Current State
            const isTripleWait = doc.pipeline_status === 'TRIPLE_EXTRACTED' || doc.status === 'TRIPLE_EXTRACTED';
            const isEntityWait = doc.pipeline_status === 'ENTITY_EXTRACTED' || doc.status === 'ENTITY_EXTRACTED';

            currentStep = "FETCH_PIPELINE";
            // 1. Fetch Pipeline Data (Dictionary or Triples)
            console.log(`[Continue] Fetching pipeline data for doc ${doc.id}...`);
            const pipeRes = await docApi.getPipelineData(kbId, doc.id);
            const pipelineData = pipeRes.data || {};

            if (isTripleWait) {
                currentStep = "CONFIRMING";
                // NEXT: Confirm Ingestion
                console.log("[Continue] TRIPLE_EXTRACTED -> Confirming...");
                // Prefer pipeline_metadata.preview_id, fallback to pipelineData.preview_id
                const previewId = doc.pipeline_metadata?.preview_id || pipelineData.preview_id;

                if (!previewId) {
                    console.error("Missing Preview ID. Metadata:", doc.pipeline_metadata, "PipelineData:", pipelineData);
                    throw new Error(`Missing Preview ID for confirmation. Doc ID: ${doc.id}`);
                }

                // Update status to STORING before confirm (for immediate UI feedback)
                await docApi.updatePipelineStatus(kbId, doc.id, {
                    status: 'STORING',
                    metadata: pipelineData
                });
                onRefresh();
                
                // Clear spinner immediately - button will show as disabled instead
                setProcessingDocId(null);

                await extractionApi.confirm(previewId, {
                    enable_inference: doc.enable_inference ?? false,
                    callback_url: "http://127.0.0.1:8000/api/knowledge-bases/ingest/callback",
                    kb_id: kbId,
                    doc_id: doc.id
                });

                console.log("[Continue] Confirmed.");
            } else if (isEntityWait) {
                currentStep = "UPDATE_STATUS_EXTRACTING";
                // NEXT: Extract Triples
                console.log("[Continue] ENTITY_EXTRACTED -> Extracting Triples...");

                if (!pipelineData.dictionary) {
                    console.warn("[Continue] No entity dictionary found. This might cause extraction to fail or run without dictionary.");
                }

                // Update status to loading
                await docApi.updatePipelineStatus(kbId, doc.id, {
                    status: 'EXTRACTING_TRIPLES',
                    metadata: pipelineData
                });
                onRefresh();

                // Clear spinner immediately - button will show as disabled instead
                setProcessingDocId(null);

                currentStep = "PREVIEW_REQUEST";
                // Robust File Path Lookup
                let filePath = doc.file_path || pipelineData.file_path;
                // Fallback if missing or placeholder
                if (!filePath || filePath === 'RESUME_AUTO_LOOKUP') {
                    filePath = `/data/uploads/${kbId}/${doc.id}_${doc.filename}`;
                    console.log(`[Continue] Path missing. Constructed fallback: ${filePath}`);
                }

                // Construct Params from Doc
                const res = await extractionApi.preview({
                    kb_id: kbId,
                    doc_id: doc.id,
                    file_path: filePath,
                    chunking: {
                        strategy: doc.chunking_strategy || 'fixed_size',
                        ...(doc.chunking_config || {})
                    },
                    graph: {
                        extractor_type: (doc.extractor_type as any) || 'simple',
                        max_paths_per_chunk: doc.max_paths || 20,
                        num_workers: 4,
                        generate_inverse_relations: doc.generate_inverse ?? true,
                    },
                    enable_text_cleaning: doc.enable_text_cleaning ?? false,
                    enable_subject_restoration: doc.enable_subject_restoration ?? true,
                    enable_entity_normalization: doc.enable_entity_normalization ?? true,
                    normalization_algorithm: 'embedding',
                    normalization_threshold: 0.85,

                    entity_dictionary: pipelineData.dictionary,
                    callback_url: "http://127.0.0.1:8000/api/knowledge-bases/ingest/callback"
                });

                currentStep = "UPDATE_STATUS_TRIPLE_EXTRACTED";
                // Save Result (TRIPLE_EXTRACTED)
                await docApi.updatePipelineStatus(kbId, doc.id, {
                    status: 'TRIPLE_EXTRACTED',
                    metadata: {
                        preview_id: res.data.preview_id,
                        doc_id: doc.id,
                        triples: res.data.triples,
                        node_count: res.data.node_count,
                        file_path: filePath,
                        dictionary: pipelineData.dictionary
                    }
                });
                console.log("[Continue] Triple Extraction Complete.");

                // [AUTO-CONFIRM OPTION]
                // If user wants explicit flow: Entity -> Triple -> Confirm, we stop here.
                // If user wants Entity -> [Triple -> Confirm] (Seamless), we can add confirm here.
                // For now, let's stick to the visible steps unless requested otherwise, 
                // BUT we fixed the Confirm step to be recoverable.
            }

            onRefresh();

        } catch (error: any) {
            console.error(`Continue processing failed at step: ${currentStep}`, error);
            const msg = error.response?.data?.detail || error.message || "Operation failed";

            // [Auto-Recovery] If Preview is lost (404 during CONFIRMING), revert to ENTITY_EXTRACTED
            if (currentStep === "CONFIRMING" && (msg.includes("Preview not found") || error.response?.status === 404)) {
                try {
                    console.log("[Recovery] Preview lost. Reverting to ENTITY_EXTRACTED...");
                    await docApi.updatePipelineStatus(kbId, doc.id, {
                        status: 'ENTITY_EXTRACTED',
                        metadata: doc.pipeline_metadata // Keep existing metadata (dictionary etc)
                    });
                    onRefresh();
                    setErrorDialog({
                        isOpen: true,
                        title: "Session Expired",
                        message: "The preview session expired (likely due to server restart). The document status has been reset to 'Entity Extracted'. Please click 'Continue' again to re-generate the triples."
                    });
                    return;
                } catch (recoveryErr) {
                    console.error("Failed to recover:", recoveryErr);
                }
            }

            setErrorDialog({
                isOpen: true,
                title: `Error at step: ${currentStep}`,
                message: msg
            });
        } finally {
            setProcessingDocId(null);
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


    // Helper to get status badge
    const getStatusBadge = (status: string, pipeline_status?: string, metadata?: any) => {
        // Royal Blue styling for standard 'completed' status
        const publishedStyle = { backgroundColor: '#4169E1', color: 'white', borderColor: '#4169E1' };

        // [CHECK MODE] If Batch Mode, force Processing badge for intermediate states
        if (metadata?.execution_mode === 'batch' && (pipeline_status === 'TRIPLE_EXTRACTED' || pipeline_status === 'ENTITY_EXTRACTED')) {
            return <span className="badge badge-warning" style={{ animation: 'pulse 2s infinite' }}>Processing...</span>;
        }

        const statusMap: Record<string, { class: string; label: string }> = {
            completed: { class: 'badge-success', label: 'Published' },
            processing: { class: 'badge-warning', label: 'Processing' },
            deleting: { class: 'badge-warning', label: 'Deleting...' },
            error: { class: 'badge-danger', label: 'Error' }
        };

        // Graph Pipeline Status Overrides
        if (status === 'processing' && pipeline_status) {
            switch (pipeline_status) {
                // Active Steps (Processing style)
                case 'EXTRACTING_ENTITIES':
                    return <span className="badge badge-warning" style={{ animation: 'pulse 2s infinite' }}>Entities...</span>;
                case 'EXTRACTING_TRIPLES':
                    return <span className="badge badge-warning" style={{ animation: 'pulse 2s infinite' }}>Triples...</span>;
                case 'STORING':
                    return <span className="badge badge-warning" style={{ animation: 'pulse 2s infinite' }}>Storing</span>;

                // Completed Intermediate Steps (Old Published style - Green)
                case 'ENTITY_EXTRACTED':
                    return <span className="badge badge-success">Entities</span>;
                case 'TRIPLE_EXTRACTED':
                    return <span className="badge badge-success">Triples</span>;

                // Final Step (Royal Blue)
                case 'COMPLETED':
                    return <span className="badge" style={publishedStyle}>Published</span>;

                default:
                    break;
            }
        }

        // Final Status Overrides
        if (status === 'completed') return <span className="badge" style={publishedStyle}>Published</span>;

        const config = statusMap[status] || { class: 'badge-secondary', label: status };
        return <span className={`badge ${config.class}`}>{config.label}</span>;
    };

    // Helper to get delete message
    const getDeleteMessage = () => {
        if (!deleteConfirmState.docId) return "";
        const doc = documents.find(d => d.id === deleteConfirmState.docId);
        if (!doc) return "";

        return doc.status === 'processing'
            ? "This document is currently being processed. Deleting it will stop the process. Are you sure you want to delete it?"
            : "Are you sure you want to delete this document?";
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
                    <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>Documents ({safeDocuments.length})</h3>
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
                            {safeDocuments.length === 0 ? (
                                <tr>
                                    <td colSpan={8} style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                        <FileText size={48} style={{ margin: '0 auto 1rem', opacity: 0.2 }} />
                                        <p style={{ margin: 0 }}>No documents uploaded yet</p>
                                    </td>
                                </tr>
                            ) : (
                                safeDocuments.map((doc) => (
                                    <tr
                                        key={doc.id}
                                        onClick={() => {
                                            // [MODIFIED] Check for Waiting State (Step Run Paused)
                                            // Robust check: pipeline_status OR status
                                            const isTripleWait = doc.pipeline_status === 'TRIPLE_EXTRACTED' || doc.status === 'TRIPLE_EXTRACTED';
                                            const isEntityWait = doc.pipeline_status === 'ENTITY_EXTRACTED' || doc.status === 'ENTITY_EXTRACTED';

                                            // [CHECK MODE] If this is a Batch Run, ignore intermediate waiting states!
                                            const isBatchMode = doc.pipeline_metadata?.execution_mode === 'batch';

                                            if ((isTripleWait || isEntityWait) && !isBatchMode) {
                                                // [MODIFIED] Direct Continue (No Modal) - Only if NOT Batch Mode
                                                handleContinueProcessing(doc);
                                                return;
                                            }

                                            // If processing (or batch mode running), do nothing (no response)
                                            if (doc.status === 'processing' || (isBatchMode && (isTripleWait || isEntityWait))) {
                                                return;
                                            } else {
                                                // Default: View Chunks
                                                onViewChunks(doc);
                                            }
                                        }}
                                        style={{
                                            borderBottom: '1px solid var(--border)',
                                            cursor: doc.status === 'processing' ? 'default' : 'pointer', // Change cursor
                                            transition: 'background-color 0.15s ease',
                                            backgroundColor: (
                                                (doc.pipeline_metadata?.execution_mode !== 'batch') && (
                                                    (doc.pipeline_status === 'TRIPLE_EXTRACTED' || doc.status === 'TRIPLE_EXTRACTED') ||
                                                    (doc.pipeline_status === 'ENTITY_EXTRACTED' || doc.status === 'ENTITY_EXTRACTED')
                                                )
                                            ) ? '#f0fdf4' : undefined // Slight green tint for waiting (Step Run only)
                                        }}
                                        className={doc.status === 'processing' ? '' : "hover:bg-gray-50"}
                                    >
                                        <td style={{ padding: '1rem', fontWeight: 500 }}>{doc.filename}</td>
                                        <td style={{ padding: '1rem' }}>
                                            <span className="badge badge-secondary" style={{ fontSize: '0.75rem' }}>{doc.file_type.toUpperCase()}</span>
                                        </td>
                                        <td style={{ padding: '1rem' }}>{getStatusBadge(doc.status, doc.pipeline_status, doc.pipeline_metadata)}</td>
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
                                                {/* CONTINUE BUTTON - Hide if Batch Mode */}
                                                {(() => {
                                                    // Step Run 관련 상태 확인
                                                    const pipelineStatus = doc.pipeline_status || doc.status;
                                                    const isStepRun = doc.pipeline_metadata?.execution_mode !== 'batch' && [
                                                        'EXTRACTING_ENTITIES',
                                                        'EXTRACTING_TRIPLES',
                                                        'ENTITY_EXTRACTED',
                                                        'TRIPLE_EXTRACTED',
                                                        'STORING'
                                                    ].includes(pipelineStatus);

                                                    if (!isStepRun) return null;

                                                    // 버튼 활성/비활성 판단
                                                    const isDeleting = doc.status === 'deleting';
                                                    const isExtracting = ['EXTRACTING_ENTITIES', 'EXTRACTING_TRIPLES', 'STORING'].includes(pipelineStatus);
                                                    const isWaitingForContinue = ['ENTITY_EXTRACTED', 'TRIPLE_EXTRACTED'].includes(pipelineStatus);
                                                    const isButtonDisabled = isDeleting || isExtracting || !!processingDocId;

                                                    return (
                                                        <button
                                                            className={`btn ${isButtonDisabled ? '' : 'btn-primary'}`}
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                handleContinueProcessing(doc);
                                                            }}
                                                            disabled={isButtonDisabled}
                                                            title={isDeleting ? "Deleting..." : isExtracting ? "Processing..." : "Continue Processing"}
                                                            style={{
                                                                padding: '0.4rem',
                                                                minWidth: 'auto',
                                                                borderRadius: '6px',
                                                                opacity: isButtonDisabled ? 0.5 : 1,
                                                                cursor: isButtonDisabled ? 'not-allowed' : 'pointer',
                                                                display: 'flex',
                                                                alignItems: 'center',
                                                                justifyContent: 'center',
                                                                fontSize: '0.8rem',
                                                                fontWeight: 600
                                                            }}
                                                        >
                                                            <ChevronsRight size={18} strokeWidth={2.5} />
                                                        </button>
                                                    );
                                                })()}

                                                <button
                                                    className="btn btn-icon"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleViewEntities(doc.id, doc.filename);
                                                    }}
                                                    title="View Entity List"
                                                    disabled={(() => {
                                                        if (doc.status === 'deleting') return true;
                                                        if (isLoadingResults) return true;
                                                        // Enable if status indicates data exists, regardless of processing state
                                                        const pStatus = doc.pipeline_status || doc.status;
                                                        const hasData = ['ENTITY_EXTRACTED', 'EXTRACTING_TRIPLES', 'TRIPLE_EXTRACTED', 'STORING', 'COMPLETED', 'completed'].includes(pStatus);
                                                        return !hasData;
                                                    })()}
                                                    style={{
                                                        color: (() => {
                                                            if (doc.status === 'deleting') return 'var(--text-tertiary)';
                                                            const pStatus = doc.pipeline_status || doc.status;
                                                            const hasData = ['ENTITY_EXTRACTED', 'EXTRACTING_TRIPLES', 'TRIPLE_EXTRACTED', 'STORING', 'COMPLETED', 'completed'].includes(pStatus);
                                                            return hasData ? '#3b82f6' : 'var(--text-tertiary)';
                                                        })(),
                                                        opacity: (() => {
                                                            if (doc.status === 'deleting') return 0.5;
                                                            const pStatus = doc.pipeline_status || doc.status;
                                                            const hasData = ['ENTITY_EXTRACTED', 'EXTRACTING_TRIPLES', 'TRIPLE_EXTRACTED', 'STORING', 'COMPLETED', 'completed'].includes(pStatus);
                                                            return hasData ? 1 : 0.5;
                                                        })()
                                                    }}
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
                                                    disabled={(() => {
                                                        if (doc.status === 'deleting') return true;
                                                        if (isLoadingResults) return true;
                                                        // Enable if status indicates data exists, regardless of processing state
                                                        const pStatus = doc.pipeline_status || doc.status;
                                                        const hasData = ['TRIPLE_EXTRACTED', 'STORING', 'COMPLETED', 'completed'].includes(pStatus);
                                                        return !hasData;
                                                    })()}
                                                    style={{
                                                        color: (() => {
                                                            if (doc.status === 'deleting') return 'var(--text-tertiary)';
                                                            const pStatus = doc.pipeline_status || doc.status;
                                                            const hasData = ['TRIPLE_EXTRACTED', 'STORING', 'COMPLETED', 'completed'].includes(pStatus);
                                                            return hasData ? '#3b82f6' : 'var(--text-tertiary)';
                                                        })(),
                                                        opacity: (() => {
                                                            if (doc.status === 'deleting') return 0.5;
                                                            const pStatus = doc.pipeline_status || doc.status;
                                                            const hasData = ['TRIPLE_EXTRACTED', 'STORING', 'COMPLETED', 'completed'].includes(pStatus);
                                                            return hasData ? 1 : 0.5;
                                                        })()
                                                    }}
                                                >
                                                    <Database size={18} />
                                                </button>
                                                <button
                                                    className="btn btn-icon danger"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setDeleteConfirmState({ isOpen: true, docId: doc.id });
                                                    }}
                                                    title="Delete Document"
                                                    disabled={doc.status === 'deleting'}
                                                    style={{
                                                        color: 'var(--error)',
                                                        opacity: doc.status === 'deleting' ? 0.5 : 1,
                                                        cursor: doc.status === 'deleting' ? 'not-allowed' : 'pointer'
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
            </div >

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

            <ConfirmDialog
                isOpen={deleteConfirmState.isOpen}
                title="Delete Document"
                message={getDeleteMessage()}
                onConfirm={() => {
                    if (deleteConfirmState.docId) {
                        onDeleteDocument(deleteConfirmState.docId);
                    }
                    setDeleteConfirmState({ isOpen: false, docId: null });
                }}
                onCancel={() => setDeleteConfirmState({ isOpen: false, docId: null })}
                confirmText="Delete"
                cancelText="Cancel"
                isDestructive={true}
            />

            {
                dictionaryData && (
                    <EntityDictionaryModal
                        isOpen={showDictionaryModal}
                        onClose={() => setShowDictionaryModal(false)}
                        dictionary={dictionaryData.dictionary}
                        entityCount={dictionaryData.entity_count}
                    />
                )
            }

            {
                previewData && (
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
                )
            }

            <ConfirmDialog
                isOpen={errorDialog.isOpen}
                title={errorDialog.title}
                message={errorDialog.message}
                onConfirm={() => setErrorDialog(prev => ({ ...prev, isOpen: false }))}
                onCancel={() => setErrorDialog(prev => ({ ...prev, isOpen: false }))}
                confirmText="Close"
                cancelText="Dismiss"
                isDestructive={true}
            />
        </>
    );
}
