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
    const [strategy, setStrategy] = useState('size');
    const [config, setConfig] = useState({
        chunk_size: 500,
        overlap: 100,
        parent_size: 2000,
        child_size: 500,
        parent_overlap: 0,
        child_overlap: 100,
        h1: true,
        h2: true,
        h3: true,
        semantic_mode: false,
        buffer_size: 1,
        breakpoint_type: 'percentile',
        breakpoint_amount: 95,
        // Graph RAG settings
        graph_section_size: 2500,
        graph_section_overlap: 1000
    });
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
                chunking_strategy: strategy,
                chunking_config: config,
                metric_type: 'COSINE',
                graph_backend: enableGraphRag ? graphBackend : 'none'
            });
            onCreateComplete();
            onClose();
            // Reset form
            setName('');
            setDescription('');
            setStrategy('size');
            setEnableGraphRag(false);
        } catch (err) {
            console.error(err);
            alert('Failed to create Knowledge Base');
        } finally {
            setIsCreating(false);
        }
    };

    const strategies = [
        {
            id: 'size',
            name: 'Fixed Size',
            description: 'Chunks text into fixed-size segments with overlap.',
            icon: <FileText size={20} />
        },
        {
            id: 'parent_child',
            name: 'Parent-Child',
            description: 'Creates large parent chunks for context and small child chunks for retrieval.',
            icon: <Settings size={20} />
        },
        {
            id: 'context_aware',
            name: 'Context Aware',
            description: 'Splits text based on document structure (headers, markdown).',
            icon: <FileText size={20} />
        }
    ];

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

                                {/* Graph Extraction Settings */}
                                <div style={{ marginTop: '1rem', padding: '1rem', background: '#f1f5f9', borderRadius: '8px' }}>
                                    <label style={{ display: 'block', marginBottom: '0.75rem', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Graph Extraction Settings</label>
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                        <div>
                                            <LabelWithTooltip
                                                label="Section Size"
                                                tooltip="Size of text sections for graph extraction (in characters). Larger sections provide more context for better entity/relation extraction. Recommended: 2500 (~600 tokens)"
                                            />
                                            <input
                                                type="number"
                                                className="input"
                                                value={config.graph_section_size}
                                                onChange={(e) => setConfig({ ...config, graph_section_size: parseInt(e.target.value) })}
                                            />
                                        </div>
                                        <div>
                                            <LabelWithTooltip
                                                label="Section Overlap"
                                                tooltip="Overlap between sections to preserve cross-boundary context. Default: 500 characters"
                                            />
                                            <input
                                                type="number"
                                                className="input"
                                                value={config.graph_section_overlap}
                                                onChange={(e) => setConfig({ ...config, graph_section_overlap: parseInt(e.target.value) })}
                                            />
                                        </div>
                                    </div>
                                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                                        Larger sections capture more context for accurate entity/relation extraction across chunk boundaries.
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>

                    <div style={{ marginBottom: '2rem' }}>
                        <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>Chunking Strategy</label>
                        <div style={{ display: 'grid', gap: '1rem', marginBottom: '1.5rem' }}>
                            {strategies.map((s) => (
                                <div key={s.id}>
                                    <div
                                        onClick={() => setStrategy(s.id)}
                                        style={{
                                            border: strategy === s.id ? '2px solid var(--primary)' : '1px solid var(--border)',
                                            borderRadius: '8px',
                                            padding: '1rem',
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'flex-start',
                                            gap: '1rem',
                                            background: strategy === s.id ? '#eff6ff' : 'white',
                                            transition: 'all 0.2s'
                                        }}
                                    >
                                        <div style={{
                                            color: strategy === s.id ? 'var(--primary)' : 'var(--text-secondary)',
                                            marginTop: '0.125rem'
                                        }}>
                                            {s.icon}
                                        </div>
                                        <div style={{ flex: 1 }}>
                                            <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>{s.name}</div>
                                            <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>{s.description}</div>
                                        </div>
                                        {strategy === s.id && (
                                            <div style={{ color: 'var(--primary)' }}>
                                                <Check size={20} />
                                            </div>
                                        )}
                                    </div>

                                    {/* Inline Configuration Form */}
                                    {strategy === s.id && (
                                        <div style={{
                                            marginTop: '0.5rem',
                                            marginLeft: '1rem',
                                            padding: '1.5rem',
                                            background: '#f8fafc',
                                            borderRadius: '8px',
                                            border: '1px solid var(--border)',
                                            borderLeft: '4px solid var(--primary)'
                                        }}>
                                            <h4 style={{ margin: '0 0 1rem 0', fontSize: '0.875rem', textTransform: 'uppercase', color: 'var(--text-secondary)', letterSpacing: '0.05em' }}>
                                                {s.name} Settings
                                            </h4>

                                            {s.id === 'size' && (
                                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                                    <div>
                                                        <LabelWithTooltip
                                                            label="Chunk Size"
                                                            tooltip="The maximum number of characters in each chunk."
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.chunk_size}
                                                            onChange={(e) => setConfig({ ...config, chunk_size: parseInt(e.target.value) })}
                                                        />
                                                    </div>
                                                    <div>
                                                        <LabelWithTooltip
                                                            label="Overlap"
                                                            tooltip="The number of characters to overlap between chunks to maintain context."
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.overlap}
                                                            onChange={(e) => setConfig({ ...config, overlap: parseInt(e.target.value) })}
                                                        />
                                                    </div>
                                                </div>
                                            )}

                                            {s.id === 'parent_child' && (
                                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                                    <div>
                                                        <LabelWithTooltip
                                                            label="Parent Chunk Size"
                                                            tooltip="Size of the larger parent chunks used for context retrieval."
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.parent_size}
                                                            onChange={(e) => setConfig({ ...config, parent_size: parseInt(e.target.value) })}
                                                        />
                                                    </div>
                                                    <div>
                                                        <LabelWithTooltip
                                                            label="Child Chunk Size"
                                                            tooltip="Size of the smaller child chunks used for precise matching."
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.child_size}
                                                            onChange={(e) => setConfig({ ...config, child_size: parseInt(e.target.value) })}
                                                        />
                                                    </div>
                                                    <div>
                                                        <LabelWithTooltip
                                                            label="Parent Overlap"
                                                            tooltip="Overlap for parent chunks."
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.parent_overlap}
                                                            onChange={(e) => setConfig({ ...config, parent_overlap: parseInt(e.target.value) })}
                                                        />
                                                    </div>
                                                    <div>
                                                        <LabelWithTooltip
                                                            label="Child Overlap"
                                                            tooltip="Overlap for child chunks."
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.child_overlap}
                                                            onChange={(e) => setConfig({ ...config, child_overlap: parseInt(e.target.value) })}
                                                        />
                                                    </div>
                                                </div>
                                            )}

                                            {s.id === 'context_aware' && (
                                                <div>
                                                    <div style={{ marginBottom: '1rem', display: 'flex', gap: '1rem' }}>
                                                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                                            <input
                                                                type="radio"
                                                                name="context_mode"
                                                                checked={!config.semantic_mode}
                                                                onChange={() => setConfig({ ...config, semantic_mode: false })}
                                                            />
                                                            Split by Headers
                                                        </label>
                                                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                                            <input
                                                                type="radio"
                                                                name="context_mode"
                                                                checked={config.semantic_mode}
                                                                onChange={() => setConfig({ ...config, semantic_mode: true })}
                                                            />
                                                            Semantic Split (LLM)
                                                        </label>
                                                    </div>

                                                    {!config.semantic_mode ? (
                                                        <div>
                                                            <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>Header Levels</label>
                                                            <div style={{ display: 'flex', gap: '1.5rem' }}>
                                                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                                                    <input
                                                                        type="checkbox"
                                                                        checked={config.h1}
                                                                        onChange={(e) => setConfig({ ...config, h1: e.target.checked })}
                                                                    />
                                                                    H1 (#)
                                                                </label>
                                                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                                                    <input
                                                                        type="checkbox"
                                                                        checked={config.h2}
                                                                        onChange={(e) => setConfig({ ...config, h2: e.target.checked })}
                                                                    />
                                                                    H2 (##)
                                                                </label>
                                                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                                                    <input
                                                                        type="checkbox"
                                                                        checked={config.h3}
                                                                        onChange={(e) => setConfig({ ...config, h3: e.target.checked })}
                                                                    />
                                                                    H3 (###)
                                                                </label>
                                                            </div>
                                                        </div>
                                                    ) : (
                                                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                                            <div>
                                                                <LabelWithTooltip
                                                                    label="Buffer Size"
                                                                    tooltip="Number of sentences to group together for comparison. Larger buffer reduces noise."
                                                                />
                                                                <input
                                                                    type="number"
                                                                    className="input"
                                                                    value={config.buffer_size}
                                                                    onChange={(e) => setConfig({ ...config, buffer_size: parseInt(e.target.value) })}
                                                                />
                                                            </div>
                                                            <div>
                                                                <LabelWithTooltip
                                                                    label="Threshold Type"
                                                                    tooltip="Method to determine the split point based on semantic similarity."
                                                                />
                                                                <select
                                                                    className="input"
                                                                    value={config.breakpoint_type}
                                                                    onChange={(e) => setConfig({ ...config, breakpoint_type: e.target.value })}
                                                                >
                                                                    <option value="percentile">Percentile</option>
                                                                    <option value="standard_deviation">Standard Deviation</option>
                                                                    <option value="interquartile">Interquartile</option>
                                                                </select>
                                                            </div>
                                                            <div>
                                                                <LabelWithTooltip
                                                                    label="Threshold Amount"
                                                                    tooltip="Sensitivity of the split. Higher values create smaller, more granular chunks."
                                                                />
                                                                <input
                                                                    type="number"
                                                                    className="input"
                                                                    value={config.breakpoint_amount}
                                                                    onChange={(e) => setConfig({ ...config, breakpoint_amount: parseFloat(e.target.value) })}
                                                                />
                                                            </div>
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
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
