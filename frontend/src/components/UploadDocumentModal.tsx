import React, { useState, useRef, useEffect } from 'react';
import { Upload, FileText, Type, Wand2 } from 'lucide-react';
import { docApi, kbApi } from '../services/api';
import MessageDialog from './MessageDialog';
import PromptDialog from './PromptDialog';
import GraphExtractionSettings from './GraphExtractionSettings';
import ModelSelector, { DEFAULT_LLM_CONFIG } from './ModelSelector';
import { useModelSettings } from '../hooks/useModelSettings';

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
                    width: '14px', height: '14px', borderRadius: '50%', border: '1px solid #94a3b8',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '9px', color: '#94a3b8', fontWeight: 'bold', flexShrink: 0, lineHeight: 1
                }}>i</div>
                {show && (
                    <div style={{
                        position: 'absolute', bottom: '120%', left: '0',
                        backgroundColor: '#333', color: '#fff', padding: '0.5rem 0.75rem',
                        borderRadius: '4px', fontSize: '0.75rem', whiteSpace: 'normal',
                        width: '200px', zIndex: 100, boxShadow: '0 2px 8px rgba(0,0,0,0.2)', pointerEvents: 'none'
                    }}>
                        {tooltip}
                        <div style={{ position: 'absolute', top: '100%', left: '10px', borderWidth: '5px', borderStyle: 'solid', borderColor: '#333 transparent transparent transparent' }}></div>
                    </div>
                )}
            </div>
        </div>
    );
};

type InputTab = 'file' | 'text';

