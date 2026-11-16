import React, { useEffect, useMemo, useState } from 'react';
import { X as XIcon, Sparkles } from 'lucide-react';
import { schemaApi } from '../services/api';

// 스키마 AI 추천 (docs/design-schema-editor.md §14, 설명서 §2.9)
// 추천(처리안 목록) → 체크 → 효과 미리보기(가상 적용 + 문제 청크 재추출, 저장 없음) → 승인하고 반영
// 처리안은 모두 기존 편집 동작(정의·range·관계/클래스 추가·멤버 지정·병합·트리플 이동/삭제)으로 반영된다.

const TYPE_COLOR: Record<string, string> = {
    set_definition: '#7c3aed', set_range: '#7c3aed', set_domain: '#7c3aed', add_property: '#2563eb', add_class: '#2563eb',
    assign_members: '#0d9488', merge_entities: '#0d9488', move_triples: '#b45309', delete_triples: '#b91c1c',
};

function detail(a: any): React.ReactNode {
    switch (a.type) {
        case 'set_definition': return <><b>{a.property}</b> 정의 → “{a.description}”{a.before ? <div style={{ color: '#94a3b8' }}>이전: {a.before}</div> : null}</>;
        case 'set_range': return <><b>{a.property}</b> range: {a.before || '(값)'} → <b>{a.range || '(값)'}</b></>;
        case 'set_domain': return <><b>{a.property}</b> domain: {a.before || '?'} → <b>{a.domain || '?'}</b></>;
        case 'add_property': return <>관계 <b>{a.name}</b> ({a.domain || '?'} → {a.range || '값'}) — {a.description}</>;
        case 'add_class': return <>클래스 <b>{a.name}</b> — {a.description}{a.members?.length ? ` · 멤버: ${a.members.join(', ')}` : ''}</>;
        case 'assign_members': return <><b>{a.class}</b> 멤버로: {a.entities.join(', ')}</>;
        case 'merge_entities': return <><b>{a.canonical}</b> ← {a.aliases.join(', ')}</>;
        case 'move_triples': return <>→ <b>{a.target_property}</b>{(a.triples || []).map((t: any, i: number) =>
            <div key={i} style={{ color: '#475569' }}>· {t.subject} —{t.predicate}→ {t.object}</div>)}</>;
        case 'delete_triples': return <>{(a.triples || []).map((t: any, i: number) =>
            <div key={i} style={{ color: '#475569' }}>· {t.subject} —{t.predicate}→ {t.object}</div>)}</>;
        default: return JSON.stringify(a);
    }
}

