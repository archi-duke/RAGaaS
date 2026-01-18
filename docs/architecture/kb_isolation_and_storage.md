# Knowledge Base Isolation and Storage Architecture

## 1. Core Concept: Strict KB Isolation
RAGaaS is designed to manage multiple Knowledge Bases (KBs) independently. Each KB acts as an isolated container for documents and their derived data.

- **Independence**: Operations on one KB (Ingestion, Search, Deletion) MUST NOT affect other KBs.
- **Scope**: Every document belongs to exactly one KB. "Deleting a document" means removing it from that specific KB's context.
- **Data Coexistence**: Data from multiple KBs coexists in the underlying databases (MongoDB, Milvus, Neo4j, Fuseki) but is logically or physically separated by `kb_id`.

## 2. Storage Backend Selection
A KB is configured with a specific **Graph Backend** at creation time. This decision is immutable for the lifecycle of the KB.

### 2.1 Graph Storage Options
- **Neo4j**:
  - Used when `graph_backend` is set to `"neo4j"` (or default).
  - High-performance property graph handling.
  - Used for "Graph RAG" features.
- **Fuseki (Jena)**:
  - Used when `graph_backend` is set to `"ontology"` (or `"fuseki"`).
  - Used for Ontology-based KBs and strict RDF/SPARQL requirements.

### 2.2 Vector Storage (Milvus)
- Always used for vector embeddings regardless of the graph backend.
- Data is segregated by Collection Name: `kb_{kb_id}` (e.g., `kb_f47c0a51_...`).

## 3. Ingest Service Workflow
The Ingest Service is stateless regarding KB configuration. It must be **explicitly told** where to store graph data.

1.  **Backend Responsibility**:
    - Checks `kb.graph_backend` in MongoDB.
    - Passes `graph_store="neo4j"` or `graph_store="fuseki"` to Ingest Service logic.
2.  **Ingest Service Responsibility**:
    - Receives `graph_store` parameter in the request.
    - **Branching Logic**:
        - If `graph_store == "neo4j"`: Calls `Neo4jConnector` -> Inserts into Neo4j.
        - If `graph_store == "fuseki"`: Calls `FusekiConnector` -> Inserts into Fuseki.
    - **Vector Storage**: Always calls `MilvusConnector`.

## 4. Deletion & Cleanup Policy
Deleting a document implies a "Cascading Deletion" across all associated stores for that specific KB.

- **MongoDB**: Delete `Document` record and `TripleChunkMapping`.
- **Milvus**: Delete entities matching `doc_id` in `kb_{kb_id}` collection.
- **Graph (Neo4j)**: `MATCH (n)-[r]->(m) WHERE r.doc_id = $doc_id DELETE r` (and orphan nodes).
- **Graph (Fuseki)**: `DELETE WHERE { GRAPH <urn:doc:{doc_id}> { ... } }` (Named Graph removal).
- **Filesystem**: Remove source file from shared storage.

> **Crucial Note**: Verifying "Garbage" means checking if data persists *for a deleted document*. It does **NOT** mean checking if the database is empty, as valid data from other KBs must remain intact.
