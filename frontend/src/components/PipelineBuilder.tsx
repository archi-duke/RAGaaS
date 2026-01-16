import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Plus, X, ChevronLeft, ChevronRight, GripVertical } from 'lucide-react';

// Stage type definitions
export type StageType = 'ann' | 'bm25' | 'brute_force' | 'graph' | 'rerank' | 'ner_filter';

export interface PipelineStage {
    type: StageType;
    params: Record<string, any>;
}

export interface PipelineConfig {
    stages: PipelineStage[];
}

interface PipelineBuilderProps {
    kbId: string;
    graphBackend?: string;
    isOntologyPromoted?: boolean;
    initialConfig?: PipelineConfig;
    onPipelineChange: (config: PipelineConfig) => void;
}

// Stage metadata
const SEARCH_STAGES: { type: StageType; label: string; category: 'search' }[] = [
    { type: 'ann', label: 'Vector (ANN)', category: 'search' },
    { type: 'bm25', label: 'Keyword (BM25)', category: 'search' },
    { type: 'brute_force', label: 'Brute Force', category: 'search' },
    { type: 'graph', label: 'Graph', category: 'search' },
];

const FILTER_STAGES: { type: StageType; label: string; category: 'filter' }[] = [
    { type: 'rerank', label: 'Re-Rank', category: 'filter' },
    { type: 'ner_filter', label: 'NER Filter', category: 'filter' },
];

const DEFAULT_PARAMS: Record<StageType, Record<string, any>> = {
    ann: { top_k: 10, threshold: 0.5, index_type: 'IVF_FLAT' },
    bm25: { top_k: 50, use_multi_pos: true },
    brute_force: { top_k: 3, threshold: 1.5 },
    graph: { hops: 2, use_relation_filter: true, enable_inverse: false, use_schema_mode: true },
    rerank: { top_k: 5, threshold: 0.0, use_llm: false, llm_strategy: 'full' },
    ner_filter: { penalty: 0.3 },
};

// Styles
const cardStyle: React.CSSProperties = {
    backgroundColor: 'white',
    border: '1px solid #e2e8f0',
    borderRadius: '12px',
    padding: '1rem',
    minWidth: '180px',
    position: 'relative',
};

const addButtonStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '48px',
    height: '48px',
    borderRadius: '50%',
    border: '2px dashed #cbd5e1',
    backgroundColor: '#f8fafc',
    cursor: 'pointer',
    transition: 'all 0.2s',
};

