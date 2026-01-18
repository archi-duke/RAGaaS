import React, { useState, useEffect } from 'react';
import { X, Save, RotateCcw } from 'lucide-react';

interface ExtractionPromptModalProps {
    isOpen: boolean;
    onClose: () => void;
    initialPrompt: string;
    onSave: (prompt: string) => void;
}

const DEFAULT_PROMPT = `Extract primary entities and their relationships from the following text.
Format: (Subject, Relation, Object)
Extract up to 5 triplets.
{examples}
Text:
{text}

Triplets (one per line, format: Subject|Relation|Object):`;

export default function ExtractionPromptModal({ isOpen, onClose, initialPrompt, onSave }: ExtractionPromptModalProps) {
    const [promptContent, setPromptContent] = useState(initialPrompt || DEFAULT_PROMPT);

    useEffect(() => {
        setPromptContent(initialPrompt || DEFAULT_PROMPT);
    }, [initialPrompt, isOpen]);

    const handleSave = () => {
        onSave(promptContent);
        onClose();
    };

    const handleReset = () => {
        if (confirm("Are you sure you want to reset to the default prompt?")) {
            setPromptContent(DEFAULT_PROMPT);
        }
    };

    if (!isOpen) return null;

    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 60 // Higher than UploadDocumentModal
        }} onClick={onClose}>
            <div className="card" style={{ width: '90%', maxWidth: '700px', maxHeight: '85vh', display: 'flex', flexDirection: 'column' }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', borderBottom: '1px solid #e2e8f0', paddingBottom: '0.75rem' }}>
                    <h3 style={{ margin: 0 }}>Edit Extraction Prompt</h3>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button className="btn" onClick={handleReset} title="Reset to Default" style={{ padding: '0.25rem' }}>
                            <RotateCcw size={18} />
                        </button>
                        <button className="btn" onClick={onClose} style={{ padding: '0.25rem' }}>
                            <X size={20} />
                        </button>
                    </div>
                </div>

                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1rem' }}>
                    <label style={{ fontSize: '0.85rem', color: '#64748b' }}>
                        Customize the LlamaIndex extraction prompt. Use <code>{`{text}`}</code> for the chunk content and <code>{`{examples}`}</code> for few-shot examples.
                    </label>
                    <textarea
                        className="input"
                        value={promptContent}
                        onChange={(e) => setPromptContent(e.target.value)}
                        style={{
                            width: '100%',
                            flex: 1,
                            minHeight: '350px',
                            fontFamily: 'monospace',
                            fontSize: '0.85rem',
                            resize: 'none',
                            padding: '1rem',
                            lineHeight: '1.5',
                            whiteSpace: 'pre-wrap'
                        }}
                    />
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', borderTop: '1px solid #e2e8f0', paddingTop: '1rem' }}>
                    <button className="btn" onClick={onClose}>Cancel</button>
                    <button className="btn btn-primary" onClick={handleSave} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <Save size={16} />
                        Save Prompt
                    </button>
                </div>
            </div>
        </div>
    );
}
