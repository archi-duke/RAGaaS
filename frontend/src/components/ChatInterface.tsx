import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, RotateCcw } from 'lucide-react';
import { retrievalApi } from '../services/api';

interface Message {
    role: 'user' | 'assistant';
    content: string;
    chunks?: any[];
    execution_time?: number;
    strategy?: string;
    has_error?: boolean;
    used_fallback?: boolean;
    pipeline_config?: any;
}

interface ChatInterfaceProps {
    kbId: string;
    strategy: string;
    // BM25 Settings
    bm25TopK: number;
    bm25Tokenizer: 'llm' | 'morpho';
    useMultiPOS: boolean;
    // ANN Settings
    annTopK: number;
    annThreshold: number;
    useParallelSearch?: boolean;
    // Reranker
    useReranker: boolean;
    rerankerTopK: number;
    rerankerThreshold: number;
    useLLMReranker: boolean;
    llmChunkStrategy: string;
    // NER
    useNER: boolean;
    // Graph
    enableGraphSearch: boolean;
    graphHops: number;
    // 2-Stage
    bruteForceTopK?: number;
    bruteForceThreshold?: number;
    // Inverse
    enableInverseSearch?: boolean;
    inverseExtractionMode?: 'always' | 'auto';
    // Graph Relation Filter (Neo4j)
    useRelationFilter?: boolean;
    // Schema Mode (for Promoted Ontology)
    useSchemaMode?: boolean;
    // Dynamic Schema (for non-promoted KB)
    useDynamicSchema?: boolean;
    useRawLog?: boolean;
    customQueryPrompt?: string; // Add this
    // Pipeline Configuration
    pipeline?: { stages: any[] };
    onChunksReceived: (chunks: any[], logs?: string[], pipeline?: any) => void;
    graphBackend?: string;
}

