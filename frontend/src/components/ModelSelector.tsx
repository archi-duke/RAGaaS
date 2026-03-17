import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Eye, EyeOff, X, Loader2, Check, Trash2, RefreshCw, Search, FileEdit } from 'lucide-react';
import { providerApi } from '../services/api';

// ── 타입 정의 ─────────────────────────────────────────────────────────────────

export interface ModelConfig {
    provider: string;
    provider_name: string;
    model: string;
    base_url?: string;
    provider_id?: string;
}

interface BuiltinProvider {
    name: string;
    base_url: string;
    has_key?: boolean;
    models?: { llm?: string[]; embedding?: string[] };
    cached_at?: string;
}

interface CustomProvider {
    provider_id: string;
    name: string;
    base_url: string;
    model_list: string[];
    provider_type: string;
    has_key: boolean;
}

interface ProvidersData {
    builtin: Record<string, BuiltinProvider>;
    custom: CustomProvider[];
}

interface ModelSelectorProps {
    type: 'llm' | 'embedding';
    value: ModelConfig;
    onChange: (config: ModelConfig, selectedType?: 'llm' | 'embedding') => void;
    disabled?: boolean;
    /** EMB 탭 선택 시 표시/저장용 (있으면 탭 전환 시 해당 값 사용) */
    valueEmbedding?: ModelConfig;
    /** EMB 탭에서 확인 시 호출 (없으면 onChange(config, 'embedding') 호출) */
    onChangeEmbedding?: (config: ModelConfig) => void;
    /** LLM일 때 모달 내 확인 버튼 위에 프롬프트 편집 버튼 표시 */
    onEditPrompt?: () => void;
}

type ProviderType = 'llm' | 'embedding' | 'both';

// ── 기본값 ────────────────────────────────────────────────────────────────────

export const DEFAULT_LLM_CONFIG: ModelConfig = {
    provider: 'openai',
    provider_name: 'OpenAI',
    model: 'gpt-4o-mini',
};

export const DEFAULT_EMBEDDING_CONFIG: ModelConfig = {
    provider: 'openai',
    provider_name: 'OpenAI',
    model: 'text-embedding-3-small',
};

// ── 프로바이더 색상 & 아이콘 (Simple Icons: https://simpleicons.org) ─────────────

const BUILTIN_COLORS: Record<string, { bg: string; text: string }> = {
    openai: { bg: '#00a67e', text: '#fff' },
    anthropic: { bg: '#c96442', text: '#fff' },
    google: { bg: '#4285f4', text: '#fff' },
};

/** Simple Icons slug per built-in provider (cdn.simpleicons.org) */
const BUILTIN_ICON_SLUGS: Record<string, string> = {
    openai: 'openai',
    anthropic: 'anthropic',
    google: 'googlegemini',
};

/** 사용자 지정 아이콘: public/icons 경로 또는 data URL (CDN보다 우선) */
const BUILTIN_ICON_DATA_URLS: Record<string, string> = {
    openai: '/icons/openai-chatgpt.png',
    google: '/icons/gemini.png',
};

const SIMPLE_ICONS_CDN = 'https://cdn.simpleicons.org';

function getBuiltinStyle(key: string) {
    return BUILTIN_COLORS[key] ?? { bg: '#64748b', text: '#fff' };
}

function getInitial(name: string) {
    return name.charAt(0).toUpperCase();
}

/** 프로바이더 아이콘: data URL 우선, 없으면 Simple Icons CDN, 실패 시 첫 글자 폴백 */
function ProviderIcon({
    providerKey,
    name,
    size = 20,
    style = {},
}: {
    providerKey: string;
    name: string;
    size?: number;
    style?: React.CSSProperties;
}) {
    const dataUrl = BUILTIN_ICON_DATA_URLS[providerKey];
    const slug = BUILTIN_ICON_SLUGS[providerKey];
    const { bg, text } = getBuiltinStyle(providerKey);
    const [imgFailed, setImgFailed] = useState(false);
    const cdnUrl = slug ? `${SIMPLE_ICONS_CDN}/${slug}/${encodeURIComponent(text)}?viewbox=auto&size=${Math.max(size - 4, 4)}` : null;

    const boxStyle: React.CSSProperties = {
        width: size,
        height: size,
        borderRadius: Math.max(size / 4, 2),
        background: bg,
        color: text,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        overflow: 'hidden',
        ...style,
    };

    const imgSize = Math.max(size - 4, 4);
    if (dataUrl) {
        // 사용자 지정 아이콘: 배경 없이 원본 그대로 표시
        return (
            <div style={{ ...boxStyle, background: 'transparent', padding: 0 }}>
                <img
                    src={dataUrl}
                    alt=""
                    width={size}
                    height={size}
                    style={{ objectFit: 'contain', display: 'block' }}
                />
            </div>
        );
    }
    if (cdnUrl && !imgFailed) {
        return (
            <div style={boxStyle}>
                <img
                    src={cdnUrl}
                    alt=""
                    width={imgSize}
                    height={imgSize}
                    style={{ objectFit: 'contain' }}
                    onError={() => setImgFailed(true)}
                />
            </div>
        );
    }
    return (
        <div style={{ ...boxStyle, fontSize: size * 0.4, fontWeight: 700 }}>
            {getInitial(name)}
        </div>
    );
}

// ── 컴포넌트 ──────────────────────────────────────────────────────────────────

