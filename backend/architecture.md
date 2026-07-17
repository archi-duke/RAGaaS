# Backend Architecture & Responsibility

This document defines the folder structure, responsibilities, and extension rules for the RAG Management System backend. This guide allows LLMs and developers to understand where to place code and how components interact.

## 1. Top-Level Directory Structure

```plaintext
backend/app/
├── api/             # API Router & Controllers (FastAPI endpoints)
├── core/            # Core Infrastructure (Configuration, Database, Milvus, Logging)
├── models/          # SQLAlchemy Database Models
├── schemas/         # Pydantic Schemas (Data Transfer Objects) -> Refactored from schemas.py
├── services/        # Business Logic & Service Layers
└── utils/           # Shared Utilities
```

## 2. Responsibilities by Module

### 2.1 API (`app/api/`)
*   **Purpose**: Handle HTTP requests, parse inputs (using Schemas), delegate to Services, and return HTTP responses.
*   **Rules**:
    *   No complex business logic here.
    *   Only dependencies injection (e.g., `db: Session`) and Service calls.
    *   One file per resource/domain (e.g., `knowledge_base.py`, `document.py`, `retrieval.py`).

### 2.2 Core (`app/core/`)
*   **Purpose**: singleton configurations and database connections.
*   **Components**:
    *   `config.py`: Environment variable loading (Pydantic Settings).
    *   `database.py`: SQLAlchemy engine & session factory.
    *   `milvus.py`: Milvus connection logic.
*   **Rules**: Global state or connection pools belong here.

### 2.3 Models (`app/models/`)
*   **Purpose**: Define database tables using SQLAlchemy ORM.
*   **files**:
    *   `knowledge_base.py`
    *   `document.py`
*   **Rules**: Only DB constraints and relationships. No business methods.

### 2.4 Schemas (`app/schemas/`)
*   **Purpose**: Define Pydantic models for request/response validation.
*   **Structure**:
    *   `common.py`: Shared enums, base models, pagination.
    *   `knowledge_base.py`: KB creation, updates, response.
    *   `document.py`: Document metadata, status.
    *   `retrieval.py`: Search requests, parameters, result formats.
*   **Rules**: Split `schemas.py` into these granular files to prevent circular imports and massive files.

### 2.5 Services (`app/services/`)
*   **Purpose**: Contain ALL business logic.
*   **Structure**:
    *   `ingestion/`: (Package)
        *   `pipeline.py`: Orchestrates parsing, splitting, embedding, storage.
        *   `text_splitter.py`: Chunking logic.
    *   `retrieval/`: (Package)
        *   `base.py`: Abstract Base Class for retrieval strategies.
        *   `vector.py`: ANN Search implementation.
        *   `keyword.py`: BM25/Keyword implementation.
        *   `hybrid.py`: Combination logic.
        *   `reranker.py`: Methods for Cross-Encoder / LLM reranking.
        *   `factory.py`: Returns the correct strategy based on request.
    *   `embedding.py`: Wrapper for embedding APIs (OpenAI etc).
    *   `ner.py`: Named Entity Recognition logic.
*   **Rules**:
    *   Services should return Pydantic models or plain DB objects, not HTTP Responses.
    *   `retrieval.py` needs refactoring into a `retrieval/` package using the Strategy Pattern.

## 3. Extension Rules

### Adding a New Retrieval Strategy (e.g., Graph RAG)
1.  **Schema**: Update `app/schemas/retrieval.py` to add new config parameters (e.g., `graph_hops`).
2.  **Service**: Create `app/services/retrieval/graph.py` implementing `RetrievalStrategy` interface.
3.  **Factory**: Register the new strategy in `app/services/retrieval/factory.py`.
4.  **API**: No changes needed in controller if Factory is used correctly.

### Adding a New Ingestion Method
1.  Modify `app/services/ingestion/` to accept new file types or parsing logic.

## 4. Design Patterns Applied

*   **Strategy Pattern**: Used in Retrieval (Vector vs Keyword vs Hybrid).
*   **Factory Pattern**: Used to instantiate Retrieval Strategies.
*   **Facade Pattern**: The Ingestion Service acts as a facade over Parsing, Chunking, and Embedding.


## 5. Detailed Coding Standards & Extension Rules

To maintain long-term stability and scalability, all new code MUST adhere to the following rules.

### 5.1 Naming Conventions
*   **Classes**: `PascalCase`. Noun-based for Models/Schemas (`KnowledgeBase`), Verb-based for Services (`RetrievalService`, `VectorStrategy`).
*   **Functions/Methods**: `snake_case`. Must be descriptive (e.g., `calculate_vector_similarity` instead of `calc_sim`).
*   **Variables**: `snake_case`. Boolean variables should start with `is_`, `has_`, or `enable_` (e.g., `is_active`, `enable_reranker`).
*   **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRY_COUNT`).
*   **Files**: `snake_case.py`. Matches the primary class or module purpose (e.g., `knowledge_base.py`).

### 5.2 File Creation Criteria
*   **New File Required When**:
    *   A class exceeds 300 lines (Single Responsibility Principle violation).
    *   A new domain concept is introduced (e.g., `billing.py`, `analytics.py`).
    *   Implementing a new Strategy (e.g., `graph.py` under `retrieval/`).
*   **Do NOT Create New File When**:
    *   Adding a helper function that is only used by one existing file (make it private `_helper`).
    *   Adding a minor utility (add to `utils/xxx.py`).

### 5.3 Responsibility Boundaries
*   **API Layer (`app/api`)**:
    *   **Allowed**: Param validation, HTTP status codes, calling Services.
    *   **Prohibited**: SQL queries, business logic loops, direct external API calls (e.g., OpenAI).
*   **Service Layer (`app/services`)**:
    *   **Allowed**: Complex logic, DB transactions, detailed error handling.
    *   **Prohibited**: Returning `HTTPException` (raise custom exceptions or let API layer handle it), depending on `UploadFile` (use bytes/streams).
*   **Core Layer (`app/core`)**:
    *   **Allowed**: Singleton setups.
    *   **Prohibited**: Business logic that changes frequently. **Consider this layer "Frozen"** unless infrastructure changes.

### 5.4 Mutation Rules (Immutable vs Mutable)
*   **Immutable (Touch with Caution)**: 
    *   `app/core/database.py`: Don't change session management lightly.
    *   `app/core/config.py`: Only append new keys; never remove existing ones without migration plan.
*   **Mutable (Open for Extension)**:
    *   `app/services/retrieval/*`: Add new files for new algorithms.
    *   `app/schemas/*`: Add fields for new requirements (backward compatible).

### 5.5 Internal vs External Access
*   **Private Implementation**: Prefix with `_` (e.g., `_cosine_similarity`). These should NOT be called from outside the class/module.
*   **Public Interface**: Explicitly exported in `__init__.py` if it's a package.
*   **LLM Guideline**: When implementing a feature, **always check `__init__.py`** to see what is exposed. Do not import from internal sub-modules if a public facade exists.

## 6. System Behavior Policies

### 6.1 File Upload & Ingestion
*   **Overwrite Policy (Strict)**: When a user uploads a file with a filename that already exists in the Knowledge Base, the system **MUST overwrite** the existing document. Rejecting the upload with a 409 Conflict is PROHIBITED.
*   **Cleanup Requirement**: Before processing the re-uploaded file, existing derived data (Chunks, Embeddings, Graph Triples) associated with the `doc_id` MUST be invalidated/deleted to prevent duplication or stale data.
*   **User Intent**: The user's latest upload is always the source of truth.
