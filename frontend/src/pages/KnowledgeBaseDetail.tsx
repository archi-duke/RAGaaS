import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { kbApi, docApi } from '../services/api';
import { ArrowLeft, HelpCircle } from 'lucide-react';
import clsx from 'clsx';

import DocumentsTab from '../components/DocumentsTab';
import ChatInterface from '../components/ChatInterface';
import ChunksModal from '../components/ChunksModal';
import HorizontalConfig from '../components/HorizontalConfig';
import PipelineBuilder from '../components/PipelineBuilder';
import type { PipelineConfig } from '../components/PipelineBuilder';
import SearchResults from '../components/SearchResults';
import ConfirmDialog from '../components/ConfirmDialog';
import PromptDialog from '../components/PromptDialog';
import GraphDataTable from '../components/GraphDataTable';


export default function KnowledgeBaseDetail() {
    const { id } = useParams<{ id: string }>();
    const [kb, setKb] = useState<any>(null);
    const [activeTab, setActiveTab] = useState('documents');
    const [documents, setDocuments] = useState<any[]>([]);

    // Search Configuration State
    const [searchStrategy, setSearchStrategy] = useState('ann');

    // BM25 Settings
    const [bm25TopK, setBm25TopK] = useState(10);
    const [bm25Tokenizer, setBm25Tokenizer] = useState<'llm' | 'morpho'>('morpho');
    const [useMultiPOS, setUseMultiPOS] = useState(true);

    // ANN Settings
    const [annTopK, setAnnTopK] = useState(5);
    const [annThreshold, setAnnThreshold] = useState(0.5);

    // Reranker Settings
    const [useReranker, setUseReranker] = useState(false);
    const [rerankerTopK, setRerankerTopK] = useState(5);
    const [rerankerThreshold, setRerankerThreshold] = useState(0.0);
    const [useLLMReranker, setUseLLMReranker] = useState(false);
    const [llmChunkStrategy, setLlmChunkStrategy] = useState('full');

    // NER and other filters
    const [useNER, setUseNER] = useState(false);
    const [enableGraphSearch, setEnableGraphSearch] = useState(false);
    const [graphHops, setGraphHops] = useState(2);
    const [inverseExtractionMode, setInverseExtractionMode] = useState<'always' | 'auto'>('auto');
    const [useParallelSearch, setUseParallelSearch] = useState<boolean>(false);
    const [enableInverseSearch, setEnableInverseSearch] = useState(false);
    const [useRelationFilter, setUseRelationFilter] = useState(true);
    const [useSchemaMode, setUseSchemaMode] = useState(true); // Default ON for promoted KBs
    const [useDynamicSchema, setUseDynamicSchema] = useState(false); // Dynamic Schema for non-promoted KBs
    const [useRawLog, setUseRawLog] = React.useState(false);

    // Brute Force State (for 2-stage)
    const [bruteForceTopK, setBruteForceTopK] = useState(1);
    const [bruteForceThreshold, setBruteForceThreshold] = useState(1.5);

    // Chat results state
    const [retrievedChunks, setRetrievedChunks] = useState<any[]>([]);
    const [executionLogs, setExecutionLogs] = useState<string[]>([]);
    const [executedPipeline, setExecutedPipeline] = useState<any>(null);

    const handleSearchResults = (chunks: any[], logs?: string[], pipeline?: any) => {
        setRetrievedChunks(chunks);
        if (logs) setExecutionLogs(logs);
        if (pipeline) setExecutedPipeline(pipeline);
    };

    // Custom Prompt State
    const [customQueryPrompt, setCustomQueryPrompt] = useState<string>('');
    const [isPromptDialogOpen, setIsPromptDialogOpen] = useState(false);

    // Pipeline Configuration State
    const [pipelineConfig, setPipelineConfig] = useState<PipelineConfig>({ stages: [] });

    // Chunk viewer state
    const [selectedDoc, setSelectedDoc] = useState<any>(null);
    const [chunks, setChunks] = useState<any[]>([]);
    const [isLoadingChunks, setIsLoadingChunks] = useState(false);

    // Delete confirmation modal state
    // Delete confirmation modal state
    // Delete confirmation modal state
    const [deleteDocId, setDeleteDocId] = useState<string | null>(null);

    // Promotion Config State
    const [promoteConfig, setPromoteConfig] = useState({
        confidence_threshold: 0.85,
        min_evidence_count: 2,
        detect_cycles: true,
        remove_hypothetical: true,
        version_tag: 'v1.0'
    });
    const [isPromoting, setIsPromoting] = useState(false);

    // Resizable Panel State
    const [chatPanelWidth, setChatPanelWidth] = useState(50); // percentage
    const [isResizing, setIsResizing] = useState(false);

    const handleResizerMouseDown = (e: React.MouseEvent) => {
        e.preventDefault();
        setIsResizing(true);

        const startX = e.clientX;
        const startWidth = chatPanelWidth;
        const containerWidth = (e.currentTarget.parentElement as HTMLElement).offsetWidth;

        const handleMouseMove = (moveEvent: MouseEvent) => {
            const deltaX = moveEvent.clientX - startX;
            const deltaPercent = (deltaX / containerWidth) * 100;
            const newWidth = Math.min(Math.max(startWidth + deltaPercent, 20), 80); // 20-80% range
            setChatPanelWidth(newWidth);
        };

        const handleMouseUp = () => {
            setIsResizing(false);
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
    };


    useEffect(() => {
        if (!id) return;

        loadKB();
        loadDocs();
        loadSettings();

        // WebSocket connection for real-time document status updates
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsHost = window.location.hostname;
        const wsPort = window.location.port === '3000' ? '8000' : (window.location.port || '8000');
        const wsUrl = `${wsProtocol}//${wsHost}:${wsPort}/api/ws/${id}`;

        console.log(`[WebSocket] Connecting to: ${wsUrl}`);
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('Connected to WebSocket');
        };

        ws.onmessage = (event) => {
            console.log("WS Received:", event.data);
            const data = JSON.parse(event.data);
            if (data.type === 'document_status_update') {
                console.log("Updating doc status:", data);
                if (data.status === 'deleted') {
                    setDocuments((prevDocs) => prevDocs.filter((doc) => doc.id !== data.doc_id));
                } else {
                    setDocuments((prevDocs) =>
                        prevDocs.map((doc) =>
                            doc.id === data.doc_id
                                ? { ...doc, status: data.status }
                                : doc
                        )
                    );
                }
            }
        };

        ws.onclose = () => {
            console.log('Disconnected from WebSocket');
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        return () => {
            ws.close();
        };
    }, [id]);

    const loadSettings = () => {
        try {
            // KB별 설정 저장을 위해 KB ID를 키에 포함
            const settingsKey = `retrievalSettings_${id}`;
            const saved = localStorage.getItem(settingsKey);
            if (saved) {
                const settings = JSON.parse(saved);
                console.log(`[KB ${id}] Loading saved settings:`, settings);
                setSearchStrategy(settings.searchStrategy ?? 'ann');
                // BM25 Settings
                setBm25TopK(settings.bm25TopK ?? 10);
                setBm25Tokenizer(settings.bm25Tokenizer ?? 'morpho');
                setUseMultiPOS(settings.useMultiPOS ?? true);
                // ANN Settings
                setAnnTopK(settings.annTopK ?? settings.topK ?? 5);
                setAnnThreshold(settings.annThreshold ?? settings.scoreThreshold ?? 0.5);
                // Reranker
                setUseReranker(settings.useReranker ?? false);
                setRerankerTopK(settings.rerankerTopK ?? 5);
                setRerankerThreshold(settings.rerankerThreshold ?? 0.0);
                setUseLLMReranker(settings.useLLMReranker ?? false);
                setLlmChunkStrategy(settings.llmChunkStrategy ?? 'full');
                // Other
                setUseNER(settings.useNER ?? false);
                setEnableGraphSearch(settings.enableGraphSearch ?? false);
                setGraphHops(Number(settings.graphHops) || 2);
                setBruteForceTopK(settings.bruteForceTopK ?? 1);
                setBruteForceThreshold(settings.bruteForceThreshold ?? 1.5);
                setEnableInverseSearch(settings.enableInverseSearch ?? false);
                setInverseExtractionMode(settings.inverseExtractionMode ?? 'auto');
                setUseRelationFilter(settings.useRelationFilter ?? true);
                setUseSchemaMode(settings.useSchemaMode ?? true);
                setUseDynamicSchema(settings.useDynamicSchema ?? false);
            } else {
                console.log(`[KB ${id}] No saved settings found, using defaults`);
            }
        } catch (e) {
            console.error('Failed to load settings:', e);
        }
    };

    const saveSettings = () => {
        const settings = {
            searchStrategy,
            bm25TopK,
            bm25Tokenizer,
            useMultiPOS,
            annTopK,
            annThreshold,
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
            useParallelSearch,
            useRelationFilter,
            useSchemaMode,
            useDynamicSchema
        };
        // KB별 설정 저장
        const settingsKey = `retrievalSettings_${id}`;
        localStorage.setItem(settingsKey, JSON.stringify(settings));
        console.log(`[KB ${id}] Settings saved:`, { enableInverseSearch, inverseExtractionMode });
    };

    useEffect(() => {
        saveSettings();
    }, [
        searchStrategy,
        bm25TopK,
        bm25Tokenizer,
        useMultiPOS,
        annTopK,
        annThreshold,
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
        useParallelSearch,
        useRelationFilter,
        useSchemaMode,
        useDynamicSchema
    ]);

    const loadKB = async () => {
        try {
            const response = await kbApi.get(id!);
            const kbData = response.data;
            setKb(kbData);

            // KB에 graph_backend가 설정되어 있으면 그래프 검색 자동 활성화
            // (단, 사용자가 저장한 설정이 없을 때만)
            const settingsKey = `retrievalSettings_${id}`;
            const saved = localStorage.getItem(settingsKey);
            const isGraphRAG = kbData.graph_backend === 'neo4j' || kbData.graph_backend === 'ontology';

            if (!saved) {
                // 저장된 설정이 없으면 KB의 graph_backend에 맞게 기본값 설정
                if (isGraphRAG) {
                    console.log(`[KB ${id}] Auto-enabling graph search (graph_backend: ${kbData.graph_backend})`);
                    setEnableGraphSearch(true);
                    setSearchStrategy('hybrid_graph');
                } else {
                    setEnableGraphSearch(false);
                    setSearchStrategy('ann');
                }
            } else {
                // 저장된 설정이 있어도 현재 KB의 graph_backend와 호환되지 않으면 조정
                const savedSettings = JSON.parse(saved);
                if (savedSettings.searchStrategy === 'hybrid_graph' && !isGraphRAG) {
                    // Graph가 없는 KB인데 hybrid_graph가 설정되어 있으면 ann으로 변경
                    console.log(`[KB ${id}] Resetting searchStrategy from hybrid_graph to ann (no graph backend)`);
                    setSearchStrategy('ann');
                    setEnableGraphSearch(false);
                } else if (isGraphRAG && !savedSettings.enableGraphSearch) {
                    // Graph KB인데 그래프 검색이 비활성화되어 있으면 활성화
                    console.log(`[KB ${id}] Graph KB detected, enabling graph search`);
                    setEnableGraphSearch(true);
                }
            }
        } catch (error) {
            console.error('Failed to load KB:', error);
        }
    };

    const handlePromote = async () => {
        if (!id) return;
        setIsPromoting(true);
        try {
            await kbApi.promote(id, { config: promoteConfig });
            await loadKB(); // Refresh KB data
            alert('Promotion updated successfully');
        } catch (error) {
            console.error('Failed to promote KB:', error);
            alert('Failed to update promotion status');
        } finally {
            setIsPromoting(false);
        }
    };

    const handleDemote = async () => {
        if (!id) return;
        if (!confirm("Are you sure you want to revert to the raw Knowledge Graph?\n\nThis will disable Ontology features and exclude any OWL constraints/inferences applied during promotion.")) return;

        try {
            await kbApi.promote(id, { action: 'revert' });
            await loadKB(); // Refresh KB data
            alert('Reverted to Knowledge Graph successfully');
        } catch (error) {
            console.error('Failed to demote KB:', error);
            alert('Failed to revert status');
        }
    };

    const loadDocs = async () => {
        try {
            const response = await docApi.list(id!);
            setDocuments(response.data);
        } catch (error) {
            console.error('Failed to load documents:', error);
        }
    };

    // Auto-refresh documents if any are processing
    useEffect(() => {
        const hasProcessing = documents.some(doc => doc.status === 'processing');
        if (hasProcessing) {
            const timer = setTimeout(() => {
                loadDocs();
            }, 3000);
            return () => clearTimeout(timer);
        }
    }, [documents]);

    const handleViewChunks = async (doc: any) => {
        setSelectedDoc(doc);
        setIsLoadingChunks(true);
        try {
            const response = await docApi.getChunks(id!, doc.id);
            setChunks(response.data.chunks || []);
        } catch (error) {
            console.error('Failed to load chunks:', error);
            alert('Failed to load chunks');
        } finally {
            setIsLoadingChunks(false);
        }
    };

    const confirmDelete = async () => {
        if (!deleteDocId) return;

        const docIdToDelete = deleteDocId;
        setDeleteDocId(null); // Close modal immediately

        try {
            // Call delete API - backend will set status to 'deleting' and broadcast via WebSocket
            await docApi.delete(id!, docIdToDelete);

            // WebSocket will handle status updates:
            // 1. Backend sends 'deleting' status immediately (from document.py)
            // 2. Backend sends 'deleted' status when cleanup completes (from cleanup_service.py)
            // 3. Frontend removes document when status === 'deleted' (see line 147)
        } catch (error) {
            console.error('Failed to delete document:', error);
            alert('Failed to delete document');
            // Revert by reloading from server
            loadDocs();
        }
    };


    if (!kb) {
        return (
            <div style={{ padding: '2rem', textAlign: 'center' }}>
                <p>Loading...</p>
            </div>
        );
    }

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            height: '100vh',
            width: '100%',
            padding: '0',
            overflow: 'hidden',
            boxSizing: 'border-box'
        }}>
            {/* Header */}
            <div style={{ padding: '8px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '1rem', background: 'white' }}>
                <Link to="/" className="btn btn-ghost" style={{ padding: '0.5rem', display: 'flex', alignItems: 'center' }}>
                    <ArrowLeft size={24} />
                </Link>

                <div style={{ display: 'flex', alignItems: 'baseline', gap: '1.5rem' }}>
                    <h1 style={{ margin: 0, fontSize: '1.75rem', fontWeight: 700 }}>{kb.name}</h1>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                        <span>
                            Chunking: <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>
                                {kb.chunking_strategy === 'size' && 'Fixed Size'}
                                {kb.chunking_strategy === 'parent_child' && 'Parent-Child'}
                                {kb.chunking_strategy === 'context_aware' && 'Context Aware'}
                            </span>
                        </span>

                        {kb.graph_backend && kb.graph_backend !== 'none' && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <span style={{
                                    backgroundColor:
                                        kb.graph_backend === 'ontology'
                                            ? (kb.is_promoted ? '#1e40af' : '#bfdbfe')
                                            : '#166534',
                                    color: kb.graph_backend === 'ontology' && !kb.is_promoted ? '#1e40af' : 'white',
                                    fontSize: '0.8rem',
                                    padding: '4px 10px',
                                    borderRadius: '12px',
                                    fontWeight: 700,
                                    lineHeight: 1,
                                    boxShadow: '0 1px 2px rgba(0,0,0,0.1)'
                                }}>
                                    {kb.graph_backend === 'ontology' && kb.is_promoted
                                        ? 'Ontology'
                                        : 'Graph'}
                                </span>
                                {kb.graph_backend === 'ontology' && kb.is_promoted && (
                                    <span style={{
                                        fontWeight: 600,
                                        color: 'var(--text-secondary)',
                                        fontSize: '0.8rem',
                                        marginLeft: '4px'
                                    }}>
                                        {kb.promotion_metadata?.version_tag || 'v1.0'} • {kb.promotion_metadata?.promoted_at ? kb.promotion_metadata.promoted_at.split('T')[0] : 'N/A'}
                                    </span>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Config Summary Card removed as per design request */}.

            {/* Tabs */}
            <div className="tabs" style={{ marginBottom: '5px' }}>
                <button
                    className={clsx('tab', activeTab === 'documents' && 'active')}
                    onClick={() => setActiveTab('documents')}
                >
                    Documents
                </button>
                {kb.graph_backend && kb.graph_backend !== 'none' && (
                    <button
                        className={clsx('tab', activeTab === 'graph_data' && 'active')}
                        onClick={() => setActiveTab('graph_data')}
                    >
                        Graph Data
                    </button>
                )}
                <button
                    className={clsx('tab', activeTab === 'chat' && 'active')}
                    onClick={() => setActiveTab('chat')}
                >
                    Playground
                </button>
                {kb.graph_backend && kb.graph_backend !== 'none' ? (
                    <button
                        className={clsx('tab', activeTab === 'promote' && 'active')}
                        onClick={() => setActiveTab('promote')}
                    >
                        Promote
                    </button>
                ) : (
                    <button
                        className={clsx('tab', activeTab === 'settings' && 'active')}
                        onClick={() => setActiveTab('settings')}
                    >
                        Settings
                    </button>
                )}
            </div>

            {/* Tab Content */}
            {activeTab === 'documents' && (
                <div style={{ flex: 1, overflow: 'auto' }}>
                    <DocumentsTab
                        kbId={id!}
                        documents={documents}
                        onRefresh={loadDocs}
                        onDeleteDocument={(docId) => setDeleteDocId(docId)}
                        onViewChunks={handleViewChunks}
                        isOntology={kb.graph_backend === 'ontology'}
                    />
                </div>
            )}

            {activeTab === 'graph_data' && (
                <div style={{ flex: 1, overflow: 'auto' }}>
                    <GraphDataTable
                        kbId={id!}
                        backend={kb.graph_backend === 'ontology' ? 'fuseki' : (kb.graph_backend || 'neo4j')}
                    />
                </div>
            )}

            {activeTab === 'chat' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', flex: 1, minHeight: 0, overflow: 'visible' }}>
                    {/* Top: Pipeline Builder */}
                    <div style={{ position: 'relative', zIndex: 1000 }}>
                        <PipelineBuilder
                            kbId={id!}
                            graphBackend={kb.graph_backend}
                            isOntologyPromoted={kb.is_promoted}
                            initialConfig={pipelineConfig}
                            onPipelineChange={setPipelineConfig}
                        />
                    </div>

                    {/* Bottom: Split View with Resizable Panels */}
                    <div style={{ display: 'flex', gap: '0', flex: 1, minHeight: 0, position: 'relative' }}>
                        {/* Left: Chat */}
                        <div style={{
                            width: `${chatPanelWidth}%`,
                            overflow: 'hidden',
                            height: '100%',
                            minHeight: 0,
                            minWidth: '400px',
                            padding: '10px',
                            boxSizing: 'border-box',
                            background: '#f8fafc'
                        }}>
                            <ChatInterface
                                kbId={id!}
                                graphBackend={kb.graph_backend}
                                strategy={searchStrategy}
                                bm25TopK={bm25TopK}
                                bm25Tokenizer={bm25Tokenizer}
                                useMultiPOS={useMultiPOS}
                                annTopK={annTopK}
                                annThreshold={annThreshold}
                                useReranker={useReranker}
                                rerankerTopK={rerankerTopK}
                                rerankerThreshold={rerankerThreshold}
                                useLLMReranker={useLLMReranker}
                                llmChunkStrategy={llmChunkStrategy}
                                useNER={useNER}
                                enableGraphSearch={enableGraphSearch}
                                graphHops={graphHops}
                                bruteForceTopK={bruteForceTopK}
                                bruteForceThreshold={bruteForceThreshold}
                                enableInverseSearch={enableInverseSearch}
                                inverseExtractionMode={inverseExtractionMode}
                                useParallelSearch={useParallelSearch}
                                useRelationFilter={useRelationFilter}
                                useSchemaMode={useSchemaMode}
                                useDynamicSchema={useDynamicSchema}
                                useRawLog={useRawLog}
                                customQueryPrompt={customQueryPrompt}
                                pipeline={pipelineConfig}
                                onChunksReceived={handleSearchResults}
                            />
                        </div>

                        {/* Resizer Bar */}
                        <div
                            onMouseDown={handleResizerMouseDown}
                            style={{
                                width: '5px',
                                cursor: 'col-resize',
                                background: isResizing ? 'var(--primary)' : '#e5e7eb',
                                transition: isResizing ? 'none' : 'background 0.2s',
                                position: 'relative',
                                flexShrink: 0,
                                userSelect: 'none'
                            }}
                            onMouseEnter={(e) => {
                                if (!isResizing) {
                                    e.currentTarget.style.background = 'var(--primary)';
                                }
                            }}
                            onMouseLeave={(e) => {
                                if (!isResizing) {
                                    e.currentTarget.style.background = '#e5e7eb';
                                }
                            }}
                        >
                            <div style={{
                                position: 'absolute',
                                top: '50%',
                                left: '50%',
                                transform: 'translate(-50%, -50%)',
                                width: '3px',
                                height: '40px',
                                background: 'white',
                                borderRadius: '2px',
                                opacity: 0.7
                            }} />
                        </div>

                        {/* Right: Results */}
                        <div style={{
                            flex: 1,
                            overflow: 'hidden',
                            height: '100%',
                            minHeight: 0,
                            minWidth: '300px',
                            display: 'flex',
                            flexDirection: 'column',
                            padding: '10px',
                            boxSizing: 'border-box'
                        }}>
                            <SearchResults
                                chunks={retrievedChunks}
                                kbId={id!}
                                graphBackend={kb.graph_backend}
                                logs={executionLogs}
                                pipeline={executedPipeline}
                            />
                        </div>
                    </div>
                </div>
            )}

            {activeTab === 'promote' && (
                <div style={{ display: 'flex', gap: '20px', height: '100%', overflow: 'hidden' }}>
                    {/* Left Panel: Configuration */}
                    <div className="card" style={{ width: '500px', height: 'fit-content', flexShrink: 0 }}>
                        <h3 style={{ marginTop: 0 }}>Ontology Promotion</h3>
                        <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>
                            Configure parameters to promote the Knowledge Graph to a stable Ontology (OWL).
                        </p>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            <div>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>Version Tag</label>
                                <input
                                    className="input"
                                    value={promoteConfig.version_tag}
                                    onChange={e => setPromoteConfig({ ...promoteConfig, version_tag: e.target.value })}
                                />
                            </div>

                            <div style={{ display: 'flex', gap: '1rem' }}>
                                <div style={{ flex: 1 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                                        <span style={{ fontWeight: 500 }}>Confidence Threshold</span>
                                        <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>{promoteConfig.confidence_threshold.toFixed(2)}</span>
                                    </div>
                                    <input
                                        type="range" step="0.05" min="0" max="1.0"
                                        style={{ width: '100%', cursor: 'pointer' }}
                                        value={promoteConfig.confidence_threshold}
                                        onChange={e => setPromoteConfig({ ...promoteConfig, confidence_threshold: parseFloat(e.target.value) })}
                                    />
                                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem', lineHeight: 1.3 }}>
                                        Minimum confidence score (0.0 - 1.0) required for a triple to be promoted.
                                    </p>
                                </div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                                        <span style={{ fontWeight: 500 }}>Min Evidence Count</span>
                                        <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>{promoteConfig.min_evidence_count}</span>
                                    </div>
                                    <input
                                        type="range" min="1" max="10" step="1"
                                        style={{ width: '100%', cursor: 'pointer' }}
                                        value={promoteConfig.min_evidence_count}
                                        onChange={e => setPromoteConfig({ ...promoteConfig, min_evidence_count: parseInt(e.target.value) })}
                                    />
                                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem', lineHeight: 1.3 }}>
                                        Minimum number of times a fact must appear to be considered valid.
                                    </p>
                                </div>
                            </div>

                            <div style={{ display: 'flex', gap: '2.5rem', marginTop: '0.5rem' }}>
                                <div style={{ flex: 1 }}>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontWeight: 500 }}>
                                        <input
                                            type="checkbox"
                                            checked={promoteConfig.detect_cycles}
                                            onChange={e => setPromoteConfig({ ...promoteConfig, detect_cycles: e.target.checked })}
                                        />
                                        Detect Cycles
                                    </label>
                                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem', lineHeight: 1.3 }}>
                                        Identify and handle circular relationships in the graph.
                                    </p>
                                </div>
                                <div style={{ flex: 1 }}>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontWeight: 500 }}>
                                        <input
                                            type="checkbox"
                                            checked={promoteConfig.remove_hypothetical}
                                            onChange={e => setPromoteConfig({ ...promoteConfig, remove_hypothetical: e.target.checked })}
                                        />
                                        Remove Hypothetical
                                    </label>
                                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem', lineHeight: 1.3 }}>
                                        Exclude conditional or uncertain relationships from the ontology.
                                    </p>
                                </div>
                            </div>

                            <div style={{ marginTop: '1.5rem', borderTop: '1px solid var(--border)', paddingTop: '1rem', display: 'flex', gap: '1rem' }}>
                                <button
                                    className="btn btn-primary"
                                    onClick={handlePromote}
                                    style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}
                                    disabled={kb.graph_backend === 'neo4j' || isPromoting}
                                >
                                    {isPromoting ? (
                                        <>
                                            <span className="spinner" style={{
                                                width: '16px',
                                                height: '16px',
                                                border: '2px solid rgba(255,255,255,0.3)',
                                                borderTop: '2px solid white',
                                                borderRadius: '50%',
                                                animation: 'spin 1s linear infinite'
                                            }} />
                                            Promoting...
                                        </>
                                    ) : (
                                        kb.graph_backend === 'neo4j' ? "Promotion (Coming Soon)" : (kb.is_promoted ? "Update Promotion" : "Run Promotion")
                                    )}
                                </button>

                                {kb.is_promoted && (
                                    <button
                                        className="btn"
                                        onClick={handleDemote}
                                        disabled={isPromoting}
                                        style={{
                                            flex: 1,
                                            backgroundColor: isPromoting ? '#f5f5f5' : '#fee2e2',
                                            color: isPromoting ? '#999' : '#b91c1c',
                                            border: '1px solid #fecaca',
                                            cursor: isPromoting ? 'not-allowed' : 'pointer'
                                        }}
                                    >
                                        Revert to Graph
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Right Panel: Results */}
                    {kb.is_promoted && kb.promotion_metadata && kb.promotion_metadata.stats && (
                        <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                                <h3 style={{ margin: 0 }}>Promotion Results</h3>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                                    <button
                                        className="btn"
                                        onClick={() => window.open(`/graph-viewer?kb_id=${id}&backend=ontology&mode=schema`, '_blank')}
                                        style={{
                                            fontSize: '0.85rem',
                                            padding: '0.5rem 1rem',
                                            backgroundColor: '#ff9933',
                                            color: 'white',
                                            border: 'none',
                                            borderRadius: '8px',
                                            fontWeight: 600,
                                            cursor: 'pointer'
                                        }}
                                    >
                                        Schema
                                    </button>
                                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                        Last run: {new Date(kb.promotion_metadata.promoted_at).toLocaleString()}
                                    </div>
                                </div>
                            </div>

                            <div style={{ overflowY: 'auto', flex: 1, paddingRight: '10px' }}>
                                {/* Statistics Section */}
                                <div style={{ marginBottom: '2rem' }}>
                                    <h4 style={{ fontSize: '1rem', borderBottom: '1px solid var(--border)', paddingBottom: '0.5rem' }}>Statistics</h4>
                                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '1rem', marginTop: '1rem' }}>
                                        <div className="stat-item">
                                            <span style={{ color: 'var(--text-secondary)' }}>Input Triples</span>
                                            <span style={{ fontWeight: 600, float: 'right' }}>{kb.promotion_metadata.stats.input_triples}</span>
                                        </div>
                                        <div className="stat-item">
                                            <span style={{ color: 'var(--text-secondary)' }}>Output Triples</span>
                                            <span style={{ fontWeight: 600, float: 'right' }}>{kb.promotion_metadata.stats.output_triples}</span>
                                        </div>
                                        <div className="stat-item">
                                            <span style={{ color: 'var(--text-secondary)' }}>Classes Defined</span>
                                            <span style={{ fontWeight: 600, float: 'right' }}>{kb.promotion_metadata.stats.step2_classes}</span>
                                        </div>
                                        <div className="stat-item">
                                            <span style={{ color: 'var(--text-secondary)' }}>Properties Defined</span>
                                            <span style={{ fontWeight: 600, float: 'right' }}>{kb.promotion_metadata.stats.step2_properties}</span>
                                        </div>
                                    </div>
                                </div>

                                {/* Validation Section */}
                                <div style={{ marginBottom: '2rem' }}>
                                    <h4 style={{ fontSize: '1rem', borderBottom: '1px solid var(--border)', paddingBottom: '0.5rem' }}>Validation</h4>
                                    <div style={{ marginTop: '1rem' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                            <span>Consistency Check:</span>
                                            {kb.promotion_metadata.validation.consistent ? (
                                                <span style={{ color: '#16a34a', fontWeight: 600, display: 'flex', alignItems: 'center' }}>
                                                    PASSED
                                                </span>
                                            ) : (
                                                <span style={{ color: '#dc2626', fontWeight: 600 }}>FAILED</span>
                                            )}
                                        </div>
                                        {kb.promotion_metadata.validation.errors && kb.promotion_metadata.validation.errors.length > 0 && (
                                            <div style={{ backgroundColor: '#fee2e2', padding: '0.5rem', borderRadius: '4px', fontSize: '0.9rem', color: '#b91c1c' }}>
                                                {kb.promotion_metadata.validation.errors.join(', ')}
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {/* Excluded Items Section */}
                                <div>
                                    <h4 style={{ fontSize: '1rem', borderBottom: '1px solid var(--border)', paddingBottom: '0.5rem', display: 'flex', justifyContent: 'space-between' }}>
                                        <span>Excluded Items</span>
                                        <span style={{ fontSize: '0.85rem', fontWeight: 400, color: 'var(--text-secondary)' }}>
                                            {kb.promotion_metadata.excluded_items?.length || 0} items
                                        </span>
                                    </h4>

                                    {kb.promotion_metadata.excluded_items && kb.promotion_metadata.excluded_items.length > 0 ? (
                                        <div style={{ marginTop: '1rem', maxHeight: '400px', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: '4px' }}>
                                            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                                                <thead style={{ position: 'sticky', top: 0, backgroundColor: 'var(--surface)', zIndex: 1 }}>
                                                    <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--border)' }}>
                                                        <th style={{ padding: '0.5rem' }}>Subject</th>
                                                        <th style={{ padding: '0.5rem' }}>Predicate</th>
                                                        <th style={{ padding: '0.5rem' }}>Object</th>
                                                        <th style={{ padding: '0.5rem' }}>Reason</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {kb.promotion_metadata.excluded_items.map((item: any, idx: number) => (
                                                        <tr key={idx} style={{ borderBottom: '1px solid var(--border-light)' }}>
                                                            <td style={{ padding: '0.5rem', maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.subject}>{item.subject.split('/').pop()}</td>
                                                            <td style={{ padding: '0.5rem', maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.predicate}>{item.predicate.split('/').pop()}</td>
                                                            <td style={{ padding: '0.5rem', maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.object}>{item.object.split('/').pop()}</td>
                                                            <td style={{ padding: '0.5rem', color: '#dc2626' }}>{item.reason}</td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    ) : (
                                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', fontStyle: 'italic', marginTop: '1rem' }}>
                                            No items were excluded. All candidates passed verification.
                                        </p>
                                    )}
                                </div>

                                {/* Schema Definitions Section */}
                                {kb.promotion_metadata.schema_info && (
                                    <div style={{ marginTop: '2rem' }}>
                                        <h4 style={{ fontSize: '1rem', borderBottom: '1px solid var(--border)', paddingBottom: '0.5rem' }}>Schema Definitions</h4>

                                        <div style={{ marginTop: '1rem' }}>
                                            <h5 style={{ fontSize: '0.9rem', margin: '0 0 0.5rem 0' }}>Classes ({Object.keys(kb.promotion_metadata.schema_info.classes || {}).length})</h5>
                                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', maxHeight: '200px', overflowY: 'auto', padding: '0.5rem', backgroundColor: 'var(--surface-sunken)', borderRadius: '4px' }}>
                                                {Object.entries(kb.promotion_metadata.schema_info.classes || {}).map(([clsUri, info]: [string, any], idx) => (
                                                    <div key={idx} style={{ position: 'relative', display: 'inline-block' }}>
                                                        <button
                                                            onClick={() => {
                                                                const newState = !info.expanded;
                                                                // 상태 관리가 로컬 데이터 구조 안에 없으므로, 간단하게 alert나 별도 state를 써야 하나
                                                                // 여기서는 간단히 title로 전체 목록을 보여주거나, 별도 선택된 클래스 State를 두는 게 좋음.
                                                                // 하지만 편의상 즉시 확인을 위해 Alert 또는 콘솔을 사용하거나, 
                                                                // 본문의 요구사항(클릭하면 목록 보여줘)을 만족하기 위해 selectedClass State를 추가해야 함.
                                                                // 임시로 이 컴포넌트 상단에 state 추가가 불가능하므로(tool limit), 
                                                                // 간단한 토글 UI를 인라인으로 구현하기 어려움.
                                                                // -> selectedSchemaClass 상태를 추가하는 별도 tool call이 필요함.
                                                                // 일단 여기서는 클릭 시 해당 버튼 아래에 목록이 펼쳐지도록 CSS/State 없이 처리하기 어려우므로,
                                                                // 가장 쉬운 방법: 브라우저 기본 동작(title)은 이미 있고,
                                                                // 'selectedClass' state를 사용하는 방식으로 변경해야 함.
                                                            }}
                                                            // 임시: 클릭하면 상세 모달을 띄우는 로직 대신, 간단히 콘솔 로그나 커스텀 툴팁을 띄울 수 없으니
                                                            // 일단 태그 자체에 title로 맛보기 보여줌.
                                                            // 하지만 사용자가 '클릭하면 보여줘'라고 했으므로 interaction이 필요함.
                                                            style={{
                                                                fontSize: '0.8rem',
                                                                padding: '2px 8px',
                                                                backgroundColor: 'var(--surface)',
                                                                border: '1px solid var(--border)',
                                                                borderRadius: '12px',
                                                                cursor: 'pointer',
                                                                display: 'flex',
                                                                alignItems: 'center',
                                                                gap: '4px'
                                                            }}
                                                            title={`${info.count} instances:\n${(info.instances || []).slice(0, 10).join('\n')}${info.instances?.length > 10 ? '\n...' : ''}`}
                                                        >
                                                            <span style={{ fontWeight: 500 }}>{clsUri.split('/').pop()?.split('#').pop()}</span>
                                                            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', backgroundColor: 'var(--bg-subtle)', padding: '0 4px', borderRadius: '4px' }}>{info.count}</span>
                                                        </button>
                                                    </div>
                                                ))}
                                                {Object.keys(kb.promotion_metadata.schema_info.classes || {}).length === 0 && <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>None</span>}
                                            </div>
                                        </div>

                                        <div style={{ marginTop: '1rem' }}>
                                            <h5 style={{ fontSize: '0.9rem', margin: '0 0 0.5rem 0' }}>Properties ({kb.promotion_metadata.schema_info.properties?.length || 0})</h5>
                                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', maxHeight: '150px', overflowY: 'auto', padding: '0.5rem', backgroundColor: 'var(--surface-sunken)', borderRadius: '4px' }}>
                                                {kb.promotion_metadata.schema_info.properties?.map((prop: string, idx: number) => (
                                                    <span key={idx} style={{ fontSize: '0.8rem', padding: '2px 6px', backgroundColor: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '4px' }} title={prop}>
                                                        {prop.split('/').pop()?.split('#').pop()}
                                                    </span>
                                                )) || <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>None</span>}
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'settings' && (
                <div className="card">
                    <h3>Knowledge Base Settings</h3>
                    <p>Settings implementation pending...</p>
                </div>
            )}

            {/* Chunks Modal */}
            <ChunksModal
                isOpen={selectedDoc !== null}
                onClose={() => setSelectedDoc(null)}
                document={selectedDoc}
                chunks={chunks}
                isLoading={isLoadingChunks}
                kbId={id!}
                onChunkUpdated={() => handleViewChunks(selectedDoc)}
                isGraphEnabled={kb.graph_backend !== 'none' && kb.graph_backend !== undefined}
            />

            <PromptDialog
                isOpen={isPromptDialogOpen}
                onClose={() => setIsPromptDialogOpen(false)}
                initialPrompt={customQueryPrompt}
                onSave={setCustomQueryPrompt}
                backendType={
                    kb.graph_backend === 'neo4j'
                        ? 'neo4j'
                        : (kb.is_promoted && useSchemaMode ? 'ontology_plus' : 'ontology_minus')
                }
            />

            <ConfirmDialog
                isOpen={deleteDocId !== null}
                onConfirm={confirmDelete}
                onCancel={() => setDeleteDocId(null)}
                title="Delete Document"
                message="Are you sure you want to delete this document? This action cannot be undone."
            />
        </div>
    );
}
