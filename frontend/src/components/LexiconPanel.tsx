import React, { useCallback, useEffect, useState } from 'react';
import { Check, X, Plus, RefreshCw, GitMerge, Trash2, Search } from 'lucide-react';
import { lexiconApi, schemaApi } from '../services/api';

// 용어 사전 탭 (docs/design-kb-lexicon.md L3)
// - 항목: 라벨별 한국어·영어·동의어 별칭. 사람이 고친 항목(source=user)은 재생성 때 보존된다.
// - 상위 개념 검토: LLM 이 제안한 상위 개념(유지보수성 ← 변경 용이성 …)을 묶음 단위로 승인·거절.
//   승인 전에는 검색 결과에 '검토 전' 으로 표시된다.
// - 중복 후보: 같은 별칭을 공유하는 라벨 묶음. 진짜 같은 대상이면 병합(엔티티 규칙 + 리플레이),
//   LLM 이 붙인 일반적인 별칭 때문이면 그 별칭만 삭제.

interface Entry {
    label: string; ko: string[]; en: string[]; syn: string[]; variants?: string[];
    broader: { label: string; status: string }[]; concept_only: boolean; skip: boolean; source: string;
}

const chip: React.CSSProperties = {
    display: 'inline-flex', alignItems: 'center', gap: '0.2rem', fontSize: '0.72rem', padding: '0.05rem 0.4rem',
    borderRadius: '10px', background: '#f1f5f9', border: '1px solid #e2e8f0', margin: '0.1rem',
};
const btn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.75rem', padding: '0.2rem 0.5rem' };
const cell: React.CSSProperties = { padding: '0.3rem 0.4rem', borderBottom: '1px solid #e2e8f0', verticalAlign: 'top', fontSize: '0.78rem' };
const iconBtn: React.CSSProperties = { border: 'none', background: 'none', cursor: 'pointer', padding: 0, display: 'inline-flex' };

