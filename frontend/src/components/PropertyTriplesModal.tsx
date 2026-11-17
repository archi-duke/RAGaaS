import React, { useEffect, useMemo, useState } from 'react';
import { X as XIcon } from 'lucide-react';
import { kbApi, schemaApi } from '../services/api';

// 속성 하나의 실제 트리플 목록 (스키마 편집기: 트리플 수 클릭) — docs/guides/schema-editor.md §2.2
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

// 편집 동작 (텍스트 KB) — 그래프를 직접 고치지 않고 규칙으로 남겨 리플레이·재추출 뒤에도 유지 (docs/guides/schema-editor.md §2.7)
// - 위반: 다른 관계로 이동 / 새 관계를 만들어 이동 / 삭제
// - 멤버 누락: range 멤버로 지정 / 새 클래스를 만들어 멤버로 / 삭제
type Panel = null | 'move' | 'newclass' | 'delete';

export default function PropertyTriplesModal({ kbId, property, onClose, onChanged, properties = [], classes = [], dirty = false, getSpec, onRecommend, mismatch }: {
    kbId: string; property: string; onClose: () => void; onChanged?: (msg: string) => void;
    properties?: { name: string; domain?: string; range?: string }[]; classes?: string[];
    dirty?: boolean;   // 편집기에 저장 안 한 변경이 있음 — 편집 동작 뒤 다시 불러오면 사라지므로 막는다
    getSpec?: () => { classes: any[]; properties: any[] };   // 편집 중인(저장 전) 스키마 — 재추출 테스트용
    onRecommend?: (triples: any[]) => void;                  // 선택 트리플로 AI 추천
    // 모든 관계의 불일치 모음 (데이터 검증 카드에서 클릭) — 있으면 property 대신 이 목록을 연다
    mismatch?: { status: 'violation' | 'gap' | 'all'; className?: string };
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
    const [preview, setPreview] = useState<any>(null);            // 재추출 테스트 결과
    const [previewing, setPreviewing] = useState(false);
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

    const load = () => (mismatch ? schemaApi.mismatches(kbId, mismatch.status, mismatch.className)
        : schemaApi.propertyTriples(kbId, property)).then((r) => setData(r.data))
        .catch((e) => setError(e?.response?.data?.detail?.errors?.join(' / ') || e.message));
    useEffect(() => { load(); }, [kbId, property]);   // eslint-disable-line react-hooks/exhaustive-deps

    const rows: Row[] = useMemo(() => (data?.triples || []).filter((r: Row) =>
        (filter === 'all' || r.status === filter) &&
        (!q || `${r.subject} ${r.object} ${r.doc} ${(r as any).property || ''}`.toLowerCase().includes(q.toLowerCase()))), [data, filter, q]);
    const predOf = (r: Row) => r.predicate || (r as any).property || property;
    const keyOf = (r: Row) => `${r.subject}|${predOf(r)}|${r.object}`;
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
    const tri = () => selected.map((r) => ({ subject: r.subject, predicate: predOf(r), object: r.object }));

    // 멤버 지정: 행마다 range 가 다를 수 있다 (불일치 모음) → range 별로 나눠 지정
    const gapRange = (r: Row) => (r as any).range || data.range;
    const assignRanges = Array.from(new Set(selected.filter((r) => r.status === 'gap').map(gapRange))).filter(Boolean) as string[];
    const assign = () => run('멤버 지정', async () => {
        let added = 0;
        for (const cls of assignRanges) {
            const ents = Array.from(new Set(selected.filter((r) => r.status === 'gap' && gapRange(r) === cls).map((r) => r.object)));
            const r = await schemaApi.assignMembers(kbId, cls, ents);
            added += r.data.added + r.data.moved;
        }
        return { data: { added } };
    }, (d) => `${assignRanges.join(', ')} 멤버 지정 ${d.added}건 (리플레이 완료)`);
    const doMove = () => moveTo === '__new__'
        ? run('새 관계로 이동', () => schemaApi.editTriples(kbId, { action: 'move', triples: tri(), new_property: newRel }),
            (d) => `새 관계 ${d.target_property} 를 만들고 트리플 ${d.edited}건 이동 (리플레이 완료)`)
        : run('이동', () => schemaApi.editTriples(kbId, { action: 'move', triples: tri(), target_property: moveTo }),
            (d) => `트리플 ${d.edited}건을 ${d.target_property} 로 이동 (리플레이 완료)`);
    const doDelete = () => run('삭제', () => schemaApi.editTriples(kbId, { action: 'delete', triples: tri() }),
        (d) => `트리플 ${d.edited}건 삭제 (규칙으로 남아 리플레이 뒤에도 유지 · 스키마 정렬 규칙 목록에서 복구 가능)`);
    const chunkCount = new Set(selected.filter((r) => r.source).map((r) => r.source)).size;
    const doPreview = async () => {
        if (!getSpec) return;
        setPreviewing(true);
        setError('');
        setPreview(null);
        try {
            const spec = getSpec();
            const r = await schemaApi.reextractPreview(kbId, { ...spec, triples: selected.map((x) => ({ ...x, predicate: predOf(x) })) });
            setPreview(r.data);
        } catch (e: any) {
            setError('재추출 테스트 실패: ' + errMsg(e));
        } finally { setPreviewing(false); }
    };
    const doNewClass = () => run('클래스 생성', () => schemaApi.createClass(kbId, newCls.name, newCls.description, selGapObjects),
        (d) => `클래스 ${d.class} 를 만들고 멤버 ${d.added + d.moved}개 지정 (리플레이 완료)`);

    const cell: React.CSSProperties = { padding: '0.25rem 0.4rem', borderBottom: '1px solid #e2e8f0', verticalAlign: 'top' };
    return (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)', zIndex: 2000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
            <div className="card" style={{ width: 'min(1000px, 95vw)', maxHeight: '86vh', display: 'flex', flexDirection: 'column', padding: '1rem' }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                    <h3 style={{ margin: 0 }}>{mismatch
                        ? (mismatch.status === 'violation' ? 'range 위반 — 모든 관계' : `멤버 누락${mismatch.className ? ` — range ${mismatch.className}` : ''}`)
                        : property}</h3>
                    {data && <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
                        {mismatch ? `트리플 ${data.total} · 관계 ${Object.keys(data.by_property || {}).length}개`
                            : `${data.domain || '?'} → ${data.range || '(값)'} · 트리플 ${data.total}${data.truncated ? '+ (일부만 표시)' : ''}`}
                    </span>}
                    <button className="btn btn-secondary" style={{ marginLeft: 'auto', padding: '0.2rem 0.4rem' }} onClick={onClose}><XIcon size={14} /></button>
                </div>
                {error && <div style={{ color: '#b91c1c', fontSize: '0.85rem' }}>{error}</div>}
                {!data && !error && <div>불러오는 중…</div>}
                {mismatch && data && (
                    <div style={{ fontSize: '0.76rem', color: '#475569', background: '#f8fafc', borderRadius: '6px', padding: '0.35rem 0.6rem', marginBottom: '0.4rem' }}>
                        {mismatch.status === 'violation'
                            ? <>목적어가 그 관계의 range 가 아닌 <b>다른 클래스</b>로 이미 분류된 트리플입니다. 관계를 잘못 붙였으면 <b>다른 관계로 이동</b>,
                                잘못 뽑힌 사실이면 <b>삭제</b>, 목적어 분류가 틀렸으면 그 엔티티의 클래스를 바꾸세요 (멤버 지정은 클래스를 옮깁니다).</>
                            : <>목적어가 <b>아무 클래스에도 지정되지 않은</b> 트리플입니다. 맞는 종류면 <b>range 멤버로 지정</b>, 다른 종류면 <b>새 클래스</b>,
                                '없음'·문장 조각 같은 잡음이면 <b>삭제</b>하세요.</>}
                        {' '}관계별: {Object.entries(data.by_property || {}).map(([k, v]) => `${k} ${v}`).join(', ')}
                    </div>
                )}
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
                            스키마 표에 저장하지 않은 편집이 있습니다. <b>재추출 테스트</b>는 그 편집으로 바로 해 볼 수 있고, 이동·멤버 지정·삭제는
                            스키마를 다시 불러오므로 먼저 저장한 뒤 사용하세요.
                        </div>
                    )}
                    {editable && selected.length > 0 && (
                        <div style={{ border: '1px solid #cbd5e1', borderRadius: '6px', padding: '0.4rem 0.6rem', marginBottom: '0.5rem', fontSize: '0.78rem', background: '#f8fafc' }}>
                            <div style={{ display: 'flex', gap: '0.35rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                <b>선택 {selected.length}개</b>
                                <span style={{ color: '#64748b' }}>
                                    ({['violation', 'gap', 'ok', 'value', '-'].filter((k) => selected.some((r) => r.status === k))
                                        .map((k) => `${LABEL[k].text} ${selected.filter((r) => r.status === k).length}`).join(', ')})
                                </span>
                                {getSpec && (
                                    <button className="btn btn-primary" style={sbtn} disabled={previewing || busy || chunkCount === 0 || chunkCount > 10}
                                        title={chunkCount > 10 ? '근거 청크가 10개를 넘습니다 — 선택을 줄이세요'
                                            : `편집 중인(저장 전) 스키마로 선택 트리플의 근거 청크 ${chunkCount}개만 다시 추출해 사라지는지 봅니다. 저장하지 않으며 청크당 LLM 1회.`}
                                        onClick={doPreview}>
                                        {previewing ? '재추출 테스트 중…' : `재추출 테스트 (청크 ${chunkCount})`}
                                    </button>
                                )}
                                {onRecommend && (
                                    <button className="btn btn-secondary" style={sbtn} disabled={busy || dirty || selected.length > 14}
                                        title={selected.length > 14 ? '한 번에 14개까지' : '선택한 트리플과 근거 청크를 AI 가 분석해 처리안을 제시합니다'}
                                        onClick={() => onRecommend(selected.map((x) => ({ ...x, predicate: predOf(x) })))}>
                                        AI 추천
                                    </button>
                                )}
                                <button className={`btn ${panel === 'move' ? 'btn-primary' : 'btn-secondary'}`} style={sbtn} disabled={busy || dirty}
                                    title="주어·목적어는 그대로 두고 관계만 바꿉니다" onClick={() => setPanel(panel === 'move' ? null : 'move')}>다른 관계로 이동…</button>
                                {assignRanges.length > 0 && selGapObjects.length > 0 && (
                                    <button className="btn btn-secondary" style={sbtn} disabled={busy || dirty} onClick={assign}
                                        title="선택한 '멤버 누락' 목적어를 그 관계의 range 클래스 멤버로 (class 규칙 + 리플레이)">
                                        목적어 {selGapObjects.length}개를 {assignRanges.join('·')} 멤버로
                                    </button>
                                )}
                                {selGapObjects.length > 0 && (
                                    <button className={`btn ${panel === 'newclass' ? 'btn-primary' : 'btn-secondary'}`} style={sbtn} disabled={busy || dirty}
                                        onClick={() => setPanel(panel === 'newclass' ? null : 'newclass')}>새 클래스 만들어 멤버로…</button>
                                )}
                                <button className={`btn ${panel === 'delete' ? 'btn-primary' : 'btn-secondary'}`} style={{ ...sbtn, color: panel === 'delete' ? undefined : '#b91c1c' }}
                                    disabled={busy || dirty} onClick={() => setPanel(panel === 'delete' ? null : 'delete')}>트리플 삭제…</button>
                                <button className="btn btn-secondary" style={{ ...sbtn, marginLeft: 'auto' }} onClick={() => { setSel(new Set()); setPanel(null); }}>선택 해제</button>
                            </div>
                            {preview && (
                                <div style={{ marginTop: '0.5rem', borderTop: '1px dashed #cbd5e1', paddingTop: '0.4rem' }}>
                                    <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                        <b>재추출 테스트 결과</b>
                                        <span style={{ color: '#15803d' }}>사라짐 {preview.summary.gone}</span>
                                        <span style={{ color: '#2563eb' }}>관계 바뀜 {preview.summary.moved}</span>
                                        <span style={{ color: '#b91c1c' }}>남음 {preview.summary.kept}</span>
                                        <span style={{ color: '#94a3b8' }}>청크 {preview.chunks} · {preview.model} · 저장 안 됨</span>
                                        <button className="btn btn-secondary" style={{ ...sbtn, marginLeft: 'auto' }} onClick={() => setPreview(null)}>닫기</button>
                                    </div>
                                    {(preview.results || []).map((x: any, i: number) => (
                                        <div key={i} style={{ marginTop: '0.2rem' }}>
                                            <span style={{ color: x.result === 'gone' ? '#15803d' : x.result === 'moved' ? '#2563eb' : '#b91c1c', fontWeight: 600 }}>
                                                {x.result === 'gone' ? '사라짐' : x.result === 'moved' ? '관계 바뀜' : '남음'}
                                            </span>{' '}
                                            {x.subject} —{x.predicate}→ {x.object}
                                            {x.new_predicate && <span style={{ color: '#2563eb' }}> ⇒ —{x.new_predicate}→</span>}
                                        </div>
                                    ))}
                                    <details style={{ marginTop: '0.3rem' }}>
                                        <summary style={{ cursor: 'pointer', color: '#475569' }}>근거 청크에서 새로 뽑힌 트리플 보기 (사라진 사실이 다른 관계·표기로 나왔는지 확인)</summary>
                                        {Object.entries(preview.chunk_triples || {}).map(([ch, ts]: [string, any]) => (
                                            <div key={ch} style={{ marginTop: '0.3rem' }}>
                                                <div style={{ color: '#94a3b8', fontSize: '0.7rem' }}>{ch}</div>
                                                {(ts as any[]).map((t, j) => (
                                                    <div key={j} style={{ paddingLeft: '0.6rem', color: t.out_of_schema ? '#94a3b8' : undefined }}>
                                                        · {t.subject} —{t.predicate}→ {t.object}{t.out_of_schema ? ' (스키마 밖)' : ''}
                                                    </div>
                                                ))}
                                            </div>
                                        ))}
                                    </details>
                                    <div style={{ color: '#64748b', marginTop: '0.3rem' }}>
                                        결과가 좋으면 스키마를 <b>저장</b>한 뒤 "스키마 기준 재추출"로 전체에 적용하세요. 남은 것은 정의를 더 고치거나 트리플 편집(이동·삭제)으로 처리합니다.
                                    </div>
                                    {preview.failures?.length > 0 && <div style={{ color: '#b91c1c' }}>일부 실패: {JSON.stringify(preview.failures).slice(0, 200)}</div>}
                                </div>
                            )}
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
                                {mismatch && <th style={{ ...cell, width: '14%' }}>관계 → range</th>}
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
                                            {mismatch && <td style={cell}>
                                                <b>{(r as any).property}</b>
                                                <div style={{ fontSize: '0.68rem', color: '#94a3b8' }}>→ {(r as any).range}</div>
                                            </td>}
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
                                                <td colSpan={(editable ? 5 : 4) + (mismatch ? 1 : 0)} style={{ ...cell, background: '#f8fafc' }}>
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
                                {rows.length === 0 && <tr><td style={cell} colSpan={(editable ? 5 : 4) + (mismatch ? 1 : 0)}>해당하는 트리플이 없습니다.</td></tr>}
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