export default function UploadDocumentModal({ isOpen, onClose, kbId, onUploadComplete }: UploadDocumentModalProps) {
    const [inputTab, setInputTab] = useState<InputTab>('file');
    const [file, setFile] = useState<File | null>(null);
    const [textTitle, setTextTitle] = useState('');
    const [textContent, setTextContent] = useState('');
    const [isUploading, setIsUploading] = useState(false);
    const [kbConfig, setKbConfig] = useState<any>(null);

    const [showExampleModal, setShowExampleModal] = useState(false);
    const [showPromptModal, setShowPromptModal] = useState(false);

    const [messageDialog, setMessageDialog] = useState<{ isOpen: boolean; title: string; message: string; type: 'info' | 'success' | 'error' }>({
        isOpen: false, title: '', message: '', type: 'info'
    });

    // 중앙 관리 모델 설정 (localStorage, 사용자별)
    const { settings, updateSetting } = useModelSettings();

    const [graphParams, setGraphParams] = useState({
        extractor_type: 'simple' as 'simple' | 'dynamic' | 'schema',
        max_paths_per_chunk: 20,
        max_triplets_per_chunk: 20,
        num_workers: 4,
        generate_inverse_relations: true,
        allowed_entity_types: [] as string[],
        allowed_relation_types: [] as string[],
        chunk_size: 300,
        extraction_examples_yaml: '',
        custom_prompt: '',
        enable_entity_normalization: true,
        enable_entity_typing: false,
        normalization_algorithm: 'embedding' as 'embedding' | 'string' | 'llm',
        normalization_threshold: 0.85,
        max_sample_size: 50000,
        enable_normalization_confirmation: false,
        enable_text_cleaning: false,
        enable_subject_restoration: true,
        enable_inference: false,
    });

    // 전처리 옵션 (청킹 방식과 무관하게 항상 적용 가능)
    const [preprocessingParams, setPreprocessingParams] = useState({
        enable_text_cleaning: false,
        enable_subject_restoration: true,
        enable_noun_extraction: false,
    });

    const fileInputRef = useRef<HTMLInputElement>(null);

    const [strategy, setStrategy] = useState('fixed_size');
    const [chunkingConfig, setChunkingConfig] = useState({
        chunk_size: 300, chunk_overlap: 20, window_size: 3,
        chunk_sizes: [2048, 512, 128], parent_size: 2048, child_size: 512, parent_overlap: 0, child_overlap: 100,
        target_size: 800, llm_auto_size: false,
    });

    useEffect(() => {
        if (isOpen) {
            setFile(null);
            setTextTitle('');
            setTextContent('');
            setInputTab('file');
            setIsUploading(false);
            if (kbId) loadKbConfig();
        }
    }, [isOpen, kbId]);

    const loadKbConfig = async () => {
        try {
            const res = await kbApi.get(kbId);
            setKbConfig(res.data);
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
        if (e.target.files && e.target.files[0]) setFile(e.target.files[0]);
    };

    const isFileReady = inputTab === 'file' ? !!file : (textTitle.trim().length > 0 && textContent.trim().length > 0);

    const handleUpload = async () => {
        if (!isFileReady) return;
        setIsUploading(true);
        try {
            const config = {
                ...graphParams,
                // 전처리 옵션
                enable_text_cleaning: preprocessingParams.enable_text_cleaning,
                enable_subject_restoration: preprocessingParams.enable_subject_restoration,
                enable_inference: preprocessingParams.enable_noun_extraction,
                chunking_strategy: strategy,
                chunking_config: chunkingConfig,
                // Ingest LLM (Chunk/Node Processing)
                llm_provider: settings.ingest_llm.provider,
                llm_model: settings.ingest_llm.model,
                llm_base_url: settings.ingest_llm.base_url,
                llm_provider_id: settings.ingest_llm.provider_id,
                // Chunk Grouping LLM
                chunk_grouping_llm_provider: settings.chunk_grouping_llm.provider,
                chunk_grouping_llm_model: settings.chunk_grouping_llm.model,
                chunk_grouping_llm_base_url: settings.chunk_grouping_llm.base_url,
                chunk_grouping_llm_provider_id: settings.chunk_grouping_llm.provider_id,
                // Subject Restoration LLM
                subject_restoration_llm_provider: settings.subject_restoration_llm.provider,
                subject_restoration_llm_model: settings.subject_restoration_llm.model,
                subject_restoration_llm_base_url: settings.subject_restoration_llm.base_url,
                subject_restoration_llm_provider_id: settings.subject_restoration_llm.provider_id,
                // Noun Extraction LLM
                noun_extraction_llm_provider: settings.noun_extraction_llm.provider,
                noun_extraction_llm_model: settings.noun_extraction_llm.model,
                noun_extraction_llm_base_url: settings.noun_extraction_llm.base_url,
                noun_extraction_llm_provider_id: settings.noun_extraction_llm.provider_id,
            };

            if (inputTab === 'file') {
                await docApi.upload(kbId, file!, config);
            } else {
                await docApi.uploadText(kbId, textTitle.trim(), textContent, config);
            }
            onUploadComplete();
            onClose();
        } catch (err) {
            console.error(err);
            setMessageDialog({ isOpen: true, title: 'Upload Failed', message: 'An error occurred while uploading. Please try again.', type: 'error' });
        } finally {
            setIsUploading(false);
        }
    };

    const isGraphEnabled = kbConfig && kbConfig.graph_backend && kbConfig.graph_backend !== 'none';

    const tabStyle = (active: boolean): React.CSSProperties => ({
        display: 'flex', alignItems: 'center', gap: '0.4rem',
        padding: '0.5rem 1rem', cursor: 'pointer', fontSize: '0.87rem', fontWeight: 600,
        color: active ? 'var(--primary)' : '#64748b',
        background: 'none', border: 'none',
        borderBottom: active ? '2px solid var(--primary)' : '2px solid transparent',
        transition: 'color 0.15s, border-color 0.15s', whiteSpace: 'nowrap',
    });

    return (
        <>
            <div style={{
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                backgroundColor: 'rgba(0,0,0,0.5)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50
            }} onClick={onClose}>
                <div className="card" style={{
                    width: '100%', maxWidth: '800px', maxHeight: '90vh',
                    overflow: 'hidden', display: 'flex', flexDirection: 'column', padding: 0
                }} onClick={(e) => e.stopPropagation()}>

                    {/* Header */}
                    <div style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        padding: '1.5rem', borderBottom: '1px solid #e2e8f0', backgroundColor: 'white'
                    }}>
                        <h2 style={{ margin: 0, fontSize: '1.25rem' }}>Upload Document</h2>
                        <div style={{ display: 'flex', gap: '1rem' }}>
                            <button
                                className="btn btn-primary"
                                onClick={handleUpload}
                                disabled={!isFileReady || isUploading}
                            >
                                {isUploading ? 'Uploading...' : 'Process Document'}
                            </button>
                            <button className="btn" onClick={onClose} disabled={isUploading}>Cancel</button>
                        </div>
                    </div>

                    <div style={{ padding: '1.5rem', overflowY: 'auto', flex: 1 }}>
                        {/* Input Type Tabs */}
                        <div style={{ marginBottom: '1.5rem' }}>
                            <div style={{ display: 'flex', borderBottom: '1px solid #e2e8f0', marginBottom: '1.25rem' }}>
                                <button id="tab-select-file" style={tabStyle(inputTab === 'file')} onClick={() => setInputTab('file')}>
                                    <Upload size={14} />
                                    Select File
                                </button>
                                <button id="tab-enter-content" style={tabStyle(inputTab === 'text')} onClick={() => setInputTab('text')}>
                                    <Type size={14} />
                                    Enter Content
                                </button>
                            </div>

                            {/* File Upload Panel */}
                            {inputTab === 'file' && (
                                <div
                                    style={{
                                        border: '2px dashed var(--border)', borderRadius: '8px',
                                        padding: '2rem', textAlign: 'center', cursor: 'pointer', background: '#fafafa',
                                    }}
                                    onClick={() => fileInputRef.current?.click()}
                                >
                                    <input
                                        type="file" ref={fileInputRef} style={{ display: 'none' }}
                                        onChange={handleFileChange} accept=".txt,.pdf,.md"
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
                            )}

                            {/* Text Input Panel */}
                            {inputTab === 'text' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                    <div>
                                        <label style={{ display: 'block', marginBottom: '0.3rem', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                                            Document Title <span style={{ color: '#ef4444' }}>*</span>
                                        </label>
                                        <input
                                            id="text-doc-title"
                                            type="text"
                                            className="input"
                                            placeholder="e.g. Company Policy 2024"
                                            value={textTitle}
                                            onChange={(e) => setTextTitle(e.target.value)}
                                            style={{ width: '100%' }}
                                        />
                                        <p style={{ margin: '0.25rem 0 0', fontSize: '0.75rem', color: '#94a3b8' }}>
                                            Will be saved as <code>{textTitle.trim() ? textTitle.trim().replace(/[^\w\s-]/g, '').replace(/\s+/g, '_') + '.txt' : 'text_document.txt'}</code>
                                        </p>
                                    </div>
                                    <div>
                                        <label style={{ display: 'block', marginBottom: '0.3rem', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                                            Content <span style={{ color: '#ef4444' }}>*</span>
                                        </label>
                                        <textarea
                                            id="text-doc-content"
                                            className="input"
                                            placeholder="Paste or type your document content here..."
                                            value={textContent}
                                            onChange={(e) => setTextContent(e.target.value)}
                                            rows={10}
                                            style={{ width: '100%', resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.6 }}
                                        />
                                        <p style={{ margin: '0.25rem 0 0', fontSize: '0.75rem', color: '#94a3b8' }}>
                                            {textContent.length.toLocaleString()} characters
                                        </p>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* ── Preprocessing Options ── */}
                        <div style={{ marginBottom: '1.5rem', background: '#f8fafc', padding: '15px', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1.25rem', color: '#475569', fontWeight: 600 }}>
                                <Wand2 size={18} className="text-primary" style={{ color: 'var(--primary)' }} />
                                <span>Preprocessing Options</span>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1.25rem' }}>

                                {/* Col 1: Clean Text */}
                                <div>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                        <input
                                            type="checkbox"
                                            checked={preprocessingParams.enable_text_cleaning}
                                            onChange={(e) => setPreprocessingParams(p => ({ ...p, enable_text_cleaning: e.target.checked }))}
                                            style={{ width: '1.1rem', height: '1.1rem', accentColor: 'var(--primary)', flexShrink: 0 }}
                                        />
                                        <div>
                                            <span style={{ color: '#1e293b', fontWeight: 600, fontSize: '0.9rem' }}>Clean Text</span>
                                            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Remove bullets, numbers, noise</div>
                                        </div>
                                    </label>
                                </div>

                                {/* Col 2: Subject Restoration */}
                                <div>
                                    <div>
                                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', marginBottom: '0.4rem' }}>
                                            <input
                                                type="checkbox"
                                                checked={preprocessingParams.enable_subject_restoration}
                                                onChange={(e) => setPreprocessingParams(p => ({ ...p, enable_subject_restoration: e.target.checked }))}
                                                style={{ width: '1.1rem', height: '1.1rem', accentColor: 'var(--primary)', flexShrink: 0 }}
                                            />
                                            <div>
                                                <span style={{ color: '#1e293b', fontWeight: 600, fontSize: '0.9rem' }}>Subject Restoration</span>
                                                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Resolve omitted subjects (KR)</div>
                                            </div>
                                        </label>
                                        {preprocessingParams.enable_subject_restoration && (
                                            <div style={{ marginLeft: '1.6rem' }}>
                                                <ModelSelector
                                                    type="llm"
                                                    value={settings.subject_restoration_llm}
                                                    onChange={(cfg) => updateSetting('subject_restoration_llm', cfg)}
                                                />
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {/* Col 3: Noun Extraction (그래프 활성화 시에만 유의미) */}
                                <div>
                                    <div>
                                        <label style={{
                                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                                            cursor: isGraphEnabled ? 'pointer' : 'not-allowed',
                                            marginBottom: '0.4rem',
                                            opacity: isGraphEnabled ? 1 : 0.45
                                        }}>
                                            <input
                                                type="checkbox"
                                                checked={preprocessingParams.enable_noun_extraction}
                                                disabled={!isGraphEnabled}
                                                onChange={(e) => setPreprocessingParams(p => ({ ...p, enable_noun_extraction: e.target.checked }))}
                                                style={{ width: '1.1rem', height: '1.1rem', accentColor: 'var(--primary)', flexShrink: 0 }}
                                            />
                                            <div>
                                                <span style={{ color: '#1e293b', fontWeight: 600, fontSize: '0.9rem' }}>Noun Extraction</span>
                                                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                                                    {isGraphEnabled ? 'Build named entity dictionary' : 'Graph 활성화 시 사용 가능'}
                                                </div>
                                            </div>
                                        </label>
                                        {preprocessingParams.enable_noun_extraction && isGraphEnabled && (
                                            <div style={{ marginLeft: '1.6rem' }}>
                                                <ModelSelector
                                                    type="llm"
                                                    value={settings.noun_extraction_llm}
                                                    onChange={(cfg) => updateSetting('noun_extraction_llm', cfg)}
                                                />
                                            </div>
                                        )}
                                    </div>
                                </div>

                            </div>
                        </div>

                        {/* Chunking Strategy */}
                        <div style={{ marginBottom: '10px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.8rem' }}>
                                <label style={{ fontWeight: 600, color: '#334155', whiteSpace: 'nowrap' }}>Chunking Strategy</label>
                                <select
                                    className="input"
                                    value={strategy}
                                    onChange={(e) => setStrategy(e.target.value)}
                                    style={{ flex: 1, maxWidth: '420px', padding: '0.75rem', borderRadius: '8px', border: '1px solid #e2e8f0', backgroundColor: '#fff', fontSize: '0.9rem', color: '#1e293b', cursor: 'pointer' }}
                                >
                                    {[
                                        { id: 'fixed_size', name: 'Fixed Size (Standard)' },
                                        { id: 'sliding_window', name: 'Sliding Window (Contextual)' },
                                        { id: 'hierarchical', name: 'Hierarchical (Parent-Child)' },
                                        { id: 'context_aware', name: 'Context Aware (LLM-based)' }
                                    ].map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                                </select>
                            </div>
                            <div style={{
                                padding: '15px',
                                background: '#f8fafc',
                                border: '1px solid #e2e8f0',
                                borderRadius: '8px',
                                display: 'grid',
                                gridTemplateColumns: strategy === 'context_aware' ? '2fr 3fr' : '1fr',
                                gap: '1.5rem',
                                alignItems: 'flex-start'
                            }}>
                                {/* Col 1: Chunking params */}
                                <div>
                                    {strategy === 'fixed_size' && (
                                        <div style={{ display: 'flex', gap: '0.75rem' }}>
                                            <div style={{ flex: 1 }}>
                                                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '0.25rem' }}>Chunk Size</div>
                                                <input type="number" className="input" style={{ width: '100%' }} value={chunkingConfig.chunk_size} onChange={(e) => setChunkingConfig({ ...chunkingConfig, chunk_size: parseInt(e.target.value) })} />
                                            </div>
                                            <div style={{ flex: 1 }}>
                                                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '0.25rem' }}>Overlap</div>
                                                <input type="number" className="input" style={{ width: '100%' }} value={chunkingConfig.chunk_overlap} onChange={(e) => setChunkingConfig({ ...chunkingConfig, chunk_overlap: parseInt(e.target.value) })} />
                                            </div>
                                        </div>
                                    )}
                                    {strategy === 'sliding_window' && (
                                        <div style={{ maxWidth: '320px' }}>
                                            <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '0.25rem' }}>Window Size</div>
                                            <input type="number" className="input" value={chunkingConfig.window_size} onChange={(e) => setChunkingConfig({ ...chunkingConfig, window_size: parseInt(e.target.value) })} />
                                        </div>
                                    )}
                                    {strategy === 'hierarchical' && (
                                        <div>
                                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                <div style={{ flex: 1 }}>
                                                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '0.25rem' }}>Parent Chunk Size</div>
                                                    <input
                                                        type="number"
                                                        className="input"
                                                        value={chunkingConfig.parent_size}
                                                        onChange={(e) => setChunkingConfig({ ...chunkingConfig, parent_size: parseInt(e.target.value) })}
                                                    />
                                                </div>
                                                <div style={{ flex: 1 }}>
                                                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '0.25rem' }}>Parent Overlap</div>
                                                    <input
                                                        type="number"
                                                        className="input"
                                                        value={chunkingConfig.parent_overlap}
                                                        onChange={(e) => setChunkingConfig({ ...chunkingConfig, parent_overlap: parseInt(e.target.value) })}
                                                    />
                                                </div>
                                                <div style={{ flex: 1 }}>
                                                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '0.25rem' }}>Child Chunk Size</div>
                                                    <input
                                                        type="number"
                                                        className="input"
                                                        value={chunkingConfig.child_size}
                                                        onChange={(e) => setChunkingConfig({ ...chunkingConfig, child_size: parseInt(e.target.value) })}
                                                    />
                                                </div>
                                                <div style={{ flex: 1 }}>
                                                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '0.25rem' }}>Child Overlap</div>
                                                    <input
                                                        type="number"
                                                        className="input"
                                                        value={chunkingConfig.child_overlap}
                                                        onChange={(e) => setChunkingConfig({ ...chunkingConfig, child_overlap: parseInt(e.target.value) })}
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                    {strategy === 'context_aware' && (
                                        <div>
                                            <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '0.5rem' }}>LLM</div>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                                <div style={{ flex: 1, marginTop: '-4px' }}>
                                                    <ModelSelector
                                                        type="llm"
                                                        value={settings.chunk_grouping_llm}
                                                        onChange={(cfg) => updateSetting('chunk_grouping_llm', cfg)}
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>

                                {/* Col 2: LLMs (only for context-aware) */}
                                {strategy === 'context_aware' && (
                                    <div style={{ borderLeft: '1px solid #e2e8f0', paddingLeft: '1.5rem' }}>
                                        <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '0.5rem' }}>Target Chunk Size</div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', cursor: 'pointer', fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                                                <input
                                                    type="checkbox"
                                                    checked={chunkingConfig.llm_auto_size}
                                                    onChange={(e) => setChunkingConfig({ ...chunkingConfig, llm_auto_size: e.target.checked })}
                                                    style={{ width: '1rem', height: '1rem' }}
                                                />
                                                <span>Auto Size</span>
                                            </label>
                                            <input
                                                type="number"
                                                className="input"
                                                value={chunkingConfig.target_size}
                                                onChange={(e) => setChunkingConfig({ ...chunkingConfig, target_size: parseInt(e.target.value) })}
                                                disabled={chunkingConfig.llm_auto_size}
                                                style={{ opacity: chunkingConfig.llm_auto_size ? 0.5 : 1, width: '60%' }}
                                            />
                                        </div>
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
                                ingestLlm={settings.ingest_llm}
                                onIngestLlmChange={(cfg) => updateSetting('ingest_llm', cfg)}
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
        </>
    );
}
