import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Plus, X, ChevronLeft, ChevronRight, GripVertical, Download, Check } from 'lucide-react';
import ModelSelector, { DEFAULT_LLM_CONFIG, DEFAULT_EMBEDDING_CONFIG, type ModelConfig } from './ModelSelector';
import { useModelSettings } from '../hooks/useModelSettings';

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
    ann: { top_k: 10, threshold: 0.5, index_type: 'IVF_FLAT', embedding_model: DEFAULT_EMBEDDING_CONFIG },
    bm25: { top_k: 50, use_multi_pos: true },
    brute_force: { top_k: 3, threshold: 1.5 },
    graph: {
        hops: 2,
        is_auto_hops: true,
        top_k: 10,
        use_relation_filter: true,
        enable_inverse: true,
        inverse_mode: 'always',
        use_schema_mode: false,
        use_dynamic_schema: false,
        enable_entity_expansion: false,
        merge_mode: 'union',
        custom_query_prompt: '',
        model_type: 'llm' as 'llm' | 'embedding',
        llm_model: DEFAULT_LLM_CONFIG,
        embedding_model: DEFAULT_EMBEDDING_CONFIG,
    },
    rerank: {
        top_k: 5,
        threshold: 0.0,
        use_llm: false,
        llm_strategy: 'full',
        model_type: 'llm' as 'llm' | 'embedding',
        llm_model: DEFAULT_LLM_CONFIG,
        embedding_model: DEFAULT_EMBEDDING_CONFIG,
    },
    ner_filter: { penalty: 0.3, tokenizer: 'regex', mode: 'nnp' },
};

// Styles
const cardStyle: React.CSSProperties = {
    backgroundColor: 'white',
    border: '1px solid #e2e8f0',
    borderRadius: '12px',
    padding: '0.75rem 0.75rem 0.65rem 0.75rem',
    minWidth: '180px',
    height: '160px',
    boxSizing: 'border-box',
    position: 'relative',
};

