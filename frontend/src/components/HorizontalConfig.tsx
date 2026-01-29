import React from 'react';

interface HorizontalConfigProps {
    // Search Strategy
    searchStrategy: string;
    setSearchStrategy: (value: string) => void;

    // BM25 Settings
    bm25TopK: number;
    setBm25TopK: (value: number) => void;
    bm25Tokenizer: 'llm' | 'morpho';
    setBm25Tokenizer: (value: 'llm' | 'morpho') => void;
    useMultiPOS: boolean;
    setUseMultiPOS: (value: boolean) => void;

    // ANN Settings
    annTopK: number;
    setAnnTopK: (value: number) => void;
    annThreshold: number;
    setAnnThreshold: (value: number) => void;
    useParallelSearch?: boolean;
    setUseParallelSearch?: (value: boolean) => void;

    // Reranker
    useReranker: boolean;
    setUseReranker: (value: boolean) => void;
    rerankerTopK: number;
    setRerankerTopK: (value: number) => void;
    rerankerThreshold: number;
    setRerankerThreshold: (value: number) => void;
    useLLMReranker: boolean;
    setUseLLMReranker: (value: boolean) => void;
    llmChunkStrategy: string;
    setLlmChunkStrategy: (value: string) => void;

    // NER Filter
    useNER: boolean;
    setUseNER: (value: boolean) => void;

    // Graph/Ontology
    enableGraphSearch: boolean;
    setEnableGraphSearch: (value: boolean) => void;
    graphHops: number;
    setGraphHops: (value: number) => void;
    enableInverseSearch?: boolean;
    setEnableInverseSearch?: (value: boolean) => void;
    inverseExtractionMode?: 'always' | 'auto';
    setInverseExtractionMode?: (value: 'always' | 'auto') => void;

    // 2-Stage (Brute Force)
    bruteForceTopK: number;
    setBruteForceTopK: (value: number) => void;
    bruteForceThreshold: number;
    setBruteForceThreshold: (value: number) => void;

    // Graph Relation Filter (Neo4j only)
    useRelationFilter?: boolean;
    setUseRelationFilter?: (value: boolean) => void;

    // KB Info
    chunkingStrategy?: string;
    graphBackend?: string;
    promotionMetadata?: any;
    isOntologyPromoted?: boolean;

    // Schema Mode (for Promoted Ontology)
    useSchemaMode?: boolean;
    setUseSchemaMode?: (value: boolean) => void;

    // Debug
    useRawLog?: boolean;
    setUseRawLog?: (value: boolean) => void;

    // Dynamic Schema (for non-promoted KB)
    useDynamicSchema?: boolean;
    setUseDynamicSchema?: (value: boolean) => void;

    // Callbacks
    onOpenPromptDialog?: () => void;
    onOpenRerankPromptDialog?: () => void;
}

// Styles
const columnStyle: React.CSSProperties = {
    borderLeft: '1px solid var(--border)',
    paddingLeft: '1rem',
    maxWidth: '200px',
    boxSizing: 'border-box'
};

const labelStyle: React.CSSProperties = {
    fontSize: '0.85rem',
    fontWeight: 600,
    color: 'var(--text-primary)',
    marginBottom: '0.3rem',
    display: 'block'
};

const descStyle: React.CSSProperties = {
    fontSize: '0.8rem',
    color: 'var(--text-secondary)',
    marginTop: '0.2rem',
    lineHeight: 1.3,
    opacity: 0.9
};

