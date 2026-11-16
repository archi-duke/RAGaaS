import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Plus, Trash2, RefreshCw, Save, RotateCcw, AlertTriangle, Share2, Sparkles } from 'lucide-react';
import { schemaApi } from '../services/api';
import ReextractModal from './ReextractModal';
import SchemaGraph from './SchemaGraph';
import SchemaChecks from './SchemaChecks';
import PropertyTriplesModal from './PropertyTriplesModal';
import RecommendPanel from './RecommendPanel';

// 스키마 편집기 — 승격된 텍스트 KB 의 클래스·속성을 사람이 직접 고친다 (docs/design-schema-editor.md)
// 저장 시: 검증 → 이전 버전 이력 보관 → TBox 재생성. 이름 변경은 규칙 + 리플레이로 기존 그래프에 반영.
// 정의·방향·별칭 변경은 "스키마 기준 재추출"을 돌려야 데이터에 반영된다.

interface ClassRow { key: string; name: string; description: string; member_count?: number; renamed_from?: string; orig?: string; examples?: string[]; }
interface PropRow {
    key: string; name: string; description: string; domain: string; range: string;
    aliases: string; seed?: boolean; triple_count?: number; renamed_from?: string;
    kind?: string; type?: string; values?: string[]; value_count?: number; ref_kind?: string;
    range_suggestion?: { class: string; ratio: number; n: number; hits: number };
    range_check?: { n: number; data_class: string; data_ratio: number; declared_ratio: number | null; decision: string; family: string[] };
}
interface Spec {
    editable: boolean; reason?: string; schema_source: string; version: number; updated_at?: string;
    mode?: 'induced' | 'structured'; notes?: string[];
    member_gaps?: Record<string, { name: string; count: number; via: string[] }[]>;
    range_violations?: { property: string; range: string; name: string; class: string }[];
    classes: any[]; properties: any[]; out_of_schema: { name: string; triple_count: number }[];
    history: { version: number; at?: string; summary?: string }[];
}

let _seq = 0;
const nextKey = () => `r${++_seq}`;

const cell: React.CSSProperties = { padding: '0.3rem 0.4rem', borderBottom: '1px solid #e2e8f0', verticalAlign: 'top' };
const input: React.CSSProperties = { width: '100%', fontSize: '0.8rem', padding: '0.2rem 0.3rem', border: '1px solid #cbd5e1', borderRadius: '4px', boxSizing: 'border-box' };
const btn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.8rem', padding: '0.3rem 0.6rem' };

