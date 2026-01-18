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
    const [strategy, setStrategy] = useState('fixed_size');
    const [config, setConfig] = useState({
        chunk_size: 1024,
        chunk_overlap: 20,
        // Sliding Window
        window_size: 3,
        // Hierarchical
        chunk_sizes: [2048, 512, 128],
        // Semantic
        buffer_size: 1,
        breakpoint_threshold: 95,
        // Legacy (for backward compatibility)
        parent_size: 2000,
        child_size: 500,
        parent_overlap: 0,
        child_overlap: 100,
        h1: true,
        h2: true,
        h3: true,
        semantic_mode: false,
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
            id: 'fixed_size',
            name: 'Fixed Size',
            description: 'SentenceSplitter - 고정 크기로 문장 경계를 유지하며 분할',
            icon: <FileText size={20} />
        },
        {
            id: 'sliding_window',
            name: 'Sliding Window',
            description: 'SentenceWindowNodeParser - 문장 주변 윈도우 컨텍스트 포함',
            icon: <Settings size={20} />
        },
        {
            id: 'hierarchical',
            name: 'Hierarchical',
            description: 'HierarchicalNodeParser - 다층 계층 구조로 분할 (2048→512→128)',
            icon: <Settings size={20} />
        },
        {
            id: 'semantic',
            name: 'Semantic',
            description: 'SemanticSplitterNodeParser - 의미적 유사도 기반 분할',
            icon: <FileText size={20} />
        },
        {
            id: 'markdown',
            name: 'Markdown / Section',
            description: 'MarkdownNodeParser - 문서 구조(헤더) 기반 분할',
            icon: <FileText size={20} />
        },
        {
            id: 'hybrid',
            name: 'Hybrid',
            description: 'Markdown + Fixed Size 복합 전략',
            icon: <Settings size={20} />
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

                                            {s.id === 'fixed_size' && (
                                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                                    <div>
                                                        <LabelWithTooltip
                                                            label="Chunk Size"
                                                            tooltip="청크당 최대 문자 수"
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
                                                            label="Chunk Overlap"
                                                            tooltip="청크 간 겹치는 문자 수"
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.chunk_overlap}
                                                            onChange={(e) => setConfig({ ...config, chunk_overlap: parseInt(e.target.value) })}
                                                        />
                                                    </div>
                                                </div>
                                            )}

                                            {s.id === 'sliding_window' && (
                                                <div>
                                                    <LabelWithTooltip
                                                        label="Window Size"
                                                        tooltip="각 문장 주변에 포함할 문장 수 (기본: 3)"
                                                    />
                                                    <input
                                                        type="number"
                                                        className="input"
                                                        value={config.window_size}
                                                        onChange={(e) => setConfig({ ...config, window_size: parseInt(e.target.value) })}
                                                        min={1}
                                                        max={10}
                                                    />
                                                </div>
                                            )}

                                            {s.id === 'hierarchical' && (
                                                <div>
                                                    <LabelWithTooltip
                                                        label="Chunk Sizes (계층별)"
                                                        tooltip="계층별 청크 크기 (예: 2048, 512, 128)"
                                                    />
                                                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.chunk_sizes[0]}
                                                            onChange={(e) => setConfig({ ...config, chunk_sizes: [parseInt(e.target.value), config.chunk_sizes[1], config.chunk_sizes[2]] })}
                                                            placeholder="Level 1"
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.chunk_sizes[1]}
                                                            onChange={(e) => setConfig({ ...config, chunk_sizes: [config.chunk_sizes[0], parseInt(e.target.value), config.chunk_sizes[2]] })}
                                                            placeholder="Level 2"
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.chunk_sizes[2]}
                                                            onChange={(e) => setConfig({ ...config, chunk_sizes: [config.chunk_sizes[0], config.chunk_sizes[1], parseInt(e.target.value)] })}
                                                            placeholder="Level 3"
                                                        />
                                                    </div>
                                                </div>
                                            )}

                                            {s.id === 'semantic' && (
                                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                                    <div>
                                                        <LabelWithTooltip
                                                            label="Buffer Size"
                                                            tooltip="비교를 위해 그룹화할 문장 수"
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.buffer_size}
                                                            onChange={(e) => setConfig({ ...config, buffer_size: parseInt(e.target.value) })}
                                                            min={1}
                                                            max={5}
                                                        />
                                                    </div>
                                                    <div>
                                                        <LabelWithTooltip
                                                            label="Breakpoint Threshold"
                                                            tooltip="분할 포인트 결정 임계값 (50-99)"
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.breakpoint_threshold}
                                                            onChange={(e) => setConfig({ ...config, breakpoint_threshold: parseInt(e.target.value) })}
                                                            min={50}
                                                            max={99}
                                                        />
                                                    </div>
                                                </div>
                                            )}

                                            {s.id === 'markdown' && (
                                                <div style={{ padding: '0.5rem', background: '#e2e8f0', borderRadius: '4px', fontSize: '0.85rem', color: '#475569' }}>
                                                    Markdown 문서의 헤더 구조를 기반으로 자동 분할됩니다. 추가 설정이 필요 없습니다.
                                                </div>
                                            )}

                                            {s.id === 'hybrid' && (
                                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                                    <div>
                                                        <LabelWithTooltip
                                                            label="Chunk Size"
                                                            tooltip="Markdown 분할 후 큰 섹션에 적용할 최대 청크 크기"
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
                                                            label="Chunk Overlap"
                                                            tooltip="청크 간 겹치는 문자 수"
                                                        />
                                                        <input
                                                            type="number"
                                                            className="input"
                                                            value={config.chunk_overlap}
                                                            onChange={(e) => setConfig({ ...config, chunk_overlap: parseInt(e.target.value) })}
                                                        />
                                                    </div>
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
