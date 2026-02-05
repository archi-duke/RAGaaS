from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class GraphBackend(ABC):
    """Abstract base class for Graph RAG backends."""

    @abstractmethod
    async def query(
        self,
        kb_id: str,
        entities: List[str],
        hops: int,
        query_type: str,
        relationship_keywords: List[str],
        **kwargs
    ) -> Dict[str, Any]:
        """Execute a graph query to find relevant chunks.

        Args:
            kb_id: Knowledge Base ID
            entities: List of extracted entities from the user query
            hops: Graph traversal depth
            query_type: Analyzed query type (e.g., 'simple', 'multi_hop')
            relationship_keywords: List of relationship keywords extracted from query
            **kwargs: Additional parameters (e.g., use_relation_filter)

        Returns:
            Dict containing:
            - chunk_ids: List[str] found chunk IDs
            - sparql_query: str (The executed query, could be Cypher or SPARQL)
            - triples: List[Dict] found triples/relationships for metadata
        """
        pass
