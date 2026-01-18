import React, { useState, useRef, useEffect } from 'react';
import { Upload, FileText, X, Database, Info } from 'lucide-react';
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

// NOTE: ExtractionRuleModal and EditPromptModal have been removed.
// Graph extraction is now handled by LlamaIndex in the Ingest Service.

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

    // Graph Params - LlamaIndex based
    const [graphParams, setGraphParams] = useState({
        extractor_type: 'simple' as 'simple' | 'dynamic' | 'schema',
        max_paths_per_chunk: 10,
        max_triplets_per_chunk: 20,
        num_workers: 4,
        generate_inverse_relations: true,
        allowed_entity_types: [] as string[],
        allowed_relation_types: [] as string[],
        enable_text_cleaning: false,  // 번호/불릿 등 형식 문자 제거
        enable_inference: false,  // 규칙 기반 관계 추론
    });



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

                    {/* Graph Settings Section - LlamaIndex based */}
                    {isGraphEnabled && (
                        <div style={{ marginBottom: '1.5rem', background: '#f8fafc', padding: '1.25rem', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1.25rem', color: '#3b82f6', fontWeight: 600 }}>
                                <Database size={18} />
                                <span>Graph Extraction Settings (LlamaIndex)</span>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                                {/* Column 1: Extractor Type Selection */}
                                <div>
                                    <LabelWithTooltip
                                        label="Extractor Type"
                                        tooltip="LlamaIndex 그래프 추출기 타입 선택"
                                    />
                                    <select
                                        className="input"
                                        value={graphParams.extractor_type}
                                        onChange={(e) => setGraphParams({ ...graphParams, extractor_type: e.target.value as 'simple' | 'dynamic' | 'schema' })}
                                        style={{ width: '100%', padding: '0.5rem', fontSize: '0.85rem' }}
                                    >
                                        <option value="simple">Simple LLM (기본)</option>
                                        <option value="dynamic">Dynamic LLM</option>
                                        <option value="schema">Schema-based</option>
                                    </select>

                                    {/* Extractor-specific settings */}
                                    {graphParams.extractor_type === 'simple' && (
                                        <div style={{ marginTop: '1rem' }}>
                                            <LabelWithTooltip
                                                label={`Max Paths per Chunk: ${graphParams.max_paths_per_chunk}`}
                                                tooltip="청크당 추출할 최대 트리플 수"
                                            />
                                            <input
                                                type="range"
                                                min="5"
                                                max="50"
                                                step="5"
                                                value={graphParams.max_paths_per_chunk}
                                                onChange={(e) => setGraphParams({ ...graphParams, max_paths_per_chunk: parseInt(e.target.value) })}
                                                style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                                            />
                                        </div>
                                    )}

                                    {graphParams.extractor_type === 'dynamic' && (
                                        <div style={{ marginTop: '1rem' }}>
                                            <LabelWithTooltip
                                                label={`Max Triplets per Chunk: ${graphParams.max_triplets_per_chunk}`}
                                                tooltip="청크당 추출할 최대 트리플 수"
                                            />
                                            <input
                                                type="range"
                                                min="10"
                                                max="100"
                                                step="10"
                                                value={graphParams.max_triplets_per_chunk}
                                                onChange={(e) => setGraphParams({ ...graphParams, max_triplets_per_chunk: parseInt(e.target.value) })}
                                                style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                                            />
                                        </div>
                                    )}
                                </div>

                                {/* Column 2: Common Settings */}
                                <div>
                                    <LabelWithTooltip
                                        label={`Workers: ${graphParams.num_workers}`}
                                        tooltip="병렬 처리 워커 수"
                                    />
                                    <input
                                        type="range"
                                        min="1"
                                        max="8"
                                        step="1"
                                        value={graphParams.num_workers}
                                        onChange={(e) => setGraphParams({ ...graphParams, num_workers: parseInt(e.target.value) })}
                                        style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6', marginBottom: '1rem' }}
                                    />

                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', marginTop: '0.5rem' }}>
                                        <input
                                            type="checkbox"
                                            checked={graphParams.generate_inverse_relations}
                                            onChange={(e) => setGraphParams({ ...graphParams, generate_inverse_relations: e.target.checked })}
                                            style={{ width: '1rem', height: '1rem' }}
                                        />
                                        <span style={{ color: '#334155', fontWeight: 500 }}>역관계 자동 생성</span>
                                    </label>

                                    <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.5rem', paddingLeft: '1.5rem' }}>
                                        예: 스승 → 제자, Teacher → Student
                                    </div>

                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', marginTop: '1rem' }}>
                                        <input
                                            type="checkbox"
                                            checked={graphParams.enable_text_cleaning}
                                            onChange={(e) => setGraphParams({ ...graphParams, enable_text_cleaning: e.target.checked })}
                                            style={{ width: '1rem', height: '1rem' }}
                                        />
                                        <span style={{ color: '#334155', fontWeight: 500 }}>텍스트 정제</span>
                                    </label>

                                    <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.5rem', paddingLeft: '1.5rem' }}>
                                        번호, 불릿 등 형식 문자 제거
                                    </div>

                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', marginTop: '1rem' }}>
                                        <input
                                            type="checkbox"
                                            checked={graphParams.enable_inference}
                                            onChange={(e) => setGraphParams({ ...graphParams, enable_inference: e.target.checked })}
                                            style={{ width: '1rem', height: '1rem' }}
                                        />
                                        <span style={{ color: '#334155', fontWeight: 500 }}>추론 관계 생성</span>
                                    </label>

                                    <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.5rem', paddingLeft: '1.5rem' }}>
                                        예: 스승→스승 = 사조 (Neo4j만)
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
        </>

    );
}
