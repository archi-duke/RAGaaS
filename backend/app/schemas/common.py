from pydantic import BaseModel
from typing import Optional, List, Any
from enum import Enum

class PaginationParams(BaseModel):
    page: int = 1
    page_size: int = 10

class ResponseBase(BaseModel):
    success: bool = True
    message: Optional[str] = None
    data: Optional[Any] = None
