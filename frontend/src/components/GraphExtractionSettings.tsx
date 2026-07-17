import React, { useState } from 'react';
import { Database } from 'lucide-react';
import ModelSelector, { DEFAULT_LLM_CONFIG, type ModelConfig } from './ModelSelector';

interface GraphParams {
    extractor_type: 'simple' | 'dynamic' | 'schema';
    max_paths_per_chunk: number;
    max_triplets_per_chunk: number;
    num_workers: number;
    generate_inverse_relations: boolean;
    allowed_entity_types: string[];
    allowed_relation_types: string[];
    chunk_size: number;
    extraction_examples_yaml: string;
    custom_prompt: string;
    enable_entity_normalization: boolean;
    enable_entity_typing: boolean;
    normalization_algorithm: 'embedding' | 'string' | 'llm';
    normalization_threshold: number;
    max_sample_size: number;
    enable_normalization_confirmation: boolean;
    enable_text_cleaning: boolean;
    enable_subject_restoration: boolean;
    enable_inference: boolean;
}

interface GraphExtractionSettingsProps {
    graphParams: GraphParams;
    onParamsChange: (params: GraphParams) => void;
    onManageExamples: () => void;
    onEditPrompt: () => void;
    showEntitySample?: boolean;
    showExtractorType?: boolean;
    // LLM model configs (from central settings)
    ingestLlm?: ModelConfig;
    onIngestLlmChange?: (cfg: ModelConfig) => void;
}

