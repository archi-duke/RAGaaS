import React, { useCallback, useEffect, useState } from 'react';
import { X as XIcon, RefreshCw, Check, ArrowLeftRight, Ban, Trash2 } from 'lucide-react';
import { kbApi, schemaApi } from '../services/api';

// KB 스키마 매핑 제안 검토 / 규칙 관리 (docs/design/schema/design-schema-mismatch.md §5)
interface Proposal {
    id: string;
    kind: 'key' | 'value' | 'class' | 'entity';
    source: string;
    target: string;
    basis: string;
    evidence: Record<string, any>;
    doc_ids: string[];
}

interface Rule {
    id: string;
    rule_type: 'key' | 'value' | 'ignore' | 'entity' | 'class' | 'triple';
    source_path?: string;
    target_path?: string;
    source_value?: string;
    target_value?: string;
    pair?: string[];
    origin: string;
    status: string;
}

const BASIS_LABELS: Record<string, string> = {
    normalized: '표기 정규화',
    nesting: '중첩 차이',
    lexicon: '동의어표',
    llm: 'LLM 판정',
};

interface Props {
    kbId: string;
    onClose: () => void;
    onChanged?: () => void;
}

export default function SchemaAlignmentPanel({ kbId, onClose, onChanged }: Props) {
    const [proposals, setProposals] = useState<Proposal[]>([]);
    const [rules, setRules] = useState<Rule[]>([]);
    const [busy, setBusy] = useState<string | null>(null);
    const [message, setMessage] = useState<string>('');
    // 승격 초안 적용 시 스키마 기준 재추출(L2)을 이어서 실행 — 기본 선택, 사용자가 끌 수 있음
    const [withReextract, setWithReextract] = useState(true);
    const [rxInfo, setRxInfo] = useState<{ chunks: number; docs: number; model?: string } | null>(null);

    const load = useCallback(async () => {
        const [p, r] = await Promise.all([schemaApi.proposals(kbId), schemaApi.rules(kbId)]);
        setProposals(p.data || []);
        setRules(r.data || []);
    }, [kbId]);

    useEffect(() => { load().catch(() => setMessage('제안·규칙을 불러오지 못했습니다.')); }, [load]);
    useEffect(() => {
        schemaApi.reextractEstimate(kbId).then((r) => setRxInfo({
            chunks: r.data.total_chunks || 0, docs: (r.data.documents || []).length, model: r.data.models?.ingest,
        })).catch(() => setRxInfo(null));
    }, [kbId]);

    const run = async (key: string, fn: () => Promise<any>, done: (res: any) => string) => {
        setBusy(key);
        try {
            const res = await fn();
            setMessage(done(res?.data));
            await load();
            onChanged?.();
        } catch (e: any) {
            setMessage(`처리하지 못했습니다: ${e?.response?.data?.detail || e?.message || e}`);
        } finally {
            setBusy(null);
        }
    };

    const renormMsg = (r: any) => {
        const q = r?.renormalize?.queued?.length ?? r?.queued?.length ?? 0;
        const n = r?.renormalize?.needs_source?.length ?? r?.needs_source?.length ?? 0;
        return `재정규화 ${q}건 시작${n ? ` · 원본 없는 문서 ${n}건 (문서 행에서 원본을 다시 올려 주세요)` : ''}`;
    };

    const ruleText = (r: Rule) => {
        if (r.rule_type === 'key') return `${r.source_path} → ${r.target_path}`;
        if (r.rule_type === 'value') return `'${r.source_value}' → '${r.target_value}'`;
        if (r.rule_type === 'entity') return `엔티티 '${r.source_value}' → '${r.target_value}'`;
        if (r.rule_type === 'class') return `'${r.source_value}' ∈ ${r.target_value}`;
        if (r.rule_type === 'triple') {
            const [s, p, o] = r.pair || [];
            return r.target_path ? `트리플 이동: ${s} —${p}→ ${o}  ⇒  —${r.target_path}→` : `트리플 삭제: ${s} —${p}→ ${o}`;
        }
        return `구별 유지: ${(r.pair || []).join(' ≠ ')}`;
    };

    const btn = { display: 'inline-flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8rem', padding: '0.25rem 0.5rem' } as const;

    return (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
            onClick={onClose}>
            <div className="card" style={{ width: 'min(900px, 94vw)', maxHeight: '86vh', overflowY: 'auto', padding: '1.25rem' }}
                onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <h3 style={{ margin: 0 }}>스키마 정렬</h3>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button className="btn btn-secondary" style={btn} disabled={!!busy}
                            onClick={() => run('detect', () => schemaApi.detect(kbId), (r) => `감지 완료: 경로 제안 ${r?.paths ?? 0}건, 값 제안 ${r?.values ?? 0}건`)}>
                            <RefreshCw size={14} /> 다시 감지
                        </button>
                        <button className="btn btn-secondary" style={btn} onClick={onClose}><XIcon size={14} /></button>
                    </div>
                </div>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: 0 }}>
                    같은 의미를 다른 키·값으로 적은 문서를 찾아 매핑을 제안합니다. 수락하면 KB 규칙으로 저장되고 해당 문서가 재정규화되며,
                    이후 올리는 문서에는 자동 적용됩니다. "구별 유지"는 다른 필드로 남기고 다시 제안하지 않습니다.
                </p>
                {message && <div style={{ fontSize: '0.85rem', margin: '0.5rem 0', color: '#1e40af' }}>{message}</div>}

                {(() => {
                    const runIds = Array.from(new Set(proposals.map((p) => p.evidence?.run_id).filter(Boolean))) as string[];
                    return runIds.map((rid) => (
                        <div key={rid} style={{ background: '#eef2ff', padding: '0.6rem', borderRadius: '6px', margin: '0.5rem 0', fontSize: '0.85rem' }}>
                            승격 초안 <code>{rid}</code>: {proposals.filter((p) => p.evidence?.run_id === rid).length}건 — 잘못된 항목은 "구별 유지"로 거절한 뒤 적용하세요.
                            {rxInfo && rxInfo.docs > 0 && (
                                <div style={{ margin: '0.5rem 0', padding: '0.5rem', background: '#fff', borderRadius: '4px' }}>
                                    <label>
                                        <input type="checkbox" checked={withReextract} onChange={(e) => setWithReextract(e.target.checked)} />{' '}
                                        <b>적용 후 스키마 기준 재추출도 실행</b> (텍스트 문서 {rxInfo.docs}건, 청크 {rxInfo.chunks}개{rxInfo.model ? `, 모델 ${rxInfo.model}` : ''})
                                    </label>
                                    <ul style={{ margin: '0.3rem 0 0', paddingLeft: '1.2rem', fontSize: '0.78rem', opacity: 0.85 }}>
                                        <li>확정 스키마로 저장된 청크에서 정보를 다시 뽑아, 묶인 조건을 나누고 관계 이름을 스키마에 맞춥니다.</li>
                                        <li>청크마다 LLM 을 호출해 <b>비용이 듭니다</b>. 결과는 스키마 품질에 좌우됩니다.</li>
                                        <li>스키마 밖 사실은 보존돼 새 제안으로 올라오고, 근거 청크는 유지되며, 문서 탭 "고급 → 스키마 기준 재추출"에서 진행 확인·되돌리기가 가능합니다.</li>
                                    </ul>
                                </div>
                            )}
                            <button className="btn btn-primary" style={btn} disabled={!!busy}
                                onClick={() => run(`apply-${rid}`, () => kbApi.applyPromotion(kbId, rid, { reextract: withReextract && !!rxInfo?.docs }),
                                    (r) => `승격 적용: 규칙 ${r?.accepted ?? 0}건, 클래스 ${r?.classes ?? 0}, 속성 ${r?.properties ?? 0}, 리플레이 문서 ${r?.replayed ?? 0}`
                                        + (r?.reextract?.queued ? ` · 재추출 시작 (문서 ${r.reextract.queued.length}건, 진행은 고급 → 스키마 기준 재추출에서 확인)` : '')
                                        + (r?.reextract?.error ? ` · 재추출 시작 안 됨: ${r.reextract.error}` : ''))}>
                                <Check size={14} /> 승격 초안 적용
                            </button>
                        </div>
                    ));
                })()}
                <h4 style={{ margin: '1rem 0 0.5rem' }}>제안 {proposals.length}건</h4>
                {proposals.length === 0 ? (
                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>검토할 제안이 없습니다.</div>
                ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                        <thead>
                            <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--border)' }}>
                                <th style={{ padding: '0.4rem' }}>종류</th><th>원래 표기 → 표준</th><th>근거</th><th>보유 문서</th><th style={{ textAlign: 'right' }}>처리</th>
                            </tr>
                        </thead>
                        <tbody>
                            {proposals.map((p) => (
                                <tr key={p.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                    <td style={{ padding: '0.4rem' }}>{({ key: '키', value: '값', class: '클래스', entity: '엔티티 병합' } as Record<string, string>)[p.kind] || p.kind}</td>
                                    <td><code>{p.source}</code> → <code>{p.target}</code>
                                        <div style={{ fontSize: '0.72rem', opacity: 0.7 }}>
                                            멤버 {p.evidence?.source_members ?? '-'} / {p.evidence?.target_members ?? '-'}{p.evidence?.path ? ` · 경로 ${p.evidence.path}` : ''}
                                        </div>
                                    </td>
                                    <td>{BASIS_LABELS[p.basis] || p.basis}</td>
                                    <td>{p.doc_ids.length}건</td>
                                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                                        <button className="btn btn-primary" style={btn} disabled={!!busy}
                                            onClick={() => run(p.id, () => schemaApi.accept(kbId, p.id), renormMsg)}><Check size={14} /> 수락</button>{' '}
                                        <button className="btn btn-secondary" style={btn} disabled={!!busy}
                                            onClick={() => run(p.id, () => schemaApi.accept(kbId, p.id, { swap: true }), renormMsg)}><ArrowLeftRight size={14} /> 방향 바꿔 수락</button>{' '}
                                        <button className="btn btn-secondary" style={btn} disabled={!!busy}
                                            onClick={() => run(p.id, () => schemaApi.reject(kbId, p.id), () => '구별 유지로 기록했습니다.')}><Ban size={14} /> 구별 유지</button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '1.25rem 0 0.5rem' }}>
                    <h4 style={{ margin: 0 }}>KB 규칙 {rules.length}건</h4>
                    <button className="btn btn-secondary" style={btn} disabled={!!busy}
                        onClick={() => run('renorm', () => schemaApi.renormalize(kbId), renormMsg)}>
                        <RefreshCw size={14} /> 규칙 미반영 문서 재정규화
                    </button>
                </div>
                {rules.length === 0 ? (
                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>저장된 규칙이 없습니다.</div>
                ) : (
                    <ul style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '0.85rem' }}>
                        {rules.map((r) => (
                            <li key={r.id} style={{ marginBottom: '0.25rem' }}>
                                <code>{ruleText(r)}</code>
                                <span style={{ opacity: 0.6 }}> · {r.origin.startsWith('proposal') ? '제안 수락' : r.origin === 'auto' ? '자동(표기 정규화)' : r.origin.startsWith('schema_editor') ? '스키마 편집기' : '사용자'}</span>
                                {' '}
                                <button className="btn btn-secondary" style={{ ...btn, padding: '0.1rem 0.35rem' }} disabled={!!busy}
                                    onClick={() => run(r.id, () => schemaApi.deleteRule(kbId, r.id), () => '규칙을 삭제했습니다. 이미 반영된 데이터는 그대로입니다 — "규칙 미반영 문서 재정규화"를 누르면 다시 적용됩니다(텍스트 문서는 리플레이).')}>
                                    <Trash2 size={12} />
                                </button>
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </div>
    );
}
