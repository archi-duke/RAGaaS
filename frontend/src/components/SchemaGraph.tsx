import React, { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

// 스키마 편집기의 그래프 보기 — 지금 편집 중인 스키마(저장 전 포함)를 그래프로 (docs/design-schema-editor.md §8)
// - 텍스트 KB: 클래스 = 노드, range 가 클래스인 속성 = 링크, 나머지 속성 = domain 클래스의 값 속성
// - 구조화 KB: 유형 → 중첩 필드(경로 세그먼트) 트리, 마지막 세그먼트 = 값 속성

export interface GraphClass { name: string; description?: string; member_count?: number; }
export interface GraphProp {
    name: string; description?: string; domain?: string; range?: string; aliases?: string;
    kind?: string; type?: string; triple_count?: number; values?: string[]; ref_kind?: string;
}
interface Attr { name: string; full: string; description?: string; aliases?: string; count?: number; values?: string[]; }
interface GNode { id: string; label: string; kind: 'class' | 'struct' | 'attr' | 'none'; description?: string; attrs: Attr[]; count?: number; }
interface GLink { source: string; target: string; label: string; description?: string; curvature?: number; }

const COLORS = { class: '#2563eb', struct: '#0d9488', attr: '#94a3b8', none: '#f59e0b' };

function build(structured: boolean, classes: GraphClass[], props: GraphProp[], showAttrs: boolean, nested: boolean) {
    const nodes = new Map<string, GNode>();
    const links: GLink[] = [];
    const add = (id: string, label: string, kind: GNode['kind'], extra: Partial<GNode> = {}) => {
        if (!nodes.has(id)) nodes.set(id, { id, label, kind, attrs: [], ...extra });
        return nodes.get(id)!;
    };
    classes.filter((c) => c.name).forEach((c) => add(`c:${c.name}`, c.name, 'class', { description: c.description, count: c.member_count }));

    if (structured && !nested) {
        // 기본: 중첩 블록은 유형 안의 값 속성(경로)으로 접고, 다른 레코드를 가리키는 경로만 유형 간 링크로
        for (const p of props) {
            if (!p.kind || !p.name) continue;
            const owner = add(`c:${p.kind}`, p.kind, 'class');
            if (p.ref_kind) {
                add(`c:${p.ref_kind}`, p.ref_kind, 'class');
                links.push({ source: owner.id, target: `c:${p.ref_kind}`, label: p.name, description: p.description });
            } else {
                owner.attrs.push({ name: p.name, full: p.name, description: p.description, aliases: p.aliases,
                    count: p.triple_count, values: p.values });
            }
        }
    } else if (structured) {
        for (const p of props) {
            const segs = p.name.split('.').filter(Boolean);
            if (!segs.length || !p.kind) continue;
            let parent = add(`c:${p.kind}`, p.kind, 'class');
            for (let i = 0; i < segs.length - 1; i++) {
                const id = `s:${p.kind}/${segs.slice(0, i + 1).join('.')}`;
                const isNew = !nodes.has(id);
                const child = add(id, segs[i], 'struct');
                if (isNew) links.push({ source: parent.id, target: id, label: segs[i] });
                parent = child;
            }
            parent.attrs.push({ name: segs[segs.length - 1], full: p.name, description: p.description, aliases: p.aliases,
                count: p.triple_count, values: p.values });
        }
    } else {
        const classSet = new Set(classes.map((c) => c.name));
        for (const p of props) {
            if (!p.name) continue;
            const dom = p.domain && classSet.has(p.domain) ? `c:${p.domain}` : null;
            const rng = p.range && classSet.has(p.range) ? `c:${p.range}` : null;
            if (dom && rng) {
                links.push({ source: dom, target: rng, label: p.name, description: p.description });
            } else {
                const owner = dom ? nodes.get(dom)! : add('none', 'domain 미지정', 'none');
                owner.attrs.push({ name: p.name, full: p.name, description: p.description, aliases: p.aliases,
                    count: p.triple_count, values: p.range ? [`→ ${p.range}`] : undefined });
            }
        }
    }
    if (showAttrs) {
        for (const n of Array.from(nodes.values())) {
            if (n.kind === 'attr') continue;
            n.attrs.slice(0, 40).forEach((a) => {
                const id = `a:${n.id}/${a.full}`;
                add(id, a.name, 'attr', { description: a.description });
                links.push({ source: n.id, target: id, label: '' });
            });
        }
    }
    // 같은 두 노드 사이 여러 링크는 곡률을 달리해 겹치지 않게
    const pairCount: Record<string, number> = {};
    for (const l of links) {
        const k = [l.source, l.target].sort().join('|');
        const i = pairCount[k] = (pairCount[k] || 0) + 1;
        if (l.source === l.target) {
            l.curvature = 0.5 + (i - 1) * 0.25;   // 자기 관계는 고리로 (겹치지 않게 크기를 달리)
        } else {
            l.curvature = i === 1 ? 0 : (i % 2 === 0 ? 1 : -1) * Math.ceil((i - 1) / 2) * 0.25;
        }
    }
    return { nodes: Array.from(nodes.values()), links };
}

export default function SchemaGraph({ structured, classes, props }: { structured: boolean; classes: GraphClass[]; props: GraphProp[] }) {
    const wrap = useRef<HTMLDivElement>(null);
    const fg = useRef<any>(null);
    const [width, setWidth] = useState(800);
    const [showAttrs, setShowAttrs] = useState(false);
    const [nested, setNested] = useState(false);   // 구조화 KB: 중첩 블록 펼치기
    const [sel, setSel] = useState<{ node?: GNode; link?: GLink } | null>(null);
    const data = useMemo(() => build(structured, classes, props, showAttrs, nested), [structured, classes, props, showAttrs, nested]);

    useEffect(() => {
        const el = wrap.current;
        if (!el) return;
        const ro = new ResizeObserver(() => setWidth(el.clientWidth));
        ro.observe(el);
        setWidth(el.clientWidth);
        return () => ro.disconnect();
    }, []);
    useEffect(() => {
        fg.current?.d3Force('charge')?.strength(showAttrs ? -120 : -400);
        fg.current?.d3Force('link')?.distance(showAttrs ? 50 : 120);
        const t = setTimeout(() => fg.current?.zoomToFit(400, 40), 600);
        return () => clearTimeout(t);
    }, [data, showAttrs]);

    const graphW = Math.max(300, width - (sel ? 320 : 0));
    const nodeById = useMemo(() => new Map(data.nodes.map((n) => [n.id, n])), [data]);

    return (
        <div ref={wrap} style={{ position: 'relative', border: '1px solid #e2e8f0', borderRadius: '8px', background: '#f8fafc', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', top: 8, left: 10, zIndex: 2, fontSize: '0.75rem', color: '#475569', display: 'flex', gap: '0.75rem', alignItems: 'center', background: 'rgba(248,250,252,0.9)', padding: '2px 6px', borderRadius: '4px' }}>
                <span><span style={{ color: COLORS.class }}>●</span> {structured ? '유형' : '클래스'}</span>
                {structured && <span><span style={{ color: COLORS.struct }}>●</span> 중첩 필드</span>}
                {showAttrs && <span><span style={{ color: COLORS.attr }}>●</span> 값 속성</span>}
                {!structured && data.nodes.some((n) => n.kind === 'none') && <span><span style={{ color: COLORS.none }}>●</span> domain 미지정 속성</span>}
                {structured && <label style={{ cursor: 'pointer' }} title="YAML 중첩 블록(fit_signals 등)을 별도 노드로 펼칩니다 — 클래스가 아니라 레코드에 붙은 속성 묶음입니다">
                    <input type="checkbox" checked={nested} onChange={(e) => setNested(e.target.checked)} /> 중첩 블록 펼치기
                </label>}
                <label style={{ cursor: 'pointer' }}>
                    <input type="checkbox" checked={showAttrs} onChange={(e) => setShowAttrs(e.target.checked)} /> 값 속성도 노드로
                </label>
                <span style={{ opacity: 0.7 }}>노드·링크를 누르면 정의가 보입니다 · 저장 전 편집도 반영</span>
            </div>
            <div style={{ display: 'flex' }}>
                <ForceGraph2D
                    ref={fg}
                    width={graphW}
                    height={560}
                    graphData={data as any}
                    backgroundColor="#f8fafc"
                    cooldownTicks={120}
                    nodeRelSize={6}
                    linkCurvature="curvature"
                    linkColor={() => '#94a3b8'}
                    linkWidth={(l: any) => (l.label ? 1.6 : 0.6)}
                    linkDirectionalArrowLength={(l: any) => (l.label ? 6 : 0)}
                    linkDirectionalArrowRelPos={0.9}
                    nodeLabel={(n: any) => n.description || n.label}
                    linkLabel={(l: any) => l.description ? `${l.label}: ${l.description}` : l.label}
                    onNodeClick={(n: any) => setSel({ node: nodeById.get(n.id) })}
                    onLinkClick={(l: any) => l.label && setSel({ link: l })}
                    onBackgroundClick={() => setSel(null)}
                    nodeCanvasObjectMode={() => 'replace'}
                    nodeCanvasObject={(n: any, ctx, scale) => {
                        const r = n.kind === 'class' ? 9 : n.kind === 'attr' ? 3.5 : 6;
                        ctx.beginPath();
                        ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
                        ctx.fillStyle = COLORS[n.kind as keyof typeof COLORS];
                        ctx.fill();
                        if (sel?.node?.id === n.id) { ctx.lineWidth = 2 / scale; ctx.strokeStyle = '#1e293b'; ctx.stroke(); }
                        if (n.kind === 'attr' && scale < 1.2) return;
                        const fs = (n.kind === 'class' ? 13 : 11) / scale;
                        ctx.font = `${n.kind === 'class' ? 'bold ' : ''}${fs}px sans-serif`;
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'top';
                        ctx.fillStyle = '#1e293b';
                        const extra = n.kind !== 'attr' && n.attrs?.length && !showAttrs ? ` (${n.attrs.length})` : '';
                        ctx.fillText(`${n.label}${extra}`, n.x, n.y + r + 2 / scale);
                    }}
                    linkCanvasObjectMode={() => 'after'}
                    linkCanvasObject={(l: any, ctx, scale) => {
                        if (!l.label || scale < 0.6) return;
                        const s = l.source, t = l.target;
                        if (typeof s !== 'object' || typeof t !== 'object') return;
                        if (s === t) {
                            // 자기 관계 고리: 노드 위쪽에 라벨
                            const fsz = 10 / scale;
                            ctx.font = `${fsz}px sans-serif`;
                            ctx.fillStyle = '#475569';
                            ctx.textAlign = 'center';
                            ctx.textBaseline = 'middle';
                            const idx = data.links.filter((x: any) => x.source === s && x.target === s).indexOf(l);
                            ctx.fillText(l.label, s.x, s.y - (34 + idx * 12) / scale * (scale > 1 ? 1 : 1));
                            return;
                        }
                        // 곡선 링크의 중간점
                        const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2;
                        const dx = t.x - s.x, dy = t.y - s.y;
                        const c = l.curvature || 0;
                        const x = mx - dy * c / 2, y = my + dx * c / 2;
                        const fs = 10 / scale;
                        ctx.font = `${fs}px sans-serif`;
                        const w = ctx.measureText(l.label).width;
                        ctx.fillStyle = 'rgba(248,250,252,0.85)';
                        ctx.fillRect(x - w / 2 - 2 / scale, y - fs / 2 - 1 / scale, w + 4 / scale, fs + 2 / scale);
                        ctx.fillStyle = '#475569';
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'middle';
                        ctx.fillText(l.label, x, y);
                    }}
                />
                {sel && (
                    <div style={{ width: 320, maxHeight: 560, overflowY: 'auto', borderLeft: '1px solid #e2e8f0', background: '#fff', padding: '0.75rem', fontSize: '0.8rem' }}>
                        {sel.node && (
                            <>
                                <div style={{ fontWeight: 700, fontSize: '0.9rem' }}>{sel.node.label}</div>
                                <div style={{ color: '#64748b', marginBottom: '0.4rem' }}>
                                    {{ class: structured ? '유형' : '클래스', struct: '중첩 필드', attr: '값 속성', none: 'domain 미지정' }[sel.node.kind]}
                                    {sel.node.count != null ? ` · 멤버 ${sel.node.count}` : ''}
                                </div>
                                {sel.node.description && <div style={{ marginBottom: '0.5rem' }}>{sel.node.description}</div>}
                                {(() => {
                                    const out = data.links.filter((l: any) => (l.source?.id ?? l.source) === sel.node!.id && l.label);
                                    const inc = data.links.filter((l: any) => (l.target?.id ?? l.target) === sel.node!.id && l.label);
                                    const nm = (x: any) => nodeById.get(x?.id ?? x)?.label;
                                    return <>
                                        {out.length > 0 && <div style={{ marginBottom: '0.4rem' }}><b>나가는 관계</b>{out.map((l, i) => <div key={i}>· {l.label} → {nm(l.target)}{l.description ? <span style={{ color: '#64748b' }}> — {l.description}</span> : null}</div>)}</div>}
                                        {inc.length > 0 && <div style={{ marginBottom: '0.4rem' }}><b>들어오는 관계</b>{inc.map((l, i) => <div key={i}>· {nm(l.source)} → {l.label}</div>)}</div>}
                                    </>;
                                })()}
                                {sel.node.attrs.length > 0 && (
                                    <div><b>값 속성 {sel.node.attrs.length}개</b>
                                        {sel.node.attrs.map((a) => (
                                            <div key={a.full} style={{ marginTop: '0.3rem' }}>
                                                · <b>{a.name}</b>{a.count != null ? <span style={{ color: '#94a3b8' }}> ({a.count})</span> : null}
                                                {a.description && <div style={{ color: '#475569', paddingLeft: '0.7rem' }}>{a.description}</div>}
                                                {a.aliases && <div style={{ color: '#64748b', paddingLeft: '0.7rem' }}>별칭: {a.aliases}</div>}
                                                {a.values && a.values.length > 0 && <div style={{ color: '#94a3b8', paddingLeft: '0.7rem' }}>값: {a.values.slice(0, 5).join(', ')}</div>}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </>
                        )}
                        {sel.link && (
                            <>
                                <div style={{ fontWeight: 700, fontSize: '0.9rem' }}>{sel.link.label}</div>
                                <div style={{ color: '#64748b', marginBottom: '0.4rem' }}>
                                    {nodeById.get((sel.link.source as any)?.id ?? sel.link.source)?.label} → {nodeById.get((sel.link.target as any)?.id ?? sel.link.target)?.label}
                                </div>
                                {sel.link.description ? <div>{sel.link.description}</div> : <div style={{ color: '#94a3b8' }}>정의 없음</div>}
                            </>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