export default function ModelSelector({ type, value, onChange, disabled, valueEmbedding, onChangeEmbedding, onEditPrompt }: ModelSelectorProps) {
    const [isOpen, setIsOpen] = useState(false);
    const [providers, setProviders] = useState<ProvidersData>({ builtin: {}, custom: [] });
    const [loading, setLoading] = useState(false);

    // 팝업 내 선택 상태 (type은 props에서 전달)
    const [selectedProvider, setSelectedProvider] = useState(value.provider);
    const [selectedModel, setSelectedModel] = useState(value.model);
    const [directInput, setDirectInput] = useState(false); // 모델 직접 입력 모드

    const CUSTOM_OPTION = '__custom__';
    const [customForm, setCustomForm] = useState({
        name: '', base_url: '', api_key: '', extra_headers_text: '', model_list_text: '',
        provider_type: 'both' as ProviderType,
        embedding_request_format: 'minimal' as 'openai' | 'minimal',
    });
    const [showKey, setShowKey] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState('');
    const [isEditing, setIsEditing] = useState(false);

    // 모델 목록 가져오기 (custom form)
    const [fetchingModels, setFetchingModels] = useState(false);
    const [fetchedModels, setFetchedModels] = useState<string[]>([]);
    const [pickedModels, setPickedModels] = useState<Set<string>>(new Set());
    const [showModelPicker, setShowModelPicker] = useState(false);
    const [modelSearch, setModelSearch] = useState('');
    const [fetchError, setFetchError] = useState('');

    // 메인 선택 — 모델 새로고침
    const [refreshingModels, setRefreshingModels] = useState(false);
    const [liveModelList, setLiveModelList] = useState<string[] | null>(null); // null = 미조회

    // Built-in 프로바이더 API Key 등록
    const [builtinApiKey, setBuiltinApiKey] = useState('');
    const [showBuiltinKey, setShowBuiltinKey] = useState(false);
    const [refreshError, setRefreshError] = useState('');

    const triggerRef = useRef<HTMLDivElement>(null);
    const popupRef = useRef<HTMLDivElement>(null);
    const [popupHeight, setPopupHeight] = useState(420);

    // Measure popup height after it is rendered so position is accurate.
    useLayoutEffect(() => {
        if (!isOpen) return;
        const h = popupRef.current?.offsetHeight;
        if (h && Number.isFinite(h)) {
            setPopupHeight(h);
        }
    }, [isOpen, loading, selectedProvider, selectedModel, directInput, showModelPicker, type]);

    // ── 팝업 열릴 때 초기화 ───────────────────────────────────────────────────
    useEffect(() => {
        if (!isOpen) return;
        const source = type === 'llm' ? value : (valueEmbedding ?? DEFAULT_EMBEDDING_CONFIG);
        setSelectedProvider(source.provider);
        setSelectedModel(source.model);
        setDirectInput(false);
        setLiveModelList(null);
        setSaveError('');
        setFetchError('');
        setShowModelPicker(false);
        loadProvidersForType(type);
    }, [isOpen, type]);

    const loadProvidersForType = async (t: 'llm' | 'embedding') => {
        setLoading(true);
        try {
            const res = await providerApi.list({ model_type: t });
            setProviders(res.data);
        } catch {
            // ignore
        } finally {
            setLoading(false);
        }
    };

    // 프로바이더 변경 시 live 목록 초기화
    useEffect(() => {
        setLiveModelList(null);
        setDirectInput(false);
        setBuiltinApiKey('');
        setRefreshError('');
        setIsEditing(false);
    }, [selectedProvider]);

    // ── 외부 클릭 닫기 ────────────────────────────────────────────────────────
    useEffect(() => {
        if (!isOpen) return;
        const handler = (e: MouseEvent) => {
            const target = e.target as Node;
            if (triggerRef.current?.contains(target)) return;
            if (popupRef.current?.contains(target)) return;
            setIsOpen(false);
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [isOpen]);

    // ── 프로바이더 목록 로드 ─────────────────────────────────────────────────────
    const loadProviders = () => loadProvidersForType(type);

    // ── 저장된/캐시된 모델 목록 ───────────────────────────────────────────────────
    const getStoredModelList = (providerKey: string): string[] => {
        if (providerKey === '__custom__') return [];
        const builtin = providers.builtin[providerKey];
        if (builtin?.models) {
            const list = type === 'embedding' ? builtin.models.embedding : builtin.models.llm;
            return list ?? [];
        }
        const custom = providers.custom.find(c => c.provider_id === providerKey);
        return custom?.model_list ?? [];
    };

    // 표시할 모델 목록: live 새로고침이 있으면 우선 사용
    const displayModelList = liveModelList ?? getStoredModelList(selectedProvider);

    // ── 프로바이더 선택 ───────────────────────────────────────────────────────
    const handleProviderChange = (providerKey: string) => {
        if (providerKey === CUSTOM_OPTION) {
            setCustomForm({ name: '', base_url: '', api_key: '', extra_headers_text: '', model_list_text: '', provider_type: 'both', embedding_request_format: 'minimal' });
            setSaveError('');
            setFetchError('');
            setShowModelPicker(false);
        }
        setSelectedProvider(providerKey);
        if (providerKey !== CUSTOM_OPTION) {
            const models = getStoredModelList(providerKey);
            setSelectedModel(models[0] ?? '');
            setLiveModelList(null);
        }
    };

    // ── 확인 (type에 따라 onChange / onChangeEmbedding 호출) ───────────────────
    const handleConfirm = () => {
        const builtin = providers.builtin[selectedProvider];
        const custom = providers.custom.find(c => c.provider_id === selectedProvider);
        const providerName = builtin?.name ?? custom?.name ?? selectedProvider;
        const base_url = builtin?.base_url ?? custom?.base_url;
        const config = {
            provider: selectedProvider,
            provider_name: providerName,
            model: selectedModel,
            base_url,
            provider_id: custom?.provider_id,
        };
        if (type === 'embedding' && onChangeEmbedding) {
            onChangeEmbedding(config);
        } else {
            onChange(config, type);
        }
        setIsOpen(false);
    };

    /** Parse extra_headers_text "Header-Name: value" per line into Record */
    const parseExtraHeaders = (text: string): Record<string, string> => {
        const out: Record<string, string> = {};
        for (const line of text.split('\n')) {
            const t = line.trim();
            if (!t) continue;
            const idx = t.indexOf(':');
            if (idx <= 0) continue;
            const key = t.slice(0, idx).trim();
            const val = t.slice(idx + 1).trim();
            if (key) out[key] = val;
        }
        return out;
    };

    // ── Custom 저장/수정 ────────────────────────────────────────────────────────
    const handleSaveCustom = async () => {
        const needApiKey = !isEditing && customForm.embedding_request_format !== 'minimal';
        // 수정 시에는 API Key를 입력하지 않아도 기존 키를 유지한다고 가정하거나(백엔드 구현에 따라), 
        // 여기서는 필수로 입력하게 하거나 사용자 편의를 따름.
        // 현재 백엔드 로직상 암호화 키 변경 이슈 해결을 위해 새로 입력하는 것이 안전함.
        if (!customForm.name.trim() || !customForm.base_url.trim() || (needApiKey && !customForm.api_key.trim())) {
            setSaveError(needApiKey ? 'Name, API URL, and API Key are required.' : 'Name and API URL are required.');
            return;
        }
        setSaving(true);
        setSaveError('');
        try {
            const model_list = customForm.model_list_text
                .split('\n').map(s => s.trim()).filter(Boolean);
            const extra_headers = parseExtraHeaders(customForm.extra_headers_text);

            let res;
            if (isEditing) {
                res = await providerApi.updateCustom(selectedProvider, {
                    name: customForm.name.trim(),
                    base_url: customForm.base_url.trim(),
                    api_key: customForm.api_key || '',
                    model_list,
                    provider_type: customForm.provider_type,
                    embedding_request_format: customForm.embedding_request_format,
                    ...(Object.keys(extra_headers).length > 0 && { extra_headers }),
                });
                setIsEditing(false);
            } else {
                res = await providerApi.createCustom({
                    name: customForm.name.trim(),
                    base_url: customForm.base_url.trim(),
                    api_key: customForm.api_key || '',
                    model_list,
                    provider_type: customForm.provider_type,
                    embedding_request_format: customForm.embedding_request_format,
                    ...(Object.keys(extra_headers).length > 0 && { extra_headers }),
                });
            }
            await loadProviders();
            setSelectedProvider(res.data.provider_id);
            setSelectedModel(model_list[0] ?? '');
        } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } } };
            setSaveError(err.response?.data?.detail ?? 'Save failed');
        } finally {
            setSaving(false);
        }
    };

    // ── Custom 수정 시작 ────────────────────────────────────────────────────────
    const handleStartEditCustom = () => {
        const c = providers.custom.find(p => p.provider_id === selectedProvider);
        if (!c) return;

        // extra_headers를 다시 텍스트로 변환
        let headersText = '';
        const rawHeaders = (c as any).extra_headers;
        if (rawHeaders) {
            headersText = Object.entries(rawHeaders)
                .map(([k, v]) => `${k}: ${v}`)
                .join('\n');
        }

        setCustomForm({
            name: c.name,
            base_url: c.base_url,
            api_key: '', // 보안상 빈 값으로 시작 (사용자가 새로 입력하게 함)
            extra_headers_text: headersText,
            model_list_text: c.model_list.join('\n'),
            provider_type: c.provider_type as ProviderType,
            embedding_request_format: (c as any).embedding_request_format || (c.provider_type === 'embedding' ? 'minimal' : 'openai'),
        });
        setIsEditing(true);
        setSaveError('');
    };

    // ── Custom 삭제 ───────────────────────────────────────────────────────────
    const handleDeleteCustom = async (providerId: string, e: React.MouseEvent) => {
        e.stopPropagation();
        if (!window.confirm('Delete this provider?')) return;
        try {
            await providerApi.deleteCustom(providerId);
            await loadProviders();
            if (selectedProvider === providerId) {
                const firstKey = Object.keys(providers.builtin)[0] ?? '';
                setSelectedProvider(firstKey);
                setSelectedModel(getStoredModelList(firstKey)[0] ?? '');
            }
        } catch { /* ignore */ }
    };

    // ── [Custom 폼] API에서 모델 목록 가져오기 ────────────────────────────────
    const handleFetchModelsForForm = async () => {
        if (!customForm.base_url.trim() || !customForm.api_key.trim()) {
            setFetchError('Enter API URL and API Key first.');
            return;
        }
        setFetchingModels(true);
        setFetchError('');
        setShowModelPicker(false);
        try {
            const extra_headers = parseExtraHeaders(customForm.extra_headers_text);
            const res = await providerApi.fetchModels({
                base_url: customForm.base_url.trim(),
                api_key: customForm.api_key,
                ...(Object.keys(extra_headers).length > 0 && { extra_headers }),
            });
            const models: string[] = res.data.models;
            setFetchedModels(models);
            // 기존 textarea 내용이 있으면 해당 항목 선택 상태로 초기화
            const existing = new Set(
                customForm.model_list_text.split('\n').map(s => s.trim()).filter(Boolean)
            );
            setPickedModels(existing.size > 0 ? existing : new Set(models));
            setShowModelPicker(true);
            setModelSearch('');
        } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } }; message?: string };
            setFetchError(err.response?.data?.detail ?? err.message ?? 'Failed to fetch models');
        } finally {
            setFetchingModels(false);
        }
    };

    // 체크박스 토글
    const togglePickedModel = (model: string) => {
        setPickedModels(prev => {
            const next = new Set(prev);
            next.has(model) ? next.delete(model) : next.add(model);
            return next;
        });
    };

    // 선택 적용 → textarea에 반영
    const applyModelPicker = () => {
        const ordered = fetchedModels.filter(m => pickedModels.has(m));
        setCustomForm(p => ({ ...p, model_list_text: ordered.join('\n') }));
        setShowModelPicker(false);
    };

    // ── [메인] Built-in API Key 등록 ───────────────────────────────────────────
    const handleRegisterBuiltinKey = async () => {
        if (!builtinApiKey.trim()) {
            setRefreshError('Enter API Key.');
            return;
        }
        setRefreshingModels(true);
        setRefreshError('');
        try {
            await providerApi.updateBuiltinKey(selectedProvider, builtinApiKey.trim());
            setBuiltinApiKey('');
            await loadProviders();
            // 등록 후 자동으로 모델 목록 조회
            const res = await providerApi.fetchModels({ provider_id: selectedProvider, model_type: type });
            const models: string[] = res.data.models;
            await loadProviders();
            if (models.length > 0) setSelectedModel(models[0]);
            if (res.data.models_changed) {
                alert('Model list has changed. The updated list has been applied.');
            }
        } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } }; message?: string };
            setRefreshError(err.response?.data?.detail ?? err.message ?? 'Registration/fetch failed');
        } finally {
            setRefreshingModels(false);
        }
    };

    // ── [메인] Built-in 모델 새로고침 (저장된 키 사용) ───────────────────────────
    const handleRefreshBuiltinModels = async () => {
        setRefreshingModels(true);
        setRefreshError('');
        try {
            const res = await providerApi.fetchModels({ provider_id: selectedProvider, model_type: type });
            const models: string[] = res.data.models;
            await loadProviders();
            if (models.length > 0 && !models.includes(selectedModel)) {
                setSelectedModel(models[0]);
            }
            if (res.data.models_changed) {
                alert('Model list has changed. The updated list has been applied.');
            }
        } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } }; message?: string };
            setRefreshError(err.response?.data?.detail ?? err.message ?? 'Fetch failed');
        } finally {
            setRefreshingModels(false);
        }
    };

    // ── [메인] Custom 프로바이더 모델 새로고침 ────────────────────────────────
    const handleRefreshModels = async () => {
        const customProvider = providers.custom.find(c => c.provider_id === selectedProvider);
        if (!customProvider) return;
        setRefreshingModels(true);
        setRefreshError('');
        try {
            const res = await providerApi.fetchModels({ provider_id: selectedProvider, model_type: type });
            const models: string[] = res.data.models;
            setLiveModelList(models);
            if (models.length > 0 && !models.includes(selectedModel)) {
                setSelectedModel(models[0]);
            }
            if (res.data.models_changed) {
                alert('Model list has changed. The updated list has been applied.');
            }
        } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } }; message?: string };
            setRefreshError(err.response?.data?.detail ?? err.message ?? 'Fetch failed');
        } finally {
            setRefreshingModels(false);
        }
    };

    // ── 필터링 ────────────────────────────────────────────────────────────────
    const filteredBuiltin = Object.entries(providers.builtin);
    const filteredCustom = providers.custom.filter(c =>
        c.provider_type === type || c.provider_type === 'both'
    );

    const isCustomProvider = providers.custom.some(c => c.provider_id === selectedProvider);
    const isAddingCustom = selectedProvider === CUSTOM_OPTION;
    const filteredFetched = fetchedModels.filter(m =>
        m.toLowerCase().includes(modelSearch.toLowerCase())
    );

    // ── 팝업 위치 계산 (뷰포트 내 유지) ─────────────────────────────────────
    const isFormMode = isAddingCustom || isEditing;

    const getPopupStyle = (): React.CSSProperties => {
        // 수정/추가 모드: 화면 중앙 고정 (폼이 길어 trigger 기준 배치 시 잘림)
        if (isFormMode) {
            return {
                position: 'fixed' as const,
                top: '50%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
                zIndex: 9999,
                maxHeight: '85vh',
                overflowY: 'auto' as const,
            };
        }
        const trigger = triggerRef.current;
        if (!trigger) {
            return { position: 'fixed' as const, top: '50%', left: '50%', transform: 'translate(-50%, -50%)', zIndex: 9999, maxHeight: '75vh', overflowY: 'auto' as const };
        }
        const rect = trigger.getBoundingClientRect();
        const gap = 8;
        const padding = 12;
        const maxH = Math.floor(window.innerHeight * 0.75);
        const popupH = Math.min(popupHeight, maxH);
        const spaceBelow = window.innerHeight - rect.bottom - gap - padding;
        const spaceAbove = rect.top - gap - padding;
        let top: number;
        if (spaceBelow >= popupH) {
            top = rect.bottom + gap;
        } else if (spaceAbove >= popupH) {
            top = rect.top - popupH - gap;
        } else {
            top = padding;
        }
        top = Math.max(padding, Math.min(top, window.innerHeight - popupH - padding));
        let left = rect.left;
        const maxW = 380;
        if (left + maxW > window.innerWidth - padding) left = window.innerWidth - maxW - padding;
        if (left < padding) left = padding;
        return {
            position: 'fixed' as const,
            top,
            left,
            zIndex: 9999,
            maxHeight: `${maxH}px`,
            overflowY: 'auto' as const,
        };
    };

    // ── 렌더 ─────────────────────────────────────────────────────────────────
    return (
        <div ref={triggerRef} style={{ position: 'relative', display: 'inline-block' }}>

            {/* ─── 인라인 표시 ─── */}
            <div
                onClick={() => !disabled && setIsOpen(v => !v)}
                style={{
                    display: 'flex', alignItems: 'center', gap: '6px',
                    padding: '3px 8px', background: '#f8fafc',
                    borderRadius: '6px', border: '1px solid #e2e8f0',
                    opacity: disabled ? 0.5 : 1,
                    cursor: disabled ? 'not-allowed' : 'pointer',
                    userSelect: 'none',
                    transition: 'border-color 0.15s, background 0.15s',
                }}
                onMouseEnter={e => { if (!disabled) { e.currentTarget.style.borderColor = '#7c3aed'; e.currentTarget.style.background = '#faf5ff'; } }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.background = '#f8fafc'; }}
            >
                {BUILTIN_ICON_SLUGS[value.provider] ? (
                    <ProviderIcon providerKey={value.provider} name={value.provider_name} size={13} style={{ position: 'relative', top: '1px' }} />
                ) : (
                    <div style={{
                        width: 13, height: 13, borderRadius: 4,
                        background: '#7c3aed', color: '#fff',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: '0.6rem', fontWeight: 700, flexShrink: 0,
                        position: 'relative', top: '1px',
                    }}>{getInitial(value.provider_name)}</div>
                )}
                <span style={{ fontSize: '0.72rem', color: '#334155', whiteSpace: 'nowrap', position: 'relative', top: '-1px' }}>{value.model}</span>
            </div>

            {/* ─── 팝업 ─── */}
            {isOpen && createPortal(
                <>
                {isFormMode && (
                    <div
                        onClick={() => setIsOpen(false)}
                        style={{
                            position: 'fixed', inset: 0, zIndex: 9998,
                            background: 'rgba(0,0,0,0.25)',
                        }}
                    />
                )}
                <div
                    ref={popupRef}
                    style={{
                        ...getPopupStyle(),
                        background: 'white',
                        border: '1px solid #e2e8f0',
                        borderRadius: '10px',
                        boxShadow: '0 8px 30px rgba(0,0,0,0.15)',
                        padding: '1rem',
                        minWidth: '320px',
                        width: 'max-content',
                        maxWidth: '380px',
                    }}
                >
                    {/* 헤더 */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.8rem' }}>
                        <span style={{ fontWeight: 600, fontSize: '0.85rem', color: '#334155' }}>
                            {type === 'llm' ? 'LLM Model' : 'Embedding Model'}
                        </span>
                        <button
                            onClick={() => setIsOpen(false)}
                            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 0, display: 'flex' }}
                        >
                            <X size={14} />
                        </button>
                    </div>

                    {loading ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#94a3b8', fontSize: '0.8rem', padding: '0.5rem 0' }}>
                            <Loader2 size={14} /> Loading...
                        </div>
                    ) : (
                        <>
                            {/* Provider 드롭다운 (Custom 옵션 포함) */}
                            <div style={{ marginBottom: '0.7rem' }}>
                                <div style={{ fontSize: '0.68rem', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.35rem' }}>
                                    Provider
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
                                    {isAddingCustom ? (
                                        <div style={{
                                            width: '28px', height: '28px', borderRadius: '6px',
                                            background: '#7c3aed', color: '#fff',
                                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                                            fontSize: '0.85rem', fontWeight: 600, flexShrink: 0,
                                        }}>+</div>
                                    ) : isCustomProvider ? (
                                        <div style={{
                                            width: '28px', height: '28px', borderRadius: '6px',
                                            background: '#7c3aed', color: '#fff',
                                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                                            fontSize: '0.7rem', fontWeight: 700, flexShrink: 0,
                                        }}>
                                            {getInitial(providers.custom.find(c => c.provider_id === selectedProvider)?.name ?? 'C')}
                                        </div>
                                    ) : (
                                        <ProviderIcon
                                            providerKey={selectedProvider}
                                            name={providers.builtin[selectedProvider]?.name ?? selectedProvider}
                                            size={28}
                                        />
                                    )}
                                    <select
                                        value={selectedProvider}
                                        onChange={(e) => handleProviderChange(e.target.value)}
                                        style={{
                                            flex: 1,
                                            minWidth: '140px',
                                            padding: '0.45rem 0.6rem',
                                            fontSize: '0.82rem',
                                            border: '1px solid #e2e8f0',
                                            borderRadius: '8px',
                                            background: 'white',
                                            color: '#334155',
                                            cursor: 'pointer',
                                            outline: 'none'
                                        }}
                                    >
                                        {filteredBuiltin.map(([key, p]) => (
                                            <option key={key} value={key}>
                                                {p.name}
                                            </option>
                                        ))}
                                        {filteredCustom.map(c => (
                                            <option key={c.provider_id} value={c.provider_id}>
                                                {c.name}
                                            </option>
                                        ))}
                                        <option value={CUSTOM_OPTION}>Custom</option>
                                    </select>
                                    {isCustomProvider && (
                                        <div style={{ display: 'flex', gap: '2px' }}>
                                            <button
                                                onClick={handleStartEditCustom}
                                                title="Edit Config"
                                                style={{
                                                    background: 'none', border: 'none', cursor: 'pointer', color: '#cbd5e1', padding: '4px', display: 'flex', borderRadius: '4px'
                                                }}
                                                onMouseEnter={e => { e.currentTarget.style.color = 'var(--primary)'; e.currentTarget.style.background = '#f5f3ff'; }}
                                                onMouseLeave={e => { e.currentTarget.style.color = '#cbd5e1'; e.currentTarget.style.background = 'none'; }}
                                            >
                                                <FileEdit size={14} />
                                            </button>
                                            <button
                                                onClick={(e) => handleDeleteCustom(selectedProvider, e)}
                                                title="Delete"
                                                style={{
                                                    background: 'none', border: 'none', cursor: 'pointer', color: '#cbd5e1', padding: '4px', display: 'flex', borderRadius: '4px'
                                                }}
                                                onMouseEnter={e => { e.currentTarget.style.color = '#ef4444'; e.currentTarget.style.background = '#fef2f2'; }}
                                                onMouseLeave={e => { e.currentTarget.style.color = '#cbd5e1'; e.currentTarget.style.background = 'none'; }}
                                            >
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {isAddingCustom || isEditing ? (
                                /* Custom 추가/수정 폼 */
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>

                                    {/* 암호화 안내 */}
                                    <div style={{
                                        display: 'flex', alignItems: 'center', gap: '6px',
                                        background: '#f0fdf4', border: '1px solid #bbf7d0',
                                        borderRadius: '6px', padding: '0.4rem 0.6rem',
                                        fontSize: '0.7rem', color: '#166534',
                                    }}>
                                        <span>🔒</span>
                                        <span>API Key is encrypted and stored with Fernet.</span>
                                    </div>

                                    {/* 이름 */}
                                    <div>
                                        <div style={{ fontSize: '0.72rem', fontWeight: 500, color: '#475569', marginBottom: '3px' }}>
                                            Name <span style={{ color: '#ef4444' }}>*</span>
                                        </div>
                                        <input className="input" style={{ fontSize: '0.8rem', padding: '0.35rem 0.5rem' }}
                                            placeholder="My Custom LLM"
                                            value={customForm.name}
                                            onChange={e => setCustomForm(p => ({ ...p, name: e.target.value }))} />
                                    </div>

                                    {/* API Base URL */}
                                    <div>
                                        <div style={{ fontSize: '0.72rem', fontWeight: 500, color: '#475569', marginBottom: '3px' }}>
                                            API Base URL <span style={{ color: '#ef4444' }}>*</span>
                                        </div>
                                        <input className="input" style={{ fontSize: '0.8rem', padding: '0.35rem 0.5rem' }}
                                            placeholder="https://api.example.com/v1"
                                            value={customForm.base_url}
                                            onChange={e => setCustomForm(p => ({ ...p, base_url: e.target.value }))} />
                                    </div>

                                    {/* API Key */}
                                    <div>
                                        <div style={{ fontSize: '0.72rem', fontWeight: 500, color: '#475569', marginBottom: '3px' }}>
                                            API Key {customForm.embedding_request_format !== 'minimal' && <span style={{ color: '#ef4444' }}>*</span>}
                                            {customForm.embedding_request_format === 'minimal' && <span style={{ color: '#94a3b8', fontWeight: 400 }}> (optional for Minimal)</span>}
                                        </div>
                                        <div style={{ position: 'relative' }}>
                                            <input className="input"
                                                style={{ fontSize: '0.8rem', padding: '0.35rem 2rem 0.35rem 0.5rem', width: '100%', boxSizing: 'border-box' }}
                                                type={showKey ? 'text' : 'password'}
                                                placeholder={isEditing ? "(Keep empty to use existing key)" : "sk-..."}
                                                value={customForm.api_key}
                                                onChange={e => setCustomForm(p => ({ ...p, api_key: e.target.value }))} />
                                            <button type="button" onClick={() => setShowKey(v => !v)}
                                                style={{ position: 'absolute', right: '7px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 0, display: 'flex' }}>
                                                {showKey ? <EyeOff size={13} /> : <Eye size={13} />}
                                            </button>
                                        </div>
                                    </div>

                                    {/* Extra Headers (optional) */}
                                    <div>
                                        <div style={{ fontSize: '0.72rem', fontWeight: 500, color: '#475569', marginBottom: '3px' }}>
                                            Extra Headers <span style={{ color: '#94a3b8', fontWeight: 400 }}>(optional)</span>
                                        </div>
                                        <textarea
                                            className="input"
                                            style={{ fontSize: '0.78rem', padding: '0.35rem 0.5rem', resize: 'vertical', minHeight: '48px' }}
                                            placeholder={'Header-Name: value\nX-Custom-Header: my-value'}
                                            value={customForm.extra_headers_text}
                                            onChange={e => setCustomForm(p => ({ ...p, extra_headers_text: e.target.value }))}
                                        />
                                        <div style={{ fontSize: '0.65rem', color: '#94a3b8', marginTop: '2px' }}>
                                            One per line: Header-Name: value
                                        </div>
                                    </div>

                                    {/* Embedding Request Format - when provider supports embedding */}
                                    {(customForm.provider_type === 'embedding' || customForm.provider_type === 'both') && (
                                        <div>
                                            <div style={{ fontSize: '0.72rem', fontWeight: 500, color: '#475569', marginBottom: '5px' }}>
                                                Embedding Format
                                            </div>
                                            <select
                                                className="input"
                                                style={{ fontSize: '0.8rem', padding: '0.35rem 0.5rem', width: '100%' }}
                                                value={customForm.embedding_request_format}
                                                onChange={e => setCustomForm(p => ({ ...p, embedding_request_format: e.target.value as 'openai' | 'minimal' }))}
                                            >
                                                <option value="minimal">Minimal (headers only, no model in body)</option>
                                                <option value="openai">OpenAI compatible</option>
                                            </select>
                                            <div style={{ fontSize: '0.65rem', color: '#94a3b8', marginTop: '2px' }}>
                                                Minimal: x-dep-ticket 등 extra headers만 사용, body에 input만 전송
                                            </div>
                                        </div>
                                    )}

                                    {/* 사용 유형 */}
                                    <div>
                                        <div style={{ fontSize: '0.72rem', fontWeight: 500, color: '#475569', marginBottom: '5px' }}>Usage Type</div>
                                        <div style={{ display: 'flex', gap: '6px' }}>
                                            {(['llm', 'embedding', 'both'] as ProviderType[]).map(pt => {
                                                const labels: Record<ProviderType, string> = { llm: 'LLM', embedding: 'Embedding', both: 'LLM + Embedding' };
                                                const isActive = customForm.provider_type === pt;
                                                return (
                                                    <label key={pt} style={{
                                                        display: 'flex', alignItems: 'center', gap: '4px',
                                                        cursor: 'pointer', fontSize: '0.73rem',
                                                        padding: '3px 8px', borderRadius: '6px', border: '1px solid',
                                                        borderColor: isActive ? '#2563eb' : '#e2e8f0',
                                                        background: isActive ? '#eff6ff' : 'white',
                                                        color: isActive ? '#1d4ed8' : '#64748b',
                                                        transition: 'all 0.1s', userSelect: 'none',
                                                    }}>
                                                        <input type="radio" name="provider_type_radio" value={pt}
                                                            checked={isActive}
                                                            onChange={() => setCustomForm(p => ({ ...p, provider_type: pt }))}
                                                            style={{ display: 'none' }} />
                                                        {labels[pt]}
                                                    </label>
                                                );
                                            })}
                                        </div>
                                    </div>

                                    {/* ── 모델 목록 ── */}
                                    <div>
                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                                            <div style={{ fontSize: '0.72rem', fontWeight: 500, color: '#475569' }}>
                                                Model List <span style={{ color: '#94a3b8', fontWeight: 400 }}>(one per line)</span>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={handleFetchModelsForForm}
                                                disabled={fetchingModels}
                                                style={{
                                                    display: 'flex', alignItems: 'center', gap: '4px',
                                                    fontSize: '0.7rem', fontWeight: 500,
                                                    color: fetchingModels ? '#94a3b8' : '#2563eb',
                                                    background: 'none', border: 'none', cursor: fetchingModels ? 'not-allowed' : 'pointer',
                                                    padding: '2px 0',
                                                }}
                                            >
                                                {fetchingModels
                                                    ? <><Loader2 size={11} /> Fetching...</>
                                                    : <><RefreshCw size={11} /> Fetch from API</>
                                                }
                                            </button>
                                        </div>

                                        {/* 모델 선택기 (API 조회 후 표시) */}
                                        {showModelPicker ? (
                                            <div style={{
                                                border: '1px solid #e2e8f0', borderRadius: '8px',
                                                overflow: 'hidden', background: '#fafafa',
                                            }}>
                                                {/* 검색 */}
                                                <div style={{ padding: '0.4rem 0.5rem', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', gap: '6px', background: 'white' }}>
                                                    <Search size={12} color="#94a3b8" />
                                                    <input
                                                        style={{ border: 'none', outline: 'none', fontSize: '0.78rem', flex: 1, background: 'transparent', color: '#334155' }}
                                                        placeholder="Search models..."
                                                        value={modelSearch}
                                                        onChange={e => setModelSearch(e.target.value)}
                                                    />
                                                    <span style={{ fontSize: '0.68rem', color: '#94a3b8', flexShrink: 0 }}>
                                                        {pickedModels.size}/{fetchedModels.length}
                                                    </span>
                                                </div>

                                                {/* 모델 체크 목록 */}
                                                <div style={{ maxHeight: '160px', overflowY: 'auto' }}>
                                                    {filteredFetched.length === 0 ? (
                                                        <div style={{ padding: '0.5rem', fontSize: '0.75rem', color: '#94a3b8', textAlign: 'center' }}>
                                                            No results
                                                        </div>
                                                    ) : filteredFetched.map(m => {
                                                        const checked = pickedModels.has(m);
                                                        return (
                                                            <label key={m} style={{
                                                                display: 'flex', alignItems: 'center', gap: '8px',
                                                                padding: '0.32rem 0.6rem', cursor: 'pointer',
                                                                background: checked ? '#eff6ff' : 'transparent',
                                                                borderBottom: '1px solid #f1f5f9',
                                                                fontSize: '0.78rem', color: checked ? '#1d4ed8' : '#334155',
                                                                userSelect: 'none',
                                                            }}>
                                                                <input
                                                                    type="checkbox"
                                                                    checked={checked}
                                                                    onChange={() => togglePickedModel(m)}
                                                                    style={{ accentColor: '#2563eb', margin: 0, flexShrink: 0 }}
                                                                />
                                                                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m}</span>
                                                            </label>
                                                        );
                                                    })}
                                                </div>

                                                {/* 하단 액션 */}
                                                <div style={{
                                                    display: 'flex', alignItems: 'center', gap: '6px',
                                                    padding: '0.35rem 0.6rem', borderTop: '1px solid #e2e8f0',
                                                    background: 'white',
                                                }}>
                                                    <button
                                                        onClick={() => setPickedModels(new Set(fetchedModels))}
                                                        style={{ fontSize: '0.68rem', color: '#2563eb', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                                                    >Select All</button>
                                                    <span style={{ color: '#e2e8f0' }}>|</span>
                                                    <button
                                                        onClick={() => setPickedModels(new Set())}
                                                        style={{ fontSize: '0.68rem', color: '#64748b', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                                                    >Deselect All</button>
                                                    <div style={{ flex: 1 }} />
                                                    <button
                                                        onClick={() => setShowModelPicker(false)}
                                                        className="btn"
                                                        style={{ fontSize: '0.72rem', padding: '0.2rem 0.5rem' }}
                                                    >Cancel</button>
                                                    <button
                                                        onClick={applyModelPicker}
                                                        className="btn btn-primary"
                                                        style={{ fontSize: '0.72rem', padding: '0.2rem 0.5rem' }}
                                                        disabled={pickedModels.size === 0}
                                                    >
                                                        {pickedModels.size} applied
                                                    </button>
                                                </div>
                                            </div>
                                        ) : (
                                            <textarea
                                                className="input"
                                                style={{ fontSize: '0.78rem', padding: '0.35rem 0.5rem', resize: 'vertical', minHeight: '64px' }}
                                                placeholder={'my-model-v1\nmy-model-v2'}
                                                value={customForm.model_list_text}
                                                onChange={e => setCustomForm(p => ({ ...p, model_list_text: e.target.value }))}
                                            />
                                        )}

                                        {fetchError && (
                                            <div style={{ fontSize: '0.7rem', color: '#ef4444', marginTop: '4px' }}>
                                                ⚠ {fetchError}
                                            </div>
                                        )}
                                    </div>

                                    {saveError && (
                                        <div style={{ fontSize: '0.72rem', color: '#ef4444', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '5px', padding: '0.3rem 0.5rem' }}>
                                            {saveError}
                                        </div>
                                    )}

                                    <div style={{ display: 'flex', gap: '8px', marginTop: '0.1rem' }}>
                                        <button className="btn" style={{ flex: 1, fontSize: '0.78rem', padding: '0.35rem' }}
                                            onClick={() => {
                                                if (isEditing) {
                                                    setIsEditing(false);
                                                } else {
                                                    const firstKey = Object.keys(providers.builtin)[0] ?? providers.custom[0]?.provider_id ?? '';
                                                    if (firstKey) handleProviderChange(firstKey);
                                                }
                                                setSaveError('');
                                                setShowModelPicker(false);
                                            }}>
                                            Cancel
                                        </button>
                                        <button className="btn btn-primary" style={{ flex: 1, fontSize: '0.78rem', padding: '0.35rem' }}
                                            onClick={handleSaveCustom} disabled={saving}>
                                            {saving ? 'Saving...' : (isEditing ? 'Update' : 'Register')}
                                        </button>
                                    </div>
                                </div>

                            ) : (
                                <>
                                    {/* Model 섹션 (Provider 선택됐을 때) */}
                                    <div style={{ marginBottom: '0.75rem' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.35rem', flexWrap: 'wrap', gap: '6px' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <span style={{ fontSize: '0.68rem', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                                                    Model
                                                </span>
                                                {liveModelList && (
                                                    <span style={{ marginLeft: '6px', fontSize: '0.62rem', color: '#10b981', fontWeight: 500, textTransform: 'none', letterSpacing: 0 }}>
                                                        ✓ Live list ({liveModelList.length} items)
                                                    </span>
                                                )}
                                            </div>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                {/* Custom: API로 조회 */}
                                                {isCustomProvider && (
                                                    <button
                                                        onClick={handleRefreshModels}
                                                        disabled={refreshingModels}
                                                        title="Fetch latest model list with stored API Key"
                                                        style={{
                                                            display: 'flex', alignItems: 'center', gap: '3px',
                                                            fontSize: '0.68rem', color: refreshingModels ? '#94a3b8' : '#2563eb',
                                                            background: 'none', border: 'none',
                                                            cursor: refreshingModels ? 'not-allowed' : 'pointer', padding: 0,
                                                        }}
                                                    >
                                                        {refreshingModels ? <Loader2 size={11} /> : <RefreshCw size={11} />}
                                                        {refreshingModels ? 'Fetching...' : 'Fetch from API'}
                                                    </button>
                                                )}
                                                {/* Built-in has_key: API로 조회 */}
                                                {!isCustomProvider && (providers.builtin[selectedProvider]?.has_key) && (
                                                    <button
                                                        onClick={handleRefreshBuiltinModels}
                                                        disabled={refreshingModels}
                                                        title="Fetch latest model list with stored API Key"
                                                        style={{
                                                            display: 'flex', alignItems: 'center', gap: '3px',
                                                            fontSize: '0.68rem', color: refreshingModels ? '#94a3b8' : '#2563eb',
                                                            background: 'none', border: 'none',
                                                            cursor: refreshingModels ? 'not-allowed' : 'pointer', padding: 0,
                                                        }}
                                                    >
                                                        {refreshingModels ? <Loader2 size={11} /> : <RefreshCw size={11} />}
                                                        {refreshingModels ? 'Fetching...' : 'Fetch from API'}
                                                    </button>
                                                )}
                                                {/* 직접 입력 토글 */}
                                                <button
                                                    onClick={() => {
                                                        setDirectInput(v => !v);
                                                        if (!directInput) setSelectedModel('');
                                                    }}
                                                    style={{
                                                        fontSize: '0.68rem',
                                                        color: directInput ? '#7c3aed' : '#94a3b8',
                                                        background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                                                        textDecoration: 'underline',
                                                    }}
                                                >
                                                    {directInput ? 'Select from list' : 'Direct input'}
                                                </button>
                                            </div>
                                        </div>

                                        {/* Built-in 프로바이더 API Key 등록 (키 미등록 시) */}
                                        {!isCustomProvider && !(providers.builtin[selectedProvider]?.has_key) && (
                                            <div style={{
                                                background: '#fffbeb', border: '1px solid #fcd34d',
                                                borderRadius: '8px', padding: '0.6rem 0.7rem',
                                                marginBottom: '0.5rem',
                                            }}>
                                                <div style={{ fontSize: '0.7rem', color: '#92400e', fontWeight: 500, marginBottom: '6px' }}>
                                                    🔑 Register API Key (encrypted storage, auto-fetch model list)
                                                </div>
                                                <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                                                    <div style={{ position: 'relative', flex: 1 }}>
                                                        <input
                                                            className="input"
                                                            style={{ fontSize: '0.78rem', padding: '0.3rem 2rem 0.3rem 0.5rem', width: '100%', boxSizing: 'border-box' }}
                                                            type={showBuiltinKey ? 'text' : 'password'}
                                                            placeholder="sk-... or enter API Key"
                                                            value={builtinApiKey}
                                                            onChange={e => { setBuiltinApiKey(e.target.value); setRefreshError(''); }}
                                                            onKeyDown={e => e.key === 'Enter' && handleRegisterBuiltinKey()}
                                                            autoFocus
                                                        />
                                                        <button
                                                            type="button"
                                                            onClick={() => setShowBuiltinKey(v => !v)}
                                                            style={{ position: 'absolute', right: '6px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 0, display: 'flex' }}
                                                        >
                                                            {showBuiltinKey ? <EyeOff size={12} /> : <Eye size={12} />}
                                                        </button>
                                                    </div>
                                                    <button
                                                        className="btn btn-primary"
                                                        style={{ fontSize: '0.75rem', padding: '0.3rem 0.7rem', flexShrink: 0 }}
                                                        onClick={handleRegisterBuiltinKey}
                                                        disabled={refreshingModels || !builtinApiKey.trim()}
                                                    >
                                                        {refreshingModels ? <Loader2 size={12} /> : 'Register'}
                                                    </button>
                                                </div>
                                                {refreshError && (
                                                    <div style={{ fontSize: '0.7rem', color: '#ef4444', marginTop: '5px' }}>
                                                        ⚠ {refreshError}
                                                    </div>
                                                )}
                                            </div>
                                        )}

                                        {/* Custom 프로바이더 에러 */}
                                        {isCustomProvider && refreshError && (
                                            <div style={{ fontSize: '0.7rem', color: '#ef4444', marginBottom: '5px' }}>
                                                ⚠ {refreshError}
                                            </div>
                                        )}

                                        {directInput ? (
                                            <input
                                                className="input"
                                                style={{ fontSize: '0.82rem', padding: '0.38rem 0.5rem' }}
                                                placeholder="Enter model name directly (e.g. gpt-4o-2024-11-20)"
                                                value={selectedModel}
                                                onChange={e => setSelectedModel(e.target.value)}
                                                autoFocus
                                            />
                                        ) : displayModelList.length > 0 ? (
                                            <select className="input" style={{ fontSize: '0.82rem', padding: '0.38rem 0.5rem' }}
                                                value={selectedModel}
                                                onChange={e => setSelectedModel(e.target.value)}>
                                                {displayModelList.map(m => <option key={m} value={m}>{m}</option>)}
                                            </select>
                                        ) : (
                                            <input className="input" style={{ fontSize: '0.82rem', padding: '0.38rem 0.5rem' }}
                                                placeholder="Enter model name directly"
                                                value={selectedModel}
                                                onChange={e => setSelectedModel(e.target.value)} />
                                        )}
                                    </div>

                                    {/* 프롬프트 편집 (Model 탭이 LLM일 때만, 확인 버튼 위) */}
                                    {type === 'llm' && onEditPrompt && (
                                        <button
                                            type="button"
                                            onClick={() => { onEditPrompt(); }}
                                            style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                gap: '0.3rem',
                                                width: '100%',
                                                padding: '0.38rem',
                                                fontSize: '0.8rem',
                                                backgroundColor: '#f1f5f9',
                                                color: '#475569',
                                                border: '1px solid #e2e8f0',
                                                borderRadius: '6px',
                                                cursor: 'pointer',
                                                marginBottom: '10px'
                                            }}
                                        >
                                            <FileEdit size={14} />
                                            Edit Prompt
                                        </button>
                                    )}
                                    {/* 확인 버튼 */}
                                    <button
                                        className="btn btn-primary"
                                        style={{ width: '100%', fontSize: '0.82rem', padding: '0.42rem' }}
                                        onClick={handleConfirm}
                                        disabled={!selectedModel.trim()}
                                    >
                                        Confirm
                                    </button>
                                </>
                            )}
                        </>
                    )}
                </div>
                </>,
                document.body
            )
            }
        </div >
    );
}
