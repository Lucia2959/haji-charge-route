from fastapi import APIRouter, Query

from ..models import PlaceResult
from ..services import kakao

router = APIRouter(prefix="/api/places", tags=["places"])


@router.get("/search", response_model=list[PlaceResult])
async def search(query: str = Query(..., min_length=1, max_length=200)) -> list[PlaceResult]:
    """출발지·도착지 주소 검색."""
    return await kakao.search_places(query)
