import React, { useEffect, useMemo, useState } from 'react';
import { X as XIcon } from 'lucide-react';
import { kbApi, schemaApi } from '../services/api';

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

// 편집 동작 (텍스트 KB) — 그래프를 직접 고치지 않고 규칙으로 남겨 리플레이·재추출 뒤에도 유지 (docs/guide-schema-editor.md §2.7)
// - 위반: 다른 관계로 이동 / 새 관계를 만들어 이동 / 삭제
// - 멤버 누락: range 멤버로 지정 / 새 클래스를 만들어 멤버로 / 삭제
type Panel = null | 'move' | 'newclass' | 'delete';

export default function PropertyTriplesModal({ kbId, property, onClose, onChanged, properties = [], classes = [], dirty = false }: {
    kbId: string; property: string; onClose: () => void; onChanged?: (msg: string) => void;
    properties?: { name: string; domain?: string; range?: string }[]; classes?: string[];
    dirty?: boolean;   // 편집기에 저장 안 한 변경이 있음 — 편집 동작 뒤 다시 불러오면 사라지므로 막는다
}) {
    const [data, setData] = useState<any>(null);
    const [error, setError] = useState('');
    const [filter, setFilter] = useState<string>('all');
    const [q, setQ] = useState('');
    const [sel, setSel] = useState<Set<string>>(new Set());     // 선택한 트리플 키 (주어|관계|목적어)
    const [busy, setBusy] = useState(false);
    const [panel, setPanel] = useState<Panel>(null);
    const [moveTo, setMoveTo] = useState('');                     // 기존 관계 이름 또는 '__new__'
    const [newRel, setNewRel] = useState({ name: '', domain: '', range: '', description: '' });
    const [newCls, setNewCls] = useState({ name: '', description: '' });
    // 근거 청크 펼치기: 행 번호 → 청크 내용 (청크 id 기준 캐시)
    const [openRow, setOpenRow] = useState<number | null>(null);
    const [chunks, setChunks] = useState<Record<string, { content?: string; error?: string }>>({});

    const toggleChunk = async (i: number, source?: string | null) => {
        if (!source) return;
        if (openRow === i) { setOpenRow(null); return; }
        setOpenRow(i);
        if (chunks[source]) return;
        try {
            const r = await kbApi.getChunk(kbId, source);
            setChunks((c) => ({ ...c, [source]: { content: r.data?.content || '' } }));
        } catch (e: any) {
            setChunks((c) => ({ ...c, [source]: { error: e?.response?.status === 404 ? '청크를 찾지 못했습니다 (재처리 등으로 id 가 바뀌었을 수 있음)' : '청크를 불러오지 못했습니다' } }));
        }
    };

    const load = () => schemaApi.propertyTriples(kbId, property).then((r) => setData(r.data))
        .catch((e) => setError(e?.response?.data?.detail?.errors?.join(' / ') || e.message));
    useEffect(() => { load(); }, [kbId, property]);   // eslint-disable-line react-hooks/exhaustive-deps

    const rows: Row[] = useMemo(() => (data?.triples || []).filter((r: Row) =>
        (filter === 'all' || r.status === filter) &&
        (!q || `${r.subject} ${r.object} ${r.doc}`.toLowerCase().includes(q.toLowerCase()))), [data, filter, q]);
    const keyOf = (r: Row) => `${r.subject}|${r.predicate || property}|${r.object}`;
    const selected: Row[] = (data?.triples || []).filter((r: Row) => sel.has(keyOf(r)));
    const selGapObjects = Array.from(new Set(selected.filter((r) => r.status === 'gap').map((r) => r.object)));
    const editable = data && data.mode !== 'structured';
    const errMsg = (e: any) => e?.response?.data?.detail?.errors?.join(' / ') || e?.response?.data?.detail || e.message;

    const run = async (label: string, fn: () => Promise<any>, msg: (d: any) => string) => {
        setBusy(true);
        setError('');
        try {
            const r = await fn();
            onChanged?.(msg(r.data));
            setSel(new Set());
            setPanel(null);
            await load();
        } catch (e: any) {
            setError(`${label} 실패: ${errMsg(e)}`);
        } finally { setBusy(false); }
    };
    const tri = () => selected.map((r) => ({ subject: r.subject, predicate: r.predicate || property, object: r.object }));

    const assign = () => run('멤버 지정', () => schemaApi.assignMembers(kbId, data.range, selGapObjects),
        (d) => `${data.range} 멤버 지정 ${d.added + d.moved}건 (리플레이 완료)`);
    const doMove = () => moveTo === '__new__'
        ? run('새 관계로 이동', () => schemaApi.editTriples(kbId, { action: 'move', triples: tri(), new_property: newRel }),
            (d) => `새 관계 ${d.target_property} 를 만들고 트리플 ${d.edited}건 이동 (리플레이 완료)`)
        : run('이동', () => schemaApi.editTriples(kbId, { action: 'move', triples: tri(), target_property: moveTo }),
            (d) => `트리플 ${d.edited}건을 ${d.target_property} 로 이동 (리플레이 완료)`);
    const doDelete = () => run('삭제', () => schemaApi.editTriples(kbId, { action: 'delete', triples: tri() }),
        (d) => `트리플 ${d.edited}건 삭제 (규칙으로 남아 리플레이 뒤에도 유지 · 스키마 정렬 규칙 목록에서 복구 가능)`);
    const doNewClass = () => run('클래스 생성', () => schemaApi.createClass(kbId, newCls.name, newCls.description, selGapObjects),
        (d) => `클래스 ${d.class} 를 만들고 멤버 ${d.added + d.moved}개 지정 (리플레이 완료)`);

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
                    </div>
                    {editable && dirty && (
                        <div style={{ fontSize: '0.78rem', color: '#92400e', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '6px', padding: '0.35rem 0.6rem', marginBottom: '0.5rem' }}>
                            스키마 표에 저장하지 않은 편집이 있습니다. 트리플 편집은 스키마를 다시 불러오므로 그 편집이 사라집니다 — 먼저 저장한 뒤 사용하세요.
                        </div>
                    )}
                    {editable && !dirty && selected.length > 0 && (
                        <div style={{ border: '1px solid #cbd5e1', borderRadius: '6px', padding: '0.4rem 0.6rem', marginBottom: '0.5rem', fontSize: '0.78rem', background: '#f8fafc' }}>
                            <div style={{ display: 'flex', gap: '0.35rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                <b>선택 {selected.length}개</b>
                                <span style={{ color: '#64748b' }}>
                                    ({['violation', 'gap', 'ok', 'value', '-'].filter((k) => selected.some((r) => r.status === k))
                                        .map((k) => `${LABEL[k].text} ${selected.filter((r) => r.status === k).length}`).join(', ')})
                                </span>
                                <button className={`btn ${panel === 'move' ? 'btn-primary' : 'btn-secondary'}`} style={sbtn} disabled={busy}
                                    title="주어·목적어는 그대로 두고 관계만 바꿉니다" onClick={() => setPanel(panel === 'move' ? null : 'move')}>다른 관계로 이동…</button>
                                {data.range && selGapObjects.length > 0 && (
                                    <button className="btn btn-secondary" style={sbtn} disabled={busy} onClick={assign}
                                        title="선택한 '멤버 누락' 목적어를 range 클래스 멤버로 (class 규칙 + 리플레이)">
                                        목적어 {selGapObjects.length}개를 {data.range} 멤버로
                                    </button>
                                )}
                                {selGapObjects.length > 0 && (
                                    <button className={`btn ${panel === 'newclass' ? 'btn-primary' : 'btn-secondary'}`} style={sbtn} disabled={busy}
                                        onClick={() => setPanel(panel === 'newclass' ? null : 'newclass')}>새 클래스 만들어 멤버로…</button>
                                )}
                                <button className={`btn ${panel === 'delete' ? 'btn-primary' : 'btn-secondary'}`} style={{ ...sbtn, color: panel === 'delete' ? undefined : '#b91c1c' }}
                                    disabled={busy} onClick={() => setPanel(panel === 'delete' ? null : 'delete')}>트리플 삭제…</button>
                                <button className="btn btn-secondary" style={{ ...sbtn, marginLeft: 'auto' }} onClick={() => { setSel(new Set()); setPanel(null); }}>선택 해제</button>
                            </div>
                            {panel === 'move' && (
                                <div style={{ marginTop: '0.4rem', display: 'flex', gap: '0.35rem', flexWrap: 'wrap', alignItems: 'center' }}>
                                    <span>이동할 관계</span>
                                    <select value={moveTo} onChange={(e) => setMoveTo(e.target.value)} style={inp}>
                                        <option value="">선택…</option>
                                        <option value="__new__">+ 새 관계 만들기</option>
                                        {properties.filter((p) => p.name !== property).map((p) => (
                                            <option key={p.name} value={p.name}>{p.name}{p.domain || p.range ? `  (${p.domain || '?'} → ${p.range || '값'})` : ''}</option>
                                        ))}
                                    </select>
                                    {moveTo === '__new__' && <>
                                        <input style={inp} placeholder="관계 이름" value={newRel.name} onChange={(e) => setNewRel({ ...newRel, name: e.target.value })} />
                                        <select style={inp} value={newRel.domain} onChange={(e) => setNewRel({ ...newRel, domain: e.target.value })}>
                                            <option value="">domain…</option>{classes.map((c) => <option key={c} value={c}>{c}</option>)}
                                        </select>
                                        <span>→</span>
                                        <select style={inp} value={newRel.range} onChange={(e) => setNewRel({ ...newRel, range: e.target.value })}>
                                            <option value="">range (값)</option>{classes.map((c) => <option key={c} value={c}>{c}</option>)}
                                        </select>
                                        <input style={{ ...inp, minWidth: '16rem' }} placeholder="정의: Domain | 이름 | Range — 한 문장" value={newRel.description}
                                            onChange={(e) => setNewRel({ ...newRel, description: e.target.value })} />
                                    </>}
                                    <button className="btn btn-primary" style={sbtn} disabled={busy || !moveTo || (moveTo === '__new__' && !newRel.name.trim())} onClick={doMove}>
                                        {selected.length}개 이동
                                    </button>
                                </div>
                            )}
                            {panel === 'newclass' && (
                                <div style={{ marginTop: '0.4rem', display: 'flex', gap: '0.35rem', flexWrap: 'wrap', alignItems: 'center' }}>
                                    <input style={inp} placeholder="클래스 이름 (PascalCase)" value={newCls.name} onChange={(e) => setNewCls({ ...newCls, name: e.target.value })} />
                                    <input style={{ ...inp, minWidth: '16rem' }} placeholder="설명 (한 문장)" value={newCls.description} onChange={(e) => setNewCls({ ...newCls, description: e.target.value })} />
                                    <span style={{ color: '#64748b' }}>멤버: {selGapObjects.join(', ')}</span>
                                    <button className="btn btn-primary" style={sbtn} disabled={busy || !newCls.name.trim()} onClick={doNewClass}>만들고 멤버로 지정</button>
                                    <span style={{ color: '#94a3b8', width: '100%' }}>이 관계의 range 는 그대로입니다 — 이 목적어들이 다른 종류라면 이동도 함께 검토하세요.</span>
                                </div>
                            )}
                            {panel === 'delete' && (
                                <div style={{ marginTop: '0.4rem', display: 'flex', gap: '0.35rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                    <span>선택한 트리플 {selected.length}개를 그래프에서 뺍니다. 삭제는 규칙으로 남아 리플레이·재추출 뒤에도 유지되고,
                                        Documents → 스키마 정렬의 규칙 목록에서 지우면 복구됩니다.</span>
                                    <button className="btn btn-primary" style={{ ...sbtn, background: '#b91c1c', borderColor: '#b91c1c' }} disabled={busy} onClick={doDelete}>
                                        {selected.length}개 삭제
                                    </button>
                                </div>
                            )}
                        </div>
                    )}
                    <div style={{ overflowY: 'auto', flex: 1 }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                            <thead><tr style={{ textAlign: 'left', color: '#64748b', position: 'sticky', top: 0, background: '#fff' }}>
                                {editable && <th style={{ ...cell, width: '3%' }}>
                                    <input type="checkbox" title="보이는 행 전체 선택"
                                        checked={rows.length > 0 && rows.every((r) => sel.has(keyOf(r)))}
                                        onChange={(e) => setSel((s) => { const n = new Set(s); rows.forEach((r) => e.target.checked ? n.add(keyOf(r)) : n.delete(keyOf(r))); return n; })} />
                                </th>}
                                <th style={{ ...cell, width: '8%' }}>상태</th>
                                <th style={{ ...cell, width: '28%' }}>주어 (클래스)</th>
                                <th style={{ ...cell, width: '34%' }}>목적어 (클래스)</th>
                                <th style={cell}>문서 · 근거 청크</th>
                            </tr></thead>
                            <tbody>
                                {rows.map((r, i) => {
                                    const L = LABEL[r.status] || LABEL['-'];
                                    const ck = r.source ? chunks[r.source] : undefined;
                                    return (
                                        <React.Fragment key={i}>
                                        <tr style={openRow === i ? { background: '#f8fafc' } : sel.has(keyOf(r)) ? { background: '#eff6ff' } : undefined}>
                                            {editable && <td style={cell}>
                                                <input type="checkbox" checked={sel.has(keyOf(r))}
                                                    onChange={() => setSel((s) => { const n = new Set(s); n.has(keyOf(r)) ? n.delete(keyOf(r)) : n.add(keyOf(r)); return n; })} />
                                            </td>}
                                            <td style={cell}>
                                                <span title={L.help} style={{ color: L.color, background: L.bg, borderRadius: '10px', padding: '0.05rem 0.4rem', whiteSpace: 'nowrap' }}>{L.text}</span>
                                            </td>
                                            <td style={cell}>
                                                {r.subject}
                                                {r.subject_class && <span style={{ color: r.subject_mismatch ? '#b91c1c' : '#94a3b8' }}
                                                    title={r.subject_mismatch ? `domain(${data.domain})과 다른 클래스 — 방향이 뒤집혔을 수 있음` : ''}> ({r.subject_class})</span>}
                                            </td>
                                            <td style={cell}>
                                                {r.object}
                                                {r.object_class && <span style={{ color: '#94a3b8' }}> ({r.object_class})</span>}
                                                {r.predicate && r.predicate !== property && <div style={{ fontSize: '0.68rem', color: '#94a3b8' }}>별칭 관계: {r.predicate}</div>}
                                            </td>
                                            <td style={{ ...cell, color: '#64748b', cursor: r.source ? 'pointer' : 'default' }}
                                                title={r.source ? '눌러서 근거 청크 보기' : '근거 청크 정보 없음'}
                                                onClick={() => toggleChunk(i, r.source)}>
                                                <span style={{ color: r.source ? '#2563eb' : undefined, textDecoration: r.source ? 'underline' : undefined }}>
                                                    {openRow === i ? '▾ ' : r.source ? '▸ ' : ''}{r.doc}
                                                </span>
                                                {r.source && <div style={{ fontSize: '0.66rem', color: '#94a3b8', wordBreak: 'break-all' }}>{r.source}</div>}
                                            </td>
                                        </tr>
                                        {openRow === i && (
                                            <tr>
                                                <td colSpan={editable ? 5 : 4} style={{ ...cell, background: '#f8fafc' }}>
                                                    {!ck && <span style={{ color: '#64748b' }}>불러오는 중…</span>}
                                                    {ck?.error && <span style={{ color: '#b91c1c' }}>{ck.error}</span>}
                                                    {ck?.content !== undefined && (
                                                        <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.55, maxHeight: '260px', overflowY: 'auto', fontSize: '0.78rem' }}>
                                                            {highlight(ck.content, [r.subject, r.object])}
                                                        </div>
                                                    )}
                                                </td>
                                            </tr>
                                        )}
                                        </React.Fragment>
                                    );
                                })}
                                {rows.length === 0 && <tr><td style={cell} colSpan={editable ? 5 : 4}>해당하는 트리플이 없습니다.</td></tr>}
                            </tbody>
                        </table>
                    </div>
                </>}
            </div>
        </div>
    );
}


const sbtn: React.CSSProperties = { padding: '0.15rem 0.5rem', fontSize: '0.75rem' };
const inp: React.CSSProperties = { fontSize: '0.75rem', padding: '0.15rem 0.3rem', border: '1px solid #cbd5e1', borderRadius: '4px' };

// 청크 본문에서 주어·목적어를 강조 (대소문자 무시, 2글자 이상만)
function highlight(text: string, terms: string[]): React.ReactNode {
    const ts = Array.from(new Set(terms.filter((t) => t && t.length >= 2))).sort((a, b) => b.length - a.length);
    if (!ts.length) return text;
    const esc = ts.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const re = new RegExp(`(${esc.join('|')})`, 'gi');
    return text.split(re).map((part, i) =>
        ts.some((t) => t.toLowerCase() === part.toLowerCase())
            ? <mark key={i} style={{ background: '#fde68a', padding: 0 }}>{part}</mark>
            : <React.Fragment key={i}>{part}</React.Fragment>);
}
