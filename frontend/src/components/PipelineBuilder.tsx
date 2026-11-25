import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Plus, X, ChevronLeft, ChevronRight, GripVertical, Download, Check } from 'lucide-react';
import ModelSelector, { DEFAULT_LLM_CONFIG, DEFAULT_EMBEDDING_CONFIG, type ModelConfig } from './ModelSelector';
import { useModelSettings } from '../hooks/useModelSettings';
import config from '../platform/config';

// Stage type definitions
export type StageType = 'smalltalk' | 'agentic' | 'ann' | 'bm25' | 'brute_force' | 'graph' | 'rerank' | 'ner_filter';

export interface PipelineStage {
    type: StageType;
    params: Record<string, any>;
    // 스테이지 식별자 — 실패 연결이 이 값으로 대상을 가리킨다
    id?: string;
    // 실패/예외 연결 (2026-11-25): 실패하면 넘어갈 뒤쪽 스테이지 id. 없으면 실패를 알리고 멈춘다.
    // 정상 연결(카드 위쪽 화살표)은 성공 시 다음 스테이지. 실패 연결 대상은 실패했을 때만 실행된다.
    on_failure?: string;
}

const newStageId = () => `s_${Math.random().toString(36).slice(2, 8)}`;

// 실패 연결을 둘 수 있는 스테이지 (Gate·Agentic 은 분기 대상이 아님 — Agentic 은 스스로 순서를 정한다)
const canBranch = (t: StageType) => t !== 'smalltalk' && t !== 'agentic';

// 실패 연결 정리: 없는 대상·앞쪽 대상을 가리키는 연결은 지운다
const tidyFailureLinks = (list: PipelineStage[]): PipelineStage[] => list.map((st, i) => {
    if (!st.on_failure) return st;
    const t = list.findIndex(x => x.id === st.on_failure);
    if (t > i && canBranch(st.type) && canBranch(list[t].type)) return st;
    const { on_failure, ...rest } = st;
    return rest;
});

export interface PipelineConfig {
    stages: PipelineStage[];
    // 운영/테스트 탭 (docs/design/agent/design-search-entry-and-pipeline-versions.md §6)
    // live: 운영 구성으로 실행 (외부 에이전트가 받는 결과와 같음) / test: 편집 중인 테스트 구성으로 실행
    mode?: 'live' | 'test';
}

