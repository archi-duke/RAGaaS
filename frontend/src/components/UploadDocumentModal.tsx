import React, { useState, useRef, useEffect } from 'react';
import { Upload, FileText, X, Settings, Database, Info, Eye, FileCode } from 'lucide-react';
import { docApi, kbApi } from '../services/api';
import MessageDialog from './MessageDialog';

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

const ExtractionRuleModal = ({ isOpen, onClose }: { isOpen: boolean, onClose: () => void }) => {
    const [content, setContent] = useState('');
    const [originalContent, setOriginalContent] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [isValidating, setIsValidating] = useState(false);
    const [status, setStatus] = useState<{ type: 'idle' | 'success' | 'error', message: string }>({ type: 'idle', message: '' });

    useEffect(() => {
        if (isOpen) {
            loadRules();
        }
    }, [isOpen]);

    const loadRules = async () => {
        setIsLoading(true);
        setStatus({ type: 'idle', message: '' });
        try {
            const res = await kbApi.getExtractionRules();
            setContent(res.data.content);
            setOriginalContent(res.data.content);
        } catch (err) {
            console.error("Failed to load rules", err);
        } finally {
            setIsLoading(false);
        }
    };

    const handleApply = async () => {
        setIsValidating(true);
        setStatus({ type: 'idle', message: 'Validating with LLM...' });
        try {
            // 1. Validate
            const valRes = await kbApi.validateExtractionRules(content);
            if (!valRes.data.valid) {
                setStatus({ type: 'error', message: valRes.data.message });
                setIsValidating(false);
                return;
            }

            // 2. Save
            await kbApi.saveExtractionRules(content);
            setStatus({ type: 'success', message: 'Rule applied successfully!' });
            setOriginalContent(content);
            setTimeout(() => {
                onClose();
                setStatus({ type: 'idle', message: '' });
            }, 1500);
        } catch (err: any) {
            console.error(err);
            setStatus({ type: 'error', message: err.response?.data?.detail || 'Failed to apply rules' });
        } finally {
            setIsValidating(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 60
        }} onClick={onClose}>
            <div className="card" style={{ width: '800px', height: '85vh', display: 'flex', flexDirection: 'column' }} onClick={e => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Settings size={20} color="#3b82f6" />
                        <h3 style={{ margin: 0 }}>Extraction Rule (YAML)</h3>
                    </div>
                    <button className="btn" onClick={onClose} style={{ padding: '0.4rem' }}><X size={18} /></button>
                </div>

                <p style={{ fontSize: '0.85rem', color: '#64748b', marginBottom: '1rem' }}>
                    Edit few-shot examples in YAML format for graph triple extraction.
                </p>

                <div style={{ flex: 1, marginBottom: '1rem', position: 'relative', overflow: 'hidden' }}>
                    {isLoading ? (
                        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>Loading...</div>
                    ) : (
                        <textarea
                            value={content}
                            onChange={(e) => setContent(e.target.value)}
                            style={{
                                width: '100%',
                                height: '100%',
                                background: '#1e293b',
                                color: '#e2e8f0',
                                padding: '1.25rem',
                                borderRadius: '8px',
                                fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                                fontSize: '0.9rem',
                                border: '1px solid #334155',
                                resize: 'none',
                                outline: 'none',
                                lineHeight: '1.6'
                            }}
                            spellCheck={false}
                        />
                    )}
                </div>

                {status.message && (
                    <div style={{
                        padding: '0.75rem',
                        borderRadius: '6px',
                        marginBottom: '1rem',
                        fontSize: '0.85rem',
                        background: status.type === 'error' ? '#fef2f2' : status.type === 'success' ? '#f0fdf4' : '#f1f5f9',
                        color: status.type === 'error' ? '#991b1b' : status.type === 'success' ? '#166534' : '#475569',
                        border: `1px solid ${status.type === 'error' ? '#fecaca' : status.type === 'success' ? '#bbf7d0' : '#e2e8f0'}`,
                        whiteSpace: 'pre-wrap'
                    }}>
                        {status.message}
                    </div>
                )}

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                    <button className="btn" onClick={onClose} disabled={isValidating}>Cancel</button>
                    <button
                        className="btn btn-primary"
                        onClick={handleApply}
                        disabled={isLoading || isValidating || content === originalContent}
                        style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                    >
                        {isValidating ? 'Validating...' : 'Validate & Apply'}
                    </button>
                </div>
            </div>
        </div>
    );
};

const EditPromptModal = ({ isOpen, onClose }: { isOpen: boolean, onClose: () => void }) => {
    const [content, setContent] = useState('');
    const [originalContent, setOriginalContent] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [status, setStatus] = useState<{ type: 'idle' | 'success' | 'error', message: string }>({ type: 'idle', message: '' });

    useEffect(() => {
        if (isOpen) {
            loadPrompt();
        }
    }, [isOpen]);

    const loadPrompt = async () => {
        setIsLoading(true);
        setStatus({ type: 'idle', message: '' });
        try {
            const res = await kbApi.getExtractionPrompt();
            setContent(res.data.content);
            setOriginalContent(res.data.content);
        } catch (err) {
            console.error("Failed to load prompt", err);
            setStatus({ type: 'error', message: 'Failed to load prompt.' });
        } finally {
            setIsLoading(false);
        }
    };

    const handleSave = async () => {
        setIsLoading(true);
        setStatus({ type: 'idle', message: 'Saving...' });
        try {
            await kbApi.saveExtractionPrompt(content);
            setStatus({ type: 'success', message: 'Prompt saved successfully!' });
            setOriginalContent(content);
            setTimeout(() => {
                onClose();
                setStatus({ type: 'idle', message: '' });
            }, 1000);
        } catch (err: any) {
            console.error(err);
            setStatus({ type: 'error', message: err.response?.data?.detail || 'Failed to save prompt' });
        } finally {
            setIsLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 65 // Higher than Upload Modal
        }} onClick={onClose}>
            <div className="card" style={{ width: '800px', height: '85vh', display: 'flex', flexDirection: 'column' }} onClick={e => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <FileCode size={20} color="#3b82f6" />
                        <h3 style={{ margin: 0 }}>Edit LLM Extraction Prompt</h3>
                    </div>
                    <button className="btn" onClick={onClose} style={{ padding: '0.4rem' }}><X size={18} /></button>
                </div>

                <p style={{ fontSize: '0.85rem', color: '#64748b', marginBottom: '1rem' }}>
                    Edit the prompt used by LLM for graph extraction. Document content will be inserted at {'{text}'}.
                </p>

                <div style={{ flex: 1, marginBottom: '1rem', position: 'relative', overflow: 'hidden' }}>
                    {isLoading ? (
                        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>Loading...</div>
                    ) : (
                        <textarea
                            value={content}
                            onChange={(e) => setContent(e.target.value)}
                            style={{
                                width: '100%',
                                height: '100%',
                                background: '#1e293b',
                                color: '#e2e8f0',
                                padding: '1.25rem',
                                borderRadius: '8px',
                                fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                                fontSize: '0.9rem',
                                border: '1px solid #334155',
                                resize: 'none',
                                outline: 'none',
                                lineHeight: '1.6'
                            }}
                            spellCheck={false}
                        />
                    )}
                </div>

                {status.message && (
                    <div style={{
                        padding: '0.75rem',
                        borderRadius: '6px',
                        marginBottom: '1rem',
                        fontSize: '0.85rem',
                        background: status.type === 'error' ? '#fef2f2' : status.type === 'success' ? '#f0fdf4' : '#f1f5f9',
                        color: status.type === 'error' ? '#991b1b' : status.type === 'success' ? '#166534' : '#475569',
                        border: `1px solid ${status.type === 'error' ? '#fecaca' : status.type === 'success' ? '#bbf7d0' : '#e2e8f0'}`,
                        whiteSpace: 'pre-wrap'
                    }}>
                        {status.message}
                    </div>
                )}

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                    <button className="btn" onClick={onClose}>Cancel</button>
                    <button
                        className="btn btn-primary"
                        onClick={handleSave}
                        disabled={isLoading || content === originalContent}
                    >
                        Save Prompt
                    </button>
                </div>
            </div>
        </div>
    );
};

export default function UploadDocumentModal({ isOpen, onClose, kbId, onUploadComplete }: UploadDocumentModalProps) {
    const [file, setFile] = useState<File | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [kbConfig, setKbConfig] = useState<any>(null);
    const [messageDialog, setMessageDialog] = useState<{ isOpen: boolean; title: string; message: string; type: 'info' | 'success' | 'error' }>({
        isOpen: false,
        title: '',
        message: '',
        type: 'info'
    });

    // Graph Params
    const [graphParams, setGraphParams] = useState({
        oe_section_aware: true,
        extract_inverse_relations: true,
        confidence_threshold: 0.6,
        max_candidates_per_chunk: 20,
        graph_section_size: 2500,
        graph_section_overlap: 1000
    });

    const [showRuleModal, setShowRuleModal] = useState(false);
    const [showPromptModal, setShowPromptModal] = useState(false);

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
                <div className="card" style={{ width: '100%', maxWidth: '710px', maxHeight: '90vh', overflow: 'auto' }} onClick={(e) => e.stopPropagation()}>
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

                    {/* Graph Settings Section */}
                    {isGraphEnabled && (
                        <div style={{ marginBottom: '1.5rem', background: '#f8fafc', padding: '1.25rem', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1.25rem', color: '#3b82f6', fontWeight: 600 }}>
                                <Database size={18} />
                                <span>Graph Extraction Settings</span>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(140px, 1fr) minmax(140px, 1fr) minmax(180px, 1.2fr)', gap: '1.5rem' }}>
                                {/* Column 1: Summary Info */}
                                <div style={{ fontSize: '0.85rem', color: '#334155' }}>
                                    <div style={{ fontWeight: 'bold', marginBottom: '6px', color: '#000' }}>Chunk</div>
                                    <div style={{ display: 'flex', gap: '1rem', paddingLeft: '0.5rem', marginBottom: '0.75rem' }}>
                                        <div style={{ color: '#64748b' }}>
                                            <div>Size : </div>
                                            <div>Overlap : </div>
                                        </div>
                                        <div style={{ fontWeight: 500 }}>
                                            <div>{kbConfig?.chunking_config?.chunk_size || '500'}</div>
                                            <div>{kbConfig?.chunking_config?.overlap || '100'}</div>
                                        </div>
                                    </div>

                                    <div style={{ marginBottom: '0.75rem' }}>
                                        <span style={{ fontWeight: 'bold', color: '#000' }}>LLM Model : </span>
                                        <div style={{ color: '#64748b', paddingLeft: '0.5rem', marginTop: '0.2rem' }}>gpt-4o-mini</div>
                                    </div>

                                    <div>
                                        <span style={{ fontWeight: 'bold', color: '#000' }}>RAG Strategy : </span>
                                        <div style={{ color: '#64748b', paddingLeft: '0.5rem', marginTop: '0.2rem' }}>{chunkingStrategy === 'size' ? 'Fixed Size' : chunkingStrategy}</div>
                                    </div>
                                </div>

                                {/* Column 2: Graph Section Controls */}
                                <div style={{ fontSize: '0.85rem' }}>
                                    <div style={{ fontWeight: 'bold', marginBottom: '6px', color: '#000' }}>Graph Section</div>
                                    <div style={{ marginBottom: '0.75rem' }}>
                                        <div style={{ color: '#334155', marginBottom: '0.25rem' }}>Size</div>
                                        <input
                                            type="number"
                                            className="input"
                                            value={graphParams.graph_section_size}
                                            onChange={(e) => setGraphParams({ ...graphParams, graph_section_size: parseInt(e.target.value) || 0 })}
                                            style={{ padding: '0.4rem 0.6rem', fontSize: '0.85rem' }}
                                        />
                                    </div>
                                    <div style={{ marginBottom: '0.75rem' }}>
                                        <div style={{ color: '#334155', marginBottom: '0.25rem' }}>Overlap</div>
                                        <input
                                            type="number"
                                            className="input"
                                            value={graphParams.graph_section_overlap}
                                            onChange={(e) => setGraphParams({ ...graphParams, graph_section_overlap: parseInt(e.target.value) || 0 })}
                                            style={{ padding: '0.4rem 0.6rem', fontSize: '0.85rem' }}
                                        />
                                    </div>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', marginTop: '0.5rem' }}>
                                        <input
                                            type="checkbox"
                                            checked={graphParams.oe_section_aware}
                                            onChange={(e) => setGraphParams({ ...graphParams, oe_section_aware: e.target.checked })}
                                            style={{ width: '0.9rem', height: '0.9rem' }}
                                        />
                                        <span style={{ color: '#334155', fontWeight: 500 }}>Section Aware</span>
                                    </label>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.5rem' }}>
                                        <input
                                            type="checkbox"
                                            checked={graphParams.extract_inverse_relations}
                                            onChange={(e) => setGraphParams({ ...graphParams, extract_inverse_relations: e.target.checked })}
                                            style={{ width: '0.9rem', height: '0.9rem', cursor: 'pointer' }}
                                        />
                                        <LabelWithTooltip
                                            label="Inverse Relations"
                                            tooltip="Automatically generate inverse relations (e.g., Teacher-Student, Master-Disciple)."
                                        />
                                    </div>
                                </div>

                                {/* Column 3: Sliders */}
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                                    <div>
                                        <LabelWithTooltip
                                            label={`Confidence: ${graphParams.confidence_threshold}`}
                                            tooltip="Minimum confidence score for extracted triples."
                                        />
                                        <input
                                            type="range"
                                            min="0"
                                            max="1"
                                            step="0.1"
                                            value={graphParams.confidence_threshold}
                                            onChange={(e) => setGraphParams({ ...graphParams, confidence_threshold: parseFloat(e.target.value) })}
                                            style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                                        />
                                    </div>
                                    <div>
                                        <LabelWithTooltip
                                            label={`Max Candidates: ${graphParams.max_candidates_per_chunk}`}
                                            tooltip="Maximum number of triples to extract per chunk."
                                        />
                                        <input
                                            type="range"
                                            min="10"
                                            max="100"
                                            step="10"
                                            value={graphParams.max_candidates_per_chunk}
                                            onChange={(e) => setGraphParams({ ...graphParams, max_candidates_per_chunk: parseInt(e.target.value) })}
                                            style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                                        />
                                        <button
                                            className="btn"
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: '0.4rem',
                                                fontSize: '0.75rem', color: '#64748b', background: '#f1f5f9',
                                                border: '1px solid #e2e8f0', borderRadius: '4px', padding: '0.4rem',
                                                width: '100%', justifyContent: 'center', marginTop: '0.5rem'
                                            }}
                                            onClick={() => setShowRuleModal(true)}
                                        >
                                            <Settings size={12} />
                                            Extraction Rule
                                        </button>
                                        <button
                                            className="btn"
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: '0.4rem',
                                                fontSize: '0.75rem', color: '#64748b', background: '#f1f5f9',
                                                border: '1px solid #e2e8f0', borderRadius: '4px', padding: '0.4rem',
                                                width: '100%', justifyContent: 'center', marginTop: '0.5rem'
                                            }}
                                            onClick={() => setShowPromptModal(true)}
                                        >
                                            <FileCode size={12} />
                                            Extraction Prompt
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                        <button className="btn" onClick={onClose} disabled={isUploading}>Cancel</button>
                        <button
                            className="btn btn-primary"
                            onClick={handleUpload}
                            disabled={!file || isUploading}
                        >
                            {isUploading ? 'Uploading...' : 'Upload'}
                        </button>
                    </div>
                </div>
            </div>

            <MessageDialog
                isOpen={messageDialog.isOpen}
                title={messageDialog.title}
                message={messageDialog.message}
                type={messageDialog.type}
                onClose={() => setMessageDialog({ ...messageDialog, isOpen: false })}
            />

            <ExtractionRuleModal
                isOpen={showRuleModal}
                onClose={() => setShowRuleModal(false)}
            />
            <EditPromptModal
                isOpen={showPromptModal}
                onClose={() => setShowPromptModal(false)}
            />
        </>
    );
}