export default function RecommendPanel({ kbId, triples, onClose, onApplied }: {
    kbId: string; triples?: any[]; onClose: () => void; onApplied: (msg: string) => void;
}) {
    const [rec, setRec] = useState<any>(null);
    const [error, setError] = useState('');
    const [checked, setChecked] = useState<Set<string>>(new Set());
    const [pv, setPv] = useState<any>(null);
    const [pvKey, setPvKey] = useState('');
    const [busy, setBusy] = useState<'' | 'rec' | 'pv' | 'apply'>('rec');
    const errMsg = (e: any) => e?.response?.data?.detail?.errors?.join(' / ') || e?.response?.data?.detail || e.message;

    useEffect(() => {
        schemaApi.recommend(kbId, triples).then((r) => {
            setRec(r.data);
            setChecked(new Set((r.data.actions || []).filter((a: any) => a.confidence >= 0.7 && !a.warning).map((a: any) => a.id)));
        }).catch((e) => setError('추천 실패: ' + errMsg(e))).finally(() => setBusy(''));
    }, [kbId]);   // eslint-disable-line react-hooks/exhaustive-deps

    const chosen = useMemo(() => (rec?.actions || []).filter((a: any) => checked.has(a.id)), [rec, checked]);
    const key = chosen.map((a: any) => a.id).sort().join(',');
    const previewed = pv && pvKey === key;

    const doPreview = async () => {
        setBusy('pv'); setError('');
        try {
            const r = await schemaApi.recommendPreview(kbId, chosen, rec.problems || []);
            setPv(r.data); setPvKey(key);
        } catch (e: any) { setError('효과 미리보기 실패: ' + errMsg(e)); } finally { setBusy(''); }
    };
    const doApply = async () => {
        setBusy('apply'); setError('');
        try {
            const r = await schemaApi.recommendApply(kbId, chosen, rec.version);
            const d = r.data;
            onApplied(`AI 추천 ${chosen.length}건 반영: ` + (d.schema_saved ? `스키마 v${d.version} 저장, ` : '') + `규칙 ${d.rules_created}건, 리플레이 ${d.replayed}건`
                + (d.reextract_recommended ? ' · 정의·range 변경은 "스키마 기준 재추출"을 돌려야 전체 데이터에 반영됩니다.' : ''));
            onClose();
        } catch (e: any) { setError('반영 실패: ' + errMsg(e)); } finally { setBusy(''); }
    };

    const toggle = (id: string) => setChecked((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
    const btn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.8rem', padding: '0.3rem 0.6rem' };

    return (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)', zIndex: 2100, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
            <div className="card" style={{ width: 'min(980px, 95vw)', maxHeight: '88vh', display: 'flex', flexDirection: 'column', padding: '1rem' }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
                    <Sparkles size={16} /><h3 style={{ margin: 0 }}>AI 추천{triples ? ` — 선택한 트리플 ${triples.length}개` : ''}</h3>
                    {rec && <span style={{ fontSize: '0.78rem', color: '#64748b' }}>{rec.model} · 처리안 {rec.actions.length} · 분석한 문제 트리플 {rec.problems.length}</span>}
                    <button className="btn btn-secondary" style={{ marginLeft: 'auto', padding: '0.2rem 0.4rem' }} onClick={onClose}><XIcon size={14} /></button>
                </div>
                <p style={{ fontSize: '0.76rem', color: '#64748b', margin: '0 0 0.5rem' }}>
                    AI 가 스키마·데이터 검증 결과·문제 트리플의 근거 청크를 읽고 처리안을 냈습니다. <b>체크한 항목만</b> 적용됩니다.
                    먼저 <b>효과 미리보기</b>로 문제 청크를 재추출해 결과를 확인한 뒤 <b>승인하고 반영</b>하세요 (미리보기는 저장하지 않습니다).
                </p>
                {error && <div style={{ color: '#b91c1c', fontSize: '0.85rem', marginBottom: '0.4rem' }}>{error}</div>}
                {busy === 'rec' && <div>스키마와 문제 트리플을 분석하는 중… (30초 안팎)</div>}
                {rec && <div style={{ overflowY: 'auto', flex: 1 }}>
                    {rec.actions.length === 0 && <div>제안할 처리안이 없습니다.</div>}
                    {rec.actions.map((a: any) => (
                        <label key={a.id} style={{ display: 'flex', gap: '0.5rem', padding: '0.45rem 0.4rem', borderBottom: '1px solid #e2e8f0', fontSize: '0.8rem', background: checked.has(a.id) ? '#f8fafc' : undefined, cursor: 'pointer' }}>
                            <input type="checkbox" checked={checked.has(a.id)} onChange={() => toggle(a.id)} style={{ marginTop: 3 }} />
                            <div style={{ flex: 1 }}>
                                <div>
                                    <span style={{ color: '#fff', background: TYPE_COLOR[a.type] || '#64748b', borderRadius: '10px', padding: '0.05rem 0.45rem', fontSize: '0.72rem', marginRight: 6 }}>{a.label}</span>
                                    <span style={{ color: a.confidence >= 0.7 ? '#15803d' : '#b45309', fontSize: '0.72rem' }}>확신 {Math.round(a.confidence * 100)}%</span>
                                </div>
                                <div style={{ marginTop: '0.2rem' }}>{detail(a)}</div>
                                <div style={{ color: '#475569', marginTop: '0.15rem' }}>↳ {a.reason}</div>
                                {a.evidence && <div style={{ color: '#64748b', fontStyle: 'italic' }}>근거: “{a.evidence}”</div>}
                                {a.warning && <div style={{ color: '#b45309' }}>⚠ {a.warning}</div>}
                            </div>
                        </label>
                    ))}
                </div>}
                {pv && (
                    <div style={{ borderTop: '1px solid #cbd5e1', marginTop: '0.4rem', paddingTop: '0.4rem', fontSize: '0.8rem', maxHeight: '32vh', overflowY: 'auto' }}>
                        <div style={{ display: 'flex', gap: '0.7rem', flexWrap: 'wrap', alignItems: 'center' }}>
                            <b>효과 미리보기{previewed ? '' : ' (체크가 바뀌었습니다 — 다시 미리보기)'}</b>
                            <span style={{ color: '#15803d' }}>문제 트리플 사라짐 {pv.summary.gone}</span>
                            <span style={{ color: '#2563eb' }}>맞는 관계로 바뀜 {pv.summary.moved}</span>
                            <span style={{ color: '#b91c1c' }}>남음 {pv.summary.kept}</span>
                            <span title="재추출된 트리플 중 range 가 있는 관계에서, 목적어가 range 클래스 멤버인 비율">
                                재추출 결과 range 일치 {pv.range_fit.ok}/{pv.range_fit.ok + pv.range_fit.bad}</span>
                            <span style={{ color: '#94a3b8' }}>청크 {pv.chunks} · 가상 규칙 {pv.rules_simulated} · {pv.model}</span>
                        </div>
                        {(pv.results || []).map((x: any, i: number) => (
                            <div key={i}>
                                <span style={{ color: x.result === 'gone' ? '#15803d' : x.result === 'moved' ? '#2563eb' : '#b91c1c', fontWeight: 600 }}>
                                    {x.result === 'gone' ? '사라짐' : x.result === 'moved' ? '바뀜' : '남음'}</span>{' '}
                                {x.subject} —{x.predicate}→ {x.object}{x.new_predicate ? <span style={{ color: '#2563eb' }}> ⇒ {x.new_predicate}</span> : null}
                            </div>
                        ))}
                    </div>
                )}
                {rec && (
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginTop: '0.6rem' }}>
                        <span style={{ fontSize: '0.8rem' }}>체크 {chosen.length}개</span>
                        <button className="btn btn-secondary" style={btn} disabled={!!busy || !chosen.length} onClick={doPreview}>
                            {busy === 'pv' ? '재추출로 효과 확인 중…' : '효과 미리보기 (재추출 테스트)'}
                        </button>
                        <button className="btn btn-primary" style={{ ...btn, marginLeft: 'auto' }} disabled={!!busy || !chosen.length || !previewed}
                            title={previewed ? '체크한 처리안을 반영합니다 (스키마 저장 + 규칙 + 리플레이)' : '먼저 효과 미리보기를 하세요'}
                            onClick={doApply}>
                            {busy === 'apply' ? '반영 중…' : `승인하고 반영 (${chosen.length})`}
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
