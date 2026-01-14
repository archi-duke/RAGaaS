import React, { useState, useEffect } from 'react';
import { X, Save, RotateCcw } from 'lucide-react';
import { kbApi } from '../services/api';

interface PromptDialogProps {
    isOpen: boolean;
    onClose: () => void;
    initialPrompt: string;
    onSave: (prompt: string) => void;
    backendType: 'ontology_plus' | 'ontology_minus' | 'neo4j';
}

export default function PromptDialog({
    isOpen,
    onClose,
    initialPrompt,
    onSave,
    backendType
}: PromptDialogProps) {
    const [prompt, setPrompt] = useState(initialPrompt);
    const [systemDefault, setSystemDefault] = useState("");
    const [isLoading, setIsLoading] = useState(false);

    useEffect(() => {
        if (isOpen) {
            loadDefaultPrompt();
        }
    }, [isOpen, backendType]);

    // Update prompt when initialPrompt changes (but only if it has a value)
    useEffect(() => {
        if (initialPrompt) {
            setPrompt(initialPrompt);
        } else if (systemDefault && !prompt) {
            // If initial is empty and we have system default, use it
            setPrompt(systemDefault);
        }
    }, [initialPrompt]);

    const loadDefaultPrompt = async () => {
        setIsLoading(true);
        try {
            const res = await kbApi.getQueryPrompt(backendType);
            const content = res.data.content;
            setSystemDefault(content);

            // If user hasn't set a custom prompt yet (initialPrompt is empty), show system default
            if (!initialPrompt) {
                setPrompt(content);
            }
        } catch (error) {
            console.error("Failed to load default prompt:", error);
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
            zIndex: 65
        }} onClick={onClose}>
            <div className="card" style={{ width: '800px', height: '85vh', display: 'flex', flexDirection: 'column' }} onClick={e => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Save size={20} color="#3b82f6" />
                        <h3 style={{ margin: 0 }}>Edit Query Prompt</h3>
                    </div>
                    <button className="btn" onClick={onClose} style={{ padding: '0.4rem' }}>
                        <X size={18} />
                    </button>
                </div>

                <p style={{ fontSize: '0.85rem', color: '#64748b', marginBottom: '1rem' }}>
                    Customize the instructions given to the LLM for generating graph queries (SPARQL/Cypher).
                </p>

                <div style={{ flex: 1, marginBottom: '1rem', position: 'relative', overflow: 'hidden' }}>
                    <textarea
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
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
                        placeholder="Enter custom instructions for query generation..."
                    />
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <button
                        className="btn"
                        onClick={() => setPrompt(systemDefault)}
                        title="Reset to default"
                        style={{ color: '#64748b', fontSize: '0.85rem' }}
                    >
                        <RotateCcw size={14} />
                        Reset Default
                    </button>

                    <div style={{ display: 'flex', gap: '1rem' }}>
                        <button className="btn" onClick={onClose}>Cancel</button>
                        <button
                            className="btn btn-primary"
                            onClick={() => {
                                onSave(prompt);
                                onClose();
                            }}
                        >
                            Save Changes
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
