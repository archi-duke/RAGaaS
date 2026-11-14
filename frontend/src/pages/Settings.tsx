import { useEffect, useState } from 'react';
import { AlertCircle, Check, Key, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { providerApi } from '../services/api';

// 프로바이더 설정 화면.
//
// 백엔드 API(providers)는 처음부터 있었지만 화면이 없어서, API Key 를 바꾸려면
// curl 을 직접 쳐야 했다. 더 나쁜 것은 키가 **DB(암호화)에 저장**되고 .env 는
// 폴백이라는 점이다 — .env 만 고치고 반영됐다고 착각하기 쉽다. 이 화면이 그
// 혼란을 없앤다.

type BuiltinProvider = {
    name: string;
    base_url: string;
    has_key: boolean;
    models?: { llm?: string[]; embedding?: string[] };
};

type CustomProvider = {
    id: string;
    name: string;
    base_url: string;
    provider_type: string;
    model_list?: string[];
};

type ProvidersResponse = {
    builtin?: Record<string, BuiltinProvider>;
    custom?: CustomProvider[];
};

type Notice = { kind: 'ok' | 'error'; text: string } | null;

const CARD: React.CSSProperties = {
    background: '#fff',
    border: '1px solid #e5e7eb',
    borderRadius: '8px',
    padding: '1.25rem 1.5rem',
    marginBottom: '1rem',
};

export default function Settings() {
    const [data, setData] = useState<ProvidersResponse>({});
    const [loading, setLoading] = useState(true);
    const [notice, setNotice] = useState<Notice>(null);

    // providerId → 입력 중인 키. 저장 후 비운다(화면에 키를 남기지 않는다).
    const [keyInput, setKeyInput] = useState<Record<string, string>>({});
    const [busy, setBusy] = useState<string | null>(null);

    const load = async () => {
        try {
            const res = await providerApi.list();
            setData(res.data ?? {});
        } catch (e: unknown) {
            setNotice({ kind: 'error', text: `프로바이더 목록을 불러오지 못했습니다: ${describe(e)}` });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
    }, []);

    const saveKey = async (providerId: string) => {
        const key = (keyInput[providerId] ?? '').trim();
        if (!key) {
            setNotice({ kind: 'error', text: 'API Key 를 입력하세요.' });
            return;
        }
        setBusy(providerId);
        setNotice(null);
        try {
            await providerApi.updateBuiltinKey(providerId, key);
            setKeyInput((prev) => ({ ...prev, [providerId]: '' })); // 입력값은 남기지 않는다
            setNotice({ kind: 'ok', text: `${providerId} API Key 를 저장했습니다 (암호화 저장).` });
            await load();
        } catch (e: unknown) {
            setNotice({ kind: 'error', text: `키 저장 실패: ${describe(e)}` });
        } finally {
            setBusy(null);
        }
    };

    const refreshModels = async (providerId: string) => {
        setBusy(providerId);
        setNotice(null);
        try {
            const res = await providerApi.fetchModels({ provider_id: providerId });
            const n = res.data?.models?.length ?? 0;
            setNotice({
                kind: 'ok',
                text: `${providerId} 모델 ${n}개를 조회했습니다${res.data?.models_changed ? ' (목록 변경됨)' : ''}.`,
            });
            await load();
        } catch (e: unknown) {
            setNotice({ kind: 'error', text: `모델 조회 실패: ${describe(e)}` });
        } finally {
            setBusy(null);
        }
    };

    const removeCustom = async (providerId: string, name: string) => {
        if (!window.confirm(`커스텀 프로바이더 "${name}" 을 삭제합니다. 계속할까요?`)) return;
        setBusy(providerId);
        try {
            await providerApi.deleteCustom(providerId);
            setNotice({ kind: 'ok', text: `"${name}" 을 삭제했습니다.` });
            await load();
        } catch (e: unknown) {
            setNotice({ kind: 'error', text: `삭제 실패: ${describe(e)}` });
        } finally {
            setBusy(null);
        }
    };

    const builtin = Object.entries(data.builtin ?? {});
    const custom = data.custom ?? [];

    return (
        <div className="container">
            <div style={{ marginBottom: '1.5rem' }}>
                <h2 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
                    <Key size={22} />
                    설정 — 프로바이더
                </h2>
                <p style={{ color: '#6b7280', fontSize: '0.875rem', marginTop: '0.5rem' }}>
                    API Key 는 암호화되어 DB 에 저장됩니다. <code>.env</code> 는 DB 값이 없을 때의 폴백이므로,
                    여기서 저장한 값이 실제로 사용됩니다.
                </p>
            </div>

            {notice && (
                <div
                    style={{
                        ...CARD,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                        background: notice.kind === 'ok' ? '#f0fdf4' : '#fef2f2',
                        borderColor: notice.kind === 'ok' ? '#bbf7d0' : '#fecaca',
                        color: notice.kind === 'ok' ? '#15803d' : '#b91c1c',
                        fontSize: '0.875rem',
                    }}
                >
                    {notice.kind === 'ok' ? <Check size={16} /> : <AlertCircle size={16} />}
                    {notice.text}
                </div>
            )}

            {loading ? (
                <div style={CARD}>불러오는 중…</div>
            ) : (
                <>
                    <h3 style={{ fontSize: '1rem', margin: '1.5rem 0 0.75rem' }}>기본 프로바이더</h3>
                    {builtin.length === 0 && <div style={CARD}>등록된 기본 프로바이더가 없습니다.</div>}
                    {builtin.map(([id, p]) => (
                        <div key={id} style={CARD}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
                                <strong>{p.name || id}</strong>
                                <span
                                    style={{
                                        fontSize: '0.75rem',
                                        padding: '0.125rem 0.5rem',
                                        borderRadius: '999px',
                                        background: p.has_key ? '#dcfce7' : '#fef3c7',
                                        color: p.has_key ? '#15803d' : '#92400e',
                                    }}
                                >
                                    {p.has_key ? '키 등록됨' : '키 없음'}
                                </span>
                                <span style={{ color: '#6b7280', fontSize: '0.8125rem' }}>{p.base_url}</span>
                            </div>

                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                <input
                                    type="password"
                                    autoComplete="off"
                                    placeholder={p.has_key ? '새 키를 입력하면 교체됩니다' : 'API Key 입력'}
                                    value={keyInput[id] ?? ''}
                                    onChange={(e) => setKeyInput((prev) => ({ ...prev, [id]: e.target.value }))}
                                    style={{
                                        flex: '1 1 320px',
                                        padding: '0.5rem 0.75rem',
                                        border: '1px solid #d1d5db',
                                        borderRadius: '6px',
                                        fontSize: '0.875rem',
                                    }}
                                />
                                <button
                                    className="btn btn-primary"
                                    onClick={() => saveKey(id)}
                                    disabled={busy === id || !(keyInput[id] ?? '').trim()}
                                >
                                    저장
                                </button>
                                <button
                                    className="btn"
                                    onClick={() => refreshModels(id)}
                                    disabled={busy === id || !p.has_key}
                                    title={p.has_key ? '프로바이더 API 에서 모델 목록을 다시 받아옵니다' : '키를 먼저 등록하세요'}
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}
                                >
                                    <RefreshCw size={16} />
                                    모델 새로고침
                                </button>
                            </div>

                            <div style={{ marginTop: '0.75rem', color: '#6b7280', fontSize: '0.8125rem' }}>
                                LLM {p.models?.llm?.length ?? 0}개 · Embedding {p.models?.embedding?.length ?? 0}개
                            </div>
                        </div>
                    ))}

                    <h3 style={{ fontSize: '1rem', margin: '2rem 0 0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        커스텀 프로바이더
                        <span style={{ color: '#6b7280', fontSize: '0.8125rem', fontWeight: 400 }}>
                            ({custom.length}개)
                        </span>
                    </h3>
                    {custom.length === 0 ? (
                        <div style={{ ...CARD, color: '#6b7280', fontSize: '0.875rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <Plus size={16} />
                            등록된 커스텀 프로바이더가 없습니다. OpenAI 호환 엔드포인트를 쓰려면 여기에 추가합니다.
                        </div>
                    ) : (
                        custom.map((c) => (
                            <div key={c.id} style={{ ...CARD, display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                <div style={{ flex: 1 }}>
                                    <strong>{c.name}</strong>
                                    <div style={{ color: '#6b7280', fontSize: '0.8125rem', marginTop: '0.25rem' }}>
                                        {c.base_url} · {c.provider_type} · 모델 {c.model_list?.length ?? 0}개
                                    </div>
                                </div>
                                <button
                                    className="btn"
                                    onClick={() => removeCustom(c.id, c.name)}
                                    disabled={busy === c.id}
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', color: '#b91c1c' }}
                                >
                                    <Trash2 size={16} />
                                    삭제
                                </button>
                            </div>
                        ))
                    )}
                </>
            )}
        </div>
    );
}

// axios 오류에서 사람이 읽을 메시지를 꺼낸다. 백엔드는 {detail} 로 사유를 준다.
function describe(e: unknown): string {
    const err = e as { response?: { data?: { detail?: string }; status?: number }; message?: string };
    return err?.response?.data?.detail ?? (err?.response?.status ? `HTTP ${err.response.status}` : err?.message ?? '알 수 없는 오류');
}
