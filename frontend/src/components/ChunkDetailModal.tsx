import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Database, ChevronDown, ChevronUp, FlaskConical } from 'lucide-react';
import { extractionApi, kbApi } from '../services/api';
import ExtractionExampleModal from './ExtractionExampleModal';
import ExtractionPromptModal from './ExtractionPromptModal';
import GraphExtractionSettings from './GraphExtractionSettings';

interface Triple {
    subject: string;
    predicate: string;
    object: string;
    confidence?: number;
    is_inverse?: boolean;
}

interface ChunkDetailModalProps {
    isOpen: boolean;
    onClose: () => void;
    chunk: {
        id: string;
        content: string;
    } | null;
    title?: string;
    onSave?: (content: string) => Promise<void>;
    isGraphEnabled?: boolean;
    kbId?: string; // Knowledge Base ID for saving triples
}

// LabelWithTooltip Component (reused from UploadDocumentModal)
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



export default function ChunkDetailModal({ isOpen, onClose, chunk, title = 'Chunk Content', onSave, isGraphEnabled = false, kbId }: ChunkDetailModalProps) {
    const [isEditing, setIsEditing] = useState(false);
    const [editContent, setEditContent] = useState('');
    const [isSaving, setIsSaving] = useState(false);

    // Extract Test states
    const [showExtractionSettings, setShowExtractionSettings] = useState(false);
    const [isExtracting, setIsExtracting] = useState(false);
    const [extractedTriples, setExtractedTriples] = useState<Triple[]>([]);
    const [showResults, setShowResults] = useState(false);
    const [selectedTriples, setSelectedTriples] = useState<Set<number>>(new Set());
    const [isSavingTriples, setIsSavingTriples] = useState(false);

    // Modal states for Examples and Prompt
    const [showExampleModal, setShowExampleModal] = useState(false);
    const [showPromptModal, setShowPromptModal] = useState(false);

    // Selection state for partial extraction
    const contentRef = useRef<HTMLDivElement>(null);
    const [selectionText, setSelectionText] = useState('');

    // Track text selection within the content area
    useEffect(() => {
        const handleSelectionChange = () => {
            const selection = window.getSelection();
            if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
                if (selectionText) setSelectionText(''); // Optimize check
                return;
            }

            const text = selection.toString().trim();
            // Check if selection is inside contentRef
            if (contentRef.current && contentRef.current.contains(selection.anchorNode)) {
                if (text !== selectionText) setSelectionText(text);
            } else {
                if (selectionText) setSelectionText('');
            }
        };

        document.addEventListener('selectionchange', handleSelectionChange);
        return () => document.removeEventListener('selectionchange', handleSelectionChange);
    }, [selectionText]);

    // Graph Params (same structure as UploadDocumentModal)
    const [graphParams, setGraphParams] = useState({
        extractor_type: 'simple' as 'simple' | 'dynamic' | 'schema',
        max_paths_per_chunk: 10,
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

    useEffect(() => {
        if (chunk) {
            setEditContent(chunk.content);
        }
        setIsEditing(false);
        // Reset extraction states when chunk changes
        setShowExtractionSettings(false);
        setExtractedTriples([]);
        setShowResults(false);
        setSelectedTriples(new Set());
    }, [chunk]);

    // Load default extraction prompt
    useEffect(() => {
        const loadPrompt = async () => {
            try {
                const promptRes = await kbApi.getExtractionPrompt();
                const serverPrompt = promptRes.data?.content;
                if (serverPrompt && serverPrompt !== 'Prompt not found in DB.') {
                    setGraphParams(prev => ({ ...prev, custom_prompt: serverPrompt }));
                }
            } catch (err) {
                console.warn('Failed to load extraction prompt:', err);
            }
        };
        if (isOpen && isGraphEnabled) {
            loadPrompt();
        }
    }, [isOpen, isGraphEnabled]);

    if (!isOpen || !chunk) return null;

    const handleSave = async () => {
        if (!onSave || !editContent.trim()) return;
        setIsSaving(true);
        try {
            await onSave(editContent);
            setIsEditing(false);
        } catch (error) {
            console.error('Failed to save chunk:', error);
            alert('Failed to save chunk content');
        } finally {
            setIsSaving(false);
        }
    };

    const handleExtract = async () => {
        setIsExtracting(true);
        // Use selected text if available, otherwise full content
        const textToExtract = selectionText || chunk.content;

        try {
            const res = await extractionApi.extractChunk({
                chunk_text: textToExtract,
                extractor_type: graphParams.extractor_type,
                max_paths_per_chunk: graphParams.max_paths_per_chunk,
                max_triplets_per_chunk: graphParams.max_triplets_per_chunk,
                num_workers: graphParams.num_workers,
                generate_inverse_relations: graphParams.generate_inverse_relations,
                enable_subject_restoration: graphParams.enable_subject_restoration,
                enable_text_cleaning: graphParams.enable_text_cleaning,
                custom_prompt: graphParams.custom_prompt || undefined,
            });
            setExtractedTriples(res.data.triples || []);
            setShowResults(true);
            setSelectedTriples(new Set()); // Reset selection
        } catch (error: any) {
            console.error('Extract failed:', error);
            alert(error.response?.data?.detail || 'An error occurred during triple extraction.');
        } finally {
            setIsExtracting(false);
        }
    };

    const handleToggleTriple = (index: number) => {
        const newSelected = new Set(selectedTriples);
        if (newSelected.has(index)) {
            newSelected.delete(index);
        } else {
            newSelected.add(index);
        }
        setSelectedTriples(newSelected);
    };

    const handleToggleAll = () => {
        if (selectedTriples.size === extractedTriples.length) {
            setSelectedTriples(new Set());
        } else {
            setSelectedTriples(new Set(extractedTriples.map((_, idx) => idx)));
        }
    };

    const handleApplyTriples = async () => {
        if (selectedTriples.size === 0) return;
        if (!kbId) {
            alert('Knowledge Base ID is missing.');
            return;
        }

        setIsSavingTriples(true);
        try {
            const triplesToSave = Array.from(selectedTriples).map(idx => extractedTriples[idx]);

            // Save triples to the triple store
            await extractionApi.saveChunkTriples({
                kb_id: kbId,
                chunk_id: chunk.id,
                triples: triplesToSave,
            });

            alert(`${selectedTriples.size} triples have been successfully saved.`);
            setSelectedTriples(new Set());
            setShowResults(false);
        } catch (error: any) {
            console.error('Save triples failed:', error);
            alert(error.response?.data?.detail || 'An error occurred while saving triples.');
        } finally {
            setIsSavingTriples(false);
        }
    };

    return createPortal(
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
                zIndex: 99999
            }}
            onClick={onClose}
        >
            <div
                className="card"
                style={{
                    width: '90%',
                    maxWidth: '900px',
                    maxHeight: '90vh',
                    overflow: 'auto',
                    backgroundColor: 'white',
                    padding: '24px',
                    borderRadius: '12px',
                    boxShadow: '0 20px 50px rgba(0,0,0,0.3)',
                    border: '1px solid #e2e8f0'
                }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
                    <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 700, color: '#1e293b', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        📄 {title}
                    </h3>
                    <div style={{ display: 'flex', gap: '8px' }}>
                        {/* Extract Test Button - only for graph-enabled KBs */}
                        {isGraphEnabled && !isEditing && (
                            <button
                                className="k-button k-button-sm k-rounded-md k-button-solid"
                                onClick={() => setShowExtractionSettings(!showExtractionSettings)}
                                style={{
                                    cursor: 'pointer',
                                    fontWeight: 600,
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '5px',
                                    fontSize: '0.85rem',
                                    backgroundColor: showExtractionSettings ? '#3b82f6' : '#f1f5f9',
                                    color: showExtractionSettings ? 'white' : '#3b82f6',
                                    border: '1px solid #3b82f6'
                                }}
                            >
                                <FlaskConical size={14} />
                                Extract Test
                                {showExtractionSettings ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                            </button>
                        )}
                        {onSave && !isEditing && (
                            <button
                                onClick={() => setIsEditing(true)}
                                style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem' }}
                            >
                                Edit
                            </button>
                        )}
                        <button
                            className="k-button k-button-sm k-rounded-md k-button-solid k-button-solid-base"
                            onClick={onClose}
                            style={{ cursor: 'pointer', fontSize: '0.85rem' }}
                        >
                            Close
                        </button>
                    </div>
                </div>

                {/* Meta Info */}
                <div style={{
                    fontSize: '0.85rem',
                    color: '#64748b',
                    marginBottom: '1.25rem',
                    padding: '8px 12px',
                    backgroundColor: '#f1f5f9',
                    borderRadius: '6px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                }}>
                    <span style={{ fontWeight: 600 }}>Chunk ID:</span>
                    <code style={{ fontFamily: 'monospace', color: '#0f172a' }}>{chunk.id}</code>
                </div>

                {showExtractionSettings && isGraphEnabled && (
                    <div style={{ marginBottom: '1.25rem' }}>
                        <GraphExtractionSettings
                            graphParams={graphParams}
                            onParamsChange={setGraphParams}
                            onManageExamples={() => setShowExampleModal(true)}
                            onEditPrompt={() => setShowPromptModal(true)}
                            showEntitySample={false}
                            showExtractorType={false}
                        />
                        
                        {/* Extract Button */}
                        <div style={{ textAlign: 'center', marginTop: '1rem' }}>
                            <button
                                className="btn btn-primary"
                                onClick={handleExtract}
                                disabled={isExtracting}
                                style={{
                                    padding: '0.65rem 2rem',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '0.5rem',
                                    fontSize: '0.9rem',
                                    fontWeight: 600
                                }}
                            >
                                <FlaskConical size={16} />
                                {isExtracting ? 'Extracting...' : (selectionText ? 'Extract (Selection)' : 'Extract')}
                            </button>
                        </div>
                    </div>
                )}

                {/* Extracted Triples Results */}
                {showResults && extractedTriples.length > 0 && (
                    <div style={{ marginBottom: '1.25rem', background: '#eff6ff', padding: '1rem', borderRadius: '12px', border: '1px solid #bfdbfe' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                            <span style={{ fontWeight: 600, color: '#1e40af', fontSize: '0.9rem' }}>
                                🔹 Extracted Triples ({extractedTriples.length} results, {selectedTriples.size} selected)
                            </span>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                <button
                                    className="btn btn-primary"
                                    onClick={handleApplyTriples}
                                    disabled={selectedTriples.size === 0 || isSavingTriples}
                                    style={{
                                        padding: '0.25rem 0.75rem',
                                        fontSize: '0.75rem',
                                        minWidth: '80px'
                                    }}
                                >
                                    {isSavingTriples ? 'Saving...' : `Apply (${selectedTriples.size})`}
                                </button>
                                <button
                                    className="btn"
                                    onClick={() => setShowResults(false)}
                                    style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
                                >
                                    Hide
                                </button>
                            </div>
                        </div>
                        <div style={{ /* maxHeight removed to show full list */ }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                                <thead>
                                    <tr style={{ backgroundColor: '#dbeafe' }}>
                                        <th style={{ padding: '8px', textAlign: 'center', borderBottom: '1px solid #bfdbfe', width: '40px' }}>
                                            <input
                                                type="checkbox"
                                                checked={selectedTriples.size === extractedTriples.length && extractedTriples.length > 0}
                                                onChange={handleToggleAll}
                                                style={{ width: '1rem', height: '1rem', cursor: 'pointer' }}
                                            />
                                        </th>
                                        <th style={{ padding: '8px', textAlign: 'left', borderBottom: '1px solid #bfdbfe' }}>Subject</th>
                                        <th style={{ padding: '8px', textAlign: 'center', borderBottom: '1px solid #bfdbfe' }}>Predicate</th>
                                        <th style={{ padding: '8px', textAlign: 'left', borderBottom: '1px solid #bfdbfe' }}>Object</th>
                                        <th style={{ padding: '8px', textAlign: 'center', borderBottom: '1px solid #bfdbfe', width: '80px' }}>Conf.</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {extractedTriples.map((triple, idx) => (
                                        <tr key={idx} style={{ backgroundColor: triple.is_inverse ? '#fef9c3' : 'white' }}>
                                            <td style={{ padding: '8px', textAlign: 'center', borderBottom: '1px solid #e2e8f0' }}>
                                                <input
                                                    type="checkbox"
                                                    checked={selectedTriples.has(idx)}
                                                    onChange={() => handleToggleTriple(idx)}
                                                    style={{ width: '1rem', height: '1rem', cursor: 'pointer' }}
                                                />
                                            </td>
                                            <td style={{ padding: '8px', borderBottom: '1px solid #e2e8f0' }}>{triple.subject}</td>
                                            <td style={{ padding: '8px', textAlign: 'center', borderBottom: '1px solid #e2e8f0', fontStyle: 'italic', color: '#0284c7' }}>
                                                {triple.predicate}
                                                {triple.is_inverse && <span style={{ marginLeft: '4px', fontSize: '0.7rem', color: '#ca8a04' }}>(inv)</span>}
                                            </td>
                                            <td style={{ padding: '8px', borderBottom: '1px solid #e2e8f0' }}>{triple.object}</td>
                                            <td style={{ padding: '8px', textAlign: 'center', borderBottom: '1px solid #e2e8f0', color: '#64748b' }}>
                                                {triple.confidence?.toFixed(2) || '-'}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {showResults && extractedTriples.length === 0 && (
                    <div style={{ marginBottom: '1.25rem', background: '#fef3c7', padding: '1rem', borderRadius: '12px', border: '1px solid #f59e0b', textAlign: 'center', color: '#92400e' }}>
                        ⚠️ No triples extracted. Try different settings or text.
                    </div>
                )}

                {/* Content Area */}
                <div style={{ position: 'relative' }}>
                    {isEditing ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            <textarea
                                value={editContent}
                                onChange={(e) => setEditContent(e.target.value)}
                                style={{
                                    width: '100%',
                                    minHeight: '400px',
                                    padding: '16px',
                                    borderRadius: '8px',
                                    border: '2px solid #3b82f6',
                                    fontSize: '0.95rem',
                                    lineHeight: 1.6,
                                    fontFamily: 'inherit',
                                    resize: 'vertical',
                                    outline: 'none'
                                }}
                                autoFocus
                                disabled={isSaving}
                            />
                            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                                <button
                                    className="btn"
                                    onClick={() => setIsEditing(false)}
                                    disabled={isSaving}
                                    style={{ padding: '0.5rem 1.5rem' }}
                                >
                                    Cancel
                                </button>
                                <button
                                    className="btn btn-primary"
                                    onClick={handleSave}
                                    disabled={isSaving || !editContent.trim()}
                                    style={{ padding: '0.5rem 2rem', minWidth: '100px' }}
                                >
                                    {isSaving ? 'Saving...' : 'Save Changes'}
                                </button>
                            </div>
                        </div>
                    ) : (
                        <div
                            style={{
                                padding: '20px',
                                backgroundColor: '#f8fafc',
                                borderRadius: '10px',
                                whiteSpace: 'pre-wrap',
                                lineHeight: 1.7,
                                border: '1px solid #e2e8f0',
                                fontSize: '1rem',
                                color: '#334155',
                                maxHeight: showExtractionSettings || showResults ? '40vh' : '60vh',
                                overflowY: 'auto'
                            }}
                            ref={contentRef}
                        >
                            {chunk.content.replace(/(\r\n|\n|\r){2,}/gm, '\n')}
                        </div>
                    )}
                </div>
            </div>

            {/* Extraction Example Modal */}
            <ExtractionExampleModal
                isOpen={showExampleModal}
                onClose={() => setShowExampleModal(false)}
                initialYaml={graphParams.extraction_examples_yaml}
                onSave={(yaml) => setGraphParams(prev => ({ ...prev, extraction_examples_yaml: yaml }))}
            />

            {/* Extraction Prompt Modal */}
            <ExtractionPromptModal
                isOpen={showPromptModal}
                onClose={() => setShowPromptModal(false)}
                initialPrompt={graphParams.custom_prompt}
                onSave={(prompt) => setGraphParams(prev => ({ ...prev, custom_prompt: prompt }))}
            />
        </div>,
        document.body
    );
}
