"""장소 검색 라우터 (장소검색 모달 M-01).

프런트는 선택 결과의 좌표를 `"lng,lat"` 문자열로 만들어 보관한다 → 경로계산 시
지오코딩을 다시 타지 않아 API 호출 1회를 아끼고 정확도도 높다.
"""

from fastapi import APIRouter, Query

from ..models import PlaceResult
from ..services import kakao

router = APIRouter(prefix="/api/places", tags=["places"])


@router.get("/search", response_model=list[PlaceResult])
async def search(query: str = Query(..., min_length=1, max_length=200)) -> list[PlaceResult]:
    """출발지·도착지 주소 검색.

    max_length=200은 과대 입력으로 외부 API 호출이 낭비되는 것을 막는 상한이다
    (Pydantic이 위반 시 422를 반환하므로 서비스 계층까지 내려가지 않는다).
    """
    return await kakao.search_places(query)