const LabelWithTooltip = ({ label, tooltip }: { label: string, tooltip: string }) => {
    const [show, setShow] = useState(false);
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.3rem', position: 'relative' }}>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>{label}</label>
            <div
                style={{ cursor: 'help', display: 'flex', alignItems: 'center' }}
                onMouseEnter={() => setShow(true)}
                onMouseLeave={() => setShow(false)}
            >
                <div style={{
                    width: '14px', height: '14px', borderRadius: '50%', border: '1px solid #94a3b8',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '9px', color: '#94a3b8', fontWeight: 'bold', flexShrink: 0, lineHeight: 1
                }}>i</div>
                {show && (
                    <div style={{
                        position: 'absolute', bottom: '120%', left: '0',
                        backgroundColor: '#333', color: '#fff', padding: '0.5rem 0.75rem',
                        borderRadius: '4px', fontSize: '0.75rem', whiteSpace: 'normal',
                        width: '200px', zIndex: 100, boxShadow: '0 2px 8px rgba(0,0,0,0.2)', pointerEvents: 'none'
                    }}>
                        {tooltip}
                        <div style={{
                            position: 'absolute', top: '100%', left: '10px',
                            borderWidth: '5px', borderStyle: 'solid',
                            borderColor: '#333 transparent transparent transparent'
                        }}></div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default function GraphExtractionSettings({
    graphParams,
    onParamsChange,
    onManageExamples,
    onEditPrompt,
    showEntitySample = true,
    showExtractorType = false,
    ingestLlm = DEFAULT_LLM_CONFIG,
    onIngestLlmChange,
}: GraphExtractionSettingsProps) {
    const [isMaxPathsUnlimited, setIsMaxPathsUnlimited] = useState(graphParams.max_paths_per_chunk >= 1000);

    const updateParams = (updates: Partial<GraphParams>) => {
        onParamsChange({ ...graphParams, ...updates });
    };

    return (
        <div style={{ marginBottom: '1.5rem', background: '#eff6ff', padding: '15px', borderRadius: '12px', border: '1px solid #bfdbfe' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1.25rem', color: '#3b82f6', fontWeight: 600 }}>
                <Database size={18} />
                <span>Graph Extraction Settings (LlamaIndex)</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
                {/* Configuration Column */}
                <div>
                    <h4 style={{ margin: '0 0 1rem 0', fontSize: '0.9rem', color: '#475569' }}>Configuration</h4>

                    {showExtractorType && (
                        <div style={{ marginBottom: '1rem' }}>
                            <LabelWithTooltip label="Extractor Type" tooltip="Select LlamaIndex extractor type" />
                            <select
                                className="input"
                                value={graphParams.extractor_type}
                                onChange={(e) => updateParams({ extractor_type: e.target.value as 'simple' | 'dynamic' | 'schema' })}
                                style={{ width: '100%', padding: '0.5rem', fontSize: '0.85rem' }}
                            >
                                <option value="simple">Simple LLM (Default)</option>
                                <option value="dynamic">Dynamic LLM</option>
                                <option value="schema">Schema-based</option>
                            </select>
                        </div>
                    )}

                    {showEntitySample && graphParams.max_sample_size !== undefined && (
                        <div style={{ marginBottom: '1rem' }}>
                            <LabelWithTooltip
                                label={`Entity Sample: ${graphParams.max_sample_size / 1000}k`}
                                tooltip="Text sample size for entity dictionary building"
                            />
                            <input
                                type="range"
                                min="10000"
                                max="100000"
                                step="10000"
                                value={graphParams.max_sample_size}
                                onChange={(e) => updateParams({ max_sample_size: parseInt(e.target.value) })}
                                style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                            />
                        </div>
                    )}

                    {(!showExtractorType || graphParams.extractor_type === 'simple') && (
                        <div style={{ marginBottom: '1rem' }}>
                            <div style={{ marginBottom: '0.3rem' }}>
                                <LabelWithTooltip
                                    label={`Max Paths: ${isMaxPathsUnlimited ? '∞' : graphParams.max_paths_per_chunk}`}
                                    tooltip="Max graph paths to extract per chunk"
                                />
                                {!showExtractorType && (
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.75rem', cursor: 'pointer', color: '#334155', marginTop: '0.2rem', marginBottom: '0.4rem' }}>
                                        <input
                                            type="checkbox"
                                            checked={isMaxPathsUnlimited}
                                            onChange={(e) => {
                                                const isUnlimited = e.target.checked;
                                                setIsMaxPathsUnlimited(isUnlimited);
                                                updateParams({ max_paths_per_chunk: isUnlimited ? 1000 : 20 });
                                            }}
                                            style={{ width: '0.85rem', height: '0.85rem', accentColor: '#3b82f6' }}
                                        />
                                        Unlimited
                                    </label>
                                )}
                            </div>
                            <input
                                type="range"
                                min="5"
                                max="50"
                                step="5"
                                disabled={!showExtractorType && isMaxPathsUnlimited}
                                value={(!showExtractorType && isMaxPathsUnlimited) ? 50 : graphParams.max_paths_per_chunk}
                                onChange={(e) => updateParams({ max_paths_per_chunk: parseInt(e.target.value) })}
                                style={{
                                    width: '100%',
                                    cursor: (!showExtractorType && isMaxPathsUnlimited) ? 'not-allowed' : 'pointer',
                                    accentColor: '#3b82f6',
                                    opacity: (!showExtractorType && isMaxPathsUnlimited) ? 0.5 : 1
                                }}
                            />
                        </div>
                    )}

                    {showExtractorType && graphParams.extractor_type === 'dynamic' && graphParams.max_triplets_per_chunk !== undefined && (
                        <div style={{ marginBottom: '1rem' }}>
                            <LabelWithTooltip
                                label={`Max Triplets: ${graphParams.max_triplets_per_chunk}`}
                                tooltip="Max triples per chunk"
                            />
                            <input
                                type="range"
                                min="10"
                                max="100"
                                step="10"
                                value={graphParams.max_triplets_per_chunk}
                                onChange={(e) => updateParams({ max_triplets_per_chunk: parseInt(e.target.value) })}
                                style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                            />
                        </div>
                    )}

                    <div>
                        <LabelWithTooltip
                            label={`Workers: ${graphParams.num_workers}`}
                            tooltip="Number of parallel workers"
                        />
                        <input
                            type="range"
                            min="1"
                            max="8"
                            step="1"
                            value={graphParams.num_workers}
                            onChange={(e) => updateParams({ num_workers: parseInt(e.target.value) })}
                            style={{ width: '100%', cursor: 'pointer', accentColor: '#3b82f6' }}
                        />
                    </div>
                </div>

                {/* Options Column */}
                <div>
                    <h4 style={{ margin: '0 0 1rem 0', fontSize: '0.9rem', color: '#475569' }}>Options</h4>

                    {/* Triple Extraction LLM — always active in graph mode */}
                    {onIngestLlmChange && (
                        <div style={{ marginBottom: '1rem' }}>
                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', marginBottom: '0.4rem' }}>
                                <div style={{
                                    width: '1.1rem', height: '1.1rem', borderRadius: '3px',
                                    background: '#3b82f6', display: 'flex', alignItems: 'center',
                                    justifyContent: 'center', flexShrink: 0, marginTop: '2px'
                                }}>
                                    <svg width="9" height="7" viewBox="0 0 9 7" fill="none">
                                        <path d="M1 3.5L3.5 6L8 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                                    </svg>
                                </div>
                                <div>
                                    <span style={{ color: '#334155', fontWeight: 500, fontSize: '0.9rem' }}>Triple Extraction</span>
                                    <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Graph triple extraction &amp; entity grouping</div>
                                </div>
                            </div>
                            <div style={{ marginLeft: '1.6rem' }}>
                                <ModelSelector
                                    type="llm"
                                    value={ingestLlm}
                                    onChange={onIngestLlmChange}
                                />
                            </div>
                        </div>
                    )}

                    {/* Entity Typing */}
                    <div style={{ marginBottom: '1rem' }}>
                        <label style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', cursor: 'pointer' }}>
                            <input
                                type="checkbox"
                                checked={graphParams.enable_entity_typing}
                                onChange={(e) => updateParams({ enable_entity_typing: e.target.checked })}
                                style={{ width: '1.1rem', height: '1.1rem', accentColor: '#3b82f6', flexShrink: 0, marginTop: '2px' }}
                            />
                            <div>
                                <span style={{ color: '#334155', fontWeight: 500, fontSize: '0.9rem' }}>엔티티 타입 자동 분류 (rdf:type)</span>
                                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>인제스트 시 각 엔티티에 클래스 타입을 부여합니다 (온톨로지 승격 품질 향상)</div>
                            </div>
                        </label>
                    </div>
                </div>

                {/* Customization Column */}
                <div>
                    <h4 style={{ margin: '0 0 1rem 0', fontSize: '0.9rem', color: '#475569' }}>Customization</h4>

                    <button
                        className="btn"
                        style={{ width: '100%', marginBottom: '0.75rem', justifyContent: 'center', background: '#fff', border: '1px solid #cbd5e1' }}
                        onClick={onManageExamples}
                    >
                        Manage Examples
                    </button>

                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'default', marginBottom: '1.25rem', justifyContent: 'center' }}>
                        <input
                            type="checkbox"
                            checked={!!graphParams.extraction_examples_yaml}
                            readOnly
                            style={{ width: '0.9rem', height: '0.9rem', accentColor: '#3b82f6' }}
                        />
                        <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Examples Added</span>
                    </label>

                    <button
                        className="btn"
                        style={{ width: '100%', marginBottom: '0.75rem', justifyContent: 'center', background: '#fff', border: '1px solid #cbd5e1' }}
                        onClick={onEditPrompt}
                    >
                        Edit Extraction Prompt
                    </button>

                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'default', justifyContent: 'center' }}>
                        <input
                            type="checkbox"
                            checked={!!graphParams.custom_prompt}
                            readOnly
                            style={{ width: '0.9rem', height: '0.9rem', accentColor: '#3b82f6' }}
                        />
                        <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Custom Prompt Active</span>
                    </label>
                </div>
            </div>
        </div>
    );
}
