import axios from 'axios';

const api = axios.create({
    baseURL: 'http://localhost:8000/api',
    headers: {
        'Content-Type': 'application/json',
    },
});

export const kbApi = {
    list: () => api.get('/knowledge-bases/'),
    create: (data: { name: string; description: string; chunking_strategy: string; chunking_config: any; metric_type?: string; graph_backend?: 'none' | 'ontology' | 'neo4j'; ontology_schema?: string }) => api.post('/knowledge-bases/', data),
    extractSchema: (file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        return api.post('/knowledge-bases/extract-schema', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
    },
    get: (id: string) => api.get(`/knowledge-bases/${id}`),
    delete: (id: string) => api.delete(`/knowledge-bases/${id}`),
    promote: (id: string, payload: any = {}) => api.post(`/knowledge-bases/${id}/promote`, payload),
    getExtractionRules: () => api.get('/knowledge-bases/extraction-rules/content'),
    validateExtractionRules: (content: string) => api.post('/knowledge-bases/extraction-rules/validate', { content }),
    saveExtractionRules: (content: string) => api.post('/knowledge-bases/extraction-rules/save', { content }),
    getExtractionPrompt: () => api.get('/knowledge-bases/extraction-prompt/content'),
    saveExtractionPrompt: (content: string) => api.post('/knowledge-bases/extraction-prompt/save', { content }),
    getQueryPrompt: (type: 'ontology_plus' | 'ontology_minus' | 'neo4j' = 'ontology_minus') => api.get('/knowledge-bases/query-prompt/content', { params: { type } }),
    getTriples: (kbId: string, backend: string, skip: number = 0, limit: number = 50, sort?: any, filter?: any) => api.get(`/retrieval/graph/triples/${kbId}`, { params: { backend, skip, limit, include_chunk_text: false, sort: sort ? JSON.stringify(sort) : undefined, filter: filter ? JSON.stringify(filter) : undefined } }),
    getChunk: (kbId: string, chunkId: string) => api.get(`/knowledge-bases/${kbId}/chunks/${chunkId}`),
};

export const docApi = {
    list: (kbId: string) => api.get(`/knowledge-bases/${kbId}/documents`),
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
            // Send preview_only flag
            if (config.preview_only !== undefined) {
                formData.append('preview_only', String(config.preview_only));
            }
            // Send Entity Dictionary (Pass-through)
            if (config.entity_dictionary) {
                formData.append('entity_dictionary', JSON.stringify(config.entity_dictionary));
            }
        }
        return api.post(`/knowledge-bases/${kbId}/documents`, formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
    },

    delete: (kbId: string, docId: string) => api.delete(`/knowledge-bases/${kbId}/documents/${docId}`),
    getChunks: (kbId: string, docId: string) => api.get(`/knowledge-bases/${kbId}/documents/${docId}/chunks`),
    updateChunk: (kbId: string, docId: string, chunkId: string, content: string) => {
        const formData = new FormData();
        formData.append('content', content);
        return api.put(`/knowledge-bases/${kbId}/documents/${docId}/chunks/${chunkId}`, formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
    },
    update: (kbId: string, docId: string, data: { extraction_examples?: string; custom_prompt?: string }) =>
        api.patch(`/knowledge-bases/${kbId}/documents/${docId}`, data),

    // [NEW] Update Pipeline Status (for Resume)
    updatePipelineStatus: (kbId: string, docId: string, data: { status: string; metadata: any }) =>
        api.put(`/knowledge-bases/${kbId}/documents/${docId}/pipeline`, data),
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
    }) => api.post(`/knowledge-bases/${kbId}/retrieve`, data),
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
        // Pipeline Configuration
        pipeline?: { stages: any[] };
    }) => api.post(`/knowledge-bases/${kbId}/chat`, data),
};

// Ingest Service API (runs on port 8001)
const ingestApi = axios.create({
    baseURL: 'http://localhost:8001/api',
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
    }) => ingestApi.post('/preview', data),

    confirm: (previewId: string, data?: {
        enable_inference?: boolean;
        callback_url?: string;
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
    }) => ingestApi.post('/preview-dictionary', data),
};


export default api;
