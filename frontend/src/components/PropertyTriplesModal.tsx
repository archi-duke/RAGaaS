import React, { useEffect, useMemo, useState } from 'react';
import { X as XIcon } from 'lucide-react';
import { schemaApi } from '../services/api';

// 속성 하나의 실제 트리플 목록 (스키마 편집기: 트리플 수 클릭) — docs/guide-schema-editor.md §2.2
// 상태: ok(목적어가 range 멤버) / gap(멤버 누락) / violation(다른 클래스) / value(서술·수치) / -(range 없음)

interface Row {
    subject: string; object: string; subject_class?: string; object_class?: string; status: string;
    subject_mismatch?: boolean; predicate?: string; doc?: string; source?: string | null;
}
const LABEL: Record<string, { text: string; color: string; bg: string; help: string }> = {
    ok: { text: '일치', color: '#15803d', bg: '#dcfce7', help: '목적어가 range 클래스 멤버' },
    gap: { text: '멤버 누락', color: '#b45309', bg: '#fef3c7', help: '목적어에 클래스가 없음 — 맞으면 range 멤버로 지정' },
    violation: { text: 'range 위반', color: '#b91c1c', bg: '#fee2e2', help: '목적어가 다른 클래스 멤버 — 잘못 뽑혔거나 range 가 틀림' },
    value: { text: '값', color: '#475569', bg: '#f1f5f9', help: '문장·수치·등급 — 일치율 판정에서 제외' },
    '-': { text: 'range 없음', color: '#64748b', bg: '#f8fafc', help: '이 속성에 range 가 없어 판정하지 않음' },
};

