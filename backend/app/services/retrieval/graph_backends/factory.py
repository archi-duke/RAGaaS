from typing import Dict
from .base import GraphBackend
from .neo4j import Neo4jBackend
from .fuseki import FusekiBackend

class GraphBackendFactory:
    """Factory for creating GraphBackend instances."""
    
    _backends: Dict[str, GraphBackend] = {}

    @classmethod
    def get_backend(cls, backend_name: str) -> GraphBackend:
        """Get or create a graph backend instance."""
        backend_key = backend_name.lower()
        
        if backend_key not in cls._backends:
            if backend_key == "neo4j":
                cls._backends[backend_key] = Neo4jBackend()
            elif backend_key == "ontology" or backend_key == "fuseki":
                cls._backends[backend_key] = FusekiBackend()
            else:
                # Default to Fuseki if unknown, or raise error. 
                # For now, default to Fuseki as per original logic.
                cls._backends[backend_key] = FusekiBackend()
        
        return cls._backends[backend_key]
