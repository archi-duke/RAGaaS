import React, { useState, useRef, useEffect } from 'react';
import { Upload, X, FileText, Database, Eye, Check, Settings } from 'lucide-react';
import { docApi, kbApi, extractionApi } from '../services/api';
import MessageDialog from './MessageDialog';
import PromptDialog from './PromptDialog';
import ExtractionPreviewModal from './ExtractionPreviewModal';
import EntityDictionaryModal from './EntityDictionaryModal';
import GraphExtractionSettings from './GraphExtractionSettings';

interface UploadDocumentModalProps {
    isOpen: boolean;
    onClose: () => void;
    kbId: string;
    onUploadComplete: () => void;
    initialState?: {
        file?: File; // Optional if starting fresh
        docId?: string;
        filename?: string;
        filePath?: string;
        step?: 'ENTITY_EXTRACTED' | 'TRIPLE_EXTRACTED';
        data?: any;
    };
}

const LabelWithTooltip = ({ label, tooltip }: { label: string, tooltip: string }) => {
    const [show, setShow] = useState(false);
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.3rem', position: 'relative' }}>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>{label}</label>
            <div
                style={{ cursor: 'help', display: 'flex', alignItems: 'center' }}
                onMouseEnter={() => setShow(true)}
                onMouseLeave={() => setShow(false)}
            >
                <div style={{
                    width: '14px',
                    height: '14px',
                    borderRadius: '50%',
                    border: '1px solid #94a3b8',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '9px',
                    color: '#94a3b8',
                    fontWeight: 'bold',
                    flexShrink: 0,
                    lineHeight: 1
                }}>i</div>
                {show && (
                    <div style={{
                        position: 'absolute',
                        bottom: '120%',
                        left: '0',
                        backgroundColor: '#333',
                        color: '#fff',
                        padding: '0.5rem 0.75rem',
                        borderRadius: '4px',
                        fontSize: '0.75rem',
                        whiteSpace: 'normal',
                        width: '200px',
                        zIndex: 100,
                        boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
                        pointerEvents: 'none'
                    }}>
                        {tooltip}
                        <div style={{
                            position: 'absolute',
                            top: '100%',
                            left: '10px',
                            borderWidth: '5px',
                            borderStyle: 'solid',
                            borderColor: '#333 transparent transparent transparent'
                        }}></div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default function UploadDocumentModal({ isOpen, onClose, kbId, onUploadComplete, initialState }: UploadDocumentModalProps) {
    const [file, setFile] = useState<File | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [kbConfig, setKbConfig] = useState<any>(null);

    // Modals state
    const [showExampleModal, setShowExampleModal] = useState(false);
    const [showPromptModal, setShowPromptModal] = useState(false);
    const [showPreviewModal, setShowPreviewModal] = useState(false);
    const [isExtracting, setIsExtracting] = useState(false);
    const [previewData, setPreviewData] = useState<{
        preview_id: string;
        doc_id: string;
        triples: any[];
        node_count: number;
        stats?: any[];
    } | null>(null);

    // New State for Step Run
    const [isStepRunning, setIsStepRunning] = useState(false);

    const [messageDialog, setMessageDialog] = useState<{ isOpen: boolean; title: string; message: string; type: 'info' | 'success' | 'error' }>({
        isOpen: false,
        title: '',
        message: '',
        type: 'info'
    });
    // Graph Params - LlamaIndex based
    const [graphParams, setGraphParams] = useState({
        extractor_type: 'simple' as 'simple' | 'dynamic' | 'schema',
        max_paths_per_chunk: 20, // Default changed to 20
        max_triplets_per_chunk: 20,
        num_workers: 4,
        generate_inverse_relations: true,
        allowed_entity_types: [] as string[],
        allowed_relation_types: [] as string[],
        enable_text_cleaning: false,  // Format char removal
        enable_subject_restoration: true,  // Restore omitted subjects (KR)
        enable_inference: false,  // Rule-based inference
        chunk_size: 300, // Matching Doc2Graph (500 chars approx)
        extraction_examples_yaml: '', // Few-Shot Examples (YAML)
        custom_prompt: '', // Custom Extraction Prompt
        enable_entity_normalization: true,  // Default TRUE
        normalization_algorithm: 'embedding' as 'embedding' | 'string' | 'llm',
        normalization_threshold: 0.85,
        max_sample_size: 50000, // Max chars for dictionary building
        enable_normalization_confirmation: false,  // User review before applying
    });

    const [isMaxPathsUnlimited, setIsMaxPathsUnlimited] = useState(false);

    // Dictionary Modal State
    const [showDictionaryModal, setShowDictionaryModal] = useState(false);
    const [dictionaryData, setDictionaryData] = useState<{
        preview_id: string;
        doc_id: string;
        file_path: string;
        entity_count: number;
        dictionary: any;
    } | null>(null);

    const fileInputRef = useRef<HTMLInputElement>(null);

    // Resume State Tracking
    const [resumedDocId, setResumedDocId] = useState<string | null>(null);
    const [isEntityExtracted, setIsEntityExtracted] = useState(false);

    // Chunking Strategy State (Moved from CreateKnowledgeBaseModal)
    const [strategy, setStrategy] = useState('fixed_size');
    const [chunkingConfig, setChunkingConfig] = useState({
        chunk_size: 300,
        chunk_overlap: 20,
        window_size: 3,
        chunk_sizes: [2048, 512, 128],
        buffer_size: 1,
        breakpoint_threshold: 95,
        // Legacy/Other
        parent_size: 2000,
        child_size: 500,
        parent_overlap: 0,
        child_overlap: 100,
    });

    useEffect(() => {
        if (isOpen) {
            // Reset state on open
            setFile(null);
            setPreviewData(null);
            setDictionaryData(null);
            setIsEntityExtracted(false);
            setIsUploading(false);
            setIsExtracting(false);
            setIsStepRunning(false);
            setResumedDocId(null);


            if (kbId) {
                loadKbConfig();
            }

            if (initialState) {
                console.log("Resuming from state:", initialState);
                if (initialState.docId) {
                    setResumedDocId(initialState.docId);

                    // Fetch full document details to ensure we have the file_path
                    docApi.list(kbId).then(res => {
                        const foundDoc = res.data.find((d: any) => d.id === initialState.docId);
                        if (foundDoc && foundDoc.file_path) {
                            console.log("Found resumed document:", foundDoc);
                            // Pre-fill path if not already in initialState
                            if (!initialState.filePath) {
                                initialState.filePath = foundDoc.file_path;
                            }
                        }
                    }).catch(err => console.error("Failed to fetch document details:", err));


                    // [Optimization] If data is missing (checking dictionary or triples), fetch it
                    const needsData = (initialState.step === 'ENTITY_EXTRACTED' && !initialState.data?.dictionary) ||
                        (initialState.step === 'TRIPLE_EXTRACTED' && !initialState.data?.triples);

                    if (needsData) {
                        console.log("Fetching heavy pipeline data on demand...");
                        docApi.getPipelineData(kbId, initialState.docId)
                            .then(res => {
                                const enrichedData = { ...initialState.data, ...res.data };
                                if (initialState.step === 'ENTITY_EXTRACTED') {
                                    setDictionaryData(enrichedData);
                                    setIsEntityExtracted(true);
                                    setShowDictionaryModal(true);
                                } else if (initialState.step === 'TRIPLE_EXTRACTED') {
                                    setPreviewData(enrichedData);
                                    setIsEntityExtracted(true);
                                    setShowPreviewModal(true);
                                }
                            })
                            .catch(err => console.error("Failed to fetch pipeline data:", err));
                    } else {
                        // Data already present (legacy or pre-loaded)
                        if (initialState.step === 'ENTITY_EXTRACTED' && initialState.data) {
                            setDictionaryData(initialState.data);
                            setIsEntityExtracted(true);
                            setShowDictionaryModal(true);
                        } else if (initialState.step === 'TRIPLE_EXTRACTED' && initialState.data) {
                            setPreviewData(initialState.data);
                            setIsEntityExtracted(true);
                            // Don't auto-show modal if just resuming to 'Continue' state, let user decide
                            // setShowPreviewModal(true);
                        }
                    }
                }
            }
        }
    }, [isOpen, kbId, initialState]);

    const loadKbConfig = async () => {
        try {
            const res = await kbApi.get(kbId);
            const data = res.data;
            setKbConfig(data);

            // Initialize graph params from KB config
            setGraphParams(prev => ({
                ...prev,
                graph_section_size: data.chunking_config?.graph_section_size || 2500,
                graph_section_overlap: data.chunking_config?.graph_section_overlap || 1000
            }));

            // Load extraction prompt from server and set as default
            try {
                const promptRes = await kbApi.getExtractionPrompt();
                const serverPrompt = promptRes.data?.content;
                if (serverPrompt && serverPrompt !== 'Prompt not found in DB.') {
                    setGraphParams(prev => ({ ...prev, custom_prompt: serverPrompt }));
                }
            } catch (promptErr) {
                console.warn('Failed to load extraction prompt from server:', promptErr);
            }
        } catch (err) {
            console.error("Failed to load KB config", err);
        }
    };

    if (!isOpen) return null;

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            setFile(e.target.files[0]);
        }
    };

    const handleUpload = async () => {
        // Standard Upload (Batch Run)
        if (!file && !resumedDocId) return;

        setIsUploading(true);
        try {
            const config = {
                ...graphParams,
                chunking_strategy: strategy,
                chunking_config: chunkingConfig,
                entity_dictionary: dictionaryData?.dictionary,
                execution_mode: 'batch'
            };

            if (file) {
                await docApi.upload(kbId, file, config);
                onUploadComplete();
                onClose();
            } else if (resumedDocId) {
                // If resuming but choosing Batch Run, we might trigger a re-process or just continue?
                // The current backend doesn't support 're-batch' easily from frontend without re-upload in this flow.
                // But for now, let's assume Batch Run is primarily for new uploads.
                alert("Cannot batch run without file. Please proceed with Extraction steps or re-upload.");
            }

        } catch (err) {
            console.error(err);
            setMessageDialog({
                isOpen: true,
                title: 'Upload Failed',
                message: 'An error occurred while uploading. Please try again.',
                type: 'error'
            });
        } finally {
            setIsUploading(false);
        }
    };

    const handlePreviewConfirm = async () => {
        if (!previewData) return;
        setIsExtracting(true);
        try {
            await extractionApi.confirm(previewData.preview_id, {
                enable_inference: graphParams.enable_inference,
                callback_url: "http://127.0.0.1:8000/api/knowledge-bases/ingest/callback"
            });
            onUploadComplete();
            onClose();
        } catch (err: any) {
            console.error('Confirm failed:', err);
            setMessageDialog({
                isOpen: true,
                title: 'Save Failed',
                message: err.response?.data?.detail || 'An error occurred while saving data.',
                type: 'error'
            });
        } finally {
            setIsExtracting(false);
        }
    };

    const handlePreviewDiscard = () => {
        setShowPreviewModal(false);
    };

    const isGraphEnabled = kbConfig && kbConfig.graph_backend && kbConfig.graph_backend !== 'none';

    // --- ACTION HANDLERS ---

    const handleExtractEntities = async (silent: boolean = false) => {
        if (!file && !resumedDocId) return null;

        setIsExtracting(true);
        try {
            let currentDocId = resumedDocId;
            let currentFilePath = "";

            if (!currentDocId && file) {
                const uploadRes = await docApi.upload(kbId, file, {
                    ...graphParams,
                    chunking_strategy: strategy,
                    chunking_config: chunkingConfig,
                    preview_only: true
                });
                currentDocId = uploadRes.data.id;
                currentFilePath = uploadRes.data.file_path || `/data/uploads/${kbId}/${currentDocId}_${file.name}`;
                // Update local state for subsequent steps
                setResumedDocId(currentDocId);
            } else if (resumedDocId) {
                if (file) {
                    const uploadRes = await docApi.upload(kbId, file, {
                        ...graphParams,
                        chunking_strategy: strategy,
                        chunking_config: chunkingConfig,
                        preview_only: true,
                        execution_mode: 'step'
                    });
                    currentDocId = uploadRes.data.id;
                    currentFilePath = uploadRes.data.file_path;
                } else {
                    // Try to guess path if not available
                    currentFilePath = initialState?.filePath || "";
                    if (!currentFilePath && initialState?.filename) {
                        currentFilePath = `/data/uploads/${kbId}/${resumedDocId}_${initialState.filename}`;
                    }
                }
            }

            if (!currentDocId) throw new Error("No Document ID");

            // Update status for real-time reflection
            await docApi.updatePipelineStatus(kbId, currentDocId, {
                status: 'EXTRACTING_ENTITIES',
                metadata: {}
            });

            console.log("Requesting Entity Dictionary Preview...");
            const res = await extractionApi.previewDictionary({
                kb_id: kbId,
                doc_id: currentDocId,
                file_path: currentFilePath,
                chunking: {
                    strategy: strategy,
                    ...chunkingConfig
                },
                sampling_size: graphParams.max_sample_size,
                callback_url: "http://127.0.0.1:8000/api/knowledge-bases/ingest/callback"
            });

            const dictData = {
                preview_id: res.data.preview_id,
                doc_id: currentDocId,
                file_path: currentFilePath,
                entity_count: res.data.entity_count,
                dictionary: res.data.dictionary
            };

            setDictionaryData(dictData);
            setIsEntityExtracted(true);

            await docApi.updatePipelineStatus(kbId, currentDocId, {
                status: 'ENTITY_EXTRACTED',
                metadata: {
                    ...dictData
                }
            });

            if (!silent) {
                setShowDictionaryModal(true);
            }
            return dictData;

        } catch (err: any) {
            console.error('Entity Extraction failed:', err);
            setMessageDialog({
                isOpen: true,
                title: 'Extraction Failed',
                message: err.response?.data?.detail || 'Failed to extract entities.',
                type: 'error'
            });
            setIsEntityExtracted(false);
            return null;
        } finally {
            setIsExtracting(false);
        }
    };

    const handleExtractTriples = async (silent: boolean = false, entityDataOverride?: any) => {
        if (!kbId) return null;

        setIsExtracting(true);
        try {
            // Use override or state
            const dictionaryInfo = entityDataOverride || dictionaryData;

            let currentDocId = dictionaryInfo?.doc_id || resumedDocId;
            let currentFilePath = dictionaryInfo?.file_path || initialState?.filePath || "";

            if (!currentFilePath) {
                const effectiveFileName = file?.name || initialState?.filename;
                if (currentDocId && effectiveFileName) {
                    currentFilePath = `/data/uploads/${kbId}/${currentDocId}_${effectiveFileName}`;
                }
            }

            if (file && (!currentDocId || !currentFilePath)) {
                const uploadRes = await docApi.upload(kbId, file, {
                    ...graphParams,
                    chunking_strategy: strategy,
                    chunking_config: chunkingConfig,
                    preview_only: true
                });
                currentDocId = uploadRes.data.id;
                currentFilePath = uploadRes.data.file_path || `/data/uploads/${kbId}/${currentDocId}_${file.name}`;
            }

            if (!currentDocId) {
                throw new Error("Missing Document ID. Please upload a file first.");
            }

            // Update status for real-time reflection
            await docApi.updatePipelineStatus(kbId, currentDocId, {
                status: 'EXTRACTING_TRIPLES',
                metadata: {}
            });

            console.log("Requesting Triple Extraction Preview...", { currentDocId, currentFilePath });
            const res = await extractionApi.preview({
                kb_id: kbId,
                doc_id: currentDocId,
                file_path: currentFilePath || "RESUME_AUTO_LOOKUP",
                chunking: {
                    strategy: strategy,
                    ...chunkingConfig
                },
                graph: {
                    extractor_type: graphParams.extractor_type,
                    max_paths_per_chunk: graphParams.max_paths_per_chunk,
                    max_triplets_per_chunk: graphParams.max_triplets_per_chunk,
                    num_workers: graphParams.num_workers,
                    generate_inverse_relations: graphParams.generate_inverse_relations,
                },
                graph_store: kbConfig?.graph_backend === 'neo4j' ? 'neo4j' : 'fuseki',
                enable_text_cleaning: graphParams.enable_text_cleaning,
                enable_subject_restoration: graphParams.enable_subject_restoration,
                enable_entity_normalization: graphParams.enable_entity_normalization,
                extraction_examples_yaml: graphParams.extraction_examples_yaml || undefined,
                custom_prompt: graphParams.custom_prompt || undefined,
                normalization_algorithm: graphParams.normalization_algorithm,
                normalization_threshold: graphParams.normalization_threshold,
                entity_dictionary: dictionaryInfo?.dictionary,
                callback_url: "http://127.0.0.1:8000/api/knowledge-bases/ingest/callback"
            });

            const tripleData = {
                preview_id: res.data.preview_id,
                doc_id: currentDocId,
                triples: res.data.triples,
                node_count: res.data.node_count,
                stats: res.data.stats,
            };

            setPreviewData(tripleData);

            await docApi.updatePipelineStatus(kbId, currentDocId, {
                status: 'TRIPLE_EXTRACTED',
                metadata: {
                    ...tripleData,
                    file_path: currentFilePath
                }
            });

            if (!silent) {
                setShowPreviewModal(true);
            }
            return tripleData;

        } catch (err: any) {
            console.error('Triple Extraction failed:', err);
            const errorMsg = err.response?.data?.detail || err.message || 'Failed to extract triples.';

            if (typeof errorMsg === 'string' && (errorMsg.includes('No such file') || errorMsg.includes('File not found'))) {
                setMessageDialog({
                    isOpen: true,
                    title: 'Original File Missing',
                    message: 'The original file could not be found on the server. Please click "Select File" to upload it again, then retry extraction.',
                    type: 'error'
                });
            } else {
                setMessageDialog({
                    isOpen: true,
                    title: 'Extraction Failed',
                    message: errorMsg,
                    type: 'error'
                });
            }
            return null;
        } finally {
            setIsExtracting(false);
        }
    };

    const handleContinue = async () => {
        // Step 2: From Entity Extracted -> Extract Triples
        if (dictionaryData && !previewData) {
            console.log("handleContinue: Resuming from Entity Extraction -> Extract Triples");
            await handleExtractTriples(true); // Silent run
            onUploadComplete();
            onClose();
            return;
        }

        // Step 3: From Triple Extracted -> Confirm
        if (previewData) {
            console.log("handleContinue: Resuming from Triple Extraction -> Confirm");
            await handlePreviewConfirm();
            return;
        }
    };

    const handleStepRun = async () => {
        if (!file && !resumedDocId) return;
        setIsStepRunning(true);

        try {
            // 1. Run Entity Extraction (Silent)
            // Step Run now STOPS after Entity Extraction.
            const entityResult = await handleExtractEntities(true);
            if (!entityResult) throw new Error("Entity Extraction failed");

            // 3. Close (Enter Waiting State)
            onUploadComplete();
            onClose();

        } catch (error) {
            console.error("Step Run failed:", error);
        } finally {
            setIsStepRunning(false);
        }
    };

    return (
        <>
            <div style={{
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                backgroundColor: 'rgba(0,0,0,0.5)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                zIndex: 50
            }} onClick={onClose}>

                <div className="card" style={{
                    width: '100%',
                    maxWidth: '600px',
                    maxHeight: '90vh',
                    overflow: 'hidden',
                    display: 'flex',
                    flexDirection: 'column',
                    padding: 0
                }} onClick={(e) => e.stopPropagation()}>
                    <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        padding: '1.5rem',
                        borderBottom: '1px solid #e2e8f0',
                        backgroundColor: 'white'
                    }}>
                        <h2 style={{ margin: 0, fontSize: '1.25rem' }}>Upload Document</h2>
                        <div style={{ display: 'flex', gap: '1rem' }}>
                            {/* RESUME MODE: Show Continue if we are in waiting state (Have docID, and either dictionary or triples) */}
                            {resumedDocId && (
                                <button
                                    className="btn btn-primary"
                                    onClick={handleContinue}
                                    disabled={isUploading || isExtracting || isStepRunning}
                                >
                                    Continue
                                </button>
                            )}

                            {/* STANDARD MODE: Show Step Run & Batch Run (Upload) - Only if NOT resuming */}
                            {!resumedDocId && (
                                <>
                                    {isGraphEnabled && (
                                        <button
                                            className="btn"
                                            onClick={handleStepRun}
                                            disabled={(!file && !resumedDocId) || isUploading || isExtracting || isStepRunning}
                                            style={{
                                                border: '1px solid #3b82f6',
                                                color: '#3b82f6',
                                                background: 'white'
                                            }}
                                        >
                                            {isStepRunning ? 'Processing Step Run...' : 'Step Run'}
                                        </button>
                                    )}

                                    <button
                                        className="btn btn-primary"
                                        onClick={handleUpload}
                                        disabled={(!file && !resumedDocId) || isUploading || isExtracting || isStepRunning}
                                    >
                                        {isUploading ? 'Uploading...' : 'Batch Run'}
                                    </button>
                                </>
                            )}
                            <button className="btn" onClick={onClose} disabled={isUploading || isExtracting || isStepRunning}>Cancel</button>
                        </div>
                    </div>

                    <div style={{
                        padding: '1.5rem',
                        overflowY: 'auto',
                        flex: 1
                    }}>
                        <div style={{ marginBottom: '2rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>Select File</label>
                            <div
                                style={{
                                    border: '2px dashed var(--border)',
                                    borderRadius: '8px',
                                    padding: '2rem',
                                    textAlign: 'center',
                                    cursor: 'pointer',
                                    background: '#fafafa',
                                    opacity: resumedDocId ? 0.6 : 1,
                                    pointerEvents: resumedDocId ? 'none' : 'auto'
                                }}
                                onClick={() => fileInputRef.current?.click()}
                            >
                                <input
                                    type="file"
                                    ref={fileInputRef}
                                    style={{ display: 'none' }}
                                    onChange={(e) => {
                                        handleFileChange(e);
                                        if (!resumedDocId) {
                                            setIsEntityExtracted(false);
                                            setResumedDocId(null);
                                            setDictionaryData(null);
                                            setPreviewData(null);
                                        }
                                    }}
                                    accept=".txt,.pdf,.md"
                                    disabled={!!resumedDocId}
                                />
                                {file ? (
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', color: 'var(--primary)' }}>
                                        <FileText size={24} />
                                        <span style={{ fontWeight: 500 }}>{file.name}</span>
                                    </div>
                                ) : (
                                    <div style={{ color: 'var(--text-secondary)' }}>
                                        {resumedDocId ? (
                                            <div style={{ color: 'var(--primary)', fontWeight: 600 }}>
                                                Resuming Document Processing... (File on server)
                                            </div>
                                        ) : (
                                            <>
                                                <Upload size={32} style={{ marginBottom: '0.5rem' }} />
                                                <p style={{ margin: 0 }}>Click to upload PDF, TXT, or MD</p>
                                            </>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Chunking Strategy Section */}
                        <div style={{ marginBottom: '2rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.8rem', fontWeight: 600, color: '#334155' }}>Chunking Strategy</label>

                            <div style={{ marginBottom: '1rem' }}>
                                <select
                                    className="input"
                                    value={strategy}
                                    onChange={(e) => setStrategy(e.target.value)}
                                    style={{
                                        width: '100%',
                                        padding: '0.75rem',
                                        borderRadius: '8px',
                                        border: '1px solid #e2e8f0',
                                        backgroundColor: '#fff',
                                        fontSize: '0.95rem',
                                        color: '#1e293b',
                                        cursor: 'pointer'
                                    }}
                                >
                                    {[
                                        { id: 'fixed_size', name: 'Fixed Size (Standard)' },
                                        { id: 'sliding_window', name: 'Sliding Window (Contextual)' },
                                        { id: 'hierarchical', name: 'Hierarchical (Parent-Child)' },
                                        { id: 'semantic', name: 'Semantic (Meaning-based)' },
                                        { id: 'markdown', name: 'Markdown (Structure-based)' },
                                        { id: 'hybrid', name: 'Hybrid (Markdown + Fixed)' }
                                    ]
                                        .filter(s => !(isGraphEnabled && s.id === 'semantic'))
                                        .map(s => (
                                            <option key={s.id} value={s.id}>{s.name}</option>
                                        ))}
                                </select>
                                <div style={{ fontSize: '0.8rem', color: '#64748b', marginTop: '0.5rem', paddingLeft: '0.2rem' }}>
                                    {strategy === 'fixed_size' && "Standard fixed-length chunks. Best for general use."}
                                    {strategy === 'sliding_window' && "Captures surrounding context for each chunk."}
                                    {strategy === 'hierarchical' && "Creates parent-child structure for detailed retrieval."}
                                    {strategy === 'semantic' && "Splits text based on semantic meaning changes."}
                                    {strategy === 'markdown' && "Splits based on document headers (#, ##)."}
                                    {strategy === 'hybrid' && "Combines structural splitting with size limits."}
                                </div>
                            </div>

                            {/* Configuration Panel for Selected Strategy */}
                            <div style={{ padding: '1.25rem', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px' }}>
                                {strategy === 'fixed_size' && (
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                        <div>
                                            <LabelWithTooltip label="Chunk Size" tooltip="Characters per chunk" />
                                            <input type="number" className="input" value={chunkingConfig.chunk_size} onChange={(e) => setChunkingConfig({ ...chunkingConfig, chunk_size: parseInt(e.target.value) })} />
                                        </div>
                                        <div>
                                            <LabelWithTooltip label="Overlap" tooltip="Character overlap" />
                                            <input type="number" className="input" value={chunkingConfig.chunk_overlap} onChange={(e) => setChunkingConfig({ ...chunkingConfig, chunk_overlap: parseInt(e.target.value) })} />
                                        </div>
                                    </div>
                                )}
                                {strategy === 'sliding_window' && (
                                    <div>
                                        <LabelWithTooltip label="Window Size" tooltip="Number of sentences around" />
                                        <input type="number" className="input" value={chunkingConfig.window_size} onChange={(e) => setChunkingConfig({ ...chunkingConfig, window_size: parseInt(e.target.value) })} />
                                    </div>
                                )}
                                {strategy === 'hierarchical' && (
                                    <div>
                                        <LabelWithTooltip label="Levels (Large->Small)" tooltip="e.g., 2048, 512, 128" />
                                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                                            {chunkingConfig.chunk_sizes.map((size, idx) => (
                                                <input key={idx} type="number" className="input" value={size}
                                                    onChange={(e) => {
                                                        const newSizes = [...chunkingConfig.chunk_sizes];
                                                        newSizes[idx] = parseInt(e.target.value);
                                                        setChunkingConfig({ ...chunkingConfig, chunk_sizes: newSizes });
                                                    }} />
                                            ))}
                                        </div>
                                    </div>
                                )}
                                {strategy === 'semantic' && (
                                    <div>
                                        <LabelWithTooltip label="Breakpoint Percentile" tooltip="Threshold for splitting (50-99)" />
                                        <input
                                            type="number" className="input"
                                            value={chunkingConfig.breakpoint_threshold}
                                            onChange={(e) => setChunkingConfig({ ...chunkingConfig, breakpoint_threshold: parseInt(e.target.value) })}
                                            min={50} max={99}
                                        />
                                    </div>
                                )}
                                {(strategy === 'markdown' || strategy === 'hybrid') && (
                                    <div style={{ fontSize: '0.85rem', color: '#64748b' }}>
                                        Automatically splits by document headers (#, ##).
                                        {strategy === 'hybrid' && " Fallback to fixed size for large sections."}
                                    </div>
                                )}
                            </div>
                        </div>

                        {isGraphEnabled && (
                            <GraphExtractionSettings
                                graphParams={graphParams}
                                onParamsChange={setGraphParams}
                                onManageExamples={() => setShowExampleModal(true)}
                                onEditPrompt={() => setShowPromptModal(true)}
                                showEntitySample={true}
                            />
                        )}

                    </div>


                </div>
            </div>

            <PromptDialog
                isOpen={showExampleModal}
                onClose={() => setShowExampleModal(false)}
                initialPrompt={graphParams.extraction_examples_yaml}
                onSave={(yaml) => setGraphParams(prev => ({ ...prev, extraction_examples_yaml: yaml }))}
                mode="extraction_examples"
            />
            <PromptDialog
                isOpen={showPromptModal}
                onClose={() => setShowPromptModal(false)}
                initialPrompt={graphParams.custom_prompt}
                onSave={(prompt) => setGraphParams(prev => ({ ...prev, custom_prompt: prompt }))}
                mode="extraction_prompt"
            />

            <MessageDialog
                isOpen={messageDialog.isOpen}
                title={messageDialog.title}
                message={messageDialog.message}
                type={messageDialog.type}
                onClose={() => setMessageDialog({ ...messageDialog, isOpen: false })}
            />
            {
                previewData && (
                    <ExtractionPreviewModal
                        isOpen={showPreviewModal}
                        onClose={() => setShowPreviewModal(false)}
                        previewId={previewData.preview_id}
                        triples={previewData.triples}
                        nodeCount={previewData.node_count}
                        isLoading={isExtracting}
                        onConfirm={handlePreviewConfirm}
                        onDiscard={handlePreviewDiscard}
                    />
                )
            }
            {
                dictionaryData && (
                    <EntityDictionaryModal
                        isOpen={showDictionaryModal}
                        onClose={() => setShowDictionaryModal(false)}
                        dictionary={dictionaryData.dictionary}
                        entityCount={dictionaryData.entity_count}
                        isLoading={isExtracting}
                    />
                )
            }
        </>
    );
}
