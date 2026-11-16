import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Play, ArrowLeftRight, Trash2 } from 'lucide-react';
import { schemaApi } from '../services/api';

// 관계 방향 검증 (데이터 품질 D1) — 같은 클래스끼리 잇는 관계(인물→인물, 이론→이론)는 클래스 검사로
// 방향 오류를 못 잡는다. 트리플마다 원문 문장으로 LLM 이 판정한 결과를 보고, 사람이 골라서 뒤집거나 지운다.
// 적용은 triple 규칙(@flip / 삭제) + 리플레이 — 규칙 목록에서 되돌릴 수 있다.

interface Item { subject: string; predicate: string; object: string; verdict: string; reason: string; evidence: string[]; doc?: string; }

const VERDICT: Record<string, { label: string; color: string }> = {
    reverse: { label: '방향 반대', color: '#dc2626' },
    unrelated: { label: '관계 아님', color: '#d97706' },
    unsure: { label: '판단 불가', color: '#64748b' },
    forward: { label: '맞음', color: '#16a34a' },
};
const cell: React.CSSProperties = { padding: '0.3rem 0.4rem', borderBottom: '1px solid #e2e8f0', verticalAlign: 'top', fontSize: '0.78rem' };
const btn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.78rem', padding: '0.25rem 0.55rem' };