// LLM 사용 스테이지
const cardStyleLLM: React.CSSProperties = {
    ...cardStyle,
    height: '160px',
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
    const [copied, setCopied] = useState(false);
    const { settings } = useModelSettings();

    const handleCopyPipeline = () => {
        const config: PipelineConfig = { stages };
        navigator.clipboard.writeText(JSON.stringify(config, null, 2));
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    // Generic Prompt Editor state (for Graph, Rerank, etc.)
    const [editingPromptStage, setEditingPromptStage] = useState<number | null>(null);
    const [tempPrompt, setTempPrompt] = useState('');
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
                const response = await fetch(`${import.meta.env.BASE_URL}api/knowledge-bases/${kbId}/pipeline`);
                if (response.ok) {
                    const config = await response.json();
                    if (config.stages && config.stages.length > 0) {
                        // Adjust graph stage parameters based on promotion status
                        const adjustedStages = config.stages.map((stage: PipelineStage) => {
                            const params = { ...stage.params };
                            if (stage.type === 'graph') {
                                // If not promoted (Schema None), ensure filters are enabled
                                if (!isOntologyPromoted) {
                                    params.use_relation_filter = true;
                                    params.enable_inverse = true;
                                    params.use_schema_mode = false;
                                } else {
                                    // If promoted, respect saved settings or default to schema mode on
                                    if (params.use_schema_mode === undefined) {
                                        params.use_schema_mode = true;
                                    }
                                }
                                // Graph 필터는 기본 LLM
                                params.model_type = 'llm';
                                return { ...stage, params };
                            }
                            if (stage.type === 'rerank') {
                                params.model_type = 'llm';
                                return { ...stage, params };
                            }
                            return stage;
                        });

                        setStages(adjustedStages);
                    }
                }
            } catch (error) {
                console.error('Failed to load pipeline config:', error);
            } finally {
                setIsLoading(false);
            }
        };
        loadPipeline();
    }, [kbId, isOntologyPromoted]);

    // Save pipeline config to backend (debounced)
    useEffect(() => {
        if (isLoading) return; // Don't save during initial load

        const saveTimeout = setTimeout(async () => {
            try {
                await fetch(`${import.meta.env.BASE_URL}api/knowledge-bases/${kbId}/pipeline`, {
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

    // --- Prompt Functions ---
    const loadGlobalRerankPrompt = async () => {
        setIsLoadingPrompt(true);
        setPromptError('');
        try {
            const response = await fetch(`${import.meta.env.BASE_URL}api/knowledge-bases/settings/rerank-prompt`);
            if (!response.ok) throw new Error('Failed to load global prompt');
            const data = await response.json();
            setTempPrompt(data.content);
        } catch (e: any) {
            setPromptError(e.message || 'Failed to load prompt');
        } finally {
            setIsLoadingPrompt(false);
        }
    };

    const loadGraphDefaultPrompt = async () => {
        setIsLoadingPrompt(true);
        setPromptError('');
        try {
            const backendType = graphBackend === 'neo4j'
                ? 'neo4j'
                : (isOntologyPromoted ? 'ontology_plus' : 'ontology_minus');
            const response = await fetch(`${import.meta.env.BASE_URL}api/knowledge-bases/query-prompt/content?type=${backendType}`);
            if (!response.ok) throw new Error('Failed to load default graph prompt');
            const data = await response.json();
            setTempPrompt(data.content);
        } catch (e: any) {
            setPromptError(e.message || 'Failed to load prompt');
        } finally {
            setIsLoadingPrompt(false);
        }
    };

    const openGraphPromptEditor = (index: number) => {
        setEditingPromptStage(index);
        setTempPrompt('');
        setPromptError('');
        loadGraphDefaultPrompt();
    };

    const handleSavePrompt = async () => {
        setIsLoadingPrompt(true);
        setPromptError('');
        try {
            if (editingPromptStage === -1) {
                // Global Rerank Prompt → txt file
                const response = await fetch(`${import.meta.env.BASE_URL}api/knowledge-bases/settings/rerank-prompt`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: tempPrompt })
                });
                if (!response.ok) throw new Error('Failed to save rerank prompt');
            } else if (editingPromptStage !== null) {
                // Graph Query Prompt → txt file (used by generator at runtime)
                const backendType = graphBackend === 'neo4j'
                    ? 'neo4j'
                    : (isOntologyPromoted ? 'ontology_plus' : 'ontology_minus');
                const response = await fetch(`${import.meta.env.BASE_URL}api/knowledge-bases/query-prompt/save`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: tempPrompt, type: backendType })
                });
                if (!response.ok) throw new Error('Failed to save query prompt');
            }
            setEditingPromptStage(null);
        } catch (e: any) {
            setPromptError(e.message || 'Failed to save prompt');
        } finally {
            setIsLoadingPrompt(false);
        }
    };
    // --- End Prompt Functions ---

    const handleAddStage = (type: StageType) => {
        const params = { ...DEFAULT_PARAMS[type] };

        // Use centralized model settings for new stages
        if (type === 'ann') {
            // Check if user has a custom ingest_llm or if we should have a 'default_embedding' in settings
            // For now, use DEFAULT_EMBEDDING_CONFIG or if we want to be more specific, 
            // we could add ingest_embedding to useModelSettings. 
            // But let's use the current settings for now.
        }
        if (type === 'graph') {
            params.use_schema_mode = isOntologyPromoted ?? false;
            params.llm_model = settings.graph_query_llm;
        }
        if (type === 'rerank') {
            params.llm_model = settings.chat_llm; // or a dedicated rerank_llm if we add one
        }

        const newStage: PipelineStage = {
            type,
            params
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

        const usesLLM =
            stage.type === 'graph' ||
            (stage.type === 'rerank' && stage.params.use_llm);

        const baseStyle = usesLLM ? cardStyleLLM : cardStyle;
        const cardStyles: React.CSSProperties = {
            ...baseStyle,
            paddingBottom: stage.type === 'graph' ? 0 : '0.65rem',
            width: 'fit-content',
            minWidth: '180px',
            flexShrink: 0,
            ...(stage.type === 'graph' && { height: 'auto', minHeight: '160px' }),
        };

        return (
            <div key={index} style={cardStyles}>
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

                        {stage.type === 'graph' && (graphBackend === 'neo4j' || graphBackend === 'ontology') && (
                            isOntologyPromoted ? (
                                // Promoted: Show toggleable Schema On/Off button
                                <button
                                    onClick={() => {
                                        const current = !!(stage.params.use_schema_mode ?? true);
                                        const nextSchemaMode = !current;
                                        const newStages = [...stages];
                                        const p = { ...newStages[index].params };

                                        if (nextSchemaMode) {
                                            // Backup
                                            p._prev_use_relation_filter = p.use_relation_filter ?? true;
                                            p._prev_enable_inverse = p.enable_inverse ?? false;
                                            p._prev_inverse_mode = p.inverse_mode ?? 'always';
                                            p._prev_enable_entity_expansion = p.enable_entity_expansion ?? false;

                                            // Force
                                            p.use_schema_mode = true;
                                            p.use_relation_filter = true;
                                            p.enable_inverse = true;
                                            p.inverse_mode = 'always';
                                            p.enable_entity_expansion = true;
                                        } else {
                                            // Restore
                                            p.use_schema_mode = false;
                                            if (p._prev_use_relation_filter !== undefined) p.use_relation_filter = p._prev_use_relation_filter;
                                            if (p._prev_enable_inverse !== undefined) p.enable_inverse = p._prev_enable_inverse;
                                            if (p._prev_inverse_mode !== undefined) p.inverse_mode = p._prev_inverse_mode;
                                            if (p._prev_enable_entity_expansion !== undefined) p.enable_entity_expansion = p._prev_enable_entity_expansion;

                                            delete p._prev_use_relation_filter;
                                            delete p._prev_enable_inverse;
                                            delete p._prev_inverse_mode;
                                            delete p._prev_enable_entity_expansion;
                                        }

                                        newStages[index] = { ...newStages[index], params: p };
                                        setStages(newStages);
                                    }}
                                    style={{
                                        fontSize: '0.65rem',
                                        color: !!(stage.params.use_schema_mode ?? true) ? '#fff' : '#1e40af',
                                        backgroundColor: !!(stage.params.use_schema_mode ?? true) ? '#1e40af' : '#eff6ff',
                                        border: '1px solid #1e40af',
                                        padding: '2px 8px',
                                        borderRadius: '12px',
                                        fontWeight: 600,
                                        lineHeight: '1.2',
                                        cursor: 'pointer',
                                        transition: 'all 0.2s ease',
                                        marginLeft: '8px'
                                    }}
                                >
                                    {!!(stage.params.use_schema_mode ?? true) ? 'Schema On' : 'Schema Off'}
                                </button>
                            ) : (
                                // Not promoted: Show disabled "Schema None" text
                                <span
                                    style={{
                                        fontSize: '0.65rem',
                                        color: '#cbd5e1',
                                        backgroundColor: '#f8fafc',
                                        border: '1px solid #e2e8f0',
                                        padding: '2px 8px',
                                        borderRadius: '12px',
                                        fontWeight: 600,
                                        lineHeight: '1.2',
                                        cursor: 'default',
                                        marginLeft: '8px'
                                    }}
                                >
                                    Schema None
                                </span>
                            )
                        )}

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
                    <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', alignItems: 'flex-start' }}>
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
                                minWidth="100px"
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
                    <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', alignItems: 'flex-start' }}>
                        <ParamSlider
                            label="Top K"
                            value={params.top_k}
                            min={1} max={100}
                            onChange={(v) => handleParamChange(index, 'top_k', v)}
                        />
                            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.3rem', paddingTop: '0.25rem', minWidth: 0 }}>
                            <div style={{ display: 'flex', alignItems: 'center' }}>
                                <ParamSelect
                                    label="Tokenizer"
                                    minWidth="80px"
                                    value={params.tokenizer || 'kiwi'}
                                    options={[
                                        { value: 'kiwi', label: 'Kiwi' },
                                        { value: 'spacy', label: 'spaCy' }
                                    ]}
                                    onChange={(v) => handleParamChange(index, 'tokenizer', v)}
                                />
                            </div>
                            <ParamCheckbox
                                label="Multi-POS"
                                checked={params.use_multi_pos}
                                onChange={(v) => handleParamChange(index, 'use_multi_pos', v)}
                            />
                        </div>
                    </div>
                );

            case 'brute_force':
                return (
                    <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', alignItems: 'flex-start' }}>
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
                const isAutoHops = params.is_auto_hops ?? true;
                const showLatencyWarning = !isAutoHops && params.hops >= 4;
                return (
                    <>
                        <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', alignItems: 'flex-start' }}>
                            {/* 슬라이더: 왼쪽 고정 */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', flexShrink: 0 }}>
                                <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem' }}>
                                    <ParamSlider
                                        label="Hops"
                                        value={isAutoHops ? 2 : params.hops}
                                        min={1} max={5}
                                        onChange={(v) => handleParamChange(index, 'hops', v)}
                                        disabled={isAutoHops}
                                    />
                                    <ParamSlider
                                        label="Top K"
                                        value={params.top_k || 10}
                                        min={1} max={50}
                                        onChange={(v) => handleParamChange(index, 'top_k', v)}
                                    />
                                </div>
                                {showLatencyWarning && (
                                    <div style={{
                                        color: '#c2410c',
                                        fontSize: '0.65rem',
                                        marginTop: '-16px',
                                        paddingLeft: '4px',
                                        whiteSpace: 'nowrap',
                                        display: 'flex',
                                        gap: '3px',
                                        alignItems: 'center'
                                    }}>
                                        <span style={{ flexShrink: 0 }}>⚠️</span>
                                        <span>High latency</span>
                                    </div>
                                )}
                            </div>
                            {/* 슬라이더 옆: 2x2 체크박스 → Inverse Search → QueryLLM */}
                            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.3rem', paddingBottom: 0, minWidth: 0 }}>
                                {/* 1행: Auto Hops | Entity Expand */}
                                <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', alignItems: 'center' }}>
                                    <ParamCheckbox label="Auto Hops" checked={isAutoHops} onChange={(v) => handleParamChange(index, 'is_auto_hops', v)} />
                                    <ParamCheckbox
                                        label="Entity Expand"
                                        checked={!!params.enable_entity_expansion}
                                        onChange={(v) => handleParamChange(index, 'enable_entity_expansion', v)}
                                        disabled={!!params.use_schema_mode}
                                    />
                                </div>
                                {/* 2행: Rel Filter | Dynamic Schema */}
                                <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', alignItems: 'center' }}>
                                    <ParamCheckbox
                                        label="Rel Filter"
                                        checked={params.use_relation_filter}
                                        onChange={(v) => handleParamChange(index, 'use_relation_filter', v)}
                                        disabled={!!params.use_schema_mode}
                                    />
                                    {!isOntologyPromoted ? (
                                        <ParamCheckbox
                                            label="Dynamic Schema"
                                            checked={params.use_dynamic_schema ?? false}
                                            onChange={(v) => handleParamChange(index, 'use_dynamic_schema', v)}
                                        />
                                    ) : (
                                        <div />
                                    )}
                                </div>
                                {/* 3행: Inverse Search */}
                                <div style={{ display: 'flex', alignItems: 'center' }}>
                                    <ParamSelect
                                        label="Inverse Search"
                                        layout="inline"
                                        minWidth="80px"
                                        disabled={!!params.use_schema_mode}
                                        value={!params.enable_inverse ? 'none' : (params.inverse_mode || 'always')}
                                        options={[
                                            { value: 'none', label: 'None' },
                                            { value: 'auto', label: 'Auto' },
                                            { value: 'always', label: 'Always' }
                                        ]}
                                        onChange={(v) => {
                                            const newStages = [...stages];
                                            newStages[index] = {
                                                ...newStages[index],
                                                params: {
                                                    ...newStages[index].params,
                                                    enable_inverse: v !== 'none',
                                                    inverse_mode: v === 'none' ? (params.inverse_mode || 'always') : v
                                                }
                                            };
                                            setStages(newStages);
                                        }}
                                    />
                                </div>
                                {/* 4행: Model (Graph는 기본 LLM) */}
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', flexWrap: 'wrap' }}>
                                    <span style={{ fontSize: '0.7rem', color: '#475569', flexShrink: 0 }}>Model</span>
                                    <ModelSelector
                                        type="llm"
                                        value={params.llm_model || DEFAULT_LLM_CONFIG}
                                        onChange={(cfg) => handleParamChange(index, 'llm_model', cfg)}
                                        onEditPrompt={() => openGraphPromptEditor(index)}
                                    />
                                </div>
                            </div>
                        </div>
                    </>
                );

            case 'rerank': {
                const llmMode: string = params.use_llm
                    ? (params.llm_strategy || 'full')
                    : 'none';
                return (
                    <>
                        <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', alignItems: 'flex-start' }}>
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
                            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.3rem', paddingTop: '0.5rem', paddingLeft: '0.5rem', minWidth: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center' }}>
                                    <ParamSelect
                                        label="LLM"
                                        minWidth="80px"
                                        value={llmMode}
                                        options={[
                                            { value: 'none', label: 'None' },
                                            { value: 'full', label: 'Full' },
                                            { value: 'limited', label: 'Limited' },
                                        ]}
                                        onChange={(v) => {
                                            const newStages = [...stages];
                                            newStages[index] = {
                                                ...newStages[index],
                                                params: {
                                                    ...newStages[index].params,
                                                    use_llm: v !== 'none',
                                                    llm_strategy: v !== 'none' ? v : newStages[index].params.llm_strategy,
                                                }
                                            };
                                            setStages(newStages);
                                        }}
                                    />
                                </div>
                                {/* Model Selector: LLM 드롭박스 바로 아래 */}
                                {params.use_llm && (
                                    <div style={{ display: 'flex', alignItems: 'center' }}>
                                        <ModelSelector
                                            type="llm"
                                            value={params.llm_model || DEFAULT_LLM_CONFIG}
                                            onChange={(cfg) => handleParamChange(index, 'llm_model', cfg)}
                                            onEditPrompt={() => { setEditingPromptStage(-1); setTempPrompt(''); setPromptError(''); loadGlobalRerankPrompt(); }}
                                        />
                                    </div>
                                )}
                            </div>
                        </div>
                    </>
                );
            }

            case 'ner_filter':
                const isRegex = !params.tokenizer || params.tokenizer === 'regex';
                return (
                    <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', alignItems: 'flex-start' }}>
                        <ParamSlider
                            label="Penalty"
                            value={params.penalty}
                            min={0} max={1} step={0.05}
                            onChange={(v) => handleParamChange(index, 'penalty', v)}
                        />
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', paddingTop: '0.25rem', minWidth: '90px' }}>
                            <ParamSelect
                                label="Engine"
                                minWidth="90px"
                                value={params.tokenizer || 'regex'}
                                options={[
                                    { value: 'regex', label: 'Regex' },
                                    { value: 'kiwi', label: 'Kiwi' },
                                    { value: 'spacy', label: 'spaCy' }
                                ]}
                                onChange={(v) => handleParamChange(index, 'tokenizer', v)}
                            />
                            {!isRegex && (
                                <ParamSelect
                                    label="Mode"
                                    minWidth="90px"
                                    value={params.mode || 'nnp'}
                                    options={[
                                        { value: 'nnp', label: 'NNP' },
                                        { value: 'ner', label: 'NER' }
                                    ]}
                                    onChange={(v) => handleParamChange(index, 'mode', v)}
                                />
                            )}
                        </div>
                    </div>
                );

            default:
                return null;
        }
    };


    return (
        <div className="card" style={{
            padding: '1rem 1rem 10px 1rem',
            overflow: 'visible',
            position: 'relative',
            zIndex: 100
        }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '1rem' }}>
                <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>
                    Search Pipeline
                </h3>
                <button
                    onClick={handleCopyPipeline}
                    title="Copy Pipeline JSON"
                    style={{
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        padding: '4px',
                        display: 'flex',
                        alignItems: 'center',
                        borderRadius: '4px',
                        transition: 'background 0.2s',
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#f1f5f9'}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                >
                    {copied ? (
                        <Check size={16} color="#10b981" />
                    ) : (
                        <Download size={16} color="#64748b" />
                    )}
                </button>
            </div>

            {/* Wrapper for stages and add button */}
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start', overflow: 'visible' }}>
                {/* Scrollable stages container */}
                <div style={{
                    display: 'flex',
                    gap: '0.5rem',
                    alignItems: 'flex-start',
                    overflowX: 'auto',
                    paddingBottom: '2px'
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

            {/* Generic Prompt Editor Modal */}
            {editingPromptStage !== null && createPortal(
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
                        <h3 style={{ marginTop: 0, marginBottom: '0.4rem', fontSize: '1.1rem', fontWeight: 600 }}>
                            {editingPromptStage === -1
                                ? 'LLM Rerank Prompt'
                                : (graphBackend === 'neo4j' ? 'Cypher Query Generation Prompt' : 'SPARQL Query Generation Prompt')}
                        </h3>
                        <p style={{ fontSize: '0.8rem', color: '#64748b', marginBottom: '0.75rem' }}>
                            {editingPromptStage === -1
                                ? "System prompt for LLM-based reranking. Use {query} and {chunk_content} as placeholders."
                                : graphBackend === 'neo4j'
                                    ? "System prompt used by the LLM to generate Cypher queries for Neo4j graph search."
                                    : "System prompt used by the LLM to generate SPARQL queries for ontology graph search."}
                        </p>
                        {promptError && (
                            <div style={{ color: '#ef4444', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                                {promptError}
                            </div>
                        )}
                        <textarea
                            value={tempPrompt}
                            onChange={(e) => setTempPrompt(e.target.value)}
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
                            placeholder="Enter custom instructions..."
                        />
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1rem' }}>
                            <button
                                onClick={() => setEditingPromptStage(null)}
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
                                onClick={handleSavePrompt}
                                disabled={isLoadingPrompt}
                                style={{
                                    padding: '0.5rem 1rem',
                                    backgroundColor: '#3b82f6',
                                    color: 'white',
                                    border: 'none',
                                    borderRadius: '6px',
                                    cursor: isLoadingPrompt ? 'not-allowed' : 'pointer',
                                    fontSize: '0.9rem',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                {isLoadingPrompt ? 'Saving...' : 'Save Changes'}
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
    onChange,
    disabled = false
}: {
    label: string;
    value: number;
    min: number;
    max: number;
    step?: number;
    onChange: (v: number) => void;
    disabled?: boolean;
}) {
    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '0.1rem',
            minHeight: '100px',
            opacity: disabled ? 0.5 : 1,
            pointerEvents: disabled ? 'none' : 'auto'
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
                    height: '70px',
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
                        disabled={disabled}
                        onChange={(e) => onChange(Number(e.target.value))}
                        style={{
                            width: '70px',
                            height: '6px',
                            margin: 0,
                            padding: 0,
                            cursor: disabled ? 'not-allowed' : 'pointer',
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
    onChange,
    disabled
}: {
    label: string;
    checked: boolean;
    onChange: (v: boolean) => void;
    disabled?: boolean;
}) {
    return (
        <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.4rem',
            fontSize: '0.8rem',
            cursor: disabled ? 'not-allowed' : 'pointer',
            color: '#475569',
            opacity: disabled ? 0.6 : 1,
            whiteSpace: 'nowrap'
        }}>
            <input
                type="checkbox"
                checked={checked}
                disabled={disabled}
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
    disabled,
    minWidth = '130px',
    layout = 'vertical'
}: {
    label: string;
    value: string;
    options: { value: string; label: string }[];
    onChange: (v: string) => void;
    disabled?: boolean;
    minWidth?: string;
    /** 'vertical' = label above dropdown, 'inline' = label left of dropdown */
    layout?: 'vertical' | 'inline';
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
            // Consider estimated list height (approx 160px)
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

    // Close on outside click
    React.useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                // Check if the click is inside the portal (since it's a direct child of body, 
                // no special handling is needed unless stopPropagation is used in the portal div)
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
                width: 'auto',
                minWidth: minWidth,
                cursor: disabled ? 'not-allowed' : 'pointer',
                opacity: disabled ? 0.6 : 1
            }}
        >
            {/* Label + dropdown: vertical (label top) or inline (label left) */}
            <div
                onClick={() => !disabled && setIsOpen(!isOpen)}
                style={{
                    display: 'flex',
                    flexDirection: layout === 'inline' ? 'row' : 'column',
                    alignItems: layout === 'inline' ? 'center' : 'stretch',
                    gap: layout === 'inline' ? '0.4rem' : '2px'
                }}
            >
                <div style={{ fontSize: '0.7rem', color: '#64748b', fontWeight: 500, flexShrink: 0 }}>{label}</div>
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
                    transition: 'all 0.2s',
                    minWidth: layout === 'inline' ? minWidth : undefined
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
                        top: isUpward ? 'auto' : coords.top + 45, // Consider trigger height
                        bottom: isUpward ? (window.innerHeight - coords.top) + 4 : 'auto',
                        width: Math.max(coords.width, parseInt(minWidth)),
                        minWidth: minWidth,
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
                            onMouseDown={(e) => {
                                e.preventDefault(); // Prevent blur
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