export default function PropertyTriplesModal({ kbId, property, onClose, onChanged }: {
    kbId: string; property: string; onClose: () => void; onChanged?: (msg: string) => void;
}) {
    const [data, setData] = useState<any>(null);
    const [error, setError] = useState('');
    const [filter, setFilter] = useState<string>('all');
    const [q, setQ] = useState('');
    const [sel, setSel] = useState<Set<string>>(new Set());
    const [busy, setBusy] = useState(false);

    const load = () => schemaApi.propertyTriples(kbId, property).then((r) => setData(r.data))
        .catch((e) => setError(e?.response?.data?.detail?.errors?.join(' / ') || e.message));
    useEffect(() => { load(); }, [kbId, property]);   // eslint-disable-line react-hooks/exhaustive-deps

    const rows: Row[] = useMemo(() => (data?.triples || []).filter((r: Row) =>
        (filter === 'all' || r.status === filter) &&
        (!q || `${r.subject} ${r.object} ${r.doc}`.toLowerCase().includes(q.toLowerCase()))), [data, filter, q]);
    const gapNames = Array.from(sel);

    const assign = async () => {
        if (!data?.range || !gapNames.length) return;
        setBusy(true);
        try {
            const r = await schemaApi.assignMembers(kbId, data.range, gapNames);
            onChanged?.(`${data.range} 멤버 지정 ${r.data.added + r.data.moved}건 (리플레이 완료)`);
            setSel(new Set());
            await load();
        } catch (e: any) {
            setError('멤버 지정 실패: ' + (e?.response?.data?.detail?.errors?.join(' / ') || e.message));
        } finally { setBusy(false); }
    };

    const cell: React.CSSProperties = { padding: '0.25rem 0.4rem', borderBottom: '1px solid #e2e8f0', verticalAlign: 'top' };
    return (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
            <div className="card" style={{ width: 'min(1000px, 95vw)', maxHeight: '86vh', display: 'flex', flexDirection: 'column', padding: '1rem' }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                    <h3 style={{ margin: 0 }}>{property}</h3>
                    {data && <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
                        {data.domain || '?'} → {data.range || '(값)'} · 트리플 {data.total}{data.truncated ? '+ (일부만 표시)' : ''}
                    </span>}
                    <button className="btn btn-secondary" style={{ marginLeft: 'auto', padding: '0.2rem 0.4rem' }} onClick={onClose}><XIcon size={14} /></button>
                </div>
                {error && <div style={{ color: '#b91c1c', fontSize: '0.85rem' }}>{error}</div>}
                {!data && !error && <div>불러오는 중…</div>}
                {data && <>
                    <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap', alignItems: 'center', marginBottom: '0.5rem', fontSize: '0.78rem' }}>
                        {['all', 'ok', 'gap', 'violation', 'value', '-'].filter((k) => k === 'all' || data.counts?.[k]).map((k) => (
                            <button key={k} className={`btn ${filter === k ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '0.15rem 0.5rem', fontSize: '0.75rem' }}
                                title={k === 'all' ? '' : LABEL[k].help} onClick={() => setFilter(k)}>
                                {k === 'all' ? `전체 ${data.total}` : `${LABEL[k].text} ${data.counts[k]}`}
                            </button>
                        ))}
                        <input placeholder="주어·목적어·문서 검색" value={q} onChange={(e) => setQ(e.target.value)}
                            style={{ fontSize: '0.78rem', padding: '0.15rem 0.4rem', border: '1px solid #cbd5e1', borderRadius: '4px', width: '200px' }} />
                        {data.range && data.mode !== 'structured' && (
                            <button className="btn btn-primary" style={{ marginLeft: 'auto', padding: '0.2rem 0.55rem', fontSize: '0.75rem' }}
                                disabled={busy || !gapNames.length} onClick={assign}
                                title="체크한 '멤버 누락' 목적어를 range 클래스 멤버로 지정합니다 (class 규칙 + 리플레이)">
                                선택 {gapNames.length}개를 {data.range} 멤버로
                            </button>
                        )}
                    </div>
                    <div style={{ overflowY: 'auto', flex: 1 }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                            <thead><tr style={{ textAlign: 'left', color: '#64748b', position: 'sticky', top: 0, background: '#fff' }}>
                                <th style={{ ...cell, width: '8%' }}>상태</th>
                                <th style={{ ...cell, width: '28%' }}>주어 (클래스)</th>
                                <th style={{ ...cell, width: '34%' }}>목적어 (클래스)</th>
                                <th style={cell}>문서 · 근거 청크</th>
                            </tr></thead>
                            <tbody>
                                {rows.map((r, i) => {
                                    const L = LABEL[r.status] || LABEL['-'];
                                    return (
                                        <tr key={i}>
                                            <td style={cell}>
                                                <span title={L.help} style={{ color: L.color, background: L.bg, borderRadius: '10px', padding: '0.05rem 0.4rem', whiteSpace: 'nowrap' }}>{L.text}</span>
                                            </td>
                                            <td style={cell}>
                                                {r.subject}
                                                {r.subject_class && <span style={{ color: r.subject_mismatch ? '#b91c1c' : '#94a3b8' }}
                                                    title={r.subject_mismatch ? `domain(${data.domain})과 다른 클래스 — 방향이 뒤집혔을 수 있음` : ''}> ({r.subject_class})</span>}
                                            </td>
                                            <td style={cell}>
                                                {r.status === 'gap' && data.mode !== 'structured' && (
                                                    <input type="checkbox" style={{ marginRight: 4 }} checked={sel.has(r.object)}
                                                        onChange={() => setSel((s) => { const n = new Set(s); n.has(r.object) ? n.delete(r.object) : n.add(r.object); return n; })} />
                                                )}
                                                {r.object}
                                                {r.object_class && <span style={{ color: '#94a3b8' }}> ({r.object_class})</span>}
                                                {r.predicate && r.predicate !== property && <div style={{ fontSize: '0.68rem', color: '#94a3b8' }}>별칭 관계: {r.predicate}</div>}
                                            </td>
                                            <td style={{ ...cell, color: '#64748b' }}>
                                                {r.doc}
                                                {r.source && <div style={{ fontSize: '0.66rem', color: '#94a3b8', wordBreak: 'break-all' }}>{r.source}</div>}
                                            </td>
                                        </tr>
                                    );
                                })}
                                {rows.length === 0 && <tr><td style={cell} colSpan={4}>해당하는 트리플이 없습니다.</td></tr>}
                            </tbody>
                        </table>
                    </div>
                </>}
            </div>
        </div>
    );
}