export default function PipelineBuilder({
    kbId,
    graphBackend,
    isOntologyPromoted,
    initialConfig,
    onPipelineChange
}: PipelineBuilderProps) {
    const [stages, setStages] = useState<PipelineStage[]>(initialConfig?.stages || []);
    const [showDropdown, setShowDropdown] = useState(false);
    const [isLoading, setIsLoading] = useState(true);

    // Rerank Prompt Editor state
    const [showRerankPromptModal, setShowRerankPromptModal] = useState(false);
    const [rerankPrompt, setRerankPrompt] = useState('');
    const [isLoadingPrompt, setIsLoadingPrompt] = useState(false);
    const [promptError, setPromptError] = useState('');

    // Determine if we have any search stages
    const hasSearchStage = stages.some(s =>
        ['ann', 'bm25', 'brute_force', 'graph'].includes(s.type)
    );

    // Available stages based on current state
    const availableStages = hasSearchStage
        ? [...SEARCH_STAGES, ...FILTER_STAGES]
        : SEARCH_STAGES;

    // Filter graph if no graph backend
    const filteredStages = graphBackend && graphBackend !== 'none'
        ? availableStages
        : availableStages.filter(s => s.type !== 'graph');

    // Load pipeline config from backend on mount
    useEffect(() => {
        const loadPipeline = async () => {
            try {
                const response = await fetch(`/api/knowledge-bases/${kbId}/pipeline`);
                if (response.ok) {
                    const config = await response.json();
                    if (config.stages && config.stages.length > 0) {
                        setStages(config.stages);
                    }
                }
            } catch (error) {
                console.error('Failed to load pipeline config:', error);
            } finally {
                setIsLoading(false);
            }
        };
        loadPipeline();
    }, [kbId]);

    // Save pipeline config to backend (debounced)
    useEffect(() => {
        if (isLoading) return; // Don't save during initial load

        const saveTimeout = setTimeout(async () => {
            try {
                await fetch(`/api/knowledge-bases/${kbId}/pipeline`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ stages })
                });
            } catch (error) {
                console.error('Failed to save pipeline config:', error);
            }
        }, 500); // Debounce 500ms

        return () => clearTimeout(saveTimeout);
    }, [stages, kbId, isLoading]);

    // Notify parent of changes
    useEffect(() => {
        onPipelineChange({ stages });
    }, [stages, onPipelineChange]);

    // --- Rerank Prompt Functions ---
    const loadRerankPrompt = async () => {
        setIsLoadingPrompt(true);
        setPromptError('');
        try {
            const response = await fetch('/api/knowledge-bases/settings/rerank-prompt');
            if (!response.ok) throw new Error('Failed to load prompt');
            const data = await response.json();
            setRerankPrompt(data.content);
        } catch (e: any) {
            setPromptError(e.message || 'Failed to load prompt');
        } finally {
            setIsLoadingPrompt(false);
        }
    };

    const openRerankPromptEditor = () => {
        loadRerankPrompt();
        setShowRerankPromptModal(true);
    };

    const saveRerankPrompt = async () => {
        setIsLoadingPrompt(true);
        setPromptError('');
        try {
            const response = await fetch('/api/knowledge-bases/settings/rerank-prompt', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: rerankPrompt })
            });
            if (!response.ok) throw new Error('Failed to save prompt');
            setShowRerankPromptModal(false);
        } catch (e: any) {
            setPromptError(e.message || 'Failed to save prompt');
        } finally {
            setIsLoadingPrompt(false);
        }
    };
    // --- End Rerank Prompt Functions ---

    const handleAddStage = (type: StageType) => {
        const newStage: PipelineStage = {
            type,
            params: { ...DEFAULT_PARAMS[type] }
        };
        setStages([...stages, newStage]);
        setShowDropdown(false);
    };

    const handleRemoveStage = (index: number) => {
        setStages(stages.filter((_, i) => i !== index));
    };

    const handleMoveStage = (index: number, direction: 'left' | 'right') => {
        const newIndex = direction === 'left' ? index - 1 : index + 1;
        if (newIndex < 0 || newIndex >= stages.length) return;

        const newStages = [...stages];
        [newStages[index], newStages[newIndex]] = [newStages[newIndex], newStages[index]];
        setStages(newStages);
    };

    const handleParamChange = (index: number, param: string, value: any) => {
        const newStages = [...stages];
        newStages[index] = {
            ...newStages[index],
            params: { ...newStages[index].params, [param]: value }
        };
        setStages(newStages);
    };

    const renderStageCard = (stage: PipelineStage, index: number) => {
        const stageInfo = [...SEARCH_STAGES, ...FILTER_STAGES].find(s => s.type === stage.type);
        const isSearch = SEARCH_STAGES.some(s => s.type === stage.type);

        return (
            <div key={index} style={cardStyle}>
                {/* Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.15rem' }}>
                        <button
                            onClick={() => handleMoveStage(index, 'left')}
                            disabled={index === 0}
                            style={{
                                background: 'none',
                                border: 'none',
                                cursor: index === 0 ? 'not-allowed' : 'pointer',
                                opacity: index === 0 ? 0.3 : 1,
                                color: '#64748b',
                                padding: '2px',
                                display: 'flex',
                                alignItems: 'center'
                            }}
                        >
                            <ChevronLeft size={16} />
                        </button>

                        <span style={{
                            fontWeight: 600,
                            fontSize: '0.9rem',
                            color: isSearch ? '#1e40af' : '#7c3aed',
                            margin: '0 2px'
                        }}>
                            {stageInfo?.label || stage.type}
                        </span>

                        <button
                            onClick={() => handleMoveStage(index, 'right')}
                            disabled={index === stages.length - 1}
                            style={{
                                background: 'none',
                                border: 'none',
                                cursor: index === stages.length - 1 ? 'not-allowed' : 'pointer',
                                opacity: index === stages.length - 1 ? 0.3 : 1,
                                color: '#64748b',
                                padding: '2px',
                                display: 'flex',
                                alignItems: 'center'
                            }}
                        >
                            <ChevronRight size={16} />
                        </button>
                    </div>

                    <button
                        onClick={() => handleRemoveStage(index)}
                        style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            color: '#94a3b8',
                            padding: '2px',
                            display: 'flex',
                            alignItems: 'center'
                        }}
                    >
                        <X size={16} />
                    </button>
                </div>

                {/* Stage-specific params */}
                {renderStageParams(stage, index)}
            </div>
        );
    };

    const renderStageParams = (stage: PipelineStage, index: number) => {
        const params = stage.params;

        switch (stage.type) {
            case 'ann':
                return (
                    <div style={{ display: 'flex', flexDirection: 'row', gap: '0.5rem', alignItems: 'flex-start' }}>
                        <ParamSlider
                            label="Top K"
                            value={params.top_k}
                            min={1} max={20}
                            onChange={(v) => handleParamChange(index, 'top_k', v)}
                        />
                        <ParamSlider
                            label="Threshold"
                            value={params.threshold}
                            min={0} max={1} step={0.05}
                            onChange={(v) => handleParamChange(index, 'threshold', v)}
                        />
                        <div style={{ paddingLeft: '0.5rem', paddingTop: '0.2rem' }}>
                            <ParamSelect
                                label="Index Type"
                                value={params.index_type || 'IVF_FLAT'}
                                options={[
                                    { value: 'FLAT', label: 'FLAT' },
                                    { value: 'IVF_FLAT', label: 'IVF_FLAT' },
                                    { value: 'HNSW', label: 'HNSW' },
                                    { value: 'LSH', label: 'LSH' }
                                ]}
                                onChange={(v) => handleParamChange(index, 'index_type', v)}
                            />
                        </div>
                    </div>
                );


            case 'bm25':
                return (
                    <div style={{ display: 'flex', flexDirection: 'row', gap: '0.5rem', alignItems: 'flex-start' }}>
                        <ParamSlider
                            label="Top K"
                            value={params.top_k}
                            min={1} max={100}
                            onChange={(v) => handleParamChange(index, 'top_k', v)}
                        />
                        <ParamCheckbox
                            label="Multi-POS"
                            checked={params.use_multi_pos}
                            onChange={(v) => handleParamChange(index, 'use_multi_pos', v)}
                        />
                    </div>
                );

            case 'brute_force':
                return (
                    <div style={{ display: 'flex', flexDirection: 'row', gap: '0.5rem', alignItems: 'flex-start' }}>
                        <ParamSlider
                            label="Top K"
                            value={params.top_k}
                            min={1} max={10}
                            onChange={(v) => handleParamChange(index, 'top_k', v)}
                        />
                        <ParamSlider
                            label="L2 Threshold"
                            value={params.threshold}
                            min={0.1} max={3} step={0.1}
                            onChange={(v) => handleParamChange(index, 'threshold', v)}
                        />
                    </div>
                );

            case 'graph':
                return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                        <ParamSlider
                            label="Hops"
                            value={params.hops}
                            min={1} max={5}
                            onChange={(v) => handleParamChange(index, 'hops', v)}
                        />
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                            <ParamCheckbox
                                label="Relation Filter"
                                checked={params.use_relation_filter}
                                onChange={(v) => handleParamChange(index, 'use_relation_filter', v)}
                            />
                            <ParamCheckbox
                                label="Inverse Relations"
                                checked={params.enable_inverse}
                                onChange={(v) => handleParamChange(index, 'enable_inverse', v)}
                            />
                            {isOntologyPromoted && (
                                <ParamCheckbox
                                    label="Schema Mode"
                                    checked={params.use_schema_mode}
                                    onChange={(v) => handleParamChange(index, 'use_schema_mode', v)}
                                />
                            )}
                        </div>
                    </div>
                );

            case 'rerank':
                return (
                    <div style={{ display: 'flex', flexDirection: 'row', gap: '0.5rem', alignItems: 'flex-start' }}>
                        <ParamSlider
                            label="Top K"
                            value={params.top_k}
                            min={1} max={20}
                            onChange={(v) => handleParamChange(index, 'top_k', v)}
                        />
                        <ParamSlider
                            label="Threshold"
                            value={params.threshold}
                            min={0} max={1} step={0.05}
                            onChange={(v) => handleParamChange(index, 'threshold', v)}
                        />
                        <div style={{
                            paddingTop: '0.5rem',
                            paddingLeft: '0.5rem',
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'flex-start',
                            gap: '0.75rem'
                        }}>
                            <ParamCheckbox
                                label="Use LLM"
                                checked={params.use_llm}
                                onChange={(v) => handleParamChange(index, 'use_llm', v)}
                            />
                            <div style={{ marginLeft: '0.3rem' }}>
                                <ParamSelect
                                    label="LLM Strategy"
                                    value={params.llm_strategy || 'full'}
                                    options={[
                                        { value: 'full', label: 'Full' },
                                        { value: 'limited', label: 'Limited' }
                                    ]}
                                    onChange={(v) => handleParamChange(index, 'llm_strategy', v)}
                                    disabled={!params.use_llm}
                                />
                            </div>
                            {params.use_llm && (
                                <button
                                    onClick={openRerankPromptEditor}
                                    style={{
                                        marginTop: '0.5rem',
                                        fontSize: '0.75rem',
                                        padding: '0.3rem 0.6rem',
                                        backgroundColor: '#f1f5f9',
                                        color: '#475569',
                                        border: '1px solid #e2e8f0',
                                        borderRadius: '4px',
                                        cursor: 'pointer'
                                    }}
                                >
                                    Edit Prompt
                                </button>
                            )}
                        </div>
                    </div>
                );

            case 'ner_filter':
                return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        <ParamSlider
                            label="Penalty"
                            value={params.penalty}
                            min={0} max={1} step={0.05}
                            onChange={(v) => handleParamChange(index, 'penalty', v)}
                        />
                    </div>
                );

            default:
                return null;
        }
    };

    return (
        <div className="card" style={{
            padding: '1rem',
            overflow: 'visible',
            position: 'relative',
            zIndex: 100
        }}>
            <h3 style={{ marginTop: 0, marginBottom: '1rem', fontSize: '1.1rem', fontWeight: 600 }}>
                Search Pipeline
            </h3>

            {/* Wrapper for stages and add button */}
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start', overflow: 'visible' }}>
                {/* Scrollable stages container */}
                <div style={{
                    display: 'flex',
                    gap: '0.5rem',
                    alignItems: 'flex-start',
                    minHeight: '120px',
                    overflowX: 'auto',
                    paddingBottom: '0.5rem'
                }}>
                    {/* Render stages */}
                    {stages.map((stage, index) => (
                        <React.Fragment key={index}>
                            {renderStageCard(stage, index)}
                            {index < stages.length - 1 && (
                                <div style={{ display: 'flex', alignItems: 'center', color: '#94a3b8', flexShrink: 0, height: '48px' }}>
                                    →
                                </div>
                            )}
                        </React.Fragment>
                    ))}
                </div>

                {/* Arrow before Add button if stages exist */}
                {stages.length > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', color: '#94a3b8', flexShrink: 0, height: '48px' }}>
                        →
                    </div>
                )}

                {/* Add button wrapper - OUTSIDE scroll container */}
                <div style={{ position: 'relative', flexShrink: 0, zIndex: 1000 }}>
                    <div
                        className="pipeline-add-button"
                        style={addButtonStyle}
                        onClick={() => setShowDropdown(!showDropdown)}
                        onMouseEnter={(e) => (e.currentTarget.style.borderColor = '#3b82f6')}
                        onMouseLeave={(e) => (e.currentTarget.style.borderColor = '#cbd5e1')}
                    >
                        <Plus size={24} style={{ color: '#64748b' }} />
                    </div>

                    {/* Dropdown - Opens to the RIGHT */}
                    {showDropdown && (
                        <div style={{
                            position: 'absolute',
                            top: 0,
                            left: 'calc(100% + 0.5rem)',
                            backgroundColor: 'white',
                            border: '1px solid #e2e8f0',
                            borderRadius: '8px',
                            boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
                            minWidth: '180px',
                            zIndex: 9999,
                            padding: '0.5rem 0'
                        }}>
                            {!hasSearchStage && (
                                <div style={{ padding: '0.25rem 1rem', fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>
                                    Search
                                </div>
                            )}
                            {hasSearchStage && (
                                <div style={{ padding: '0.25rem 1rem', fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>
                                    Add Stage
                                </div>
                            )}

                            {filteredStages.filter(s => s.category === 'search').map(stage => (
                                <div
                                    key={stage.type}
                                    onClick={() => handleAddStage(stage.type)}
                                    style={{
                                        padding: '0.5rem 1rem',
                                        cursor: 'pointer',
                                        fontSize: '0.9rem',
                                        color: '#334155'
                                    }}
                                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#f1f5f9')}
                                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                                >
                                    {stage.label}
                                </div>
                            ))}

                            {hasSearchStage && (
                                <>
                                    <div style={{ borderTop: '1px solid #e2e8f0', margin: '0.25rem 0' }} />
                                    <div style={{ padding: '0.25rem 1rem', fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>
                                        Filters
                                    </div>
                                    {filteredStages.filter(s => s.category === 'filter').map(stage => (
                                        <div
                                            key={stage.type}
                                            onClick={() => handleAddStage(stage.type)}
                                            style={{
                                                padding: '0.5rem 1rem',
                                                cursor: 'pointer',
                                                fontSize: '0.9rem',
                                                color: '#334155'
                                            }}
                                            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#f1f5f9')}
                                            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                                        >
                                            {stage.label}
                                        </div>
                                    ))}
                                </>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Empty state hint */}
            {stages.length === 0 && (
                <div style={{
                    textAlign: 'center',
                    color: '#94a3b8',
                    fontSize: '0.85rem',
                    marginTop: '0.5rem'
                }}>
                    Click + to add a search stage
                </div>
            )}

            {/* Rerank Prompt Editor Modal */}
            {showRerankPromptModal && createPortal(
                <div style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    backgroundColor: 'rgba(0, 0, 0, 0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 10000
                }}>
                    <div style={{
                        backgroundColor: 'white',
                        borderRadius: '12px',
                        padding: '1.5rem',
                        width: '700px',
                        maxHeight: '80vh',
                        display: 'flex',
                        flexDirection: 'column',
                        boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1)'
                    }}>
                        <h3 style={{ marginTop: 0, marginBottom: '1rem', fontSize: '1.1rem', fontWeight: 600 }}>
                            Edit LLM Rerank Prompt
                        </h3>
                        <p style={{ fontSize: '0.8rem', color: '#64748b', marginBottom: '0.75rem' }}>
                            Use <code style={{ backgroundColor: '#f1f5f9', padding: '0.1rem 0.3rem', borderRadius: '3px' }}>{'{query}'}</code> and <code style={{ backgroundColor: '#f1f5f9', padding: '0.1rem 0.3rem', borderRadius: '3px' }}>{'{chunk_content}'}</code> as placeholders.
                        </p>
                        {promptError && (
                            <div style={{ color: '#ef4444', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                                {promptError}
                            </div>
                        )}
                        <textarea
                            value={rerankPrompt}
                            onChange={(e) => setRerankPrompt(e.target.value)}
                            style={{
                                flex: 1,
                                minHeight: '400px',
                                width: '100%',
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
                            disabled={isLoadingPrompt}
                            placeholder="Enter custom instructions for reranking..."
                        />
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1rem' }}>
                            <button
                                onClick={() => setShowRerankPromptModal(false)}
                                style={{
                                    padding: '0.5rem 1rem',
                                    backgroundColor: '#f1f5f9',
                                    border: '1px solid #e2e8f0',
                                    borderRadius: '6px',
                                    cursor: 'pointer',
                                    fontSize: '0.9rem'
                                }}
                            >
                                Cancel
                            </button>
                            <button
                                onClick={saveRerankPrompt}
                                disabled={isLoadingPrompt}
                                style={{
                                    padding: '0.5rem 1rem',
                                    backgroundColor: '#3b82f6',
                                    color: 'white',
                                    border: 'none',
                                    borderRadius: '6px',
                                    cursor: isLoadingPrompt ? 'not-allowed' : 'pointer',
                                    fontSize: '0.9rem',
                                    fontWeight: 500
                                }}
                            >
                                {isLoadingPrompt ? 'Saving...' : 'Save Prompt'}
                            </button>
                        </div>
                    </div>
                </div>,
                document.body
            )}
        </div>
    );
}

// Helper Components
function ParamSlider({
    label,
    value,
    min,
    max,
    step = 1,
    onChange
}: {
    label: string;
    value: number;
    min: number;
    max: number;
    step?: number;
    onChange: (v: number) => void;
}) {
    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '0.2rem',
            minHeight: '120px'
        }}>
            {/* Value on Top */}
            <span style={{
                fontSize: '0.8rem',
                color: '#1e293b',
                fontWeight: 600,
                textAlign: 'center',
                minWidth: '36px',
                display: 'inline-block'
            }}>
                {step < 1 ? value.toFixed(2) : value}
            </span>

            {/* Row for Label and Slider Track */}
            <div style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                gap: 0
            }}>
                {/* Vertical Label */}
                <span style={{
                    fontSize: '0.75rem',
                    color: '#64748b',
                    fontWeight: 500,
                    writingMode: 'vertical-rl',
                    textOrientation: 'mixed',
                    marginRight: 0
                }}>
                    {label}
                </span>

                {/* Vertical Slider Track */}
                <div style={{
                    width: '24px',
                    height: '80px',
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center'
                }}>
                    <input
                        type="range"
                        min={min}
                        max={max}
                        step={step}
                        value={value}
                        onChange={(e) => onChange(Number(e.target.value))}
                        style={{
                            width: '80px',
                            height: '6px',
                            margin: 0,
                            padding: 0,
                            cursor: 'pointer',
                            accentColor: '#3b82f6',
                            transform: 'rotate(-90deg)',
                            transformOrigin: 'center',
                            background: 'transparent',
                            display: 'block'
                        } as React.CSSProperties}
                    />
                </div>
            </div>
        </div>
    );
}

function ParamCheckbox({
    label,
    checked,
    onChange
}: {
    label: string;
    checked: boolean;
    onChange: (v: boolean) => void;
}) {
    return (
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', cursor: 'pointer', color: '#475569' }}>
            <input
                type="checkbox"
                checked={checked}
                onChange={(e) => onChange(e.target.checked)}
            />
            {label}
        </label>
    );
}

function ParamSelect({
    label,
    value,
    options,
    onChange,
    disabled
}: {
    label: string;
    value: string;
    options: { value: string; label: string }[];
    onChange: (v: string) => void;
    disabled?: boolean;
}) {
    const [isOpen, setIsOpen] = React.useState(false);
    const containerRef = React.useRef<HTMLDivElement>(null);
    const [isUpward, setIsUpward] = React.useState(false);
    const [coords, setCoords] = React.useState({ top: 0, left: 0, width: 0 });

    const selectedOption = options.find(opt => opt.value === value) || options[0];

    const updatePosition = () => {
        if (containerRef.current) {
            const rect = containerRef.current.getBoundingClientRect();
            const spaceBelow = window.innerHeight - rect.bottom;
            // 리스트 예상 높이(약 160px) 고려
            setIsUpward(spaceBelow < 180);

            setCoords({
                top: rect.top,
                left: rect.left,
                width: rect.width
            });
        }
    };

    React.useEffect(() => {
        if (isOpen) {
            updatePosition();
            window.addEventListener('resize', updatePosition);
            window.addEventListener('scroll', updatePosition, true);
        }
        return () => {
            window.removeEventListener('resize', updatePosition);
            window.removeEventListener('scroll', updatePosition, true);
        };
    }, [isOpen]);

    // 외부 클릭 시 닫기
    React.useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                // Portal 내부 클릭인지도 확인해야 함 (body 직속이므로 별도 처리 불필요, 
                // 단, portal 내부 div에 stopPropagation 등을 안 썼을 때 기준)
                setIsOpen(false);
            }
        };
        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside);
        }
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isOpen]);

    return (
        <div
            ref={containerRef}
            style={{
                position: 'relative',
                width: '100px',
                cursor: disabled ? 'not-allowed' : 'pointer',
                opacity: disabled ? 0.6 : 1
            }}
        >
            {/* Label as Trigger Area */}
            <div
                onClick={() => !disabled && setIsOpen(!isOpen)}
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '2px'
                }}
            >
                <div style={{ fontSize: '0.7rem', color: '#64748b', fontWeight: 500 }}>{label}</div>
                <div style={{
                    fontSize: '0.8rem',
                    color: '#1e293b',
                    fontWeight: 600,
                    padding: '4px 8px',
                    backgroundColor: 'white',
                    border: '1px solid #e2e8f0',
                    borderRadius: '6px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                    transition: 'all 0.2s'
                }}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {selectedOption.label}
                    </span>
                    <span style={{
                        fontSize: '0.6rem',
                        color: '#94a3b8',
                        transform: isOpen ? 'rotate(180deg)' : 'none',
                        transition: 'transform 0.2s',
                        marginLeft: '4px'
                    }}>▼</span>
                </div>
            </div>

            {/* Custom Dropdown List using Portal */}
            {isOpen && createPortal(
                <div
                    style={{
                        position: 'fixed',
                        left: coords.left,
                        top: isUpward ? 'auto' : coords.top + 45, // 트리거 높이 고려
                        bottom: isUpward ? (window.innerHeight - coords.top) + 4 : 'auto',
                        width: coords.width,
                        backgroundColor: 'white',
                        border: '1px solid #e2e8f0',
                        borderRadius: '8px',
                        boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
                        zIndex: 9999,
                        overflow: 'hidden',
                        maxHeight: '160px',
                        overflowY: 'auto'
                    }}
                    onClick={(e) => e.stopPropagation()}
                >
                    {options.map((opt) => (
                        <div
                            key={opt.value}
                            onClick={() => {
                                onChange(opt.value);
                                setIsOpen(false);
                            }}
                            style={{
                                padding: '8px 12px',
                                fontSize: '0.8rem',
                                color: opt.value === value ? '#3b82f6' : '#475569',
                                backgroundColor: opt.value === value ? '#eff6ff' : 'transparent',
                                cursor: 'pointer',
                                transition: 'background-color 0.1s',
                                fontWeight: opt.value === value ? 600 : 400
                            }}
                            onMouseEnter={(e) => {
                                if (opt.value !== value) e.currentTarget.style.backgroundColor = '#f8fafc';
                            }}
                            onMouseLeave={(e) => {
                                if (opt.value !== value) e.currentTarget.style.backgroundColor = 'transparent';
                            }}
                        >
                            {opt.label}
                        </div>
                    ))}
                </div>,
                document.body
            )}
            <style>{`
                @keyframes fadeIn {
                    from { opacity: 0; transform: translateY(-4px); }
                    to { opacity: 1; transform: translateY(0); }
                }
            `}</style>
        </div>
    );
}