export default function SchemaEditor({ kbId }: { kbId: string }) {
    const [spec, setSpec] = useState<Spec | null>(null);
    const [classes, setClasses] = useState<ClassRow[]>([]);
    const [props, setProps] = useState<PropRow[]>([]);
    const [orig, setOrig] = useState<{ c: Record<string, string>; p: Record<string, string> }>({ c: {}, p: {} });
    const [check, setCheck] = useState<{ errors: string[]; warnings: string[]; summary: string } | null>(null);
    const [message, setMessage] = useState('');
    const [busy, setBusy] = useState(false);
    const [filter, setFilter] = useState('');
    const [showReextract, setShowReextract] = useState(false);
    const [view, setView] = useState<'table' | 'graph'>('table');
    const [triplesFor, setTriplesFor] = useState<string | null>(null);
    const [recFor, setRecFor] = useState<null | { triples?: any[] }>(null);   // AI 추천 (스키마 전체 또는 선택 트리플)

    const load = useCallback(async () => {
        const r = await schemaApi.getSpec(kbId);
        const s: Spec = r.data;
        setSpec(s);
        const c = (s.classes || []).map((x: any) => ({
            key: nextKey(), name: x.name, description: x.description || '', member_count: x.member_count,
            orig: x.orig, examples: x.examples,
        }));
        const p = (s.properties || []).map((x: any) => ({
            key: nextKey(), name: x.name, description: x.description || '', domain: x.domain || '', range: x.range || '',
            aliases: (x.aliases || []).join(', '), seed: x.seed, triple_count: x.triple_count,
            kind: x.kind, type: x.type, values: x.values, value_count: x.value_count, ref_kind: x.ref_kind,
            range_suggestion: x.range_suggestion, range_check: x.range_check,
        }));
        setClasses(c);
        setProps(p);
        // 행 key → 불러올 때의 이름 (이름 변경 추적용)
        setOrig({ c: Object.fromEntries(c.map((x) => [x.key, x.name])), p: Object.fromEntries(p.map((x) => [x.key, x.name])) });
        setCheck(null);
    }, [kbId]);

    useEffect(() => { load().catch(() => setMessage('스키마를 불러오지 못했습니다.')); }, [load]);

    const body = useCallback(() => ({
        base_version: spec?.version,
        classes: classes.map((c) => ({
            name: c.name, description: c.description, ...(c.orig ? { orig: c.orig } : {}),
            ...(orig.c[c.key] && orig.c[c.key] !== c.name ? { renamed_from: orig.c[c.key] } : {}),
        })),
        properties: props.map((p) => ({
            name: p.name, description: p.description, domain: p.domain, range: p.range,
            aliases: p.aliases.split(',').map((a) => a.trim()).filter(Boolean), seed: p.seed,
            ...(orig.p[p.key] && orig.p[p.key] !== p.name ? { renamed_from: orig.p[p.key] } : {}),
        })),
    }), [classes, props, orig, spec]);

    // 편집할 때마다 서버 검증 (오류·경고·변경 요약 미리보기)
    useEffect(() => {
        if (!spec?.editable) return;
        const t = setTimeout(() => {
            schemaApi.validateSpec(kbId, body()).then((r) => setCheck(r.data)).catch(() => undefined);
        }, 400);
        return () => clearTimeout(t);
    }, [kbId, body, spec]);

    // 구조화(YAML/JSON) KB: 유형·속성은 YAML 필드 구조에서 나오므로 추가·삭제·방향 변경 불가
    const structured = spec?.mode === 'structured';
    const classNames = useMemo(() => classes.map((c) => c.name).filter(Boolean), [classes]);
    const shown = props.filter((p) => !filter || `${p.name} ${p.aliases} ${p.description}`.toLowerCase().includes(filter.toLowerCase()));
    const dirty = !!check && check.summary !== '변경 없음';

    const save = async () => {
        setBusy(true);
        setMessage('');
        try {
            const r = await schemaApi.saveSpec(kbId, body());
            const d = r.data;
            setMessage(
                d.saved
                    ? `저장됨 (버전 ${d.version}): ${d.summary}` + (d.replayed ? ` · 리플레이 문서 ${d.replayed}건` : '')
                    + (d.reextract_recommended ? ' · 정의·방향·별칭 변경은 "스키마 기준 재추출"을 돌려야 데이터에 반영됩니다.' : '')
                    : '변경 사항이 없습니다.');
            await load();
        } catch (e: any) {
            const det = e?.response?.data?.detail;
            setMessage('저장 실패: ' + (det?.errors ? det.errors.join(' / ') : (typeof det === 'string' ? det : e.message)));
        } finally {
            setBusy(false);
        }
    };

    const revert = async (version: number) => {
        setBusy(true);
        try {
            const r = await schemaApi.revertSpec(kbId, version);
            setMessage(`버전 ${version} 으로 되돌림 → 새 버전 ${r.data.version}`);
            await load();
        } catch (e: any) {
            const det = e?.response?.data?.detail;
            setMessage('되돌리기 실패: ' + (det?.errors ? det.errors.join(' / ') : e.message));
        } finally {
            setBusy(false);
        }
    };

    const openReextract = () => setShowReextract(true);

    if (!spec) return <div style={{ padding: '1rem' }}>{message || '불러오는 중…'}</div>;
    if (!spec.editable) {
        return <div className="card" style={{ margin: '1rem', padding: '1rem' }}>
            <h3 style={{ marginTop: 0 }}>스키마 편집</h3>
            <p style={{ fontSize: '0.9rem' }}>{spec.reason}</p>
        </div>;
    }

    const rename = (old: string | undefined, now: string) => old && old !== now
        ? <div style={{ fontSize: '0.7rem', color: '#b45309' }}>이전: {old}</div> : null;

    return (
        <div style={{ padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                <h3 style={{ margin: 0 }}>스키마 편집</h3>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    버전 {spec.version}{spec.updated_at ? ` · ${spec.updated_at.replace('T', ' ').slice(0, 16)}` : ''} · 클래스 {classes.length} · 속성 {props.length}
                </span>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.5rem' }}>
                    <button className="btn btn-secondary" style={btn}
                        title="저장된 스키마를 그래프 뷰어(새 탭)로 — 클래스를 누르면 실제 인스턴스가 펼쳐집니다."
                        onClick={() => window.open(`${import.meta.env.BASE_URL}graph-viewer?kb_id=${kbId}&backend=ontology&mode=schema`, '_blank')}>
                        <Share2 size={14} /> 뷰어에서 열기
                    </button>
                    <button className="btn btn-secondary" style={btn} disabled={busy} onClick={() => load()}><RefreshCw size={14} /> 다시 불러오기</button>
                    {!structured && <button className="btn btn-secondary" style={btn} disabled={busy || dirty}
                        title={dirty ? '저장하지 않은 편집이 있습니다 — 먼저 저장하세요' : '스키마·데이터 검증·문제 트리플을 AI 가 분석해 처리안을 제시합니다'}
                        onClick={() => setRecFor({})}>
                        <Sparkles size={14} /> AI 추천
                    </button>}
                    {!structured && <button className="btn btn-secondary" style={btn} disabled={busy} onClick={openReextract}>스키마 기준 재추출…</button>}
                    <button className="btn btn-primary" style={btn} disabled={busy || !dirty || !!check?.errors?.length} onClick={save}><Save size={14} /> 저장</button>
                </div>
            </div>
            {structured ? (
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0 }}>
                    {(spec.notes || []).map((n, i) => <div key={i}>{n}</div>)}
                </div>
            ) : <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0 }}>
                저장하면 이전 버전이 이력에 남고 TBox 가 다시 만들어집니다. <b>이름 변경</b>은 규칙과 리플레이로 기존 그래프에 바로 반영됩니다(LLM 비용 없음).
                <b> 정의·방향(domain→range)·별칭</b> 변경은 재추출 때 프롬프트로 쓰이므로, 데이터에 반영하려면 "스키마 기준 재추출"을 실행하세요.
            </p>}

            {check && (check.errors.length > 0 || check.warnings.length > 0 || dirty) && (
                <div style={{ fontSize: '0.8rem', background: check.errors.length ? '#fef2f2' : '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '6px', padding: '0.5rem 0.75rem' }}>
                    {dirty && <div><b>변경:</b> {check.summary}</div>}
                    {check.errors.map((e, i) => <div key={`e${i}`} style={{ color: '#b91c1c' }}><AlertTriangle size={12} /> {e}</div>)}
                    {check.warnings.slice(0, 6).map((w, i) => <div key={`w${i}`} style={{ color: '#92400e' }}>· {w}</div>)}
                    {check.warnings.length > 6 && <div style={{ color: '#92400e' }}>· 경고 {check.warnings.length - 6}건 더</div>}
                </div>
            )}
            {message && <div style={{ fontSize: '0.85rem', color: '#1e40af' }}>{message}</div>}

            {!structured && (
                <SchemaChecks kbId={kbId} memberGaps={spec.member_gaps || {}} violations={spec.range_violations || []}
                    onChanged={(m) => { setMessage(m); load(); }} />
            )}

            <div style={{ display: 'flex', gap: 0 }}>
                {(['table', 'graph'] as const).map((v) => (
                    <button key={v} className={`btn ${view === v ? 'btn-primary' : 'btn-secondary'}`}
                        style={{ ...btn, borderRadius: v === 'table' ? '6px 0 0 6px' : '0 6px 6px 0' }}
                        onClick={() => setView(v)}>{v === 'table' ? '표' : '그래프'}</button>
                ))}
            </div>

            {view === 'graph' && (
                <SchemaGraph
                    structured={structured}
                    classes={classes}
                    props={props}
                />
            )}

            {/* 클래스 */}
            {view === 'table' && <>
            <div className="card" style={{ padding: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: '0.4rem' }}>
                    <h4 style={{ margin: 0 }}>{structured ? '유형' : '클래스'}</h4>
                    {!structured && <button className="btn btn-secondary" style={{ ...btn, marginLeft: 'auto' }}
                        onClick={() => setClasses([...classes, { key: nextKey(), name: '', description: '' }])}><Plus size={14} /> 클래스 추가</button>}
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                    <thead><tr style={{ textAlign: 'left', color: '#64748b' }}>
                        <th style={{ ...cell, width: '22%' }}>이름</th><th style={cell}>설명</th><th style={{ ...cell, width: '8%' }}>멤버</th><th style={{ ...cell, width: '4%' }} />
                    </tr></thead>
                    <tbody>
                        {classes.map((c, i) => (
                            <tr key={c.key}>
                                <td style={cell}>
                                    <input style={input} value={c.name} placeholder="PascalCase"
                                        onChange={(e) => setClasses(classes.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
                                    {rename(orig.c[c.key], c.name)}
                                </td>
                                <td style={cell}><input style={input} value={c.description}
                                    onChange={(e) => setClasses(classes.map((x, j) => j === i ? { ...x, description: e.target.value } : x))} /></td>
                                <td style={cell} title={(c.examples || []).join(', ')}>{c.member_count ?? '-'}</td>
                                <td style={cell}>
                                    {!structured && <button className="btn btn-secondary" style={{ ...btn, padding: '0.2rem 0.35rem' }} title="삭제 (멤버 지정 규칙은 꺼짐)"
                                        onClick={() => setClasses(classes.filter((_, j) => j !== i))}><Trash2 size={12} /></button>}
                                    {c.orig && c.orig !== c.name && <div style={{ fontSize: '0.7rem', color: '#64748b' }}>자동: {c.orig}</div>}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* 속성 */}
            <div className="card" style={{ padding: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
                    <h4 style={{ margin: 0 }}>{structured ? '속성 (YAML 필드 경로)' : '속성 (관계)'}</h4>
                    <input style={{ ...input, width: '220px' }} placeholder="이름·별칭·정의 검색" value={filter} onChange={(e) => setFilter(e.target.value)} />
                    {!structured && props.some((p) => p.range_suggestion && !p.range) && (
                        <button className="btn btn-secondary" style={{ ...btn, marginLeft: 'auto' }}
                            title="range 가 빈 속성 중 목적어 60% 이상이 한 클래스인 것에 그 클래스를 넣습니다 (저장 전 확인 가능)"
                            onClick={() => setProps(props.map((p) => (p.range_suggestion && !p.range) ? { ...p, range: p.range_suggestion.class } : p))}>
                            range 추천 모두 적용 ({props.filter((p) => p.range_suggestion && !p.range).length})
                        </button>
                    )}
                    {!structured && <button className="btn btn-secondary" style={{ ...btn, marginLeft: props.some((p) => p.range_suggestion && !p.range) ? 0 : 'auto' }}
                        onClick={() => setProps([...props, { key: nextKey(), name: '', description: '', domain: '', range: '', aliases: '' }])}><Plus size={14} /> 속성 추가</button>}
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                    <thead><tr style={{ textAlign: 'left', color: '#64748b' }}>
                        <th style={{ ...cell, width: '14%' }}>이름</th>
                        <th style={{ ...cell, width: '24%' }}>{structured ? '유형 · 값' : '방향 (domain → range)'}</th>
                        <th style={cell}>{structured ? '정의 (검색 계획·TBox 에 쓰임)' : '정의 (재추출 프롬프트에 그대로 들어감)'}</th>
                        <th style={{ ...cell, width: '18%' }}>별칭 (쉼표 구분)</th>
                        <th style={{ ...cell, width: '6%' }}>{structured ? '레코드' : '트리플'}</th>
                        <th style={{ ...cell, width: '4%' }} />
                    </tr></thead>
                    <tbody>
                        {shown.map((p) => {
                            const upd = (patch: Partial<PropRow>) => setProps(props.map((x) => x.key === p.key ? { ...x, ...patch } : x));
                            return (
                                <tr key={p.key}>
                                    <td style={cell}>
                                        <input style={input} value={p.name} onChange={(e) => upd({ name: e.target.value })} />
                                        {rename(orig.p[p.key], p.name)}
                                        {p.seed && <div style={{ fontSize: '0.7rem', color: '#64748b' }}>시드</div>}
                                    </td>
                                    {structured ? (
                                        <td style={cell}>
                                            <div style={{ fontSize: '0.72rem', color: '#475569' }}>{p.kind} · {p.ref_kind ? <b>→ {p.ref_kind} (다른 레코드 참조)</b> : p.type}{p.value_count ? ` · 값 ${p.value_count}종` : ''}</div>
                                            <div style={{ fontSize: '0.72rem', color: '#64748b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '22rem' }}
                                                title={(p.values || []).join(' | ')}>{(p.values || []).slice(0, 5).join(', ')}</div>
                                        </td>
                                    ) : <td style={cell}>
                                        <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
                                            <select style={input} value={p.domain} onChange={(e) => upd({ domain: e.target.value })}>
                                                <option value="">(지정 안 함)</option>
                                                {classNames.map((n) => <option key={n} value={n}>{n}</option>)}
                                            </select>
                                            <span>→</span>
                                            <input style={input} list={`ranges-${kbId}`} value={p.range} placeholder="클래스 또는 값"
                                                onChange={(e) => upd({ range: e.target.value })} />
                                        </div>
                                        {p.range_check && p.range && p.range_check.n >= 5 && (
                                            <div style={{ fontSize: '0.68rem', color: (p.range_check.declared_ratio ?? 0) >= 0.6 ? '#15803d' : '#b45309' }}
                                                title={`목적어 ${p.range_check.n}개 중 ${p.range} 멤버 비율${p.range_check.family?.length ? ` (계열 합산: ${p.range_check.family.join(', ')})` : ''}`}>
                                                일치 {Math.round((p.range_check.declared_ratio ?? 0) * 100)}% / {p.range_check.n}
                                            </div>
                                        )}
                                        {p.range_suggestion && p.range_suggestion.class !== p.range && (
                                            <button className="btn btn-secondary" style={{ ...btn, padding: '0.1rem 0.4rem', marginTop: '0.2rem', fontSize: '0.7rem' }}
                                                title={`목적어 ${p.range_suggestion.n}건 중 ${p.range_suggestion.hits}건이 ${p.range_suggestion.class} 멤버`}
                                                onClick={() => upd({ range: p.range_suggestion!.class })}>
                                                {p.range ? '데이터는' : '추천:'} → {p.range_suggestion.class} ({Math.round(p.range_suggestion.ratio * 100)}%)
                                            </button>
                                        )}
                                    </td>}
                                    <td style={cell}><textarea style={{ ...input, minHeight: '2.2rem', resize: 'vertical' }} value={p.description}
                                        onChange={(e) => upd({ description: e.target.value })} /></td>
                                    <td style={cell}><textarea style={{ ...input, minHeight: '2.2rem', resize: 'vertical' }} value={p.aliases}
                                        onChange={(e) => upd({ aliases: e.target.value })} /></td>
                                    <td style={cell}>
                                        {/* 저장된 이름 기준으로 조회 (이름을 바꾸는 중이면 이전 이름) */}
                                        <button className="btn btn-secondary" style={{ ...btn, padding: '0.1rem 0.45rem' }}
                                            disabled={!(orig.p[p.key] || p.name) || !p.triple_count}
                                            title="이 속성의 실제 트리플 목록 — 일치·멤버 누락·range 위반 확인"
                                            onClick={() => setTriplesFor(orig.p[p.key] || p.name)}>
                                            {p.triple_count ?? 0}
                                        </button>
                                    </td>
                                    <td style={cell}>
                                        {!structured && <button className="btn btn-secondary" style={{ ...btn, padding: '0.2rem 0.35rem' }}
                                            title="스키마에서 삭제 (기존 트리플은 남고 스키마 밖으로 분류)"
                                            onClick={() => setProps(props.filter((x) => x.key !== p.key))}><Trash2 size={12} /></button>}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
                <datalist id={`ranges-${kbId}`}>{classNames.map((n) => <option key={n} value={n} />)}</datalist>
            </div>
            </>}

            {/* 스키마 밖 관계 — 그래프에 있으나 스키마에 없는 술어 */}
            {spec.out_of_schema?.length > 0 && (
                <div className="card" style={{ padding: '0.75rem' }}>
                    <h4 style={{ margin: '0 0 0.4rem' }}>스키마 밖 관계 (그래프에만 있음)</h4>
                    <div style={{ fontSize: '0.8rem', display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                        {spec.out_of_schema.map((o) => (
                            <button key={o.name} className="btn btn-secondary" style={{ ...btn, padding: '0.15rem 0.45rem' }}
                                title="속성으로 추가"
                                onClick={() => props.some((p) => p.name === o.name) ? undefined
                                    : setProps([...props, { key: nextKey(), name: o.name, description: '', domain: '', range: '', aliases: '', triple_count: o.triple_count }])}>
                                <Plus size={11} /> {o.name} ({o.triple_count})
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* 이력 */}
            {spec.history?.length > 0 && (
                <div className="card" style={{ padding: '0.75rem' }}>
                    <h4 style={{ margin: '0 0 0.4rem' }}>이력</h4>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <tbody>
                            {spec.history.map((h) => (
                                <tr key={h.version}>
                                    <td style={{ ...cell, width: '8%' }}>v{h.version}</td>
                                    <td style={{ ...cell, width: '18%' }}>{(h.at || '').replace('T', ' ').slice(0, 16)}</td>
                                    <td style={cell}>{h.summary}</td>
                                    <td style={{ ...cell, width: '12%' }}>
                                        <button className="btn btn-secondary" style={btn} disabled={busy} onClick={() => revert(h.version)}>
                                            <RotateCcw size={12} /> 되돌리기
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {triplesFor && (
                <PropertyTriplesModal kbId={kbId} property={triplesFor} onClose={() => setTriplesFor(null)}
                    onChanged={(m) => { setMessage(m); load(); }}
                    properties={props.filter((p) => orig.p[p.key]).map((p) => ({ name: orig.p[p.key], domain: p.domain, range: p.range }))}
                    classes={classes.map((c) => orig.c[c.key] || c.name).filter(Boolean)}
                    dirty={dirty}
                    onRecommend={structured ? undefined : (tr) => setRecFor({ triples: tr })}
                    getSpec={structured ? undefined : () => { const b = body(); return { classes: b.classes, properties: b.properties }; }} />
            )}

            {recFor && (
                <RecommendPanel kbId={kbId} triples={recFor.triples} onClose={() => setRecFor(null)}
                    classes={classes.map((c) => orig.c[c.key] || c.name).filter(Boolean)}
                    properties={props.map((p) => orig.p[p.key] || p.name).filter(Boolean)}
                    onApplied={(m) => { setMessage(m); setTriplesFor(null); load(); }} />
            )}

            {showReextract && (
                <ReextractModal kbId={kbId} onClose={() => setShowReextract(false)} />
            )}
        </div>
    );
}
