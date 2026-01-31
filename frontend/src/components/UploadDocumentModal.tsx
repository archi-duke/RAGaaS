import React, { useState, useRef, useEffect } from 'react';
import { Upload, FileText } from 'lucide-react';
import { docApi, kbApi } from '../services/api';
import MessageDialog from './MessageDialog';
import PromptDialog from './PromptDialog';
import GraphExtractionSettings from './GraphExtractionSettings';

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

export default function UploadDocumentModal({ isOpen, onClose, kbId, onUploadComplete }: UploadDocumentModalProps) {
    const [file, setFile] = useState<File | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [kbConfig, setKbConfig] = useState<any>(null);

    const [showExampleModal, setShowExampleModal] = useState(false);
    const [showPromptModal, setShowPromptModal] = useState(false);

    const [messageDialog, setMessageDialog] = useState<{ isOpen: boolean; title: string; message: string; type: 'info' | 'success' | 'error' }>({
        isOpen: false,
        title: '',
        message: '',
        type: 'info'
    });

    const [graphParams, setGraphParams] = useState({
        extractor_type: 'simple' as 'simple' | 'dynamic' | 'schema',
        max_paths_per_chunk: 20,
        max_triplets_per_chunk: 20,
        num_workers: 4,
        generate_inverse_relations: true,
        allowed_entity_types: [] as string[],
        allowed_relation_types: [] as string[],
        enable_text_cleaning: false,
        enable_subject_restoration: true,
        enable_inference: false,
        chunk_size: 300,
        extraction_examples_yaml: '',
        custom_prompt: '',
        enable_entity_normalization: true,
        normalization_algorithm: 'embedding' as 'embedding' | 'string' | 'llm',
        normalization_threshold: 0.85,
        max_sample_size: 50000,
        enable_normalization_confirmation: false,
    });

    const fileInputRef = useRef<HTMLInputElement>(null);

    const [strategy, setStrategy] = useState('fixed_size');
    const [chunkingConfig, setChunkingConfig] = useState({
        chunk_size: 300,
        chunk_overlap: 20,
        window_size: 3,
        chunk_sizes: [2048, 512, 128],
        buffer_size: 1,
        breakpoint_threshold: 95,
        parent_size: 2000,
        child_size: 500,
        parent_overlap: 0,
        child_overlap: 100,
    });

    useEffect(() => {
        if (isOpen) {
            setFile(null);
            setIsUploading(false);
            if (kbId) {
                loadKbConfig();
            }
        }
    }, [isOpen, kbId]);

    const loadKbConfig = async () => {
        try {
            const res = await kbApi.get(kbId);
            const data = res.data;
            setKbConfig(data);

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
                ...graphParams,
                chunking_strategy: strategy,
                chunking_config: chunkingConfig,
            };

            await docApi.upload(kbId, file, config);
            onUploadComplete();
            onClose();

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

    const isGraphEnabled = kbConfig && kbConfig.graph_backend && kbConfig.graph_backend !== 'none';

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
                    maxWidth: '800px',
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
                            <button
                                className="btn btn-primary"
                                onClick={handleUpload}
                                disabled={!file || isUploading}
                            >
                                {isUploading ? 'Uploading...' : 'Process Document'}
                            </button>
                            <button className="btn" onClick={onClose} disabled={isUploading}>Cancel</button>
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
                            </div>

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
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                        <div>
                                            <LabelWithTooltip label="Buffer Size" tooltip="Sentences to group" />
                                            <input type="number" className="input" value={chunkingConfig.buffer_size} onChange={(e) => setChunkingConfig({ ...chunkingConfig, buffer_size: parseInt(e.target.value) })} />
                                        </div>
                                        <div>
                                            <LabelWithTooltip label="Threshold (%)" tooltip="Break if percentile > x" />
                                            <input type="number" className="input" value={chunkingConfig.breakpoint_threshold} onChange={(e) => setChunkingConfig({ ...chunkingConfig, breakpoint_threshold: parseInt(e.target.value) })} />
                                        </div>
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
        </>
    );
}