interface PipelineVersion {
    version: number;
    ref: string;
    created_at?: string;
    note?: string;
    live?: boolean;
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

// agentic: 등록된 검색 스테이지를 도구로 삼아 검색 방식·순서를 정하고 단계별로 진행 (docs/design/graph/design-agentic-filter.md).
// 파이프라인에 하나만, Gate 뒤·검색 스테이지 앞에 자동 배치.
const FILTER_STAGES: { type: StageType; label: string; category: 'filter' }[] = [
    { type: 'agentic', label: 'Agentic', category: 'filter' },
    { type: 'rerank', label: 'Re-Rank', category: 'filter' },
    { type: 'ner_filter', label: 'NER Filter', category: 'filter' },
];

// 게이트 스테이지: 검색 앞단. Small-talk(인사/잡담)이면 검색 없이 LLM 이 바로 응답하고 중단.
// KB 생성 시 기본 추가되며, 사용자가 삭제하면 스몰톡 처리도 비활성화된다.
const GATE_STAGES: { type: StageType; label: string; category: 'gate' }[] = [
    { type: 'smalltalk', label: 'Gate', category: 'gate' },
];

const DEFAULT_PARAMS: Record<StageType, Record<string, any>> = {
    smalltalk: { llm_model: DEFAULT_LLM_CONFIG },
    agentic: { llm_model: DEFAULT_LLM_CONFIG, mode: 'auto', max_steps: 6, time_budget_s: 60 },
    ann: { top_k: 10, threshold: 0.5, index_type: 'IVF_FLAT', embedding_model: DEFAULT_EMBEDDING_CONFIG },
    bm25: { top_k: 50, use_multi_pos: true },
    brute_force: { top_k: 3, threshold: 1.5 },
    graph: {
        max_hops: 6,     // 다단계 체인의 최대 홉 — 질문이 요구하는 홉 수로 가되 이 값을 넘지 않음
        top_k: 10,
        resolve_terms: true,      // 오탈자·유사어 해석 (질문 표기 → 그래프 값). 끄면 문항당 약 6초 빠름
        list_supplement: true,    // 목록 질문의 그래프 결과가 적으면(2개 미만) 문서 검색으로 보강
        graph_fallback: 'vector', // 그래프로 못 찾으면: vector(문서 검색) | none(빈 결과 — 그래프만의 성능 측정)
        use_schema_mode: false,
        use_dynamic_schema: true,  // 실제 술어 목록을 LLM 에 주어 지어낸 술어(prop:장점 등) 방지
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
    const [failureMenu, setFailureMenu] = useState<number | null>(null);   // 실패 연결 메뉴가 열린 카드
    const [isLoading, setIsLoading] = useState(true);
    const [copied, setCopied] = useState(false);
    // 운영/테스트 탭 + 버전 이력
    const [tab, setTab] = useState<'live' | 'test'>('test');
    const [liveStages, setLiveStages] = useState<PipelineStage[]>([]);
    const [liveRef, setLiveRef] = useState<string | null>(null);
    const [liveVersion, setLiveVersion] = useState<number | null>(null);
    const [changes, setChanges] = useState<string[]>([]);
    const [showPublish, setShowPublish] = useState(false);
    const [publishNote, setPublishNote] = useState('');
    const [showHistory, setShowHistory] = useState(false);
    const [versions, setVersions] = useState<PipelineVersion[]>([]);
    const [viewVersion, setViewVersion] = useState<{ ref: string; json: string; changes: string[]; warnings: string[] } | null>(null);
    const [confirmActivate, setConfirmActivate] = useState<string | null>(null);
    const [pvBusy, setPvBusy] = useState(false);
    const [pvError, setPvError] = useState('');
    const importRef = React.useRef<HTMLInputElement>(null);
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

    // smalltalk 게이트는 하나만 의미가 있으므로 이미 있으면 목록에서 제외
    const hasSmalltalk = stages.some(s => s.type === 'smalltalk');
    const gateStages = hasSmalltalk ? [] : GATE_STAGES;

    // Available stages based on current state
    // agentic 도 하나만 의미가 있다
    const hasAgentic = stages.some(s => s.type === 'agentic');
    const filterStages = hasAgentic ? FILTER_STAGES.filter(s => s.type !== 'agentic') : FILTER_STAGES;
    const availableStages = hasSearchStage
        ? [...gateStages, ...SEARCH_STAGES, ...filterStages]
        : [...gateStages, ...SEARCH_STAGES];

    // Filter graph if no graph backend
    const filteredStages = graphBackend && graphBackend !== 'none'
        ? availableStages
        : availableStages.filter(s => s.type !== 'graph');

    // 저장된 구성을 화면 상태로 (그래프·리랭크는 LLM 모델 유형 고정, 승격 전 KB 는 스키마 모드 끔)
    const adjustStages = React.useCallback((raw: PipelineStage[]): PipelineStage[] => tidyFailureLinks((raw || []).map((s: PipelineStage) => {
        const stage = s.id ? s : { ...s, id: newStageId() };
        const params = { ...(stage.params || {}) };
        if (stage.type === 'graph') {
            if (!isOntologyPromoted) {
                params.use_schema_mode = false;
            } else if (params.use_schema_mode === undefined) {
                params.use_schema_mode = true;
            }
            params.model_type = 'llm';
            return { ...stage, params };
        }
        if (stage.type === 'rerank') {
            params.model_type = 'llm';
            return { ...stage, params };
        }
        return { ...stage, params };
    })), [isOntologyPromoted]);

    const api = `${config.RAGAAS_API}knowledge-bases/${kbId}/pipeline`;

    const pvFetch = async (path: string, init?: RequestInit) => {
        const r = await fetch(`${api}${path}`, init);
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || `요청 실패 (${r.status})`);
        return d;
    };

    const refreshVersions = async () => {
        try {
            const d = await pvFetch('/versions?limit=50');
            setVersions(d.versions || []);
            const live = (d.versions || []).find((v: PipelineVersion) => v.live);
            setLiveVersion(live ? live.version : null);
            setPvError('');
        } catch (e: any) {
            setVersions([]);
            setLiveVersion(null);
            setPvError(e.message);   // 이력 저장소(Gitea) 연결 안 됨 등 — 검색에는 영향 없음
        }
    };

    // Load pipeline config (운영 + 테스트) from backend on mount
    useEffect(() => {
        const loadPipeline = async () => {
            try {
                const response = await fetch(api);
                if (response.ok) {
                    const d = await response.json();
                    const live = d.live?.config?.stages ?? d.stages ?? [];
                    const draft = d.draft?.stages ?? live;
                    setLiveStages(adjustStages(live));
                    setStages(adjustStages(draft));
                    setLiveRef(d.live?.ref ?? null);
                    setChanges(d.changes || []);
                }
            } catch (error) {
                console.error('Failed to load pipeline config:', error);
            } finally {
                setIsLoading(false);
            }
        };
        loadPipeline();
        refreshVersions();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [kbId, isOntologyPromoted]);

    // 테스트 구성 자동 저장 (debounced) — 운영에는 영향 없음
    useEffect(() => {
        if (isLoading) return; // Don't save during initial load

        const saveTimeout = setTimeout(async () => {
            try {
                const d = await pvFetch('/draft', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ stages })
                });
                setChanges(d.changes || []);
            } catch (error) {
                console.error('Failed to save pipeline draft:', error);
            }
        }, 500); // Debounce 500ms

        return () => clearTimeout(saveTimeout);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [stages, kbId, isLoading]);

