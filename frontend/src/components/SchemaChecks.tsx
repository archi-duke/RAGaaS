import React, { useState } from 'react';
import { schemaApi } from '../services/api';

// 스키마 데이터 검증 (docs/design-schema-editor.md §10)
// - 멤버 누락: range 클래스로 이어지는데 클래스가 없는 목적어 → 체크해서 멤버로 지정 (class 규칙 + 리플레이)
// - range 위반: 목적어가 다른 클래스 멤버 (방향·분류 확인용, 표시만)
// - 표기 중복: 한 클래스 범위에서 같은 개념 다른 표기 후보(LLM 제안) → 체크해서 병합 (entity 규칙 + 리플레이)

interface Gap { name: string; count: number; via: string[]; }
interface Props {
    kbId: string;
    memberGaps: Record<string, Gap[]>;
    violations: { property: string; range: string; name: string; class: string }[];
    onChanged: (msg: string) => void;
}

const btn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.78rem', padding: '0.25rem 0.55rem' };

export default function SchemaChecks({ kbId, memberGaps, violations, onChanged }: Props) {
    const [sel, setSel] = useState<Record<string, Set<string>>>({});
    const [busy, setBusy] = useState<string | null>(null);
    const [merge, setMerge] = useState<Record<string, { canonical: string; aliases: string[]; on: boolean }[]>>({});
    const classes = Object.keys(memberGaps || {}).filter((k) => (memberGaps[k] || []).length);
    if (!classes.length && !violations.length) return null;

    const toggle = (cls: string, name: string) => setSel((s) => {
        const cur = new Set(s[cls] || []);
        cur.has(name) ? cur.delete(name) : cur.add(name);
        return { ...s, [cls]: cur };
    });

    const assign = async (cls: string) => {
        const ents = Array.from(sel[cls] || []);
        if (!ents.length) return;
        setBusy(`a-${cls}`);
        try {
            const r = await schemaApi.assignMembers(kbId, cls, ents);
            onChanged(`${cls} 멤버 지정: 추가 ${r.data.added}, 이동 ${r.data.moved} · 리플레이 문서 ${r.data.replayed}`);
            setSel((s) => ({ ...s, [cls]: new Set() }));
        } catch (e: any) {
            onChanged('멤버 지정 실패: ' + (e?.response?.data?.detail?.errors?.join(' / ') || e.message));
        } finally { setBusy(null); }
    };

    const findMerges = async (cls: string) => {
        setBusy(`m-${cls}`);
        try {
            const r = await schemaApi.mergeCandidates(kbId, cls);
            setMerge((m) => ({ ...m, [cls]: (r.data.groups || []).map((g: any) => ({ ...g, on: true })) }));
            if (!(r.data.groups || []).length) onChanged(`${cls}: 표기 중복 후보 없음`);
        } catch (e: any) {
            onChanged('표기 중복 찾기 실패: ' + (e?.response?.data?.detail?.errors?.join(' / ') || e.message));
        } finally { setBusy(null); }
    };

    const applyMerges = async (cls: string) => {
        const groups = (merge[cls] || []).filter((g) => g.on);
        setBusy(`mm-${cls}`);
        try {
            let n = 0;
            for (const g of groups) {
                const r = await schemaApi.mergeEntities(kbId, g.canonical, g.aliases);
                n += r.data.merged;
            }
            onChanged(`${cls} 표기 병합 ${n}건 (리플레이 완료)`);
            setMerge((m) => ({ ...m, [cls]: [] }));
        } catch (e: any) {
            onChanged('병합 실패: ' + e.message);
        } finally { setBusy(null); }
    };

    return (
        <div className="card" style={{ padding: '0.75rem' }}>
            <h4 style={{ margin: '0 0 0.25rem' }}>데이터 검증</h4>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '0 0 0.5rem' }}>
                관계의 목적어가 range 클래스 멤버인지 데이터로 확인합니다. 클래스가 없는 목적어(멤버 누락)를 체크해 멤버로 지정하면
                class 규칙이 만들어지고 그래프가 리플레이됩니다(LLM 비용 없음). 점수·문장 같은 잡음은 체크하지 마세요.
            </p>
            {classes.map((cls) => (
                <div key={cls} style={{ marginBottom: '0.75rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.3rem' }}>
                        <b style={{ fontSize: '0.82rem' }}>{cls}</b>
                        <span style={{ fontSize: '0.75rem', color: '#64748b' }}>멤버 누락 후보 {memberGaps[cls].length}</span>
                        <button className="btn btn-secondary" style={btn} onClick={() => setSel((s) => ({ ...s, [cls]: new Set(memberGaps[cls].filter((g) => g.via.length > 1 || g.count > 1).map((g) => g.name)) }))}>
                            여러 번 나온 것 선택
                        </button>
                        <button className="btn btn-primary" style={btn} disabled={!!busy || !(sel[cls]?.size)} onClick={() => assign(cls)}>
                            선택 {sel[cls]?.size || 0}개를 {cls} 멤버로
                        </button>
                        <button className="btn btn-secondary" style={btn} disabled={!!busy} onClick={() => findMerges(cls)}
                            title="이 클래스 멤버·후보 안에서 같은 개념 다른 표기(한·영 등)를 LLM 으로 찾습니다 — 제안만, 체크해야 병합">
                            {busy === `m-${cls}` ? '찾는 중…' : '표기 중복 찾기'}
                        </button>
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem' }}>
                        {memberGaps[cls].map((g) => (
                            <label key={g.name} title={`관계: ${g.via.join(', ')}`} style={{
                                fontSize: '0.75rem', border: '1px solid #cbd5e1', borderRadius: '12px', padding: '0.1rem 0.5rem',
                                background: sel[cls]?.has(g.name) ? '#dbeafe' : '#fff', cursor: 'pointer',
                            }}>
                                <input type="checkbox" style={{ marginRight: 4 }} checked={!!sel[cls]?.has(g.name)} onChange={() => toggle(cls, g.name)} />
                                {g.name} <span style={{ color: '#94a3b8' }}>{g.count}</span>
                            </label>
                        ))}
                    </div>
                    {(merge[cls] || []).length > 0 && (
                        <div style={{ marginTop: '0.4rem', padding: '0.4rem 0.6rem', background: '#f8fafc', borderRadius: '6px', fontSize: '0.78rem' }}>
                            {(merge[cls] || []).map((g, i) => (
                                <label key={i} style={{ display: 'block' }}>
                                    <input type="checkbox" checked={g.on} onChange={() => setMerge((m) => ({ ...m, [cls]: m[cls].map((x, j) => j === i ? { ...x, on: !x.on } : x) }))} />{' '}
                                    <b>{g.canonical}</b> ← {g.aliases.join(', ')}
                                </label>
                            ))}
                            <button className="btn btn-primary" style={{ ...btn, marginTop: '0.3rem' }} disabled={!!busy} onClick={() => applyMerges(cls)}>체크한 묶음 병합</button>
                        </div>
                    )}
                </div>
            ))}
            {violations.length > 0 && (
                <details style={{ fontSize: '0.78rem' }}>
                    <summary>range 위반 {violations.length}건 — 목적어가 다른 클래스 멤버 (방향이나 분류를 확인)</summary>
                    {violations.map((v, i) => <div key={i}>· {v.property}: {v.name} 은 {v.class} (range {v.range})</div>)}
                </details>
            )}
        </div>
    );
}
