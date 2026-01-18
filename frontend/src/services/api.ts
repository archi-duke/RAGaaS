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
            // Send enable_inference as separate form field
            if (config.enable_inference !== undefined) {
                formData.append('enable_inference', String(config.enable_inference));
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

export default api;
