/**
 * useModelSettings — 사용자별 LLM/Embedding 모델 설정을 localStorage에서 관리합니다.
 * 브라우저(사용자) 단위로 독립적으로 저장되며, 앱 전역에서 공유됩니다.
 */
import { useState, useCallback } from 'react';
import { DEFAULT_LLM_CONFIG, type ModelConfig } from '../components/ModelSelector';

const STORAGE_KEY = 'ragaas_model_settings';

export interface ModelSettings {
    // Ingest (Upload)
    ingest_llm: ModelConfig;          // Chunk/Node Processing LLM (LlamaIndex)
    chunk_grouping_llm: ModelConfig;  // Chunk Grouping LLM
    subject_restoration_llm: ModelConfig; // 주어 복원 LLM
    noun_extraction_llm: ModelConfig; // 명사 추출 LLM

    // Retrieval / Chat
    chat_llm: ModelConfig;            // 최종 답변 생성 LLM
    keyword_llm: ModelConfig;         // BM25 키워드 추출 LLM
    graph_query_llm: ModelConfig;     // 그래프 쿼리(SPARQL/Cypher) 생성 LLM
}

const DEFAULT_SETTINGS: ModelSettings = {
    ingest_llm: DEFAULT_LLM_CONFIG,
    chunk_grouping_llm: DEFAULT_LLM_CONFIG,
    subject_restoration_llm: DEFAULT_LLM_CONFIG,
    noun_extraction_llm: DEFAULT_LLM_CONFIG,
    chat_llm: DEFAULT_LLM_CONFIG,
    keyword_llm: { ...DEFAULT_LLM_CONFIG, model: 'gpt-3.5-turbo' },
    graph_query_llm: DEFAULT_LLM_CONFIG,
};

function loadSettings(): ModelSettings {
    try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
            return { ...DEFAULT_SETTINGS, ...JSON.parse(saved) };
        }
    } catch {
        // ignore
    }
    return DEFAULT_SETTINGS;
}

function saveSettings(settings: ModelSettings): void {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
        // ignore
    }
}

export function useModelSettings() {
    const [settings, setSettings] = useState<ModelSettings>(loadSettings);

    const updateSetting = useCallback(<K extends keyof ModelSettings>(
        key: K,
        value: ModelSettings[K]
    ) => {
        setSettings(prev => {
            const next = { ...prev, [key]: value };
            saveSettings(next);
            return next;
        });
    }, []);

    const resetSettings = useCallback(() => {
        saveSettings(DEFAULT_SETTINGS);
        setSettings(DEFAULT_SETTINGS);
    }, []);

    return { settings, updateSetting, resetSettings };
}
