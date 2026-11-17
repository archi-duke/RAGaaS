import React, { useCallback, useEffect, useRef, useState } from 'react';
import { X as XIcon, Play, RotateCcw, AlertTriangle } from 'lucide-react';
import { schemaApi } from '../services/api';

// 스키마 기준 재추출 (승격 L2, 옵션) — docs/design/schema/design-graph-promotion.md §3(c) L2
interface Props {
    kbId: string;
    onClose: () => void;
    onChanged?: () => void;
}

const STATE_LABELS: Record<string, string> = {
    queued: '대기', running: '추출 중', done: '완료', failed: '실패', reverted: '되돌림',
};

export default function ReextractModal({ kbId, onClose, onChanged }: Props) {
    const [est, setEst] = useState<any>(null);
    const [status, setStatus] = useState<any>(null);
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [model, setModel] = useState<string>('ingest');
    const [agreed, setAgreed] = useState(false);
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState('');
    const timer = useRef<any>(null);

    const load = useCallback(async () => {
        const r = await schemaApi.reextractEstimate(kbId);
        setEst(r.data);
        setSelected(new Set((r.data.documents || []).map((d: any) => d.id)));
        if (r.data.last_run) setStatus(r.data.last_run);
    }, [kbId]);

    useEffect(() => { load().catch((e) => setMessage(`정보를 불러오지 못했습니다: ${e?.message || e}`)); }, [load]);

    const poll = useCallback(() => {
        clearInterval(timer.current);
        timer.current = setInterval(async () => {
            const r = await schemaApi.reextractStatus(kbId);
            setStatus(r.data);
            if (r.data?.status !== 'running') {
                clearInterval(timer.current);
                onChanged?.();
            }
        }, 3000);
    }, [kbId, onChanged]);

    useEffect(() => () => clearInterval(timer.current), []);
    useEffect(() => { if (status?.status === 'running') poll(); }, [status?.status, poll]);

    const docs: any[] = est?.documents || [];
    const chunkSum = docs.filter((d) => selected.has(d.id)).reduce((a, d) => a + (d.chunks || 0), 0);
    const running = status?.status === 'running';

    const start = async () => {
        setBusy(true);
        setMessage('');
        try {
            const r = await schemaApi.reextract(kbId, Array.from(selected), model);
            setMessage(`재추출을 시작했습니다 (문서 ${r.data.queued.length}건, 모델 ${r.data.model}).`);
            setStatus({ status: 'running', docs: {} });
            poll();
        } catch (e: any) {
            setMessage(`시작하지 못했습니다: ${e?.response?.data?.detail || e?.message || e}`);
        } finally {
            setBusy(false);
        }
    };

    const revert = async () => {
        if (!confirm('마지막 재추출 직전의 그래프로 되돌릴까요?')) return;
        setBusy(true);
        try {
            const r = await schemaApi.reextractRevert(kbId);
            setMessage(`되돌렸습니다: 문서 ${(r.data.reverted || []).filter((x: any) => !x.error).length}건`);
            const s = await schemaApi.reextractStatus(kbId);
            setStatus(s.data);
            onChanged?.();
        } catch (e: any) {
            setMessage(`되돌리지 못했습니다: ${e?.response?.data?.detail || e?.message || e}`);
        } finally {
            setBusy(false);
        }
    };

    const sec = { fontSize: '0.83rem', lineHeight: 1.6, margin: '0.25rem 0 0.75rem' } as const;

    return (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
            onClick={onClose}>
            <div className="card" style={{ width: 'min(860px, 94vw)', maxHeight: '88vh', overflowY: 'auto', padding: '1.25rem' }}
                onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h3 style={{ margin: 0 }}>스키마 기준 재추출 <span style={{ fontSize: '0.8rem', fontWeight: 400, opacity: 0.7 }}>(옵션)</span></h3>
                    <button className="btn btn-secondary" onClick={onClose}><XIcon size={14} /></button>
                </div>

                <h4 style={{ margin: '1rem 0 0.25rem' }}>무엇을 하나요</h4>
                <p style={sec}>
                    승격으로 확정한 스키마(클래스·속성·허용 값)를 기준으로, 이미 저장된 문서 청크에서 정보를 <b>다시 추출</b>합니다.
                    처음 추출은 스키마 없이 자유롭게 관계를 뽑아 이름이 제각각이고 조건 묶음이 한 문장으로 뭉치기 쉽습니다.
                    재추출은 스키마의 속성 이름만 쓰고, "A이거나 B일 때" 같은 묶음을 조건마다 나누며, 개수 제한 없이 뽑습니다.
                </p>

                <h4 style={{ margin: '0.5rem 0 0.25rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <AlertTriangle size={16} color="#b45309" /> 주의할 점
                </h4>
                <ul style={{ ...sec, paddingLeft: '1.2rem' }}>
                    <li><b>비용이 듭니다.</b> 청크마다 LLM 을 한 번씩 호출합니다 (선택한 문서의 청크 {chunkSum}개).</li>
                    <li><b>결과는 스키마 품질에 좌우됩니다.</b> 스키마에 없는 구조는 정밀하게 나오지 않습니다. 먼저 "스키마 정렬"에서 승격 초안을 충분히 검토하세요.</li>
                    <li><b>스키마 밖 사실은 버리지 않습니다.</b> 따로 저장하고, 완료 후 새 속성·값 제안으로 올라옵니다.</li>
                    <li><b>근거는 유지됩니다.</b> 청크를 다시 나누거나 임베딩하지 않아 트리플의 근거 청크가 그대로입니다.</li>
                    <li><b>되돌릴 수 있습니다.</b> 직전 추출 결과를 보관해 두고 아래 "되돌리기"로 복원합니다.</li>
                    <li>진행 중에는 해당 문서의 그래프 검색 결과가 잠시 바뀔 수 있습니다.</li>
                </ul>

                {!est ? <div style={sec}>불러오는 중…</div> : (
                    <>
                        {!est.eligible && <div style={{ ...sec, color: 'tomato' }}>{est.reason || '실행 조건을 만족하지 않습니다.'}</div>}
                        <div style={sec}>스키마: 클래스 {est.schema?.classes}개, 속성 {est.schema?.properties}개</div>

                        <h4 style={{ margin: '0.5rem 0 0.25rem' }}>대상 문서 (텍스트)</h4>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                            <thead>
                                <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--border)' }}>
                                    <th style={{ width: '2rem' }}>
                                        <input type="checkbox" checked={selected.size === docs.length && docs.length > 0}
                                            onChange={(e) => setSelected(e.target.checked ? new Set(docs.map((d) => d.id)) : new Set())} />
                                    </th>
                                    <th>문서</th><th>청크</th><th>현재 트리플</th><th>상태</th><th>결과</th>
                                </tr>
                            </thead>
                            <tbody>
                                {docs.map((d) => {
                                    const s = status?.docs?.[d.id];
                                    return (
                                        <tr key={d.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                            <td><input type="checkbox" disabled={running} checked={selected.has(d.id)}
                                                onChange={(e) => {
                                                    const n = new Set(selected);
                                                    if (e.target.checked) n.add(d.id); else n.delete(d.id);
                                                    setSelected(n);
                                                }} /></td>
                                            <td>{d.filename}</td>
                                            <td>{d.chunks}</td>
                                            <td>{d.triples}</td>
                                            <td>{s ? STATE_LABELS[s.state] || s.state : '-'}</td>
                                            <td style={{ fontSize: '0.75rem' }}>
                                                {s?.state === 'done' && <>트리플 {s.triples_before ?? '-'} → {s.triples} · 스키마 밖 {s.out_of_schema}{s.chunk_failures ? ` · 실패 청크 ${s.chunk_failures}` : ''}</>}
                                                {s?.state === 'failed' && <span style={{ color: 'tomato' }}>{s.error}</span>}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>

                        <h4 style={{ margin: '0.75rem 0 0.25rem' }}>추출 모델</h4>
                        <div style={sec}>
                            {Object.entries(est.models || {}).map(([k, m]) => (
                                <label key={k} style={{ marginRight: '1rem' }}>
                                    <input type="radio" name="rx-model" value={k} checked={model === k} disabled={running}
                                        onChange={() => setModel(k)} />{' '}
                                    {k === 'ingest' ? 'KB 추출 모델' : '그래프 검색 모델'} ({String(m)})
                                </label>
                            ))}
                        </div>

                        <label style={{ ...sec, display: 'block' }}>
                            <input type="checkbox" checked={agreed} disabled={running} onChange={(e) => setAgreed(e.target.checked)} />{' '}
                            위 주의할 점을 이해했고, 선택한 문서를 재추출합니다.
                        </label>

                        {message && <div style={{ ...sec, color: '#1e40af' }}>{message}</div>}
                        {status?.status && (
                            <div style={sec}>마지막 실행: {status.status === 'running' ? '진행 중' : '완료'}
                                {status.model ? ` · 모델 ${status.model}` : ''}{status.finished_at ? ` · ${String(status.finished_at).slice(0, 19)}` : ''}
                            </div>
                        )}

                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                            <button className="btn btn-secondary" disabled={busy || running || !status?.docs}
                                onClick={revert} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                                <RotateCcw size={14} /> 되돌리기
                            </button>
                            <button className="btn btn-primary" disabled={!est.eligible || !agreed || busy || running || selected.size === 0}
                                onClick={start} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                                <Play size={14} /> {running ? '진행 중…' : '재추출 실행'}
                            </button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
