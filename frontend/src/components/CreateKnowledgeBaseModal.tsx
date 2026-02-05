import React, { useState } from 'react';
import { X, FileText, Settings, Check, Info } from 'lucide-react';
import { kbApi } from '../services/api';

interface CreateKnowledgeBaseModalProps {
    isOpen: boolean;
    onClose: () => void;
    onCreateComplete: () => void;
}

const LabelWithTooltip = ({ label, tooltip }: { label: string, tooltip: string }) => {
    const [show, setShow] = useState(false);

    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
            <label style={{ fontSize: '0.875rem', fontWeight: 500 }}>{label}</label>
            <div
                style={{ position: 'relative', display: 'flex', alignItems: 'center' }}
                onMouseEnter={() => setShow(true)}
                onMouseLeave={() => setShow(false)}
            >
                <Info size={14} color="#9ca3af" style={{ cursor: 'help' }} />
                {show && (
                    <div style={{
                        width: '200px',
                        backgroundColor: '#333',
                        color: '#fff',
                        textAlign: 'center',
                        borderRadius: '6px',
                        padding: '0.5rem',
                        position: 'absolute',
                        zIndex: 10,
                        bottom: '125%',
                        left: '50%',
                        marginLeft: '-100px',
                        fontSize: '0.75rem',
                        fontWeight: 'normal',
                        pointerEvents: 'none',
                        boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)'
                    }}>
                        {tooltip}
                        <div style={{
                            content: '""',
                            position: 'absolute',
                            top: '100%',
                            left: '50%',
                            marginLeft: '-5px',
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

export default function CreateKnowledgeBaseModal({ isOpen, onClose, onCreateComplete }: CreateKnowledgeBaseModalProps) {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [enableGraphRag, setEnableGraphRag] = useState(false);
    const [graphBackend, setGraphBackend] = useState<'ontology' | 'neo4j'>('ontology');
    const [isCreating, setIsCreating] = useState(false);

    if (!isOpen) return null;


    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsCreating(true);
        try {
            await kbApi.create({
                name,
                description,
                chunking_strategy: 'fixed_size',
                chunking_config: {},
                metric_type: 'COSINE',
                graph_backend: enableGraphRag ? graphBackend : 'none'
            });
            onCreateComplete();
            onClose();
            // Reset form
            setName('');
            setDescription('');
            setEnableGraphRag(false);
        } catch (err) {
            console.error(err);
            alert('Failed to create Knowledge Base');
        } finally {
            setIsCreating(false);
        }
    };



    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 50
        }} onClick={onClose}>
            <div className="card" style={{ width: '100%', maxWidth: '710px', maxHeight: '90vh', overflow: 'auto' }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                    <h2 style={{ margin: 0 }}>Create Knowledge Base</h2>
                    <button className="btn" onClick={onClose} style={{ padding: '0.5rem' }}>
                        <X size={20} />
                    </button>
                </div>

                <form onSubmit={handleCreate}>
                    <div style={{ marginBottom: '1rem' }}>
                        <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>Name</label>
                        <input
                            className="input"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            required
                            placeholder="e.g. Product Manuals"
                        />
                    </div>
                    <div style={{ marginBottom: '1.5rem' }}>
                        <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>Description</label>
                        <textarea
                            className="input"
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            rows={3}
                            placeholder="Optional description..."
                        />
                    </div>

                    <div style={{ marginBottom: '1.5rem', padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid var(--border)' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', cursor: 'pointer' }}>
                            <input
                                type="checkbox"
                                checked={enableGraphRag}
                                onChange={(e) => setEnableGraphRag(e.target.checked)}
                                style={{ width: '1.25rem', height: '1.25rem' }}
                            />
                            <div>
                                <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>Enable Graph RAG (Beta)</div>
                                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                    Extracts entities & relations using LLM to build a knowledge graph.
                                    <span style={{ color: '#ef4444', marginLeft: '0.25rem' }}>
                                        Warning: Significantly increases ingestion time and cost.
                                    </span>
                                </div>
                            </div>
                        </label>

                        {enableGraphRag && (
                            <div style={{ marginTop: '1rem', paddingLeft: '2rem', borderTop: '1px solid #e2e8f0', paddingTop: '1rem' }}>
                                <label style={{ display: 'block', marginBottom: '0.75rem', fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>Graph Backend Strategy</label>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '1rem' }}>
                                    <div
                                        onClick={() => setGraphBackend('ontology')}
                                        style={{
                                            border: graphBackend === 'ontology' ? '2px solid var(--primary)' : '1px solid var(--border)',
                                            borderRadius: '8px',
                                            padding: '1rem',
                                            cursor: 'pointer',
                                            background: graphBackend === 'ontology' ? '#eff6ff' : 'white',
                                            transition: 'all 0.2s'
                                        }}
                                    >
                                        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
                                            <input
                                                type="radio"
                                                name="graph_backend"
                                                value="ontology"
                                                checked={graphBackend === 'ontology'}
                                                onChange={() => { }} // Controlled via parent div click
                                                style={{ marginTop: '0.25rem' }}
                                            />
                                            <div>
                                                <div style={{ fontSize: '0.9rem', fontWeight: 600, color: graphBackend === 'ontology' ? 'var(--primary)' : 'var(--text-primary)' }}>Using Jena+Fuseki</div>
                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                    Standard RDF-based storage. Reliable for entity-relation management and ontology features.
                                                </div>
                                            </div>
                                        </div>
                                    </div>

                                    <div
                                        onClick={() => setGraphBackend('neo4j')}
                                        style={{
                                            border: graphBackend === 'neo4j' ? '2px solid var(--primary)' : '1px solid var(--border)',
                                            borderRadius: '8px',
                                            padding: '1rem',
                                            cursor: 'pointer',
                                            background: graphBackend === 'neo4j' ? '#eff6ff' : 'white',
                                            transition: 'all 0.2s'
                                        }}
                                    >
                                        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
                                            <input
                                                type="radio"
                                                name="graph_backend"
                                                value="neo4j"
                                                checked={graphBackend === 'neo4j'}
                                                onChange={() => { }} // Controlled via parent div click
                                                style={{ marginTop: '0.25rem' }}
                                            />
                                            <div>
                                                <div style={{ fontSize: '0.9rem', fontWeight: 600, color: graphBackend === 'neo4j' ? 'var(--primary)' : 'var(--text-primary)' }}>Using Neo4j</div>
                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                    Native property graph database. Excellent for complex path analysis and link discovery.
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                            </div>
                        )}
                    </div>


                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                        <button type="button" className="btn" onClick={onClose} disabled={isCreating}>Cancel</button>
                        <button
                            type="submit"
                            className="btn btn-primary"
                            disabled={!name || isCreating}
                        >
                            {isCreating ? 'Creating...' : 'Create'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
