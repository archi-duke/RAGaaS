import React, { useEffect, useState } from 'react';
import { X, AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import { docApi } from '../services/api';

interface MatchedItem {
    candidate: string;
    existing: string;
}

interface SimilarItem {
    candidate: string;
    suggested: string;
    score: number;
}

interface AlignmentSection {
    matched: MatchedItem[];
    similar: SimilarItem[];
    new: string[];
}

export interface Alignment {
    existing_empty: boolean;
    disjoint: boolean;
    has_mismatch: boolean;
    classes: AlignmentSection;
    properties: AlignmentSection;
    existing_classes: string[];
    existing_properties: string[];
}

interface Decision {
    action: 'merge' | 'map' | 'create';
    target?: string;
}

type DecisionMap = Record<string, Decision>;

interface AlignmentReviewModalProps {
    isOpen: boolean;
    onClose: () => void;
    kbId?: string;
    docId?: string;
    alignment?: Alignment | null;
    onResolved: () => void;
}

// Build the initial per-candidate decision state from an alignment section:
// - "similar" items default to merging into the suggested existing name.
// - "new" items default to creating a brand new class/property.
function buildInitialDecisions(section?: AlignmentSection): DecisionMap {
    const initial: DecisionMap = {};
    if (!section) return initial;
    for (const item of section.similar || []) {
        initial[item.candidate] = { action: 'merge', target: item.suggested };
    }
    for (const candidate of section.new || []) {
        initial[candidate] = { action: 'create' };
    }
    return initial;
}

function SectionEditor({
    title,
    section,
    existingOptions,
    decisions,
    setDecision,
}: {
    title: string;
    section?: AlignmentSection;
    existingOptions: string[];
    decisions: DecisionMap;
    setDecision: (candidate: string, decision: Decision) => void;
}) {
    const [showMatched, setShowMatched] = useState(false);

    const similar = section?.similar || [];
    const newItems = section?.new || [];
    const matched = section?.matched || [];

    if (similar.length === 0 && newItems.length === 0 && matched.length === 0) {
        return null;
    }

    return (
        <div style={{ marginBottom: '1.5rem' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: '0 0 0.75rem 0' }}>{title}</h3>

            {similar.map((item) => {
                const decision = decisions[item.candidate] || { action: 'merge', target: item.suggested };
                const pct = Math.round((item.score || 0) * 100);
                return (
                    <div
                        key={`similar-${item.candidate}`}
                        style={{
                            border: '1px solid var(--border)',
                            borderRadius: '8px',
                            padding: '0.75rem 1rem',
                            marginBottom: '0.5rem',
                        }}
                    >
                        <div style={{ fontWeight: 500, marginBottom: '0.5rem' }}>
                            「{item.candidate}」
                            <span style={{ marginLeft: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                유사 항목 발견 ({pct}% 일치)
                            </span>
                        </div>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem', cursor: 'pointer' }}>
                            <input
                                type="radio"
                                name={`similar-${title}-${item.candidate}`}
                                checked={decision.action === 'merge'}
                                onChange={() => setDecision(item.candidate, { action: 'merge', target: item.suggested })}
                            />
                            <span>
                                기존 「{item.suggested}」에 병합 ({pct}%)
                            </span>
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                            <input
                                type="radio"
                                name={`similar-${title}-${item.candidate}`}
                                checked={decision.action === 'create'}
                                onChange={() => setDecision(item.candidate, { action: 'create' })}
                            />
                            <span>신규 「{item.candidate}」 생성</span>
                        </label>
                    </div>
                );
            })}

            {newItems.map((candidate) => {
                const decision = decisions[candidate] || { action: 'create' };
                const mapTarget = decision.action === 'map' ? decision.target : undefined;
                return (
                    <div
                        key={`new-${candidate}`}
                        style={{
                            border: '1px solid var(--border)',
                            borderRadius: '8px',
                            padding: '0.75rem 1rem',
                            marginBottom: '0.5rem',
                        }}
                    >
                        <div style={{ fontWeight: 500, marginBottom: '0.5rem' }}>
                            「{candidate}」
                            <span style={{ marginLeft: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                기존 온톨로지에 없는 신규 항목
                            </span>
                        </div>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem', cursor: 'pointer' }}>
                            <input
                                type="radio"
                                name={`new-${title}-${candidate}`}
                                checked={decision.action === 'create'}
                                onChange={() => setDecision(candidate, { action: 'create' })}
                            />
                            <span>신규 「{candidate}」 생성</span>
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                            <input
                                type="radio"
                                name={`new-${title}-${candidate}`}
                                checked={decision.action === 'map'}
                                disabled={existingOptions.length === 0}
                                onChange={() =>
                                    setDecision(candidate, {
                                        action: 'map',
                                        target: mapTarget || existingOptions[0],
                                    })
                                }
                            />
                            <span>기존에 매핑…</span>
                            {decision.action === 'map' && (
                                <select
                                    value={mapTarget || existingOptions[0] || ''}
                                    onChange={(e) => setDecision(candidate, { action: 'map', target: e.target.value })}
                                    style={{
                                        marginLeft: '0.5rem',
                                        padding: '0.25rem 0.5rem',
                                        borderRadius: '4px',
                                        border: '1px solid var(--border)',
                                    }}
                                >
                                    {existingOptions.map((opt) => (
                                        <option key={opt} value={opt}>
                                            {opt}
                                        </option>
                                    ))}
                                </select>
                            )}
                        </label>
                    </div>
                );
            })}

            {matched.length > 0 && (
                <div style={{ marginTop: '0.5rem' }}>
                    <button
                        type="button"
                        onClick={() => setShowMatched(!showMatched)}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.25rem',
                            background: 'none',
                            border: 'none',
                            padding: 0,
                            cursor: 'pointer',
                            color: 'var(--text-secondary)',
                            fontSize: '0.85rem',
                        }}
                    >
                        {showMatched ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        자동 정렬됨 ({matched.length})
                    </button>
                    {showMatched && (
                        <ul style={{ margin: '0.5rem 0 0 1.25rem', padding: 0, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                            {matched.map((m) => (
                                <li key={m.candidate}>
                                    「{m.candidate}」 → 「{m.existing}」
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </div>
    );
}

export default function AlignmentReviewModal({
    isOpen,
    onClose,
    kbId,
    docId,
    alignment,
    onResolved,
}: AlignmentReviewModalProps) {
    const [classDecisions, setClassDecisions] = useState<DecisionMap>({});
    const [propertyDecisions, setPropertyDecisions] = useState<DecisionMap>({});
    const [isSubmitting, setIsSubmitting] = useState(false);

    useEffect(() => {
        if (isOpen && alignment) {
            setClassDecisions(buildInitialDecisions(alignment.classes));
            setPropertyDecisions(buildInitialDecisions(alignment.properties));
        }
    }, [isOpen, alignment]);

    if (!isOpen || !alignment) return null;

    const setClassDecision = (candidate: string, decision: Decision) => {
        setClassDecisions((prev) => ({ ...prev, [candidate]: decision }));
    };
    const setPropertyDecision = (candidate: string, decision: Decision) => {
        setPropertyDecisions((prev) => ({ ...prev, [candidate]: decision }));
    };

    const handleSubmit = async () => {
        if (!kbId || !docId) return;
        setIsSubmitting(true);
        try {
            const decisions = {
                classes: classDecisions,
                properties: propertyDecisions,
            };
            await docApi.resolveAlignment(kbId, docId, decisions);
            onResolved();
        } catch (error) {
            console.error('Failed to resolve alignment:', error);
            alert('정렬 검토 결과를 저장하지 못했습니다. 다시 시도해주세요.');
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div
            style={{
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                backgroundColor: 'rgba(0,0,0,0.6)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                zIndex: 60,
            }}
        >
            <div
                className="card"
                style={{
                    width: '100%',
                    maxWidth: '800px',
                    maxHeight: '85vh',
                    overflow: 'hidden',
                    display: 'flex',
                    flexDirection: 'column',
                }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: '1rem',
                    borderBottom: '1px solid var(--border)',
                    paddingBottom: '1rem',
                }}>
                    <div>
                        <h2 style={{ margin: 0, fontSize: '1.25rem' }}>온톨로지 정렬 검토</h2>
                        <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                            이 문서의 스키마 중 기존 온톨로지와 다른 항목이 있습니다. 어떻게 반영할지 선택하세요.
                        </p>
                    </div>
                    <button className="btn" onClick={onClose} style={{ padding: '0.5rem' }}>
                        <X size={20} />
                    </button>
                </div>

                {/* Body */}
                <div style={{ flex: 1, overflow: 'auto', marginBottom: '1rem' }}>
                    {alignment.disjoint && (
                        <div style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: '0.5rem',
                            backgroundColor: '#fef3c7',
                            border: '1px solid #f59e0b',
                            borderRadius: '8px',
                            padding: '0.75rem 1rem',
                            marginBottom: '1rem',
                            color: '#92400e',
                        }}>
                            <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '0.1rem' }} />
                            <span style={{ fontSize: '0.9rem' }}>
                                이 문서는 기존 온톨로지와 겹치는 개념이 없습니다(무관 스키마). 별도 KB 사용을 권장합니다.
                            </span>
                        </div>
                    )}

                    <SectionEditor
                        title="클래스"
                        section={alignment.classes}
                        existingOptions={alignment.existing_classes || []}
                        decisions={classDecisions}
                        setDecision={setClassDecision}
                    />
                    <SectionEditor
                        title="속성"
                        section={alignment.properties}
                        existingOptions={alignment.existing_properties || []}
                        decisions={propertyDecisions}
                        setDecision={setPropertyDecision}
                    />
                </div>

                {/* Footer Actions */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'flex-end',
                    gap: '1rem',
                    borderTop: '1px solid var(--border)',
                    paddingTop: '1rem',
                }}>
                    <button
                        className="btn"
                        onClick={onClose}
                        disabled={isSubmitting}
                        style={{ minWidth: '100px' }}
                    >
                        취소
                    </button>
                    <button
                        className="btn btn-primary"
                        onClick={handleSubmit}
                        disabled={isSubmitting}
                        style={{ minWidth: '120px' }}
                    >
                        {isSubmitting ? '저장 중...' : '적용하고 저장'}
                    </button>
                </div>
            </div>
        </div>
    );
}
