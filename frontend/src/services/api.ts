import axios from 'axios';

const api = axios.create({
    baseURL: 'http://127.0.0.1:8000/api/',
    headers: {
        'Content-Type': 'application/json',
    },
});

export const kbApi = {
    list: () => api.get('knowledge-bases/'),
    create: (data: { name: string; description: string; chunking_strategy: string; chunking_config: any; metric_type?: string; graph_backend?: 'none' | 'ontology' | 'neo4j'; ontology_schema?: string }) => api.post('knowledge-bases/', data),
    extractSchema: (file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        return api.post('knowledge-bases/extract-schema', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
    },
    get: (id: string) => api.get(`knowledge-bases/${id}`),
    delete: (id: string) => api.delete(`knowledge-bases/${id}`),
    promote: (id: string, payload: any = {}) => api.post(`knowledge-bases/${id}/promote`, payload),
    getExtractionRules: () => api.get('knowledge-bases/extraction-rules/content'),
    validateExtractionRules: (content: string) => api.post('knowledge-bases/extraction-rules/validate', { content }),
    saveExtractionRules: (content: string) => api.post('knowledge-bases/extraction-rules/save', { content }),
    getExtractionPrompt: () => api.get('knowledge-bases/extraction-prompt/content'),
    saveExtractionPrompt: (content: string) => api.post('knowledge-bases/extraction-prompt/save', { content }),
    getQueryPrompt: (type: 'ontology_plus' | 'ontology_minus' | 'neo4j' = 'ontology_minus') => api.get('knowledge-bases/query-prompt/content', { params: { type } }),
    getTriples: (kbId: string, backend: string, skip: number = 0, limit: number = 50, sort?: any, filter?: any) => api.get(`graph/triples/${kbId}`, { params: { backend, skip, limit, include_chunk_text: false, sort: sort ? JSON.stringify(sort) : undefined, filter: filter ? JSON.stringify(filter) : undefined } }),
    getChunk: (kbId: string, chunkId: string) => api.get(`knowledge-bases/${kbId}/chunks/${chunkId}`),
};

export const docApi = {
    list: (kbId: string) => api.get(`knowledge-bases/${kbId}/documents`),
    upload: (kbId: string, file: File, config?: any) => {
        const formData = new FormData();
        formData.append('file', file);
        if (config) {
            formData.append('chunking_config', JSON.stringify(config));
            // Send enable_text_cleaning as separate form field
            if (config.enable_text_cleaning !== undefined) {
                formData.append('enable_text_cleaning', String(config.enable_text_cleaning));
            }
            // Send enable_subject_restoration as separate form field
            if (config.enable_subject_restoration !== undefined) {
                formData.append('enable_subject_restoration', String(config.enable_subject_restoration));
            }
            // Send enable_inference as separate form field
            if (config.enable_inference !== undefined) {
                formData.append('enable_inference', String(config.enable_inference));
            }
            // Send extraction_examples_yaml as separate form field
            if (config.extraction_examples_yaml) {
                formData.append('extraction_examples_yaml', config.extraction_examples_yaml);
            }
            // Send Entity Normalization parameters
            if (config.enable_entity_normalization !== undefined) {
                formData.append('enable_entity_normalization', String(config.enable_entity_normalization));
            }
            if (config.normalization_algorithm) {
                formData.append('normalization_algorithm', config.normalization_algorithm);
            }
            if (config.normalization_threshold !== undefined) {
                formData.append('normalization_threshold', String(config.normalization_threshold));
            }
            if (config.enable_normalization_confirmation !== undefined) {
                formData.append('enable_normalization_confirmation', String(config.enable_normalization_confirmation));
            }
            if (config.entity_dictionary) {
                formData.append('entity_dictionary', JSON.stringify(config.entity_dictionary));
            }
        }
        return api.post(`knowledge-bases/${kbId}/documents`, formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
    },

    delete: (kbId: string, docId: string) => api.delete(`knowledge-bases/${kbId}/documents/${docId}`),
    uploadText: (kbId: string, title: string, content: string, config?: any) => {
        const payload: any = { title, content };
        if (config) {
            payload.chunking_config = JSON.stringify(config);
            if (config.enable_text_cleaning !== undefined) payload.enable_text_cleaning = config.enable_text_cleaning;
            if (config.enable_subject_restoration !== undefined) payload.enable_subject_restoration = config.enable_subject_restoration;
            if (config.extraction_examples_yaml) payload.extraction_examples_yaml = config.extraction_examples_yaml;
            if (config.enable_entity_normalization !== undefined) payload.enable_entity_normalization = config.enable_entity_normalization;
            if (config.normalization_algorithm) payload.normalization_algorithm = config.normalization_algorithm;
            if (config.normalization_threshold !== undefined) payload.normalization_threshold = config.normalization_threshold;
            if (config.enable_normalization_confirmation !== undefined) payload.enable_normalization_confirmation = config.enable_normalization_confirmation;
        }
        return api.post(`knowledge-bases/${kbId}/documents/upload-text`, payload);
    },

    getChunks: (kbId: string, docId: string) => api.get(`knowledge-bases/${kbId}/documents/${docId}/chunks`),
    updateChunk: (kbId: string, docId: string, chunkId: string, content: string) => {
        const formData = new FormData();
        formData.append('content', content);
        return api.put(`knowledge-bases/${kbId}/documents/${docId}/chunks/${chunkId}`, formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
    },
    update: (kbId: string, docId: string, data: { extraction_examples?: string; custom_prompt?: string }) =>
        api.patch(`knowledge-bases/${kbId}/documents/${docId}`, data),


    // [New] Fetch Pipeline Data (Large JSONs) on demand
    getPipelineData: (kbId: string, docId: string) =>
        api.get(`knowledge-bases/${kbId}/documents/${docId}/pipeline/data`),
};

export const retrievalApi = {
    retrieve: (kbId: string, data: {
        query: string;
        top_k: number;
        score_threshold: number;
        strategy: string;
        use_reranker?: boolean;
        reranker_top_k?: number;
        reranker_threshold?: number;
        use_llm_reranker?: boolean;
        llm_chunk_strategy?: string;
        use_ner?: boolean;
        use_llm_keyword_extraction?: boolean;
        enable_graph_search?: boolean;
        graph_hops?: number;
        use_brute_force?: boolean;
        brute_force_top_k?: number;
        brute_force_threshold?: number;
        enable_inverse_search?: boolean;
        inverse_extraction_mode?: 'always' | 'auto';
    }) => api.post(`knowledge-bases/${kbId}/retrieve`, data),
    chat: (kbId: string, data: {
        query: string;
        top_k?: number;
        score_threshold?: number;
        strategy?: string;
        use_reranker?: boolean;
        reranker_top_k?: number;
        reranker_threshold?: number;
        use_llm_reranker?: boolean;
        llm_chunk_strategy?: string;
        use_ner?: boolean;
        // BM25 Settings
        bm25_top_k?: number;
        use_llm_keyword_extraction?: boolean;
        use_multi_pos?: boolean;
        use_parallel_search?: boolean;
        // ANN Settings
        ann_top_k?: number;
        ann_threshold?: number;
        // Graph Settings
        enable_graph_search?: boolean;
        graph_hops?: number;
        // 2-Stage Settings
        use_brute_force?: boolean;
        brute_force_top_k?: number;
        brute_force_threshold?: number;
        // Inverse Search
        enable_inverse_search?: boolean;
        inverse_extraction_mode?: 'always' | 'auto';
        // Graph Relation Filter
        use_relation_filter?: boolean;
        // Schema Mode (for Promoted Ontology)
        use_schema_mode?: boolean;
        // Dynamic Schema (for non-promoted KB)
        use_dynamic_schema?: boolean;
        use_raw_log?: boolean;
        custom_query_prompt?: string;
        // Model configurations
        model_config?: any;
        model_config_keyword?: any;
        // Pipeline Configuration
        pipeline?: { stages: any[] };
    }) => api.post(`knowledge-bases/${kbId}/chat`, data),
};

// Ingest Service API (runs on port 8001)
const ingestApi = axios.create({
    baseURL: 'http://127.0.0.1:8001/api',
    // Set timeout to Infinity (0) to allow long-running extraction jobs
    timeout: 0,
    headers: {
        'Content-Type': 'application/json',
    },
});

export const extractionApi = {
    preview: (data: {
        kb_id: string;
        doc_id: string;
        file_path: string;
        chunking?: any;
        graph?: any;
        graph_store?: string;
        enable_text_cleaning?: boolean;
        enable_subject_restoration?: boolean;
        enable_entity_normalization?: boolean;
        normalization_algorithm?: string;
        normalization_threshold?: number;
        enable_normalization_confirmation?: boolean;
        extraction_examples_yaml?: string;
        custom_prompt?: string;
        entity_dictionary?: any;
        callback_url?: string;
    }) => ingestApi.post('/preview', data),

    confirm: (previewId: string, data?: {
        enable_inference?: boolean;
        callback_url?: string;
        kb_id?: string;
        doc_id?: string;
    }) => ingestApi.post(`/confirm/${previewId}`, data || {}),

    discard: (previewId: string) => ingestApi.delete(`/preview/${previewId}`),

    getJobStatus: (jobId: string) => ingestApi.get(`/jobs/${jobId}`),

    // Extract triples from a single chunk (for testing extraction settings)
    extractChunk: (data: {
        chunk_text: string;
        extractor_type?: string;
        max_paths_per_chunk?: number;
        max_triplets_per_chunk?: number;
        num_workers?: number;
        generate_inverse_relations?: boolean;
        enable_text_cleaning?: boolean;
        enable_subject_restoration?: boolean;
        extraction_examples_yaml?: string;
        custom_prompt?: string;
    }) => ingestApi.post('/extract-chunk', data),

    // Save selected triples from chunk extraction to the triple store
    saveChunkTriples: (data: {
        kb_id: string;
        chunk_id: string;
        triples: any[];
    }) => ingestApi.post('/save-chunk-triples', data),

    // [New] Doc2Graph Dictionary Preview
    previewDictionary: (data: {
        kb_id: string;
        doc_id: string;
        file_path: string;
        chunking?: any;
        sampling_size?: number;
        callback_url?: string;
    }) => ingestApi.post('/preview-dictionary', data),
};


export const providerApi = {
    /** built-in + custom 프로바이더 목록 통합 조회 */
    /** built-in + custom 프로바이더 목록. model_type 지정 시 LLM/Embedding 구분 조회 */
    list: (params?: { model_type?: 'llm' | 'embedding' }) =>
        api.get('providers', { params: params ?? {} }),

    /** Custom 프로바이더 등록 */
    createCustom: (data: {
        name: string;
        base_url: string;
        api_key: string;
        model_list: string[];
        provider_type: string;
    }) => api.post('providers/custom', data),

    /** Custom 프로바이더 수정 */
    updateCustom: (providerId: string, data: {
        name: string;
        base_url: string;
        api_key: string;
        model_list: string[];
        provider_type: string;
    }) => api.put(`providers/custom/${providerId}`, data),

    /** Custom 프로바이더 삭제 */
    deleteCustom: (providerId: string) => api.delete(`providers/custom/${providerId}`),

    /** Built-in 프로바이더 API Key 등록/수정 (암호화 저장) */
    updateBuiltinKey: (providerId: string, apiKey: string) =>
        api.put(`providers/builtin/${providerId}/key`, { api_key: apiKey }),

    /**
     * 프로바이더 API에서 모델 목록 조회
     * - provider_id: openai/anthropic/google → 저장된 키 사용, 캐시 갱신
     * - provider_id: custom UUID → 저장된 키 사용
     * - base_url + api_key: 직접 입력 (캐시 갱신 안 함)
     * 반환: { models, models_changed, cached }
     */
    fetchModels: (data: { base_url?: string; api_key?: string; provider_id?: string; model_type?: string }) =>
        api.post('providers/fetch-models', data),
};

export default api;
