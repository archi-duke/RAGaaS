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
    onOpenList?: (status: 'violation' | 'gap', className?: string) => void;   // 불일치 트리플 목록 열기
}

const btn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.78rem', padding: '0.25rem 0.55rem' };

export default function SchemaChecks({ kbId, memberGaps, violations, onChanged, onOpenList }: Props) {
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
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap', marginBottom: '0.3rem' }}>
                <h4 style={{ margin: 0 }}>데이터 검증</h4>
                {onOpenList && violations.length > 0 && (
                    <button className="btn btn-secondary" style={{ ...btn, color: '#b91c1c' }} onClick={() => onOpenList('violation')}
                        title="목적어가 range 와 다른 클래스인 트리플 목록 (모든 관계)">
                        range 위반 목적어 {violations.length}종 — 트리플 목록 보기
                    </button>
                )}
                {onOpenList && classes.length > 0 && (
                    <button className="btn btn-secondary" style={{ ...btn, color: '#b45309' }} onClick={() => onOpenList('gap')}
                        title="목적어에 클래스가 없는 트리플 목록 (모든 관계)">
                        멤버 누락 {classes.reduce((n, c) => n + memberGaps[c].length, 0)}종 — 트리플 목록 보기
                    </button>
                )}
            </div>
            <details style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '0 0 0.5rem' }}>
                <summary style={{ cursor: 'pointer' }}>이 카드는 무엇을 보여 주나요?</summary>
                <div style={{ marginTop: '0.3rem', lineHeight: 1.55 }}>
                    관계마다 "목적어는 이 클래스여야 한다"(range)고 정해 두었습니다. 실제 트리플의 목적어가 그 약속을 지키는지 데이터로 확인한 결과입니다.
                    <div>· <b style={{ color: '#15803d' }}>일치</b> — 목적어가 range 클래스 멤버. 예) Person —제안함→ <u>상대성이론</u>(TheoryOrConcept)</div>
                    <div>· <b style={{ color: '#b45309' }}>멤버 누락</b> — 목적어가 <b>아직 어느 클래스에도 없음</b>. 틀린 게 아니라 분류가 빠진 것.
                        맞는 종류면 체크해 멤버로 지정하고, '없음'·'-3점'·문장 조각 같은 잡음은 트리플을 삭제합니다.</div>
                    <div>· <b style={{ color: '#b91c1c' }}>range 위반</b> — 목적어가 <b>다른 클래스로 이미 분류됨</b>. 예) requires(→ Requirement) 의 목적어 '멱등성'이 FailureHandlingPattern.
                        관계를 잘못 붙였거나(→ 다른 관계로 이동), 사실이 틀렸거나(→ 삭제), 목적어 분류가 틀린 것(→ 클래스 변경).</div>
                    <div>· 숫자 'N종'은 <b>서로 다른 목적어 수</b>입니다. 같은 목적어가 여러 트리플에 나오므로 목록의 트리플 수는 더 많을 수 있습니다.</div>
                    <div>· 아래 칩(클래스별 멤버 누락 후보)을 체크해 바로 멤버로 지정할 수 있고, 목록에서는 이동·삭제·재추출 테스트·AI 추천까지 할 수 있습니다.</div>
                </div>
            </details>
            {classes.map((cls) => (
                <div key={cls} style={{ marginBottom: '0.75rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.3rem' }}>
                        <b style={{ fontSize: '0.82rem' }}>{cls}</b>
                        {onOpenList
                            ? <button className="btn btn-secondary" style={{ ...btn, padding: '0.1rem 0.4rem' }} onClick={() => onOpenList('gap', cls)}
                                title={`range 가 ${cls} 인 관계에서 목적어에 클래스가 없는 트리플 목록`}>멤버 누락 후보 {memberGaps[cls].length}종 — 목록</button>
                            : <span style={{ fontSize: '0.75rem', color: '#64748b' }}>멤버 누락 후보 {memberGaps[cls].length}</span>}
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
