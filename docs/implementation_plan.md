# [Bug Fix & Logic Improvement] Graph Data Integrity & UI

## Problem Analysis
1. **Orphaned Data (Data Integrity)**:
   - **Issue**: Deleting a document in MongoDB does not always clean up corresponding data in Fuseki/Neo4j, leaving "orphaned triples".
   - **Root Cause**: The current deletion logic is not transactional or verified. If the Graph DB deletion fails, the MongoDB record is still deleted, leading to inconsistency.
   - **Impact**: Graph View shows triples with missing Document/Chunk info (displayed as `-` or `N/A`).

2. **UI Issues (Graph Data Table)**:
   - **Document ID Exposure**: Raw UUIDs are shown when document metadata is missing.
   - **Chunk N/A**: Warning icons (`⚠️ N/A`) appear for valid legacy data or orphans.
   - **Repetitive Content**: Users are confused why multiple rows point to the same chunk.

## Proposed Changes

### 1. Backend Logic Improvements (Critical)
#### [MODIFY] [cleanup_service.py](file:///Users/dukekimm/Works/RAGaaS/backend/app/services/ingestion/cleanup_service.py)
- **Transactional Deletion Strategy**:
  - **Proposed Order**: 
    1. **Graph DB Deletion** (Fuseki/Neo4j) - *Primary*.
    2. **Verification** - Check if data is truly gone.
    3. **MongoDB Deletion** - *Final Commit*.
  - If step 1 fails, **abort** the entire operation and report error to user. Do NOT delete the MongoDB record.
- **Post-Deletion Verification**:
  - Implement a `verify_deletion(doc_id)` function that queries Fuseki/Neo4j to ensure no triples remain for that `doc_id`.
  - Trigger `cleanup_orphans` logic (like the manual script) if verification fails.

#### [NEW] [Garbage Collection API]
- Add an Admin API endpoint (e.g., `POST /api/admin/gc`) to run the orphan cleanup logic on demand.

### 2. Frontend UI Improvements
#### [MODIFY] [GraphDataTable.tsx](file:///Users/dukekimm/Works/RAGaaS/frontend/src/components/GraphDataTable.tsx)
- **Graceful Error Handling**: 
  - Display `-` instead of `⚠️ N/A` for missing chunks.
  - Show "Unknown/Deleted" label for missing document filenames instead of raw UUIDs.
- **UX Enhancements**:
  - Add tooltip explaining "Multiple triples per chunk".

## Verification Plan
### Automated Tests
- **Deletion Test**: 
  - Ingest a document -> Verify triples exist.
  - Delete document -> Verify `doc_id` returns 0 results in Fuseki/Neo4j.
  - Verify MongoDB record is gone.

### Manual Verification
1. **Clean State Check**: 
   - Run the manual GC script (done).
   - Verify Graph Data tab looks clean (no N/A).
2. **Deletion Flow**:
   - Upload new file.
   - Delete it.
   - Check Graph Data tab to ensure no leftovers.
