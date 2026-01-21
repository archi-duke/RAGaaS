import React, { useState, useEffect } from 'react';
import { X, Save, AlertTriangle } from 'lucide-react';

interface ExtractionExampleModalProps {
    isOpen: boolean;
    onClose: () => void;
    initialYaml: string;
    onSave: (yaml: string) => void;
}

export default function ExtractionExampleModal({ isOpen, onClose, initialYaml, onSave }: ExtractionExampleModalProps) {
    const [yamlContent, setYamlContent] = useState(initialYaml);
    const [isValid, setIsValid] = useState(true);
    const [errorMsg, setErrorMsg] = useState('');

    useEffect(() => {
        setYamlContent(initialYaml);
    }, [initialYaml, isOpen]);

    const handleSave = () => {
        // Basic validation (check if not empty if required, or simple structure check)
        // For now, we trust the user or let the backend handle detailed validation errors
        // But let's check basic YAML structure superficially
        if (yamlContent.trim() && !yamlContent.includes(':')) {
            setIsValid(false);
            setErrorMsg("Invalid YAML format. It should contain keys and values (e.g., 'key: value').");
            return;
        }

        onSave(yamlContent);
        onClose();
    };

    if (!isOpen) return null;

    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 60 // Higher than UploadDocumentModal
        }} onClick={onClose}>
            <div className="card" style={{ width: '90%', maxWidth: '600px', maxHeight: '80vh', display: 'flex', flexDirection: 'column' }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', borderBottom: '1px solid #e2e8f0', paddingBottom: '0.75rem' }}>
                    <h3 style={{ margin: 0 }}>Manage Extraction Examples</h3>
                    <button className="btn" onClick={onClose} style={{ padding: '0.25rem' }}>
                        <X size={20} />
                    </button>
                </div>

                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1rem' }}>
                    <label style={{ fontSize: '0.85rem', color: '#64748b' }}>
                        Provide few-shot examples in YAML format to guide the extraction.
                    </label>
                    <textarea
                        className="input"
                        value={yamlContent}
                        onChange={(e) => {
                            setYamlContent(e.target.value);
                            setIsValid(true);
                            setErrorMsg('');
                        }}
                        placeholder={`- text: "Seong Gi-hun is Oh Il-nam's gganbu."\n  triplets:\n    - ["Seong Gi-hun", "gganbu", "Oh Il-nam"]`}
                        style={{
                            width: '100%',
                            flex: 1,
                            minHeight: '300px',
                            fontFamily: 'monospace',
                            fontSize: '0.85rem',
                            resize: 'none',
                            padding: '1rem',
                            lineHeight: '1.5',
                            border: isValid ? '1px solid #e2e8f0' : '1px solid #ef4444'
                        }}
                    />
                    {!isValid && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', color: '#ef4444', fontSize: '0.8rem' }}>
                            <AlertTriangle size={14} />
                            <span>{errorMsg}</span>
                        </div>
                    )}
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', borderTop: '1px solid #e2e8f0', paddingTop: '1rem' }}>
                    <button className="btn" onClick={onClose}>Cancel</button>
                    <button className="btn btn-primary" onClick={handleSave} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <Save size={16} />
                        Save Examples
                    </button>
                </div>
            </div>
        </div>
    );
}