export default function ChatInterface({
    kbId,
    strategy,
    bm25TopK,
    bm25Tokenizer,
    useMultiPOS,
    annTopK,
    annThreshold,
    useParallelSearch,
    useReranker,
    rerankerTopK,
    rerankerThreshold,
    useLLMReranker,
    llmChunkStrategy,
    useNER,
    enableGraphSearch,
    graphHops,
    bruteForceTopK,
    bruteForceThreshold,
    enableInverseSearch,
    inverseExtractionMode,
    useRelationFilter,
    useSchemaMode,
    useDynamicSchema,
    useRawLog,
    customQueryPrompt, // Add Destructuring
    pipeline, // Pipeline configuration
    onChunksReceived,
    graphBackend
}: ChatInterfaceProps) {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const handleSend = async () => {
        if (!input.trim()) return;

        const userMessage: Message = {
            role: 'user',
            content: input
        };

        setMessages(prev => [...prev, userMessage]);
        const queryToSend = input;
        setInput('');
        setIsLoading(true);

        // Clear previous search results
        onChunksReceived([]);

        await executeQuery(queryToSend);
    };

    const handleResend = async (query: string) => {
        if (isLoading) return;

        const userMessage: Message = {
            role: 'user',
            content: query
        };

        setMessages(prev => [...prev, userMessage]);
        setIsLoading(true);

        // Clear previous search results
        onChunksReceived([]);

        await executeQuery(query);
    };

    const executeQuery = async (queryText: string) => {

        try {
            // Auto-switch to hybrid strategy when graph search is enabled or implied by strategy
            let effectiveStrategy = strategy;

            if (strategy === 'hybrid_graph' || strategy === 'hybrid_ontology') {
                effectiveStrategy = 'hybrid';
            } else if (enableGraphSearch) {
                effectiveStrategy = 'hybrid';
            } else if (strategy === 'graph') {
                // If graph search is off but strategy is 'graph', use 'ann' instead
                effectiveStrategy = 'ann';
            }

            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
            console.log('🚀 [Frontend] Sending Chat Request to Backend');
            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

            // Determine top_k based on strategy
            const effectiveTopK = (strategy === 'hybrid' || strategy === 'hybrid_graph' || strategy === 'hybrid_ontology' || strategy === 'ann' || strategy === '2-stage') ? annTopK : bm25TopK;
            const is2Stage = strategy === '2-stage';

            console.log('[Strategy]', {
                original_strategy: strategy,
                effective_strategy: effectiveStrategy,
            });
            console.log('[Graph Settings]', {
                enable_graph_search: enableGraphSearch,
                graph_hops: graphHops,
                graph_backend: 'auto-detected by backend'
            });
            console.log('[Inverse Relation Settings] ⚠️', {
                enable_inverse_search: enableInverseSearch,
                inverse_extraction_mode: inverseExtractionMode,
            });
            console.log('[Other]', {
                top_k: effectiveTopK,
                use_reranker: useReranker,
                custom_query_prompt: customQueryPrompt ? 'SET' : 'NOT SET'
            });
            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

            const response = await retrievalApi.chat(kbId, {
                query: queryText,
                top_k: effectiveTopK,
                score_threshold: annThreshold,
                strategy: effectiveStrategy,
                use_reranker: useReranker,
                reranker_top_k: rerankerTopK,
                reranker_threshold: rerankerThreshold,
                use_llm_reranker: useLLMReranker,
                llm_chunk_strategy: llmChunkStrategy,
                use_ner: useNER,
                // BM25 Settings
                bm25_top_k: bm25TopK,
                use_llm_keyword_extraction: bm25Tokenizer === 'llm',
                use_multi_pos: useMultiPOS,
                use_parallel_search: useParallelSearch,
                // ANN Settings
                ann_top_k: annTopK,
                ann_threshold: annThreshold,
                // Graph Settings
                enable_graph_search: enableGraphSearch,
                graph_hops: Number(graphHops) || 2,
                // 2-Stage Settings
                use_brute_force: is2Stage,
                brute_force_top_k: bruteForceTopK,
                brute_force_threshold: bruteForceThreshold,
                enable_inverse_search: enableInverseSearch,
                inverse_extraction_mode: inverseExtractionMode,
                use_relation_filter: useRelationFilter,
                use_schema_mode: useSchemaMode,
                use_dynamic_schema: useDynamicSchema,
                use_raw_log: useRawLog,
                custom_query_prompt: customQueryPrompt, // Pass to API
                // Pipeline Configuration (if set, backend will use pipeline executor)
                pipeline: pipeline && pipeline.stages.length > 0 ? pipeline : undefined
            });

            // Debug: Log the raw API response to verify data integrity
            console.log('[ChatInterface] Raw API response chunks:', response.data.chunks);
            if (response.data.chunks && response.data.chunks.length > 0) {
                console.log('[ChatInterface] First chunk metadata:', response.data.chunks[0].metadata);
                console.log('[ChatInterface] First chunk extracted_keywords:', response.data.chunks[0].metadata?.extracted_keywords);
            }

            const assistantMessage: Message = {
                role: 'assistant',
                content: response.data.answer,
                chunks: response.data.chunks,
                execution_time: response.data.execution_time,
                strategy: response.data.strategy,
                has_error: response.data.has_error,
                used_fallback: response.data.used_fallback,
                pipeline_config: response.data.pipeline_config
            };

            setMessages(prev => [...prev, assistantMessage]);
            if (response.data.chunks) {
                // Pass logs and pipeline config if available
                onChunksReceived(
                    response.data.chunks,
                    response.data.execution_log,
                    response.data.pipeline_config
                );
            }
        } catch (error) {
            console.error('Chat error:', error);
            const errorMessage: Message = {
                role: 'assistant',
                content: 'Sorry, I encountered an error while processing your request.'
            };
            setMessages(prev => [...prev, errorMessage]);
        } finally {
            setIsLoading(false);
        }
    };

    const handleKeyPress = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="card" style={{
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            border: '1px solid var(--border)',
            borderRadius: '12px'
        }}>
            <h3 style={{ margin: 0, padding: '5px', borderBottom: '1px solid var(--border)' }}>
                Chat with Knowledge Base
            </h3>

            <div style={{
                flex: 1,
                overflowY: 'auto',
                padding: '1rem',
                background: '#f9fafb'
            }}>
                {messages.length === 0 && (
                    <div style={{
                        textAlign: 'center',
                        color: 'var(--text-secondary)',
                        padding: '2rem',
                        fontSize: '0.9rem',
                        marginTop: '20%'
                    }}>
                        <div style={{ marginBottom: '1rem', fontSize: '2rem' }}>💬</div>
                        Start a conversation by asking a question about your documents.
                    </div>
                )}

                {messages.map((msg, idx) => (
                    <div
                        key={idx}
                        style={{
                            marginBottom: '1rem',
                            display: 'flex',
                            justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start'
                        }}
                    >
                        <div
                            style={{
                                maxWidth: '85%',
                                padding: '0.75rem 1rem',
                                borderRadius: '12px',
                                background: msg.role === 'user'
                                    ? 'var(--primary)'
                                    : (msg.has_error || msg.used_fallback)
                                        ? 'rgba(255, 99, 71, 0.1)'  // Light tomato for error/fallback
                                        : 'white',
                                color: msg.role === 'user' ? 'white' : 'var(--text-primary)',
                                boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                                border: msg.role === 'assistant'
                                    ? (msg.has_error || msg.used_fallback)
                                        ? '1px solid rgba(255, 99, 71, 0.4)'  // Tomato border for error/fallback
                                        : '1px solid var(--border)'
                                    : 'none',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '0.25rem'
                            }}
                        >
                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', justifyContent: 'space-between' }}>
                                <div style={{ flex: 1, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                    {msg.content}
                                </div>
                                {msg.role === 'user' && (
                                    <button
                                        onClick={() => handleResend(msg.content)}
                                        disabled={isLoading}
                                        title="이 질문 다시 보내기"
                                        style={{
                                            background: 'rgba(255, 255, 255, 0.1)',
                                            border: 'none',
                                            cursor: isLoading ? 'not-allowed' : 'pointer',
                                            padding: '4px',
                                            borderRadius: '4px',
                                            opacity: isLoading ? 0.5 : 0.8,
                                            display: 'flex',
                                            alignItems: 'center',
                                            marginTop: '2px',
                                            transition: 'opacity 0.2s',
                                            flexShrink: 0
                                        }}
                                        onMouseEnter={(e) => { if (!isLoading) e.currentTarget.style.opacity = '1'; }}
                                        onMouseLeave={(e) => { e.currentTarget.style.opacity = isLoading ? '0.5' : '0.8'; }}
                                    >
                                        <RotateCcw size={12} color="white" />
                                    </button>
                                )}
                            </div>


                            {msg.role === 'assistant' && (msg.execution_time !== undefined || msg.strategy) && (
                                <div style={{
                                    marginTop: '0.5rem',
                                    paddingTop: '0.5rem',
                                    borderTop: '1px solid #eee',
                                    fontSize: '0.7rem',
                                    color: '#9ca3af',
                                    display: 'flex',
                                    gap: '1rem',
                                    alignItems: 'center'
                                }}>
                                    {msg.execution_time !== undefined && (
                                        <span title="Execution Time">⏱️ {msg.execution_time.toFixed(2)}s</span>
                                    )}
                                    {msg.strategy && (
                                        <span title="Search Strategy">⚙️ {msg.strategy}</span>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                ))}

                {isLoading && (
                    <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: '1rem' }}>
                        <div style={{
                            padding: '0.75rem 1rem',
                            borderRadius: '12px',
                            background: 'white',
                            border: '1px solid var(--border)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem'
                        }}>
                            <Loader2 size={16} className="spin" />
                            <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                                Thinking...
                            </span>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            <div style={{ padding: '1rem', borderTop: '1px solid var(--border)', background: 'white', borderBottomLeftRadius: '12px', borderBottomRightRadius: '12px' }}>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <textarea
                        className="input"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyPress={handleKeyPress}
                        placeholder="Ask a question..."
                        rows={1}
                        style={{
                            flex: 1,
                            resize: 'none',
                            padding: '0.75rem',
                            minHeight: '45px',
                            maxHeight: '150px'
                        }}
                        disabled={isLoading}
                    />
                    <button
                        className="btn btn-primary"
                        onClick={handleSend}
                        disabled={isLoading || !input.trim()}
                        style={{
                            alignSelf: 'flex-end',
                            height: '45px',
                            padding: '0 1.5rem'
                        }}
                    >
                        {isLoading ? <Loader2 size={18} className="spin" /> : <Send size={18} />}
                        Send
                    </button>
                </div>
            </div>
        </div>
    );
}
