import React from 'react';

// 에이전틱 필터의 추론 과정 — 단계별 계획·검색·관찰과 스크래치패드(에이전트 메모)
// docs/design/graph/design-agentic-filter.md §9. 스크래치패드는 짧은 마크다운(## 제목, - 목록, | 표 |)이라 간단히 그린다.

function cellColor(t: string): React.CSSProperties {
    const v = t.trim();
    if (v.startsWith('✔')) return { color: '#15803d', fontWeight: 600 };
    if (v.startsWith('✘')) return { color: '#b91c1c', fontWeight: 600 };
    if (v === '?' || v.startsWith('?')) return { color: '#b45309', fontWeight: 600 };
    return {};
}

export function ScratchpadView({ text }: { text: string }) {
    const lines = (text || '').split('\n');
    const out: React.ReactNode[] = [];
    let i = 0;
    while (i < lines.length) {
        const l = lines[i];
        if (/^\s*\|/.test(l)) {
            const rows: string[][] = [];
            while (i < lines.length && /^\s*\|/.test(lines[i])) {
                const cells = lines[i].trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
                if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);   // 구분선(|---|) 건너뜀
                i++;
            }
            out.push(
                <table key={`t${i}`} style={{ borderCollapse: 'collapse', margin: '0.25rem 0', fontSize: '0.78rem' }}>
                    <tbody>{rows.map((r, ri) => (
                        <tr key={ri} style={ri === 0 ? { background: '#f1f5f9' } : undefined}>
                            {r.map((c, ci) => <td key={ci} style={{ border: '1px solid #e2e8f0', padding: '0.15rem 0.45rem', ...(ri > 0 && ci > 0 ? cellColor(c) : {}), fontWeight: ri === 0 ? 600 : undefined }}>{c}</td>)}
                        </tr>))}
                    </tbody>
                </table>);
            continue;
        }
        if (/^\s*#{1,4}\s/.test(l)) out.push(<div key={i} style={{ fontWeight: 700, marginTop: '0.35rem' }}>{l.replace(/^\s*#{1,4}\s/, '')}</div>);
        else if (/^\s*[-*]\s/.test(l)) out.push(<div key={i} style={{ paddingLeft: '0.8rem' }}>• {l.replace(/^\s*[-*]\s/, '')}</div>);
        else if (l.trim()) out.push(<div key={i}>{l}</div>);
        i++;
    }
    return <div style={{ fontSize: '0.8rem', lineHeight: 1.5 }}>{out}</div>;
}

export default function AgenticReasoningCard({ agentic, compact = false }: { agentic: any; compact?: boolean }) {
    const [openStep, setOpenStep] = React.useState<number | null>(null);
    const [showSteps, setShowSteps] = React.useState(!compact);
    const steps: any[] = agentic.steps || [];
    return (
        <div className="card" style={{ padding: '1rem', width: '100%', boxSizing: 'border-box' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                <div style={{ fontSize: '0.9rem', fontWeight: 600 }}>Agentic 추론 과정</div>
                <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                    {steps.length}단계 · {agentic.seconds}초 · 종료: <b style={{ color: agentic.stop_reason === '근거 충분' ? '#15803d' : '#b45309' }}>{agentic.stop_reason}</b>
                </span>
            </div>
            {agentic.scratchpad && (
                <div style={{ background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '6px', padding: '0.5rem 0.75rem', marginBottom: '0.6rem' }}>
                    <div style={{ fontSize: '0.75rem', color: '#92400e', fontWeight: 600, marginBottom: '0.2rem' }}>
                        스크래치패드 (최종) — 에이전트가 단계마다 고쳐 쓴 메모. 답변은 이 표의 ✔/✘/? 를 따른다
                    </div>
                    <ScratchpadView text={agentic.scratchpad} />
                </div>
            )}
            {!agentic.scratchpad && <div style={{ fontSize: '0.78rem', color: '#94a3b8', marginBottom: '0.4rem' }}>스크래치패드가 없습니다 (계획 LLM 이 메모를 내지 않음).</div>}
            {compact && (
                <button className="btn btn-secondary" style={{ fontSize: '0.72rem', padding: '0.1rem 0.5rem', marginBottom: '0.3rem' }}
                    onClick={() => setShowSteps(!showSteps)}>{showSteps ? '단계별 과정 접기' : `단계별 과정 보기 (${steps.length}단계)`}</button>
            )}
            {showSteps && steps.map((s: any, i: number) => (
                <div key={i} style={{ borderTop: '1px solid #e2e8f0', padding: '0.4rem 0' }}>
                    <div style={{ fontSize: '0.8rem' }}>
                        <b>단계 {s.step}</b> — {s.thought}
                    </div>
                    {(s.calls || []).map((c: any, j: number) => (
                        <div key={j} style={{ fontSize: '0.76rem', color: '#475569', paddingLeft: '0.8rem', marginTop: '0.15rem' }}>
                            └ <code>{c.tool}</code>("{c.query}") <span style={{ color: '#94a3b8' }}>{c.sec}초{c.mode ? ` · 경로 ${c.mode}` : ''}</span>
                            <div style={{ color: '#64748b', paddingLeft: '0.9rem' }}>→ {String(c.observation || '').slice(0, 300)}{String(c.observation || '').length > 300 ? '…' : ''}</div>
                        </div>
                    ))}
                    {s.scratchpad && (
                        <div style={{ paddingLeft: '0.8rem', marginTop: '0.2rem' }}>
                            <button className="btn btn-secondary" style={{ fontSize: '0.7rem', padding: '0.05rem 0.4rem' }}
                                onClick={() => setOpenStep(openStep === i ? null : i)}>
                                {openStep === i ? '이 단계의 메모 닫기' : '이 단계를 시작할 때의 메모 보기'}
                            </button>
                            {openStep === i && <div style={{ background: '#f8fafc', borderRadius: '4px', padding: '0.4rem 0.6rem', marginTop: '0.2rem' }}>
                                <ScratchpadView text={s.scratchpad} /></div>}
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
}
