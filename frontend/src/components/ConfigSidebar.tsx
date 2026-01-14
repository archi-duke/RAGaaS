import React from 'react';

interface ConfigSidebarProps {
    searchStrategy: string;
    setSearchStrategy: (value: string) => void;
    topK: number;
    setTopK: (value: number) => void;
    scoreThreshold: number;
    setScoreThreshold: (value: number) => void;
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
    useNER: boolean;
    setUseNER: (value: boolean) => void;
    enableGraphSearch: boolean;
    setEnableGraphSearch: (value: boolean) => void;
    graphHops: number;
    setGraphHops: (value: number) => void;
    enableGraphRag: boolean;
    isOntologyPromoted?: boolean;
}

export default function ConfigSidebar({
    searchStrategy,
    setSearchStrategy,
    topK,
    setTopK,
    scoreThreshold,
    setScoreThreshold,
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
    enableGraphSearch,
    setEnableGraphSearch,
    graphHops,
    setGraphHops,
    enableGraphRag,
    isOntologyPromoted
}: ConfigSidebarProps) {
    return (
        <div className="card" style={{ position: 'sticky', top: '2rem', maxHeight: 'calc(100vh - 4rem)', overflowY: 'auto' }}>
            <h3 style={{ marginTop: 0 }}>Search Configuration</h3>

            {/* Strategy Selection */}
            <div style={{ marginBottom: '1.5rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 500 }}>
                    Search Strategy
                </label>
                <select
                    className="input"
                    value={searchStrategy}
                    onChange={(e) => setSearchStrategy(e.target.value)}
                >
                    <option value="ann">Vector Search (ANN)</option>
                    <option value="2-stage">2-Stage Retrieval</option>
                    <option value="keyword">Keyword Search (BM25)</option>
                    <option value="hybrid">Hybrid Search</option>
                </select>
            </div>

            {/* Top K */}
            <div style={{ marginBottom: '1.5rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 500 }}>
                    Top K Results: {topK}
                </label>
                <input
                    type="range"
                    min="1"
                    max="20"
                    value={topK}
                    onChange={(e) => setTopK(Number(e.target.value))}
                    className="input"
                    style={{ width: '100%' }}
                />
            </div>

            {/* Score Threshold */}
            <div style={{ marginBottom: '1.5rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 500 }}>
                    Score Threshold: {scoreThreshold.toFixed(2)}
                </label>
                <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.1"
                    value={scoreThreshold}
                    onChange={(e) => setScoreThreshold(Number(e.target.value))}
                    className="input"
                    style={{ width: '100%' }}
                />
            </div>

            {/* Reranker */}
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1rem', marginTop: '1rem' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                    <input
                        type="checkbox"
                        checked={useReranker}
                        onChange={(e) => setUseReranker(e.target.checked)}
                        style={{ cursor: 'pointer' }}
                    />
                    <span style={{ fontSize: '0.875rem', fontWeight: 500 }}>Use Reranker</span>
                </label>

                {useReranker && (
                    <div style={{ paddingLeft: '1.5rem', marginTop: '0.75rem' }}>
                        <div style={{ marginBottom: '1rem' }}>
                            <label style={{ fontSize: '0.75rem', display: 'block', marginBottom: '0.25rem', color: 'var(--text-secondary)' }}>
                                Reranker Top K: {rerankerTopK}
                            </label>
                            <input
                                type="range"
                                min="1"
                                max="20"
                                value={rerankerTopK}
                                onChange={(e) => setRerankerTopK(Number(e.target.value))}
                                style={{ width: '100%' }}
                            />
                        </div>

                        <div style={{ marginBottom: '1rem' }}>
                            <label style={{ fontSize: '0.75rem', display: 'block', marginBottom: '0.25rem', color: 'var(--text-secondary)' }}>
                                Threshold: {rerankerThreshold.toFixed(2)}
                            </label>
                            <input
                                type="range"
                                min="0"
                                max="1"
                                step="0.1"
                                value={rerankerThreshold}
                                onChange={(e) => setRerankerThreshold(Number(e.target.value))}
                                style={{ width: '100%' }}
                            />
                        </div>

                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                            <input
                                type="checkbox"
                                checked={useLLMReranker}
                                onChange={(e) => setUseLLMReranker(e.target.checked)}
                            />
                            <span style={{ fontSize: '0.75rem' }}>Use LLM Reranker</span>
                        </label>

                        {useLLMReranker && (
                            <div style={{ marginTop: '0.5rem' }}>
                                <label style={{ fontSize: '0.7rem', display: 'block', marginBottom: '0.25rem', color: 'var(--text-secondary)' }}>
                                    Chunk Strategy
                                </label>
                                <select
                                    className="input"
                                    value={llmChunkStrategy}
                                    onChange={(e) => setLlmChunkStrategy(e.target.value)}
                                    style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                                >
                                    <option value="full">Full</option>
                                    <option value="limited">Limited</option>
                                    <option value="smart">Smart</option>
                                </select>
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* NER Filter */}
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1rem', marginTop: '1rem' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                    <input
                        type="checkbox"
                        checked={useNER}
                        onChange={(e) => setUseNER(e.target.checked)}
                        style={{ cursor: 'pointer' }}
                    />
                    <span style={{ fontSize: '0.875rem', fontWeight: 500 }}>NER Filter</span>
                </label>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.25rem', marginLeft: '1.5rem' }}>
                    Penalizes results that don't contain entities found in the query
                </div>
            </div>

            {/* Graph Search */}
            {enableGraphRag && (
                <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1rem', marginTop: '1rem' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                        <input
                            type="checkbox"
                            checked={enableGraphSearch}
                            onChange={(e) => {
                                setEnableGraphSearch(e.target.checked);
                                if (e.target.checked) {
                                    setSearchStrategy('hybrid');
                                }
                            }}
                            style={{ cursor: 'pointer' }}
                        />
                        <span style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                            Use Graph Search (Beta)
                            {isOntologyPromoted && (
                                <span style={{
                                    fontSize: '0.7em',
                                    color: '#4CAF50',
                                    marginLeft: '6px',
                                    border: '1px solid #4CAF50',
                                    padding: '1px 6px',
                                    borderRadius: '10px',
                                    fontWeight: 'normal',
                                    verticalAlign: 'middle'
                                }}>
                                    Schema Available
                                </span>
                            )}
                        </span>
                    </label>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.25rem', marginLeft: '1.5rem' }}>
                        Augments retrieval with relationships from the knowledge graph
                    </div>

                    {enableGraphSearch && (
                        <div style={{ paddingLeft: '1.5rem', marginTop: '0.75rem' }}>
                            <label style={{ fontSize: '0.75rem', display: 'block', marginBottom: '0.25rem', color: 'var(--text-secondary)' }}>
                                Graph Hops
                            </label>
                            <div style={{ display: 'flex', gap: '1rem' }}>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                    <input
                                        type="radio"
                                        name="graphHops"
                                        checked={graphHops === 1}
                                        onChange={() => setGraphHops(1)}
                                    />
                                    <span style={{ fontSize: '0.75rem' }}>1-Hop</span>
                                </label>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                    <input
                                        type="radio"
                                        name="graphHops"
                                        checked={graphHops === 2}
                                        onChange={() => setGraphHops(2)}
                                    />
                                    <span style={{ fontSize: '0.75rem' }}>2-Hops</span>
                                </label>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