    // Notify parent of changes — 운영 탭이면 운영 구성, 테스트 탭이면 편집 중인 구성으로 채팅한다
    useEffect(() => {
        onPipelineChange(tab === 'live' ? { stages: liveStages, mode: 'live' } : { stages, mode: 'test' });
    }, [stages, liveStages, tab, onPipelineChange]);

    const handlePublish = async () => {
        setPvBusy(true);
        setPvError('');
        try {
            const d = await pvFetch('/publish', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ note: publishNote })
            });
            setLiveStages(adjustStages(d.live?.config?.stages || []));
            setLiveRef(d.live?.ref ?? null);
            setChanges(d.changes && !d.unchanged ? [] : (d.changes || []));
            setShowPublish(false);
            setPublishNote('');
            await refreshVersions();
        } catch (e: any) {
            setPvError(e.message);
        } finally {
            setPvBusy(false);
        }
    };

    const handleRevertToLive = () => {
        setStages(liveStages.map(s => ({ ...s, params: { ...s.params } })));
        setTab('test');
    };

    const handleViewVersion = async (ref: string) => {
        try {
            const d = await pvFetch(`/versions/${ref}`);
            setViewVersion({ ref, json: JSON.stringify(d.config, null, 2), changes: d.changes_from_live || [], warnings: d.warnings || [] });
        } catch (e: any) {
            setPvError(e.message);
        }
    };

    const handleLoadVersion = async (ref: string) => {
        setPvBusy(true);
        try {
            const d = await pvFetch(`/versions/${ref}/load`, { method: 'POST' });
            setStages(adjustStages(d.draft?.stages || []));
            setChanges(d.changes || []);
            setTab('test');
            setShowHistory(false);
            if ((d.warnings || []).length) setPvError(d.warnings.join(' / '));
        } catch (e: any) {
            setPvError(e.message);
        } finally {
            setPvBusy(false);
        }
    };

    const handleActivateVersion = async (v: PipelineVersion) => {
        setPvBusy(true);
        try {
            const d = await pvFetch(`/versions/${v.ref}/activate`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ version: v.version })
            });
            setLiveStages(adjustStages(d.live?.config?.stages || []));
            setLiveRef(d.live?.ref ?? null);
            setChanges(d.changes || []);
            setConfirmActivate(null);
            await refreshVersions();
        } catch (e: any) {
            setPvError(e.message);
        } finally {
            setPvBusy(false);
        }
    };

    const handleExport = () => {
        const shown = tab === 'live' ? liveStages : stages;
        const blob = new Blob([JSON.stringify({ schema: 'ragaas.pipeline/v1', stages: shown }, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `pipeline-${kbId.slice(0, 8)}-${tab === 'live' ? `live-v${liveVersion ?? 0}` : 'test'}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
    };

    const handleImport = async (file: File) => {
        try {
            const cfg = JSON.parse(await file.text());
            if (!Array.isArray(cfg.stages)) throw new Error("'stages' 배열이 없는 JSON 입니다");
            setStages(adjustStages(cfg.stages));   // 가져오기는 테스트 구성으로만
            setTab('test');
            setPvError('');
        } catch (e: any) {
            setPvError(`가져오기 실패: ${e.message}`);
        }
    };

    // --- Prompt Functions ---
    const loadGlobalRerankPrompt = async () => {
        setIsLoadingPrompt(true);
        setPromptError('');
        try {
            const response = await fetch(`${config.RAGAAS_API}knowledge-bases/settings/rerank-prompt`);
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
            const response = await fetch(`${config.RAGAAS_API}knowledge-bases/query-prompt/content?type=${backendType}`);
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
                const response = await fetch(`${config.RAGAAS_API}knowledge-bases/settings/rerank-prompt`, {
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
                const response = await fetch(`${config.RAGAAS_API}knowledge-bases/query-prompt/save`, {
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
        if (type === 'smalltalk') {
            params.llm_model = settings.chat_llm;
        }
        if (type === 'graph') {
            params.use_schema_mode = isOntologyPromoted ?? false;
            params.llm_model = settings.graph_query_llm;
        }
        if (type === 'rerank') {
            params.llm_model = settings.chat_llm; // or a dedicated rerank_llm if we add one
        }
        if (type === 'agentic') {
            // 기본은 그래프 질의 모델 — 사용자가 카드에서 바꿀 수 있다
            params.llm_model = settings.graph_query_llm;
        }

        const newStage: PipelineStage = {
            type,
            params,
            id: newStageId(),
        };
        // smalltalk 는 검색 앞단 게이트 → 맨 앞에 배치, 그 외는 맨 뒤에 추가
        // agentic 은 검색 과정을 이끄는 필터 → Gate 바로 뒤(없으면 맨 앞)
        if (type === 'smalltalk') {
            setStages([newStage, ...stages]);
        } else if (type === 'agentic') {
            const gateIdx = stages.findIndex(s => s.type === 'smalltalk');
            const at = gateIdx >= 0 ? gateIdx + 1 : 0;
            setStages([...stages.slice(0, at), newStage, ...stages.slice(at)]);
        } else {
            setStages([...stages, newStage]);
        }
        setShowDropdown(false);
    };

    const handleRemoveStage = (index: number) => {
        setStages(tidyFailureLinks(stages.filter((_, i) => i !== index)));
    };

    const handleSetFailureLink = (index: number, targetId: string | null) => {
        const next = [...stages];
        const { on_failure, ...rest } = next[index];
        next[index] = targetId ? { ...rest, on_failure: targetId } : rest;
        setStages(next);
        setFailureMenu(null);
    };

    const handleMoveStage = (index: number, direction: 'left' | 'right') => {
        const newIndex = direction === 'left' ? index - 1 : index + 1;
        if (newIndex < 0 || newIndex >= stages.length) return;

        const newStages = [...stages];
        [newStages[index], newStages[newIndex]] = [newStages[newIndex], newStages[index]];
        setStages(tidyFailureLinks(newStages));
    };

    const handleParamChange = (index: number, param: string, value: any) => {
        const newStages = [...stages];
        newStages[index] = {
            ...newStages[index],
            params: { ...newStages[index].params, [param]: value }
        };
        setStages(newStages);
    };

    const stageLabel = (t: StageType) =>
        [...GATE_STAGES, ...SEARCH_STAGES, ...FILTER_STAGES].find(s => s.type === t)?.label || t;

    // 카드 우하단 실패/예외 연결부 + 실패 경로 표시
    const renderFailurePort = (stage: PipelineStage, index: number, shown: PipelineStage[]) => {
        const agenticOn = shown.some(s => s.type === 'agentic');
        const sources = shown.map((s, i) => ({ s, i })).filter(({ s }) => s.on_failure && s.on_failure === stage.id);
        const targetIdx = stage.on_failure ? shown.findIndex(s => s.id === stage.on_failure) : -1;
        const candidates = shown.map((s, i) => ({ s, i })).filter(({ s, i }) => i > index && canBranch(s.type));
        const editable = tab === 'test';
        const linked = targetIdx >= 0;
        return (
            <>
                {sources.length > 0 && (
                    <div title="앞 스테이지가 실패했을 때만 실행됩니다 (성공하면 건너뜀)"
                        style={{ position: 'absolute', top: -9, left: 10, fontSize: '0.62rem', color: '#b91c1c',
                            background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 4, padding: '0 4px' }}>
                        실패 경로 ← {sources.map(({ s, i }) => `${i + 1}. ${stageLabel(s.type)}`).join(', ')}
                    </div>
                )}
                {canBranch(stage.type) && !agenticOn && (linked || (editable && candidates.length > 0)) && (
                    <div style={{ position: 'absolute', right: -7, bottom: -7, zIndex: 5 }}>
                        <button
                            onClick={() => editable && setFailureMenu(failureMenu === index ? null : index)}
                            title={linked
                                ? `실패/예외 시 → ${targetIdx + 1}. ${stageLabel(shown[targetIdx].type)}`
                                : '실패/예외 연결 — 없으면 실패를 알리고 파이프라인을 멈춥니다'}
                            style={{ width: 14, height: 14, borderRadius: '50%', padding: 0,
                                cursor: editable ? 'pointer' : 'default',
                                border: `2px ${linked ? 'solid' : 'dashed'} #dc2626`,
                                background: linked ? '#dc2626' : 'white' }} />
                        {failureMenu === index && editable && (
                            <div style={{ position: 'absolute', right: 0, top: 18, background: 'white', border: '1px solid #e2e8f0',
                                borderRadius: 6, boxShadow: '0 6px 12px rgba(0,0,0,0.12)', minWidth: 190, padding: '4px 0', zIndex: 9999 }}>
                                <div style={{ padding: '2px 10px', fontSize: '0.68rem', color: '#94a3b8', fontWeight: 600 }}>실패/예외 시 연결</div>
                                {candidates.map(({ s, i }) => (
                                    <div key={s.id} onClick={() => handleSetFailureLink(index, s.id!)}
                                        style={{ padding: '4px 10px', fontSize: '0.78rem', cursor: 'pointer',
                                            fontWeight: s.id === stage.on_failure ? 700 : 400, color: '#b91c1c' }}>
                                        → {i + 1}. {stageLabel(s.type)}
                                    </div>
                                ))}
                                <div onClick={() => handleSetFailureLink(index, null)}
                                    style={{ padding: '4px 10px', fontSize: '0.78rem', cursor: 'pointer', color: '#475569',
                                        fontWeight: linked ? 400 : 700 }}>
                                    연결 없음 (실패를 알리고 중단)
                                </div>
                            </div>
                        )}
                    </div>
                )}
                {linked && !agenticOn && (
                    <div style={{ position: 'absolute', right: 12, bottom: -16, fontSize: '0.62rem', color: '#b91c1c', whiteSpace: 'nowrap' }}>
                        실패 시 ↘ {targetIdx + 1}. {stageLabel(shown[targetIdx].type)}
                    </div>
                )}
            </>
        );
    };

    const renderStageCard = (stage: PipelineStage, index: number, shown: PipelineStage[] = stages) => {
        const stageInfo = [...GATE_STAGES, ...SEARCH_STAGES, ...FILTER_STAGES].find(s => s.type === stage.type);
        const isSearch = SEARCH_STAGES.some(s => s.type === stage.type);

        const usesLLM =
            stage.type === 'smalltalk' ||
            stage.type === 'agentic' ||
            stage.type === 'graph' ||
            (stage.type === 'rerank' && stage.params.use_llm);

        const baseStyle = usesLLM ? cardStyleLLM : cardStyle;
        const cardStyles: React.CSSProperties = {
            ...baseStyle,
            paddingBottom: (stage.type === 'graph' || stage.type === 'agentic') ? 0 : '0.65rem',
            width: 'fit-content',
            minWidth: '180px',
            flexShrink: 0,
            ...((stage.type === 'graph' || stage.type === 'agentic') && { height: 'auto', minHeight: '160px' }),
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

                        {/* Schema On/Off 제거 (2026-11-17) — LLM SPARQL 생성(C) 경로에만 쓰이던 옵션, C 는 화면에서 쓰지 않음 */}
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
                {renderFailurePort(stage, index, shown)}
            </div>
        );
    };

    const renderStageParams = (stage: PipelineStage, index: number) => {
        const params = stage.params;

        switch (stage.type) {
            case 'smalltalk':
                return (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', flexWrap: 'wrap', paddingTop: '0.15rem' }}>
                        <span style={{ fontSize: '0.7rem', color: '#475569', flexShrink: 0 }}>Model</span>
                        <ModelSelector
                            type="llm"
                            value={params.llm_model || DEFAULT_LLM_CONFIG}
                            onChange={(cfg) => handleParamChange(index, 'llm_model', cfg)}
                        />
                    </div>
                );

            case 'agentic':
                // Graph 카드와 같은 배치: 슬라이더 왼쪽 고정, 옆에 Mode → Model
                return (
                    <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', alignItems: 'flex-start' }}>
                        <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', flexShrink: 0 }}>
                            <ParamSlider
                                label="Max Steps"
                                value={params.max_steps ?? 6}
                                min={1} max={10}
                                onChange={(v) => handleParamChange(index, 'max_steps', v)}
                            />
                            <ParamSlider
                                label="Time (s)"
                                value={params.time_budget_s ?? 60}
                                min={10} max={120} step={5}
                                onChange={(v) => handleParamChange(index, 'time_budget_s', v)}
                            />
                        </div>
                        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.3rem', minWidth: 0 }}>
                            <div style={{ display: 'flex', alignItems: 'center' }} title="auto: 복합 질문이거나 단일 실행이 근거 없이 끝날 때만 단계 진행 / always: 항상 단계 진행">
                                <ParamSelect
                                    label="Mode"
                                    layout="inline"
                                    minWidth="80px"
                                    value={params.mode || 'auto'}
                                    options={[
                                        { value: 'auto', label: 'Auto' },
                                        { value: 'always', label: 'Always' }
                                    ]}
                                    onChange={(v) => handleParamChange(index, 'mode', v)}
                                />
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', flexWrap: 'wrap' }}>
                                <span style={{ fontSize: '0.7rem', color: '#475569', flexShrink: 0 }}>Model</span>
                                <ModelSelector
                                    type="llm"
                                    value={params.llm_model || DEFAULT_LLM_CONFIG}
                                    onChange={(cfg) => handleParamChange(index, 'llm_model', cfg)}
                                />
                            </div>
                        </div>
                    </div>
                );

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
                // Max Hop: 옛 설정(is_auto_hops/hops) 호환 — 백엔드 resolve_max_hops 와 같은 규칙
                const maxHops = params.max_hops ?? (params.is_auto_hops === false ? params.hops : 6) ?? 6;
                const showLatencyWarning = maxHops >= 7;
                return (
                    <>
                        <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', alignItems: 'flex-start' }}>
                            {/* 슬라이더: 왼쪽 고정 */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', flexShrink: 0 }}>
                                <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem' }}>
                                    <ParamSlider
                                        label="Max Hop"
                                        value={maxHops}
                                        min={1} max={8}
                                        onChange={(v) => handleParamChange(index, 'max_hops', v)}
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
                                {/* 오탈자·유사어 | 목록 보강 */}
                                <div style={{ display: 'flex', flexDirection: 'row', gap: '0.3rem', alignItems: 'center' }}>
                                    <ParamCheckbox
                                        label="Typo·Synonym"
                                        checked={params.resolve_terms ?? true}
                                        onChange={(v) => handleParamChange(index, 'resolve_terms', v)}
                                    />
                                    <ParamCheckbox
                                        label="List Supplement"
                                        checked={params.list_supplement ?? true}
                                        onChange={(v) => handleParamChange(index, 'list_supplement', v)}
                                        disabled={!!stage.on_failure || (params.graph_fallback ?? 'vector') === 'none'}
                                    />
                                </div>
                                {/* 그래프로 못 찾으면 */}
                                <div style={{ display: 'flex', alignItems: 'center' }}>
                                    <ParamSelect
                                        label="No Graph Result"
                                        layout="inline"
                                        minWidth="90px"
                                        disabled={!!stage.on_failure}
                                        value={stage.on_failure ? 'none' : (params.graph_fallback ?? 'vector')}
                                        options={[
                                            { value: 'vector', label: 'Doc Search' },
                                            { value: 'none', label: 'Empty' }
                                        ]}
                                        onChange={(v) => handleParamChange(index, 'graph_fallback', v)}
                                    />
                                </div>
                                {/* Model — 질문 분석·경로 선택·질의 계획·체인 계획에 쓰는 LLM (Dynamic Schema·쿼리 프롬프트는 C 경로 전용이라 제거) */}
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', flexWrap: 'wrap' }}>
                                    <span style={{ fontSize: '0.7rem', color: '#475569', flexShrink: 0 }}>Model</span>
                                    <ModelSelector
                                        type="llm"
                                        value={params.llm_model || DEFAULT_LLM_CONFIG}
                                        onChange={(cfg) => handleParamChange(index, 'llm_model', cfg)}
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
                {/* 운영 / 테스트 탭 */}
                <div style={{ display: 'flex', gap: '2px', background: '#f1f5f9', borderRadius: '6px', padding: '2px' }}>
                    {(['live', 'test'] as const).map(t => (
                        <button key={t} onClick={() => setTab(t)}
                            title={t === 'live' ? '운영 구성 (읽기 전용) — 외부 에이전트·API 가 받는 결과와 같습니다' : '테스트 구성 — 편집하고 시험한 뒤 운영에 반영합니다'}
                            style={{
                                border: 'none', cursor: 'pointer', borderRadius: '4px', padding: '3px 10px', fontSize: '0.8rem',
                                fontWeight: tab === t ? 600 : 400,
                                background: tab === t ? 'white' : 'transparent',
                                color: tab === t ? (t === 'live' ? '#047857' : '#1d4ed8') : '#64748b',
                                boxShadow: tab === t ? '0 1px 2px rgba(0,0,0,0.08)' : 'none'
                            }}>
                            {t === 'live' ? `운영${liveVersion ? ` v${liveVersion}` : ''}` : '테스트'}
                            {t === 'test' && changes.length > 0 && <span style={{ color: '#f59e0b', marginLeft: 4 }}>●</span>}
                        </button>
                    ))}
                </div>
                {tab === 'test' && changes.length > 0 && (
                    <>
                        <span style={{ fontSize: '0.75rem', color: '#b45309' }} title={changes.join('\n')}>운영과 다름 {changes.length}곳</span>
                        <button className="btn" onClick={() => { setPvError(''); setShowPublish(true); }}
                            style={{ fontSize: '0.75rem', padding: '3px 10px', background: '#1d4ed8', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
                            운영에 반영…
                        </button>
                        <button onClick={handleRevertToLive}
                            style={{ fontSize: '0.75rem', padding: '3px 8px', background: 'white', color: '#475569', border: '1px solid #cbd5e1', borderRadius: '4px', cursor: 'pointer' }}>
                            운영 구성으로 되돌리기
                        </button>
                    </>
                )}
                {tab === 'live' && (
                    <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                        읽기 전용{liveRef ? ` · ${liveRef.slice(0, 8)}` : ' · 이력 없음'}
                    </span>
                )}
                <div style={{ flex: 1 }} />
                <button onClick={() => { setShowHistory(true); setViewVersion(null); refreshVersions(); }}
                    style={{ fontSize: '0.75rem', padding: '3px 8px', background: 'white', color: '#475569', border: '1px solid #cbd5e1', borderRadius: '4px', cursor: 'pointer' }}>
                    이력
                </button>
                <button onClick={handleExport} title="JSON 내보내기"
                    style={{ fontSize: '0.75rem', padding: '3px 8px', background: 'white', color: '#475569', border: '1px solid #cbd5e1', borderRadius: '4px', cursor: 'pointer' }}>
                    JSON ↓
                </button>
                <button onClick={() => importRef.current?.click()} title="JSON 가져오기 (테스트 구성으로)"
                    style={{ fontSize: '0.75rem', padding: '3px 8px', background: 'white', color: '#475569', border: '1px solid #cbd5e1', borderRadius: '4px', cursor: 'pointer' }}>
                    JSON ↑
                </button>
                <input ref={importRef} type="file" accept="application/json,.json" style={{ display: 'none' }}
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) handleImport(f); e.target.value = ''; }} />
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

            {pvError && (
                <div style={{ fontSize: '0.75rem', color: '#b91c1c', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '4px', padding: '4px 8px', marginBottom: '0.5rem', display: 'flex', gap: 8 }}>
                    <span style={{ flex: 1 }}>{pvError}</span>
                    <span style={{ cursor: 'pointer' }} onClick={() => setPvError('')}>✕</span>
                </div>
            )}

            {/* Wrapper for stages and add button — 운영 탭은 읽기 전용 */}
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start', overflow: 'visible',
                ...(tab === 'live' ? { pointerEvents: 'none' as const, opacity: 0.9 } : {}) }}>
                {/* Scrollable stages container */}
                <div style={{
                    display: 'flex',
                    gap: '0.5rem',
                    alignItems: 'flex-start',
                    overflowX: 'auto',
                    paddingTop: '10px',      // 카드 위 '실패 경로' 표시 자리
                    paddingBottom: '20px'    // 카드 아래 '실패 시 ↘' 표시·연결부 자리
                }}>
                    {/* Render stages */}
                    {(tab === 'live' ? liveStages : stages).map((stage, index, shown) => (
                        <React.Fragment key={`${tab}-${index}`}>
                            {renderStageCard(stage, index, shown)}
                            {index < shown.length - 1 && (
                                <div title="정상 연결 — 성공하면 다음 스테이지로" style={{ display: 'flex', alignItems: 'center', color: '#94a3b8', flexShrink: 0, height: '48px' }}>
                                    →
                                </div>
                            )}
                        </React.Fragment>
                    ))}
                </div>

                {/* Arrow before Add button if stages exist */}
                {tab === 'test' && stages.length > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', color: '#94a3b8', flexShrink: 0, height: '48px' }}>
                        →
                    </div>
                )}

                {/* Add button wrapper - OUTSIDE scroll container */}
                <div style={{ position: 'relative', flexShrink: 0, zIndex: 1000, display: tab === 'live' ? 'none' : 'block' }}>
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
                            {filteredStages.some(s => s.category === 'gate') && (
                                <>
                                    <div style={{ padding: '0.25rem 1rem', fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>
                                        Gate
                                    </div>
                                    {filteredStages.filter(s => s.category === 'gate').map(stage => (
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
                                    <div style={{ borderTop: '1px solid #e2e8f0', margin: '0.25rem 0' }} />
                                </>
                            )}
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

            {/* 운영에 반영 — 차이·메모 확인 후 Git 커밋 */}
            {showPublish && createPortal(
                <div style={overlayStyle} onClick={() => !pvBusy && setShowPublish(false)}>
                    <div style={dialogStyle} onClick={(e) => e.stopPropagation()}>
                        <h3 style={{ margin: '0 0 0.75rem', fontSize: '1rem' }}>운영에 반영</h3>
                        <p style={{ margin: '0 0 0.5rem', fontSize: '0.85rem', color: '#475569' }}>
                            테스트 구성을 운영에 반영합니다. 반영하면 채팅·API·MCP(외부 에이전트)가 이 구성으로 동작합니다.
                            이력 저장소(Git)에 새 버전으로 남습니다.
                        </p>
                        <div style={{ fontSize: '0.8rem', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 6, padding: '0.5rem 0.75rem', maxHeight: 220, overflow: 'auto' }}>
                            {changes.length ? changes.map((c, i) => <div key={i} style={{ fontFamily: 'monospace' }}>• {c}</div>)
                                : <div style={{ color: '#64748b' }}>운영과 다른 곳이 없습니다{liveRef ? '' : ' (첫 버전으로 기록)'}</div>}
                        </div>
                        <label style={{ display: 'block', fontSize: '0.8rem', margin: '0.75rem 0 0.25rem', color: '#334155' }}>메모 (버전 설명)</label>
                        <input value={publishNote} onChange={(e) => setPublishNote(e.target.value)} placeholder="예: Max Hop 8, Typo 끔"
                            style={{ width: '100%', boxSizing: 'border-box', padding: '6px 8px', border: '1px solid #cbd5e1', borderRadius: 4, fontSize: '0.85rem' }} />
                        {pvError && <div style={{ color: '#b91c1c', fontSize: '0.8rem', marginTop: 8 }}>{pvError} — 운영은 바뀌지 않았습니다.</div>}
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: '1rem' }}>
                            <button onClick={() => setShowPublish(false)} disabled={pvBusy} style={secondaryBtn}>취소</button>
                            <button onClick={handlePublish} disabled={pvBusy} style={primaryBtn}>{pvBusy ? '반영 중…' : '반영'}</button>
                        </div>
                    </div>
                </div>,
                document.body
            )}

            {/* 버전 이력 — 보기·비교 / 테스트로 불러오기 / 운영으로 되돌리기 */}
            {showHistory && createPortal(
                <div style={overlayStyle} onClick={() => !pvBusy && setShowHistory(false)}>
                    <div style={{ ...dialogStyle, width: 'min(860px, calc(100vw - 32px))' }} onClick={(e) => e.stopPropagation()}>
                        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '0.75rem' }}>
                            <h3 style={{ margin: 0, fontSize: '1rem', flex: 1 }}>파이프라인 이력</h3>
                            <span style={{ cursor: 'pointer', color: '#64748b' }} onClick={() => setShowHistory(false)}>✕</span>
                        </div>
                        {pvError && <div style={{ color: '#b91c1c', fontSize: '0.8rem', marginBottom: 8 }}>{pvError}</div>}
                        <div style={{ display: 'flex', gap: '0.75rem', minHeight: 260 }}>
                            <div style={{ flex: '0 0 380px', maxHeight: 420, overflow: 'auto', border: '1px solid #e2e8f0', borderRadius: 6 }}>
                                {versions.length === 0 && <div style={{ padding: '0.75rem', fontSize: '0.8rem', color: '#64748b' }}>이력이 없습니다.</div>}
                                {versions.map(v => (
                                    <div key={v.ref} style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid #f1f5f9', fontSize: '0.8rem',
                                        background: viewVersion?.ref === v.ref ? '#eff6ff' : 'transparent' }}>
                                        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                                            <b>v{v.version}</b>
                                            {v.live && <span style={{ fontSize: '0.7rem', color: '#047857', border: '1px solid #6ee7b7', borderRadius: 3, padding: '0 4px' }}>운영</span>}
                                            <span style={{ color: '#94a3b8', marginLeft: 'auto' }}>{v.created_at ? new Date(v.created_at).toLocaleString() : ''}</span>
                                        </div>
                                        <div style={{ color: '#334155', margin: '2px 0 4px' }}>{v.note}</div>
                                        <div style={{ display: 'flex', gap: 6 }}>
                                            <button style={linkBtn} onClick={() => handleViewVersion(v.ref)}>보기</button>
                                            <button style={linkBtn} disabled={pvBusy} onClick={() => handleLoadVersion(v.ref)}>테스트로 불러오기</button>
                                            {!v.live && (confirmActivate === v.ref
                                                ? <>
                                                    <button style={{ ...linkBtn, color: '#b91c1c' }} disabled={pvBusy} onClick={() => handleActivateVersion(v)}>정말 운영을 v{v.version} 으로?</button>
                                                    <button style={linkBtn} onClick={() => setConfirmActivate(null)}>취소</button>
                                                </>
                                                : <button style={linkBtn} onClick={() => setConfirmActivate(v.ref)}>운영으로 되돌리기</button>)}
                                        </div>
                                    </div>
                                ))}
                            </div>
                            <div style={{ flex: 1, minWidth: 0, fontSize: '0.8rem' }}>
                                {viewVersion ? (
                                    <>
                                        <div style={{ marginBottom: 6, color: '#334155' }}>
                                            운영과 차이: {viewVersion.changes.length ? '' : '없음'}
                                            {viewVersion.changes.map((c, i) => <div key={i} style={{ fontFamily: 'monospace' }}>• {c}</div>)}
                                            {viewVersion.warnings.map((w, i) => <div key={i} style={{ color: '#b45309' }}>⚠ {w}</div>)}
                                        </div>
                                        <pre style={{ margin: 0, maxHeight: 340, overflow: 'auto', background: '#0f172a', color: '#e2e8f0', padding: '0.5rem', borderRadius: 6, fontSize: '0.75rem' }}>{viewVersion.json}</pre>
                                    </>
                                ) : <div style={{ color: '#94a3b8' }}>버전을 고르면 구성(JSON)과 운영과의 차이를 보여 줍니다.</div>}
                            </div>
                        </div>
                    </div>
                </div>,
                document.body
            )}
        </div>
    );
}

const overlayStyle: React.CSSProperties = {
    position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)', zIndex: 20000,
    display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16
};
const dialogStyle: React.CSSProperties = {
    background: 'white', borderRadius: 8, padding: '1rem 1.25rem', width: 'min(520px, calc(100vw - 32px))',
    boxShadow: '0 20px 25px -5px rgba(0,0,0,0.15)'
};
const primaryBtn: React.CSSProperties = { padding: '6px 14px', background: '#1d4ed8', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: '0.85rem' };
const secondaryBtn: React.CSSProperties = { padding: '6px 14px', background: 'white', color: '#475569', border: '1px solid #cbd5e1', borderRadius: 4, cursor: 'pointer', fontSize: '0.85rem' };
const linkBtn: React.CSSProperties = { background: 'none', border: 'none', padding: 0, color: '#1d4ed8', cursor: 'pointer', fontSize: '0.75rem' };

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