export default function LexiconPanel({ kbId, structured }: { kbId: string; structured: boolean }) {
    const [tab, setTab] = useState<'entries' | 'review' | 'dups'>('entries');
    const [status, setStatus] = useState<any>(null);
    const [q, setQ] = useState('');
    const [entries, setEntries] = useState<Entry[]>([]);
    const [total, setTotal] = useState(0);
    const [review, setReview] = useState<{ broader: string; labels: string[] }[]>([]);
    const [dups, setDups] = useState<{ labels: string[]; shared: string[] }[]>([]);
    // 중복 판정 제안 (데이터 품질 D2): 묶음 라벨 키 → {decision, canonical, reason, remove_aliases}
    const [dupSug, setDupSug] = useState<Record<string, any>>({});
    const [aliasOf, setAliasOf] = useState<Record<string, string[]>>({});   // 라벨 → 그 라벨의 별칭 (공유 별칭을 라벨별로 지우기 위함)
    const [msg, setMsg] = useState('');
    const [busy, setBusy] = useState(false);
    const [adding, setAdding] = useState<Record<string, string>>({});

    const loadStatus = useCallback(() => lexiconApi.status(kbId).then((r) => setStatus(r.data)).catch(() => undefined), [kbId]);
    const loadEntries = useCallback(() => lexiconApi.list(kbId, q || undefined).then((r) => {
        setEntries(r.data.entries || []); setTotal(r.data.total || 0);
    }).catch(() => setMsg('사전을 불러오지 못했습니다.')), [kbId, q]);
    const loadReview = useCallback(() => lexiconApi.review(kbId).then((r) => setReview(r.data.groups || [])).catch(() => undefined), [kbId]);
    const loadDups = useCallback(async () => {
        try {
            const r = await lexiconApi.duplicates(kbId);
            const groups = r.data.groups || [];
            setDups(groups);
            const rv = await lexiconApi.duplicateReview(kbId).catch(() => ({ data: { items: [] } }));
            setDupSug(Object.fromEntries((rv.data.items || []).map((i: any) => [i.labels.join('|'), i])));
            const labels = Array.from(new Set(groups.flatMap((g: any) => g.labels))) as string[];
            const m: Record<string, string[]> = {};
            for (const l of labels.slice(0, 120)) {
                const e = await lexiconApi.entry(kbId, l).catch(() => null);
                const hit = (e?.data?.entries || []).find((x: any) => x.label === l);
                if (hit) m[l] = [...hit.ko, ...hit.en, ...hit.syn];
            }
            setAliasOf(m);
        } catch { /* 무시 */ }
    }, [kbId]);

    useEffect(() => { loadStatus(); loadReview(); loadDups(); }, [loadStatus, loadReview, loadDups]);
    useEffect(() => { const t = setTimeout(loadEntries, 250); return () => clearTimeout(t); }, [loadEntries]);
    // 빌드 중이면 상태를 주기적으로 갱신
    useEffect(() => {
        if (status?.state !== 'running') return;
        const t = setInterval(() => {
            lexiconApi.status(kbId).then((r) => {
                setStatus(r.data);
                if (r.data.state !== 'running') { loadEntries(); loadReview(); loadDups(); }
            }).catch(() => undefined);
        }, 4000);
        return () => clearInterval(t);
    }, [status?.state, kbId, loadEntries, loadReview, loadDups]);

    const run = async (fn: () => Promise<any>, ok: string) => {
        setBusy(true); setMsg('');
        try { await fn(); setMsg(ok); await Promise.all([loadEntries(), loadReview(), loadDups()]); }
        catch (e: any) { setMsg(e?.response?.data?.detail || '실패했습니다.'); }
        finally { setBusy(false); }
    };

    const build = (rebuild: boolean) => run(async () => {
        await lexiconApi.build(kbId, rebuild);
        await loadStatus();
    }, rebuild ? '사전을 다시 만드는 중입니다 (사람이 고친 항목은 유지).' : '새 라벨의 별칭을 만드는 중입니다.');

    const removeAlias = (e: Entry, field: 'ko' | 'en' | 'syn', a: string) =>
        run(() => lexiconApi.edit(kbId, { label: e.label, [field]: e[field].filter((x) => x !== a) }), `'${a}' 별칭을 지웠습니다.`);
    const addAlias = (e: Entry) => {
        const v = (adding[e.label] || '').trim();
        if (!v) return;
        const isAscii = /^[\x00-\x7F]+$/.test(v);
        const field = isAscii ? 'en' : 'ko';
        run(() => lexiconApi.edit(kbId, { label: e.label, [field]: [...e[field], v] }), `'${v}' 를 ${field === 'en' ? '영어' : '한국어'} 별칭으로 추가했습니다.`)
            .then(() => setAdding({ ...adding, [e.label]: '' }));
    };

    const statusLine = () => {
        if (!status || status.state === 'idle') return '이번 서버 실행에서 만든 적 없음';
        if (status.state === 'running') return `만드는 중… ${status.done || 0}/${status.total || '?'}`;
        if (status.state === 'error') return `오류: ${status.error}`;
        return `완료 — 라벨 ${status.labels}, 새로 만든 항목 ${status.generated}, 상위 개념 ${status.concepts}`;
    };

    const aliasChips = (e: Entry, field: 'ko' | 'en' | 'syn', color: string) => e[field].map((a) => (
        <span key={field + a} style={{ ...chip, borderColor: color }}>
            {a}
            <button style={iconBtn} title="이 별칭 삭제" disabled={busy} onClick={() => removeAlias(e, field, a)}><X size={11} color="#94a3b8" /></button>
        </span>
    ));

    return (
        <div className="card" style={{ padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                <h4 style={{ margin: 0 }}>용어 사전</h4>
                <span style={{ fontSize: '0.75rem', color: '#64748b' }}>{statusLine()}</span>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.4rem' }}>
                    <button className="btn btn-secondary" style={btn} disabled={busy || status?.state === 'running'} onClick={() => build(false)}
                        title="사전에 없는 라벨만 별칭을 만든다 (적재·재추출 뒤)"><Plus size={13} /> 새 라벨 반영</button>
                    <button className="btn btn-secondary" style={btn} disabled={busy || status?.state === 'running'} onClick={() => build(true)}
                        title="LLM 이 만든 항목을 모두 다시 만든다. 사람이 고친 항목은 유지"><RefreshCw size={13} /> 전체 다시 만들기</button>
                </div>
            </div>
            <div style={{ fontSize: '0.75rem', color: '#64748b', lineHeight: 1.5 }}>
                검색할 때 질문의 말(한영·음역·동의어)을 그래프 표기로 맞추는 사전입니다. 예: 헥사고날 → Hexagonal 아키텍처, 수정 용이성 → 변경 용이성.
                별칭을 고치거나 지운 항목은 <b>사람 수정</b>으로 표시되고, 사전을 다시 만들어도 바뀌지 않습니다.
            </div>

            <div style={{ display: 'flex', gap: 0 }}>
                {([['entries', `항목 (${total})`], ['review', `상위 개념 검토 (${review.length})`], ['dups', `중복 후보 (${dups.length})`]] as const).map(([k, l], i, arr) => (
                    <button key={k} className={`btn ${tab === k ? 'btn-primary' : 'btn-secondary'}`}
                        style={{ ...btn, borderRadius: i === 0 ? '6px 0 0 6px' : i === arr.length - 1 ? '0 6px 6px 0' : 0 }}
                        onClick={() => setTab(k)}>{l}</button>
                ))}
            </div>

            {tab === 'entries' && <>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                    <Search size={14} color="#94a3b8" />
                    <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="라벨·별칭 검색 (예: 헥사고날, maintainability)"
                        style={{ flex: 1, fontSize: '0.8rem', padding: '0.25rem 0.4rem', border: '1px solid #cbd5e1', borderRadius: '4px' }} />
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead><tr style={{ textAlign: 'left', color: '#64748b', fontSize: '0.75rem' }}>
                        <th style={{ ...cell, width: '22%' }}>라벨</th><th style={cell}>별칭 (파랑 한국어 · 초록 영어 · 보라 동의어)</th><th style={{ ...cell, width: '22%' }}>상위 개념</th>
                    </tr></thead>
                    <tbody>
                        {entries.filter((e) => !e.skip).map((e) => (
                            <tr key={e.label}>
                                <td style={cell}>
                                    <div style={{ fontWeight: 600 }}>{e.label}</div>
                                    {e.concept_only && <div style={{ fontSize: '0.7rem', color: '#64748b' }}>상위 개념 항목</div>}
                                    {e.variants && e.variants.length > 0 && <div style={{ fontSize: '0.7rem', color: '#64748b' }}>같은 표기: {e.variants.join(', ')}</div>}
                                    {e.source === 'user' && <div style={{ fontSize: '0.7rem', color: '#0f766e' }}>사람 수정</div>}
                                </td>
                                <td style={cell}>
                                    {aliasChips(e, 'ko', '#93c5fd')}{aliasChips(e, 'en', '#86efac')}{aliasChips(e, 'syn', '#c4b5fd')}
                                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem', marginLeft: '0.2rem' }}>
                                        <input value={adding[e.label] || ''} placeholder="별칭 추가"
                                            onChange={(ev) => setAdding({ ...adding, [e.label]: ev.target.value })}
                                            onKeyDown={(ev) => { if (ev.key === 'Enter') addAlias(e); }}
                                            style={{ width: '7rem', fontSize: '0.72rem', padding: '0.1rem 0.3rem', border: '1px solid #e2e8f0', borderRadius: '4px' }} />
                                        <button style={iconBtn} disabled={busy} onClick={() => addAlias(e)} title="추가 (영문이면 영어, 아니면 한국어 별칭)"><Plus size={13} color="#64748b" /></button>
                                    </span>
                                </td>
                                <td style={cell}>
                                    {e.broader.map((b) => (
                                        <span key={b.label} style={{ ...chip, background: b.status === 'approved' ? '#dcfce7' : b.status === 'rejected' ? '#fee2e2' : '#f8fafc',
                                            textDecoration: b.status === 'rejected' ? 'line-through' : undefined }}>
                                            {b.label}
                                            {b.status !== 'approved' && <button style={iconBtn} title="승인" disabled={busy}
                                                onClick={() => run(() => lexiconApi.broader(kbId, { label: e.label, broader: b.label, status: 'approved' }), '승인했습니다.')}><Check size={11} color="#16a34a" /></button>}
                                            {b.status !== 'rejected' && <button style={iconBtn} title="거절" disabled={busy}
                                                onClick={() => run(() => lexiconApi.broader(kbId, { label: e.label, broader: b.label, status: 'rejected' }), '거절했습니다.')}><X size={11} color="#dc2626" /></button>}
                                        </span>
                                    ))}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {total > entries.length && <div style={{ fontSize: '0.75rem', color: '#64748b' }}>{entries.length}/{total}개 표시 — 검색으로 좁혀 보세요.</div>}
            </>}

            {tab === 'review' && <>
                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                    상위 개념은 '유지보수성이 좋은 X' 처럼 그래프에 없는 넓은 말을 하위 값으로 풀 때 씁니다. 승인한 것은 검색 결과에 '검토됨'으로, 거절한 것은 쓰지 않습니다.
                    포함 관계가 아닌 것(예: 마이크로서비스 → 백엔드 독립 배포)은 거절하세요.
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <tbody>
                        {review.map((g) => (
                            <tr key={g.broader}>
                                <td style={{ ...cell, width: '22%', fontWeight: 600 }}>{g.broader}</td>
                                <td style={cell}>{g.labels.map((l) => <span key={l} style={chip}>{l}</span>)}</td>
                                <td style={{ ...cell, width: '16%', whiteSpace: 'nowrap' }}>
                                    <button className="btn btn-secondary" style={btn} disabled={busy}
                                        onClick={() => run(() => lexiconApi.broader(kbId, { label: g.labels[0], broader: g.broader, status: 'approved', labels: g.labels }), `'${g.broader}' 를 승인했습니다.`)}><Check size={12} /> 승인</button>
                                    <button className="btn btn-secondary" style={{ ...btn, marginLeft: '0.3rem' }} disabled={busy}
                                        onClick={() => run(() => lexiconApi.broader(kbId, { label: g.labels[0], broader: g.broader, status: 'rejected', labels: g.labels }), `'${g.broader}' 를 거절했습니다.`)}><X size={12} /> 거절</button>
                                </td>
                            </tr>
                        ))}
                        {review.length === 0 && <tr><td style={cell}>검토할 상위 개념이 없습니다.</td></tr>}
                    </tbody>
                </table>
            </>}

            {tab === 'dups' && <>
                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                    같은 별칭을 공유하는 라벨 묶음입니다. 같은 대상이면 <b>병합</b>(선택한 라벨을 대표로 그래프 표기를 합침),
                    다른 대상인데 일반적인 별칭(예: '고등교육기관')이 겹친 것이면 그 <b>별칭만 삭제</b>하세요.
                    {structured && ' 구조화(YAML) KB 는 병합하지 않고 별칭만 정리합니다.'}
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <tbody>
                        {dups.map((g) => (
                            <tr key={g.labels.join('|')}>
                                <td style={{ ...cell, width: '38%' }}>
                                    {dupSug[g.labels.join('|')] && (() => {
                                        const sg = dupSug[g.labels.join('|')];
                                        const color = sg.decision === 'merge' ? '#16a34a' : sg.decision === 'distinct' ? '#d97706' : '#64748b';
                                        const label = sg.decision === 'merge' ? `제안: 같은 대상 → '${sg.canonical}' 로 병합` : sg.decision === 'distinct' ? '제안: 다른 대상 — 잘못 붙은 별칭만 정리' : '제안: 판단 불가';
                                        return <div style={{ fontSize: '0.72rem', color, marginBottom: '0.2rem' }}>{label}<div style={{ color: '#64748b' }}>{sg.reason}</div></div>;
                                    })()}
                                    {g.labels.map((l) => (
                                        <div key={l} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                            <span>{l}</span>
                                            {!structured && <button className="btn btn-secondary" style={{ ...btn, padding: '0.05rem 0.35rem' }} disabled={busy}
                                                title={`'${l}' 를 대표로 나머지를 합친다 (엔티티 규칙 + 리플레이)`}
                                                onClick={() => {
                                                    const others = g.labels.filter((x) => x !== l);
                                                    if (!window.confirm(`'${others.join(', ')}' 를 '${l}' 로 병합합니다. 그래프 표기가 바뀝니다 (규칙 목록에서 되돌릴 수 있음). 진행할까요?`)) return;
                                                    run(() => schemaApi.mergeEntities(kbId, l, others), `'${l}' 로 병합했습니다. 사전 '새 라벨 반영'을 누르면 정리됩니다.`);
                                                }}><GitMerge size={11} /> 이걸로 병합</button>}
                                        </div>
                                    ))}
                                </td>
                                <td style={cell}>
                                    <div style={{ fontSize: '0.7rem', color: '#64748b' }}>공유 별칭 — 잘못 붙은 라벨에서만 지우세요 (라벨 이름 칩의 ×)</div>
                                    {g.shared.map((a) => {
                                        const holders = g.labels.filter((l) => (aliasOf[l] || []).some((x) => x.replace(/\s/g, '').toLowerCase() === a.replace(/\s/g, '').toLowerCase()));
                                        return (
                                            <div key={a} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', flexWrap: 'wrap', marginBottom: '0.15rem' }}>
                                                <span style={{ ...chip, fontWeight: 600 }}>{a}</span>
                                                {holders.length === 0 && <span style={{ fontSize: '0.7rem', color: '#94a3b8' }}>(라벨 자체 표기)</span>}
                                                {holders.map((l) => (
                                                    <span key={l} style={{ ...chip, background: '#fff' }}>{l}
                                                        <button style={iconBtn} title={`'${l}' 에서만 '${a}' 별칭 삭제`} disabled={busy}
                                                            onClick={() => run(() => lexiconApi.removeAlias(kbId, a, [l]), `'${l}' 에서 '${a}' 별칭을 지웠습니다.`)}><X size={11} color="#dc2626" /></button>
                                                    </span>
                                                ))}
                                            </div>
                                        );
                                    })}
                                </td>
                            </tr>
                        ))}
                        {dups.length === 0 && <tr><td style={cell}>중복 후보가 없습니다.</td></tr>}
                    </tbody>
                </table>
            </>}

            {msg && <div style={{ fontSize: '0.78rem', color: '#0f766e' }}>{msg}</div>}
        </div>
    );
}
