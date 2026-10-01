from math import ceil
from typing import Any, Generic, Sequence, TypeVar

from pydantic import BaseModel
from pydantic.generics import GenericModel

T = TypeVar("T")

class PaginationParams(BaseModel):
    page: int = 1
    limit: int = 10
    @property
    def skip(self) -> int:
        return (self.page - 1) * self.limit

class PaginatedResponse(GenericModel, Generic[T]):
   
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_previous: bool
    data: list[T]

def paginate(
    *,
    data: Sequence[Any],
    total: int,
    page: int,
    limit: int,
) -> PaginatedResponse:

    total_pages = ceil(total / limit) if total else 1
    return PaginatedResponse(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1,
        data=data,
    )