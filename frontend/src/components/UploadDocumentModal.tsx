import React, { useState, useRef, useEffect } from 'react';
import { Upload, X, FileText, Settings, Database, AlertCircle, Check, Info, Eye } from 'lucide-react';
import { docApi, kbApi, extractionApi } from '../services/api';
import MessageDialog from './MessageDialog';
import PromptDialog from './PromptDialog';
import ExtractionPreviewModal from './ExtractionPreviewModal';
import EntityDictionaryModal from './EntityDictionaryModal';

interface UploadDocumentModalProps {
    isOpen: boolean;
    onClose: () => void;
    kbId: string;
    onUploadComplete: () => void;
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

// NOTE: ExtractionRuleModal and EditPromptModal have been removed.
// Graph extraction is now handled by LlamaIndex in the Ingest Service.

export default function UploadDocumentModal({ isOpen, onClose, kbId, onUploadComplete }: UploadDocumentModalProps) {
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
    } | null>(null);

    const [messageDialog, setMessageDialog] = useState<{ isOpen: boolean; title: string; message: string; type: 'info' | 'success' | 'error' }>({
        isOpen: false,
        title: '',
        message: '',
        type: 'info'
    });

    // Graph Params - LlamaIndex based
    const [graphParams, setGraphParams] = useState({
        extractor_type: 'simple' as 'simple' | 'dynamic' | 'schema',
        max_paths_per_chunk: 10,
        max_triplets_per_chunk: 20,
        num_workers: 4,
        generate_inverse_relations: true,
        allowed_entity_types: [] as string[],
        allowed_relation_types: [] as string[],
        enable_text_cleaning: false,  // Format char removal
        enable_subject_restoration: true,  // Restore omitted subjects (Korean)
        enable_inference: false,  // Rule-based inference
        extraction_examples_yaml: '', // Few-Shot Examples (YAML)
        custom_prompt: '', // Custom Extraction Prompt
        enable_entity_normalization: false,  // Merge similar entities
        normalization_algorithm: 'embedding' as 'embedding' | 'string' | 'llm',
        normalization_threshold: 0.85,
        max_sample_size: 50000, // Max chars for dictionary building
        enable_normalization_confirmation: false,  // User review before applying
    });



    // Dictionary Modal State
    const [showDictionaryModal, setShowDictionaryModal] = useState(false);
    const [dictionaryData, setDictionaryData] = useState<{
        preview_id: string;
        doc_id: string;
        entity_count: number;
        dictionary: any;
    } | null>(null);

    const fileInputRef = useRef<HTMLInputElement>(null);