export default function DirectionAuditPanel({ kbId, onChanged }: { kbId: string; onChanged: (m: string) => void }) {
    const [data, setData] = useState<any>(null);
    const [show, setShow] = useState<Set<string>>(new Set(['reverse', 'unrelated']));
    const [sel, setSel] = useState<Set<number>>(new Set());
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState('');

    const load = useCallback(() => schemaApi.directionAudit(kbId).then((r) => setData(r.data)).catch(() => setMsg('결과를 불러오지 못했습니다.')), [kbId]);
    useEffect(() => { load(); }, [load]);
    useEffect(() => {
        if (data?.run?.state !== 'running') return;
        const t = setInterval(load, 4000);
        return () => clearInterval(t);
    }, [data?.run?.state, load]);

    const items: Item[] = data?.items || [];
    const rows = useMemo(() => items.map((it, i) => ({ ...it, i })).filter((it) => show.has(it.verdict)), [items, show]);

    const start = async () => {
        setBusy(true); setMsg('');
        try { await schemaApi.directionAuditStart(kbId); await load(); setMsg('검증을 시작했습니다 (트리플 100여 개 기준 1~2분).'); }
        catch (e: any) { setMsg(e?.response?.data?.detail || '시작하지 못했습니다.'); }
        finally { setBusy(false); }
    };

    const apply = async (action: 'flip' | 'delete') => {
        const picked = items.filter((_, i) => sel.has(i));
        if (!picked.length) return;
        const what = action === 'flip' ? '주어·목적어를 뒤집습니다' : '삭제합니다';
        if (!window.confirm(`선택한 트리플 ${picked.length}개를 ${what}. 규칙 + 리플레이로 반영되고, 규칙 목록에서 되돌릴 수 있습니다. 진행할까요?`)) return;
        setBusy(true); setMsg('');
        try {
            const r = await schemaApi.editTriples(kbId, { action, triples: picked.map(({ subject, predicate, object }) => ({ subject, predicate, object })) });
            const m = `${r.data.edited}개 ${action === 'flip' ? '뒤집기' : '삭제'} 반영 (리플레이 ${r.data.replayed}건)`;
            setMsg(m); onChanged(m); setSel(new Set());
        } catch (e: any) { setMsg(e?.response?.data?.detail?.join?.(' ') || e?.response?.data?.detail || '반영하지 못했습니다.'); }
        finally { setBusy(false); }
    };

    const toggle = (i: number) => { const n = new Set(sel); if (n.has(i)) n.delete(i); else n.add(i); setSel(n); };

    return (
        <div className="card" style={{ padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                <h4 style={{ margin: 0 }}>관계 방향 검증</h4>
                <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                    {data?.run?.state === 'running' ? '검증 중…' : data?.at ? `마지막 검증 ${String(data.at).slice(0, 16)} · ${data.model} · 트리플 ${items.length}개` : '아직 검증하지 않음'}
                </span>
                <button className="btn btn-secondary" style={{ ...btn, marginLeft: 'auto' }} disabled={busy || data?.run?.state === 'running'} onClick={start}>
                    <Play size={13} /> 검증 실행</button>
            </div>
            <div style={{ fontSize: '0.75rem', color: '#64748b', lineHeight: 1.5 }}>
                인물→인물, 이론→이론처럼 같은 클래스끼리 잇는 관계는 클래스 검사로 방향 오류를 찾을 수 없습니다.
                트리플마다 원문 문장을 관계 정의와 대조해 <b>맞음 / 방향 반대 / 관계 아님 / 판단 불가</b>로 판정합니다. 판정은 제안일 뿐이니 원문을 보고 고르세요.
            </div>
            {data?.summary && (
                <div style={{ fontSize: '0.75rem' }}>
                    {Object.entries(data.summary).map(([p, c]: any) => (
                        <span key={p} style={{ marginRight: '0.8rem' }}><b>{p}</b> {Object.entries(c).map(([v, n]: any) => `${VERDICT[v]?.label || v} ${n}`).join(' · ')}</span>
                    ))}
                </div>
            )}
            <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
                {Object.entries(VERDICT).map(([k, v]) => (
                    <label key={k} style={{ fontSize: '0.75rem', display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}>
                        <input type="checkbox" checked={show.has(k)} onChange={() => { const n = new Set(show); if (n.has(k)) n.delete(k); else n.add(k); setShow(n); }} />
                        <span style={{ color: v.color }}>{v.label}</span>
                    </label>
                ))}
                <button className="btn btn-secondary" style={{ ...btn, marginLeft: 'auto' }} disabled={busy || !sel.size} onClick={() => apply('flip')}><ArrowLeftRight size={13} /> 선택 방향 뒤집기</button>
                <button className="btn btn-secondary" style={btn} disabled={busy || !sel.size} onClick={() => apply('delete')}><Trash2 size={13} /> 선택 삭제</button>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr style={{ textAlign: 'left', color: '#64748b', fontSize: '0.75rem' }}>
                    <th style={{ ...cell, width: '3%' }}><input type="checkbox" checked={rows.length > 0 && rows.every((r) => sel.has(r.i))}
                        onChange={(e) => { const n = new Set(sel); rows.forEach((r) => (e.target.checked ? n.add(r.i) : n.delete(r.i))); setSel(n); }} /></th>
                    <th style={{ ...cell, width: '30%' }}>트리플</th><th style={{ ...cell, width: '9%' }}>판정</th><th style={cell}>근거 (원문)</th>
                </tr></thead>
                <tbody>
                    {rows.map((r) => (
                        <tr key={r.i}>
                            <td style={cell}><input type="checkbox" checked={sel.has(r.i)} onChange={() => toggle(r.i)} /></td>
                            <td style={cell}><b>{r.subject}</b> —{r.predicate}→ <b>{r.object}</b>{r.doc && <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>{r.doc}</div>}</td>
                            <td style={{ ...cell, color: VERDICT[r.verdict]?.color }}>{VERDICT[r.verdict]?.label || r.verdict}</td>
                            <td style={cell}>
                                <div>{r.reason}</div>
                                {r.evidence?.length > 0 && <div style={{ fontSize: '0.72rem', color: '#64748b', marginTop: '0.15rem' }}>“{r.evidence.join(' / ')}”</div>}
                            </td>
                        </tr>
                    ))}
                    {rows.length === 0 && <tr><td style={cell} colSpan={4}>{items.length ? '선택한 판정에 해당하는 트리플이 없습니다.' : '검증 결과가 없습니다 — "검증 실행"을 누르세요.'}</td></tr>}
                </tbody>
            </table>
            {msg && <div style={{ fontSize: '0.78rem', color: '#0f766e' }}>{msg}</div>}
        </div>
    );
}