export default function HorizontalConfig({
    searchStrategy,
    setSearchStrategy,
    bm25TopK,
    setBm25TopK,
    bm25Tokenizer,
    setBm25Tokenizer,
    useMultiPOS,
    setUseMultiPOS,
    annTopK,
    setAnnTopK,
    annThreshold,
    setAnnThreshold,
    useParallelSearch,
    setUseParallelSearch,
    useReranker,
    setUseReranker,
    rerankerTopK,
    setRerankerTopK,
    rerankerThreshold,
    setRerankerThreshold,
    useLLMReranker,
    setUseLLMReranker,
    llmChunkStrategy,
    setLlmChunkStrategy,
    useNER,
    setUseNER,
    setEnableGraphSearch,
    graphHops,
    setGraphHops,
    enableInverseSearch,
    setEnableInverseSearch,
    inverseExtractionMode,
    setInverseExtractionMode,
    bruteForceTopK,
    setBruteForceTopK,
    bruteForceThreshold,
    setBruteForceThreshold,
    useRelationFilter,
    setUseRelationFilter,
    chunkingStrategy: _chunkingStrategy,  // Reserved for future use
    graphBackend,
    promotionMetadata,
    useRawLog,
    isOntologyPromoted,
    useSchemaMode,
    setUseSchemaMode,
    setUseRawLog,
    useDynamicSchema,
    setUseDynamicSchema,
    onOpenPromptDialog,
    onOpenRerankPromptDialog
}: HorizontalConfigProps) {

    // Determine available strategies based on RAG type
    const isGraphRAG = graphBackend === 'neo4j' || graphBackend === 'ontology';

    // Auto mode state
    const [isAutoHops, setIsAutoHops] = React.useState(graphHops === 2);

    // Auto "Auto" logic for Graph Hops
    // If graphHops is 2, we consider it "Auto" in this visual representation if default, 
    // but better to track it. For now, we'll assume "2" is the default safe zone.

    // Custom Slider Style for Orange Zone
    // Range: 1 to 5. Orange zone starts > 2.
    // 1 (0%), 2 (25%), 3 (50%), 4 (75%), 5 (100%)
    // Cutoff at > 2 (e.g., 35%?). 
    // Let's make 1-2 blue, 3-5 orange. 
    // Gradient stop at 2.5? (2.5-1)/4 = 37.5%.
    const sliderBackground = `linear-gradient(to right, #3b82f6 0%, #3b82f6 37.5%, #f97316 37.5%, #f97316 100%)`;

    const handleStrategyChange = (newStrategy: string) => {
        setSearchStrategy(newStrategy);
        if (newStrategy === 'hybrid_graph') {
            setEnableGraphSearch(true);
        } else {
            setEnableGraphSearch(false);
        }
    };

    const handleAutoToggle = (checked: boolean) => {
        setIsAutoHops(checked);
        if (checked) {
            setGraphHops(2); // Set to default Auto value
        }
    };

    return (
        <div className="card" style={{ padding: '1rem', overflowX: 'auto' }}>
            <h3 style={{ marginTop: 0, marginBottom: '1.2rem', fontSize: '1.1rem', fontWeight: 600 }}>
                Search Configuration
            </h3>

            <div style={{ display: 'flex', gap: '2rem', alignItems: 'flex-start' }}>

                {/* Column 1: Search Strategy */}
                <div style={{ minWidth: '180px' }}>
                    <label style={{ ...labelStyle, marginBottom: '0.8rem' }}>Search Strategy</label>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.9rem' }}>
                            <input
                                type="radio"
                                name="searchStrategy"
                                checked={searchStrategy === 'ann'}
                                onChange={() => handleStrategyChange('ann')}
                                style={{ accentColor: 'var(--primary)' }}
                            />
                            Vector (ANN)
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.9rem' }}>
                            <input
                                type="radio"
                                name="searchStrategy"
                                checked={searchStrategy === 'keyword'}
                                onChange={() => handleStrategyChange('keyword')}
                                style={{ accentColor: 'var(--primary)' }}
                            />
                            Keyword (BM25)
                        </label>
                        {(graphBackend === 'ontology' || graphBackend === 'neo4j') && (
                            <label style={{
                                display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.9rem',
                                color: searchStrategy === 'hybrid_graph' ? 'var(--primary)' : 'inherit',
                                fontWeight: searchStrategy === 'hybrid_graph' ? 500 : 400,
                                border: searchStrategy === 'hybrid_graph' ? '1px solid var(--primary)' : '1px solid transparent',
                                padding: '0.2rem 0.4rem',
                                borderRadius: '4px',
                                marginLeft: '-0.4rem'
                            }}>
                                <input
                                    type="radio"
                                    name="searchStrategy"
                                    checked={searchStrategy === 'hybrid_graph'}
                                    onChange={() => handleStrategyChange('hybrid_graph')}
                                    style={{ accentColor: 'var(--primary)' }}
                                />
                                Hybrid ({(graphBackend === 'neo4j' || !isOntologyPromoted) ? 'Graph' : 'Ontology'}→ANN)
                            </label>
                        )}
                        {/* Fallback for non-graph or other modes */}
                        {!isGraphRAG && (
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.9rem' }}>
                                <input
                                    type="radio"
                                    name="searchStrategy"
                                    checked={searchStrategy === 'hybrid'}
                                    onChange={() => handleStrategyChange('hybrid')}
                                    style={{ accentColor: 'var(--primary)' }}
                                />
                                Hybrid (BM25→ANN)
                            </label>
                        )}
                    </div>
                </div>

                {/* Separator */}
                <div style={{ width: '1px', backgroundColor: 'var(--border)', alignSelf: 'stretch' }} />

                {/* Column 2: Ontology Settings */}
                {isGraphRAG ? (
                    <div style={{ minWidth: '300px' }}>
                        <label style={{ ...labelStyle, marginBottom: '0.8rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            {(graphBackend === 'neo4j' || !isOntologyPromoted) ? 'Graph Settings' : 'Ontology Settings'}
                            {graphBackend === 'ontology' && isOntologyPromoted && (
                                <button
                                    onClick={() => setUseSchemaMode?.(!useSchemaMode)}
                                    style={{
                                        fontSize: '0.7em',
                                        color: useSchemaMode ? '#fff' : '#1e40af', // Dark Royal Blue
                                        backgroundColor: useSchemaMode ? '#1e40af' : '#eff6ff', // Blue 800 / 50
                                        border: '1px solid #1e40af',
                                        padding: '2px 10px',
                                        borderRadius: '12px',
                                        fontWeight: 600,
                                        lineHeight: '1.2',
                                        cursor: 'pointer',
                                        transition: 'all 0.2s ease',
                                        marginLeft: '8px'
                                    }}
                                >
                                    {useSchemaMode ? 'Schema On' : 'Schema Off'}
                                </button>
                            )}
                        </label>

                        <div style={{ display: 'flex', gap: '2rem' }}>
                            {/* Sub-col 1: Hops */}
                            <div style={{ width: '140px', opacity: useSchemaMode ? 0.5 : 1 }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                                    <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Graph Hops</span>
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.9rem', cursor: useSchemaMode ? 'not-allowed' : 'pointer' }}>
                                        <input
                                            type="checkbox"
                                            checked={useSchemaMode ? true : isAutoHops}
                                            onChange={(e) => handleAutoToggle(e.target.checked)}
                                            disabled={useSchemaMode}
                                        />
                                        Auto
                                    </label>
                                    <span style={{ fontWeight: 600, fontSize: '1rem', color: graphHops >= 4 ? '#f97316' : 'var(--primary)' }}>{useSchemaMode ? 'Auto' : graphHops}</span>
                                </div>

                                <div style={{ position: 'relative', height: '24px', display: 'flex', alignItems: 'center' }}>
                                    <input
                                        type="range"
                                        min="1"
                                        max="5"
                                        value={graphHops}
                                        onChange={(e) => setGraphHops(Number(e.target.value))}
                                        disabled={isAutoHops || useSchemaMode}
                                        className="custom-range"
                                        style={{
                                            width: '100%',
                                            cursor: (isAutoHops || useSchemaMode) ? 'not-allowed' : 'pointer',
                                            height: '6px',
                                            borderRadius: '3px',
                                            appearance: 'none',
                                            outline: 'none',
                                            opacity: (isAutoHops || useSchemaMode) ? 0.5 : 1,
                                            background: `linear-gradient(to right,
                                                #3b82f6 0%,
                                                #3b82f6 ${((graphHops - 1) / 4) * 100}%,
                                                #e2e8f0 ${((graphHops - 1) / 4) * 100}%,
                                                #e2e8f0 75%,
                                                #f97316 75%,
                                                #f97316 100%)`
                                        }}
                                    />
                                </div>
                                {graphHops >= 4 && !useSchemaMode && (
                                    <div style={{
                                        position: 'absolute',
                                        marginTop: '0rem',
                                        color: '#c2410c',
                                        fontSize: '0.7rem',
                                        padding: '0.2rem 0.4rem',
                                        whiteSpace: 'nowrap',
                                        zIndex: 10
                                    }}>
                                        ⚠️ High latency warning
                                    </div>
                                )}
                            </div>

                            {/* Sub-col 2: Filters */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                                <label style={{
                                    display: 'flex', alignItems: 'center', gap: '0.5rem',
                                    cursor: useSchemaMode ? 'not-allowed' : 'pointer',
                                    fontSize: '0.9rem', fontWeight: 500,
                                    opacity: useSchemaMode ? 0.5 : 1
                                }}>
                                    <input
                                        type="checkbox"
                                        checked={useRelationFilter ?? true}
                                        onChange={(e) => setUseRelationFilter?.(e.target.checked)}
                                        disabled={useSchemaMode}
                                    />
                                    Relation Filter
                                </label>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                    <label style={{
                                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                                        cursor: useSchemaMode ? 'not-allowed' : 'pointer',
                                        fontSize: '0.9rem', fontWeight: 500,
                                        opacity: useSchemaMode ? 0.5 : 1
                                    }}>
                                        <input
                                            type="checkbox"
                                            checked={enableInverseSearch || false}
                                            onChange={(e) => setEnableInverseSearch?.(e.target.checked)}
                                            disabled={useSchemaMode}
                                        />
                                        Inverse Relations
                                    </label>
                                    {/* Query Prompt Button REMOVED */}
                                    {/* Dynamic Schema - only show when NOT promoted */}
                                    {!isOntologyPromoted && (
                                        <label style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.4rem',
                                            cursor: 'pointer',
                                            fontSize: '0.8rem',
                                            color: useDynamicSchema ? 'var(--primary)' : 'var(--text-secondary)',
                                            marginTop: '0.3rem'
                                        }}>
                                            <input
                                                type="checkbox"
                                                checked={useDynamicSchema ?? false}
                                                onChange={(e) => setUseDynamicSchema?.(e.target.checked)}
                                                style={{ accentColor: 'var(--primary)' }}
                                            />
                                            Dynamic Schema
                                        </label>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div style={{ minWidth: '300px' }}>
                        <label style={{ ...labelStyle, marginBottom: '0.8rem' }}>Reranking & Filters</label>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem' }}>
                            {/* Reranker */}
                            <div>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontWeight: 500, fontSize: '0.9rem', marginBottom: '0.5rem' }}>
                                    <input
                                        type="checkbox"
                                        checked={useReranker}
                                        onChange={(e) => setUseReranker(e.target.checked)}
                                    />
                                    Use Reranker
                                </label>

                                {useReranker && (
                                    <div style={{ paddingLeft: '0.5rem', borderLeft: '2px solid var(--border)', marginLeft: '0.4rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                                        <div style={{ display: 'flex', gap: '1rem' }}>
                                            <div style={{ width: '100px' }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.2rem' }}>
                                                    <span>Top K</span>
                                                    <span>{rerankerTopK}</span>
                                                </div>
                                                <input type="range" min="1" max="20" value={rerankerTopK} onChange={(e) => setRerankerTopK(Number(e.target.value))} style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6', height: '6px' }} />
                                            </div>
                                            <div style={{ width: '100px' }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.2rem' }}>
                                                    <span>Threshold</span>
                                                    <span>{rerankerThreshold.toFixed(2)}</span>
                                                </div>
                                                <input type="range" min="0" max="1" step="0.05" value={rerankerThreshold} onChange={(e) => setRerankerThreshold(Number(e.target.value))} style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6', height: '6px' }} />
                                            </div>
                                        </div>

                                        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', cursor: 'pointer', fontSize: '0.85rem' }}>
                                                <input type="checkbox" checked={useLLMReranker} onChange={(e) => setUseLLMReranker(e.target.checked)} />
                                                LLM
                                            </label>
                                            {useLLMReranker && (
                                                <select
                                                    value={llmChunkStrategy}
                                                    onChange={(e) => setLlmChunkStrategy(e.target.value)}
                                                    style={{ padding: '0.1rem 0.3rem', fontSize: '0.8rem', borderRadius: '4px', border: '1px solid var(--border)' }}
                                                >
                                                    <option value="full">Full Context</option>
                                                    <option value="limited">Limited</option>
                                                    <option value="smart">Smart</option>
                                                </select>
                                            )}
                                        </div>
                                        {useLLMReranker && (
                                            <button
                                                onClick={() => onOpenRerankPromptDialog?.()}
                                                style={{
                                                    marginTop: '0.4rem',
                                                    fontSize: '0.75rem',
                                                    padding: '0.2rem 0.5rem',
                                                    backgroundColor: '#f1f5f9',
                                                    color: '#475569',
                                                    border: '1px solid #e2e8f0',
                                                    borderRadius: '4px',
                                                    cursor: 'pointer'
                                                }}
                                            >
                                                Edit Rerank Prompt
                                            </button>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* NER */}
                            <div style={{ borderTop: '1px solid var(--border)', paddingTop: '0.8rem' }}>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontWeight: 500, fontSize: '0.9rem' }}>
                                    <input
                                        type="checkbox"
                                        checked={useNER}
                                        onChange={(e) => setUseNER(e.target.checked)}
                                    />
                                    NER Filter
                                </label>
                                <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '0.2rem 0 0 1.4rem', lineHeight: 1.2 }}>
                                    Entity-based filtering
                                </p>
                            </div>
                        </div>
                    </div>
                )}

                <div style={{ width: '1px', backgroundColor: 'var(--border)', alignSelf: 'stretch' }} />

                {/* Column 3: ANN Settings */}
                <div style={{ minWidth: '220px' }}>
                    <label style={{ ...labelStyle, marginBottom: '0.8rem' }}>ANN Settings</label>

                    <div style={{ display: 'flex', gap: '1.5rem' }}>
                        {/* Top K */}
                        <div style={{ width: '80px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.4rem', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                <span>Top K</span>
                                <span>{annTopK}</span>
                            </div>
                            <input
                                type="range"
                                min="1"
                                max="20"
                                value={annTopK}
                                onChange={(e) => setAnnTopK(Number(e.target.value))}
                                style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                            />
                        </div>

                        {/* Threshold */}
                        <div style={{ width: '100px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.4rem', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                <span>Threshold</span>
                                <span>{annThreshold.toFixed(2)}</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="1"
                                step="0.01"
                                value={annThreshold}
                                onChange={(e) => setAnnThreshold(Number(e.target.value))}
                                style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                            />
                        </div>
                    </div>
                </div>

                <div style={{ width: '1px', backgroundColor: 'var(--border)', alignSelf: 'stretch' }} />

                {/* Column 4: Debug */}
                <div style={{ minWidth: '150px' }}>
                    <label style={{ ...labelStyle, marginBottom: '0.8rem' }}>Debug</label>
                    <div style={{ marginTop: '0.4rem' }}>
                        <label style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            cursor: 'pointer',
                            fontSize: '0.85rem',
                            color: 'var(--text-secondary)'
                        }}>
                            <input
                                type="checkbox"
                                checked={useRawLog ?? false}
                                onChange={(e) => setUseRawLog?.(e.target.checked)}
                            />
                            Show Raw Log
                        </label>
                    </div>
                </div>
            </div>
            <style>{`
                input[type=range].custom-range::-webkit-slider-thumb {
                    -webkit-appearance: none;
                    height: 16px;
                    width: 16px;
                    border-radius: 50%;
                    background: #3b82f6;
                    cursor: pointer;
                    margin-top: -5px; /* Centers thumb on track */
                    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                }
                input[type=range].custom-range::-webkit-slider-runnable-track {
                    width: 100%;
                    height: 6px;
                    cursor: pointer;
                    border-radius: 3px;
                }
            `}</style>
        </div >
    );
}