    useEffect(() => {
        if (isOpen && kbId) {
            loadKbConfig();
        }
    }, [isOpen, kbId]);

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
        if (!file) return;
        setIsUploading(true);
        try {
            const config = {
                ...graphParams
            };

            await docApi.upload(kbId, file, config);
            onUploadComplete();
            onClose();
            setFile(null);
        } catch (err) {
            console.error(err);
            setMessageDialog({
                isOpen: true,
                title: 'Upload Failed',
                message: 'An error occurred while uploading the document. Please try again.',
                type: 'error'
            });
        } finally {
            setIsUploading(false);
        }
    };

    const handleExtract = async () => {
        if (!file) return;
        setIsExtracting(true);
        try {
            // First upload file to get file_path (via standard upload but we need the path)
            // For now, we'll use the docApi to create a pending document and get its path
            const formData = new FormData();
            formData.append('file', file);

            // Upload file to backend first to get file_path
            const uploadRes = await docApi.upload(kbId, file, { ...graphParams, preview_only: true });
            const docId = uploadRes.data.id;
            const filePath = uploadRes.data.file_path || `/data/uploads/${kbId}/${file.name}`;

            if (graphParams.enable_entity_normalization) {
                // [NEW] Call Dictionary Preview API (Doc2Graph Phase 1 Only)
                console.log("Requesting Entity Dictionary Preview...");
                const res = await extractionApi.previewDictionary({
                    kb_id: kbId,
                    doc_id: docId,
                    file_path: filePath,
                    chunking: {
                        strategy: 'fixed_size',
                        chunk_size: 1024,
                        chunk_overlap: 20,
                    }
                });

                setDictionaryData({
                    preview_id: res.data.preview_id,
                    doc_id: docId,
                    entity_count: res.data.entity_count,
                    dictionary: res.data.dictionary
                });

                setShowDictionaryModal(true);

            } else {
                // Existing Triple Extraction Preview
                const res = await extractionApi.preview({
                    kb_id: kbId,
                    doc_id: docId,
                    file_path: filePath,
                    chunking: {
                        strategy: 'fixed_size',
                        chunk_size: 1024,
                        chunk_overlap: 20,
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
                    // Normalization disabled here since we handled it in separate branch if needed
                    // But actually, standard preview might verify normalization *result* (triples).
                    // User request: "Extract button shows list of entities ONLY".
                    // So if normalization is ON, we show Dictionary Modal.
                    // If normalization is OFF, we show Triple Preview Modal.
                    enable_entity_normalization: false,
                    extraction_examples_yaml: graphParams.extraction_examples_yaml || undefined,
                    custom_prompt: graphParams.custom_prompt || undefined,
                });

                setPreviewData({
                    preview_id: res.data.preview_id,
                    doc_id: docId,
                    triples: res.data.triples,
                    node_count: res.data.node_count,
                });
                setShowPreviewModal(true);
            }

        } catch (err: any) {
            console.error('Extract failed:', err);
            setMessageDialog({
                isOpen: true,
                title: '추출 실패',
                message: err.response?.data?.detail || '트리플 추출 중 오류가 발생했습니다.',
                type: 'error'
            });
        } finally {
            setIsExtracting(false);
        }
    };

    const handlePreviewConfirm = async () => {
        if (!previewData) return;
        setIsExtracting(true);
        try {
            await extractionApi.confirm(previewData.preview_id, {
                enable_inference: graphParams.enable_inference,
            });
            onUploadComplete();
            onClose();
            setFile(null);
            setPreviewData(null);
            setShowPreviewModal(false);
        } catch (err: any) {
            console.error('Confirm failed:', err);
            setMessageDialog({
                isOpen: true,
                title: '저장 실패',
                message: err.response?.data?.detail || '데이터 저장 중 오류가 발생했습니다.',
                type: 'error'
            });
        } finally {
            setIsExtracting(false);
        }
    };

    const handlePreviewDiscard = async () => {
        if (!previewData) return;
        try {
            // 1. Discard preview cache
            await extractionApi.discard(previewData.preview_id);

            // 2. Delete the created document record
            await docApi.delete(kbId, previewData.doc_id);
            console.log(`Document ${previewData.doc_id} deleted after preview cancel`);
        } catch (err) {
            console.error('Discard cleanup failed:', err);
        }
        setPreviewData(null);
        setShowPreviewModal(false);
    };

    const isGraphEnabled = kbConfig && kbConfig.graph_backend && kbConfig.graph_backend !== 'none';
    const chunkingStrategy = kbConfig?.chunking_strategy || 'size';

    return (
        <>
            <div style={{
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                backgroundColor: 'rgba(0,0,0,0.5)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                zIndex: 50
            }} onClick={onClose}>
                <div className="card" style={{ width: '100%', maxWidth: '600px', maxHeight: '90vh', overflow: 'auto' }} onClick={(e) => e.stopPropagation()}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                        <h2 style={{ margin: 0 }}>Upload Document</h2>
                        <button className="btn" onClick={onClose} style={{ padding: '0.5rem' }}>
                            <X size={20} />
                        </button>
                    </div>

                    <div style={{ marginBottom: '2rem' }}>
                        <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>Select File</label>
                        <div
                            style={{
                                border: '2px dashed var(--border)',
                                borderRadius: '8px',
                                padding: '2rem',
                                textAlign: 'center',
                                cursor: 'pointer',
                                background: '#fafafa'
                            }}
                            onClick={() => fileInputRef.current?.click()}
                        >
                            <input
                                type="file"
                                ref={fileInputRef}
                                style={{ display: 'none' }}
                                onChange={handleFileChange}
                                accept=".txt,.pdf,.md"
                            />
                            {file ? (
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', color: 'var(--primary)' }}>
                                    <FileText size={24} />
                                    <span style={{ fontWeight: 500 }}>{file.name}</span>
                                </div>
                            ) : (
                                <div style={{ color: 'var(--text-secondary)' }}>
                                    <Upload size={32} style={{ marginBottom: '0.5rem' }} />
                                    <p style={{ margin: 0 }}>Click to upload PDF, TXT, or MD</p>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Graph Settings Section - 3 Column Layout */}
                    {isGraphEnabled && (
                        <div style={{ marginBottom: '1.5rem', background: '#eff6ff', padding: '1.25rem', borderRadius: '12px', border: '1px solid #bfdbfe' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1.25rem', color: '#3b82f6', fontWeight: 600 }}>
                                <Database size={18} />
                                <span>Graph Extraction Settings (LlamaIndex)</span>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
                                {/* Column 1: Config Parameters */}
                                <div>
                                    <h4 style={{ margin: '0 0 1rem 0', fontSize: '0.9rem', color: '#475569' }}>Configuration</h4>

                                    <LabelWithTooltip label="Extractor Type" tooltip="Select LlamaIndex extractor type" />
                                    <select
                                        className="input"
                                        value={graphParams.extractor_type}
                                        onChange={(e) => setGraphParams({ ...graphParams, extractor_type: e.target.value as 'simple' | 'dynamic' | 'schema' })}
                                        style={{ width: '100%', padding: '0.5rem', fontSize: '0.85rem', marginBottom: '1rem' }}
                                    >
                                        <option value="simple">Simple LLM (Default)</option>
                                        <option value="dynamic">Dynamic LLM</option>
                                        <option value="schema">Schema-based</option>
                                    </select>

                                    {graphParams.extractor_type === 'simple' && (
                                        <div style={{ marginBottom: '1rem' }}>
                                            <LabelWithTooltip label={`Max Paths: ${graphParams.max_paths_per_chunk}`} tooltip="Max triples per chunk" />
                                            <input
                                                type="range" min="5" max="50" step="5"
                                                value={graphParams.max_paths_per_chunk}
                                                onChange={(e) => setGraphParams({ ...graphParams, max_paths_per_chunk: parseInt(e.target.value) })}
                                                style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                                            />
                                        </div>
                                    )}

                                    {graphParams.extractor_type === 'dynamic' && (
                                        <div style={{ marginBottom: '1rem' }}>
                                            <LabelWithTooltip label={`Max Triplets: ${graphParams.max_triplets_per_chunk}`} tooltip="Max triples per chunk" />
                                            <input
                                                type="range" min="10" max="100" step="10"
                                                value={graphParams.max_triplets_per_chunk}
                                                onChange={(e) => setGraphParams({ ...graphParams, max_triplets_per_chunk: parseInt(e.target.value) })}
                                                style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                                            />
                                        </div>
                                    )}

                                    <div>
                                        <LabelWithTooltip label={`Workers: ${graphParams.num_workers}`} tooltip="Number of parallel workers" />
                                        <input
                                            type="range" min="1" max="8" step="1"
                                            value={graphParams.num_workers}
                                            onChange={(e) => setGraphParams({ ...graphParams, num_workers: parseInt(e.target.value) })}
                                            style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                                        />
                                    </div>
                                </div>

                                {/* Column 2: Checkbox Options */}
                                <div>
                                    <h4 style={{ margin: '0 0 1rem 0', fontSize: '0.9rem', color: '#475569' }}>Options</h4>

                                    {/* [REMOVED] Generate Inverse Relations checkbox
                                        Inverse relations are now inferred at query time, not stored physically.
                                    */}

                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', marginBottom: '1rem' }}>
                                        <input
                                            type="checkbox"
                                            checked={graphParams.enable_text_cleaning}
                                            onChange={(e) => setGraphParams({ ...graphParams, enable_text_cleaning: e.target.checked })}
                                            style={{ width: '1.1rem', height: '1.1rem', accentColor: '#3b82f6', flexShrink: 0 }}
                                        />
                                        <div>
                                            <span style={{ color: '#334155', fontWeight: 500, fontSize: '0.9rem' }}>Clean Text</span>
                                            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Remove bullets, numbers</div>
                                        </div>
                                    </label>

                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', marginBottom: '1rem' }}>
                                        <input
                                            type="checkbox"
                                            checked={graphParams.enable_subject_restoration}
                                            onChange={(e) => setGraphParams({ ...graphParams, enable_subject_restoration: e.target.checked })}
                                            style={{ width: '1.1rem', height: '1.1rem', accentColor: '#3b82f6', flexShrink: 0 }}
                                        />
                                        <div>
                                            <span style={{ color: '#334155', fontWeight: 500, fontSize: '0.9rem' }}>Subject Restoration</span>
                                            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Resolve omitted subjects (KR)</div>
                                        </div>
                                    </label>

                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', marginBottom: '1rem' }}>
                                        <input
                                            type="checkbox"
                                            checked={graphParams.enable_entity_normalization}
                                            onChange={(e) => setGraphParams({ ...graphParams, enable_entity_normalization: e.target.checked })}
                                            style={{ width: '1.1rem', height: '1.1rem', accentColor: '#3b82f6', flexShrink: 0 }}
                                        />
                                        <div>
                                            <span style={{ color: '#334155', fontWeight: 500, fontSize: '0.9rem' }}>Entity Normalization</span>
                                            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Merge similar entities (e.g., 성기훈, 기훈 → 성기훈)</div>
                                        </div>
                                    </label>

                                    {/* Algorithm Selection - Only shown when Entity Normalization is enabled */}
                                    {graphParams.enable_entity_normalization && (
                                        <div style={{ marginLeft: '1.6rem', marginBottom: '1rem', padding: '0.75rem', background: '#f8fafc', borderRadius: '6px', border: '1px solid #e2e8f0' }}>
                                            <LabelWithTooltip label="Normalization Algorithm" tooltip="Choose similarity algorithm for entity matching" />
                                            <select
                                                className="input"
                                                value={graphParams.normalization_algorithm}
                                                onChange={(e) => setGraphParams({ ...graphParams, normalization_algorithm: e.target.value as 'embedding' | 'string' | 'llm' })}
                                                style={{ width: '100%', padding: '0.5rem', fontSize: '0.85rem', marginBottom: '0.75rem' }}
                                            >
                                                <option value="embedding">Embedding Similarity (Recommended)</option>
                                                <option value="string">String Similarity (Fast)</option>
                                                <option value="llm">LLM-based (Accurate)</option>
                                            </select>

                                            <LabelWithTooltip
                                                label={`Similarity Threshold: ${graphParams.normalization_threshold.toFixed(2)}`}
                                                tooltip="Higher = stricter matching (0.70-0.95)"
                                            />
                                            <input
                                                type="range"
                                                min="0.70"
                                                max="0.95"
                                                step="0.05"
                                                value={graphParams.normalization_threshold}
                                                onChange={(e) => setGraphParams({ ...graphParams, normalization_threshold: parseFloat(e.target.value) })}
                                                style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                                            />

                                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', marginTop: '0.75rem' }}>
                                                <input
                                                    type="checkbox"
                                                    checked={graphParams.enable_normalization_confirmation}
                                                    onChange={(e) => setGraphParams({ ...graphParams, enable_normalization_confirmation: e.target.checked })}
                                                    style={{ width: '1rem', height: '1rem', accentColor: '#3b82f6', flexShrink: 0 }}
                                                />
                                                <div>
                                                    <span style={{ color: '#334155', fontWeight: 500, fontSize: '0.85rem' }}>User Confirmation</span>
                                                    <div style={{ fontSize: '0.7rem', color: '#64748b' }}>Review merge suggestions before applying</div>
                                                </div>
                                            </label>
                                        </div>
                                    )}

                                </div>

                                {/* Column 3: Customization Actions */}
                                <div>
                                    <h4 style={{ margin: '0 0 1rem 0', fontSize: '0.9rem', color: '#475569' }}>Customization</h4>

                                    <button
                                        className="btn"
                                        style={{ width: '100%', marginBottom: '0.75rem', justifyContent: 'center', background: '#fff', border: '1px solid #cbd5e1' }}
                                        onClick={() => setShowExampleModal(true)}
                                    >
                                        Manage Examples
                                    </button>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'default', marginBottom: '1.25rem', justifyContent: 'center' }}>
                                        <input
                                            type="checkbox"
                                            checked={!!graphParams.extraction_examples_yaml}
                                            readOnly
                                            style={{ width: '0.9rem', height: '0.9rem', accentColor: '#3b82f6' }}
                                        />
                                        <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Examples Added</span>
                                    </label>

                                    <button
                                        className="btn"
                                        style={{ width: '100%', marginBottom: '0.75rem', justifyContent: 'center', background: '#fff', border: '1px solid #cbd5e1' }}
                                        onClick={() => setShowPromptModal(true)}
                                    >
                                        Edit Extraction Prompt
                                    </button>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'default', justifyContent: 'center' }}>
                                        <input
                                            type="checkbox"
                                            checked={!!graphParams.custom_prompt}
                                            readOnly
                                            style={{ width: '0.9rem', height: '0.9rem', accentColor: '#3b82f6' }}
                                        />
                                        <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Custom Prompt Active</span>
                                    </label>
                                </div>
                            </div>
                        </div>
                    )}


                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                        <button className="btn" onClick={onClose} disabled={isUploading || isExtracting}>Cancel</button>
                        {isGraphEnabled && (
                            <button
                                className="btn"
                                onClick={handleExtract}
                                disabled={!file || isUploading || isExtracting}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem',
                                    border: '1px solid #3b82f6',
                                    color: '#3b82f6'
                                }}
                            >
                                <Eye size={16} />
                                {isExtracting ? 'Extracting...' : 'Extract'}
                            </button>
                        )}
                        <button
                            className="btn btn-primary"
                            onClick={handleUpload}
                            disabled={!file || isUploading || isExtracting}
                        >
                            {isUploading ? 'Uploading...' : 'Upload'}
                        </button>
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

            {previewData && (
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
            )}

            {dictionaryData && (
                <EntityDictionaryModal
                    isOpen={showDictionaryModal}
                    onClose={() => setShowDictionaryModal(false)}
                    dictionary={dictionaryData.dictionary}
                    entityCount={dictionaryData.entity_count}
                    isLoading={isExtracting}
                />
            )}
        </>

    );
}
