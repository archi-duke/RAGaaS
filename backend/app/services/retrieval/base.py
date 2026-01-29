from abc import ABC, abstractmethod
from typing import List, Dict, Any

class RetrievalStrategy(ABC):
    """Abstract base class for all retrieval strategies."""
    
    @abstractmethod
    async def search(self, kb_id: str, query: str, top_k: int, **kwargs) -> List[Dict[str, Any]]:
        pass
