"""API 요청·응답 스키마 (Pydantic).

이 파일이 프런트(`frontend/src/lib/types.ts`)와의 계약이다. 필드를 추가·변경하면
반드시 프런트 타입도 함께 고쳐야 한다(자동 생성이 아니라 수동 동기화).

명명 규칙: 백엔드는 snake_case를 그대로 내보내고 프런트도 그대로 받는다
(alias 변환을 두지 않아 필드를 눈으로 대조할 수 있게 했다).

Optional 필드의 의미: `None`은 "값이 없음"이 아니라 대부분 **"공공 API가 제공하지
않음"**이다. 화면은 이런 필드를 렌더에서 제외한다(빈 값을 표시하지 않는다).
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class LatLng(BaseModel):
    lat: float
    lng: float


class RoutePlanRequest(BaseModel):
    """메인 화면 입력값: 출발지 / 도착지 / 현충전량."""

    origin: str = Field(..., min_length=1, max_length=200, description="출발지 (주소·지명 또는 'lng,lat')")
    destination: str = Field(..., min_length=1, max_length=200, description="도착지 (주소·지명 또는 'lng,lat')")
    current_charge_pct: float = Field(..., ge=0, le=100, description="현충전량 (%)")
    temperature_c: float = Field(20.0, ge=-40, le=60, description="외부 기온 (°C)")
    # 고속도로·자동차전용 구간에서 낼 순항속도. 미입력이면 실시간 교통속도를 그대로 쓴다.
    # 일반도로에는 적용하지 않는다 — 제한속도 편차가 커 교통속도가 더 나은 추정치다.
    # 실제 계산 속도는 법정 범위로 clamp된 뒤 실시간 교통속도가 상한이 된다
    # (정체 구간을 희망속도로 덮어써 소비를 과소평가하는 것을 막기 위해).
    cruise_speed_kmh: Optional[float] = Field(
        None, ge=30, le=150, description="고속도로 순항속도 (km/h). 미입력 시 실시간 교통속도"
    )
    # 혼잡 예측의 기준 시각. 없으면 '지금'. 타임존이 없으면 KST로 해석한다.
    # 서버에 저장하지 않는다 — 이 요청 처리 중에만 쓰인다(개인정보 요구사항).
    depart_at: Optional[datetime] = Field(
        None, description="출발 예정 시각(ISO 8601). 미지정 시 현재 시각"
    )


class AltStation(BaseModel):
    """대체 충전소 (배정 충전소가 사용불가일 때)."""

    station_id: str
    station_name: str
    location: LatLng
    available: bool
    status_reason: str


class StationCongestion(BaseModel):
    """도착 예정 시각 기준 충전소 혼잡 예측.

    wait_min은 계획(DP)이 실제로 더한 값이고, wait_lo~wait_hi는 화면 표기용 구간이다.
    단일 숫자로 보여주지 않는 이유: 대기시간은 관측값이 아니라 점유 통계에서
    유도한 파생 추정치라, 분 단위 정밀도를 주장할 근거가 없다. docs/07 §9-1.
    """

    level: str            # "여유" | "보통" | "혼잡"
    wait_min: float       # 계획에 반영된 기대 대기(분)
    wait_lo: int          # 표기 구간 하한
    wait_hi: int          # 표기 구간 상한
    confidence: str       # "낮음" | "보통" | "높음"
    n_days: int           # 근거가 된 관측일 수
    daytype_fallback: Optional[str] = None  # "weekend" = 연휴 통계가 없어 주말로 대체


class ChargePoint(BaseModel):
    """경로 상 충전이 필요한 예상 지점."""

    order: int
    distance_from_origin_km: float
    station_id: Optional[str] = None
    station_name: Optional[str] = None
    location: Optional[LatLng] = None
    # 실시간 상태(충전계획계산 시 조회)
    available: Optional[bool] = None
    status_reason: Optional[str] = None  # 사용가능/인가자전용/점검중/운영중지/상태미확인
    alternative: Optional[AltStation] = None  # 사용불가 시 대체 충전소
    # 충전 커브 기반 DP 결과 (부분충전)
    charge_from_pct: Optional[float] = None
    charge_to_pct: Optional[float] = None
    charge_kwh: Optional[float] = None
    charge_min: Optional[float] = None
    # 출발 후 이 충전소에 도착하기까지 걸리는 시간(분). 혼잡 예측 조회 기준 시각이다.
    arrive_after_min: Optional[float] = None
    # 성수기 혼잡 예측 (docs/07). 데이터가 부족하면 congestion=None → 화면 미표시.
    congestion: Optional[StationCongestion] = None


class CongestionStretch(BaseModel):
    """지도 표시용 정체/지체 연속 구간."""

    level: str  # "jam"(정체) | "delay"(지체)
    path: list[LatLng]  # 해당 구간 폴리라인 좌표
    distance_km: float
    speed_kmh: float  # 구간 평균 실제속도
    is_highway: bool


class DestinationCharging(BaseModel):
    """목적지 인근 외부인 이용가능 충전소."""

    station_id: str
    station_name: str
    note: str  # "이용 가능" / "외부인 이용가능(주차비 발생)" 등


class OriginPrecharge(BaseModel):
    """출발 전 출발지 근처 권장 충전.

    두 경우에 발생한다.
      · 1차 충전소까지 정체로 추가 소모되거나 현장 사용불가로 대체소까지 더 가야 할 때
      · 경로상 충전 없이 목적지로 직행하지만 도착 잔량이 최소치(15%)에 못 미칠 때
    station 은 출발지 인근에서 외부인이 실제 이용 가능한 충전소(있으면).
    """

    required_pct: int  # 출발지 근처에서 이만큼 이상 충전 권장
    reason: str
    station: Optional["AltStation"] = None  # 출발지 근처 이용가능 충전소


class RoutePlanResponse(BaseModel):
    vehicle: str
    origin: LatLng
    destination: LatLng
    total_distance_km: float
    duration_min: int
    current_charge_pct: float
    initial_range_km: float  # 현충전량으로 갈 수 있는 거리(=1차 충전 지점)
    charge_stops_count: int  # 충전예상지점수
    feasible: bool  # 경로상 충전 인프라로 완주 가능 여부
    # 시간(분): 주행 / 충전 / 총 (DP 최적화)
    total_charge_min: int
    total_trip_min: int
    plan_method: str  # "dp" | "greedy"
    destination_charging: Optional["DestinationCharging"] = None  # 목적지 자체 충전소
    origin_precharge: Optional["OriginPrecharge"] = None  # 출발 전 출발지 근처 권장 충전
    # 외부환경 보정 근거
    nominal_range_km: float  # 정격 완충 거리 (300km)
    effective_range_km: float  # 보정 후 유효 거리
    temperature_c: float
    avg_speed_kmh: float
    temp_factor: float  # 온도 보정계수
    speed_factor: float  # 속도 보정계수 (도로유형별 제한속도 거리가중 blend)
    highway_km: float  # 고속도로 주행거리
    local_km: float  # 일반도로 주행거리
    # 사용자가 입력한 순항속도(없으면 None)와, 실제 계산에 쓰인 고속도로 평균속도.
    # 둘을 함께 내려야 "내가 넣은 값이 반영됐는지"를 산출근거에서 확인할 수 있다.
    # 정체가 있으면 applied < 입력값이 되는 것이 정상이다.
    cruise_speed_kmh: Optional[float] = None
    highway_speed_kmh: Optional[float] = None
    # 정체·지체 (실시간 교통 기준)
    jam_km: float  # 정체 거리
    delay_km: float  # 지체 거리
    congestion_extra_kwh: float  # 정체·지체로 인한 자유주행 대비 추가 소비(kWh)
    congestion: list[CongestionStretch]  # 지도 색상 표시용 구간
    charge_points: list[ChargePoint]
    path: list[LatLng]  # 지도 폴리라인용 경로 좌표
    data_source: str  # "kakao" | "mock"
    # 성수기 혼잡 (docs/07). 수집 데이터가 없으면 둘 다 None → 화면에 안 나온다.
    congestion_wait_min: Optional[int] = None  # 계획에 반영된 예상 충전 대기 합(분)
    congestion_alternative: Optional["CongestionAlternative"] = None
    # 예측 준비 상태. 화면이 "기능이 없는 것"과 "아직 데이터를 모으는 중"을
    # 구분해 보여주기 위한 값이다 — 없으면 사용자는 기능 존재 자체를 알 수 없다.
    #   "off"        DB 미설정 → 기능 비활성
    #   "collecting" 수집 중이나 관측일이 임계 미만 → 예측 안 함
    #   "ready"      최소 한 곳 이상 예측이 붙었다
    congestion_status: Optional[str] = None
    congestion_days: Optional[int] = None  # 관측일 수(진행도). collecting일 때 유용


class CongestionAlternative(BaseModel):
    """혼잡 충전소를 피한 대안 계획 요약.

    전체 계획을 다시 싣지 않고 '얼마나 줄어드는지 + 어디로 바뀌는지'만 준다.
    사용자가 받아들이면 그 충전소를 제외하고 다시 계산하면 된다.
    """

    saved_min: int              # 총 소요시간 단축(분)
    total_charge_min: int       # 대안의 충전·정차 시간
    stations: list[str]         # 대안 계획의 충전소 이름(순서대로)
    avoided: list[str]          # 피한 혼잡 충전소 이름
    note: str


class DepartOption(BaseModel):
    """출발 시각 후보 1건."""

    offset_h: int          # 기준 출발시각 대비 시간(음수=일찍)
    depart_at: datetime
    total_trip_min: int    # 주행 + 충전·정차
    charge_wait_min: int   # 그중 예상 충전 대기
    feasible: bool


class DepartOptionsResponse(BaseModel):
    """출발 시각별 총 소요시간 비교.

    **정체 차이는 반영되지 않는다.** 카카오 실시간 교통은 현재 시점만 제공하므로
    미래 출발 시각의 정체를 알 수 없다. 여기서 달라지는 것은 충전 대기뿐이며,
    화면에도 그렇게 고지해야 한다. docs/07 §F4.
    """

    base_depart_at: datetime
    options: list[DepartOption]
    best_offset_h: Optional[int] = None  # 기준 대비 유의하게 나은 후보가 있으면
    note: str


class RealtimeCharger(BaseModel):
    charger_no: str  # 충전기 번호 (API: chgerId)
    charge_type: str  # 충전방식 (급속/완속, API: chgerType)
    connector: Optional[str] = None  # 충전기 커넥터 (API: chgerType 해석 — DC콤보/차데모/AC3상 등)
    status: str  # 충전 상태 (충전가능/충전중/운영중지/점검중/상태미확인, API: stat)
    remaining: Optional[str] = None  # 잔여시간 (공공 API 미제공)
    power_kw: float  # 충전 출력 (kW, API: output) — 충전 계산의 시간 산정 기준
    unit_price: float  # 단가 (원/kWh, 타입별 기본값) — 충전 금액 산정 기준
    # 충전요금 회원/비회원 (공공 API 미제공 → 없으면 None, 화면에서 제외)
    price_member: Optional[float] = None  # 회원가 (원/kWh)
    price_nonmember: Optional[float] = None  # 비회원가 (원/kWh)


class PlaceResult(BaseModel):
    """주소 검색 결과 (출발지·도착지 팝업)."""

    name: str  # 장소명
    address: str  # 주소
    location: LatLng


class StationSummary(BaseModel):
    id: str
    name: str
    location: LatLng
    charger_types: list[str]  # ["급속", "완속"]
    max_power_kw: float = 100.0  # 충전소 최대 출력(kW) — DP 충전시간 계산용
    # 외부인(비인가자)이 이용 가능한가. 입주민·관계자·특정차량 전용이면 False.
    # 카탈로그의 limitYn/limitDetail로 판정하며, 충전계획 후보에서 제외하는 데 쓴다.
    public_access: bool = True
    # 지역 탐색 지도에서 실시간 상태를 함께 요청했을 때만 채워진다(기본 None).
    free_chargers: Optional[int] = None  # 지금 '충전가능'인 충전기 수
    available: Optional[bool] = None     # free_chargers > 0


class StationDetail(StationSummary):
    payment_methods: list[str]  # 결제 수단 (환경부 로밍 '전기차이음' 등 결제 가능 카드)
    usage_restricted: bool  # 이용 제한 여부 (원본 API: limitYn)
    limit_detail: str = ""  # 이용 제한 내용 (API: limitDetail) — 거주/관계자/고객 구분에 사용
    parking_free: bool = True  # 주차 무료 여부 (API: parkingFree). False면 주차비 발생
    # 설치 정보 (없으면 None → 화면에서 제외)
    business_name: Optional[str] = None  # 사업자명 (API: busiNm)
    address: Optional[str] = None  # 설치 주소 (API: addr + addrDetail)
    use_time: Optional[str] = None  # 이용 가능 시간 (API: useTime)
    install_year: Optional[str] = None  # 설치 연도 (API: year)
    chargers: list[RealtimeCharger]  # 실시간 충전기 상태
    data_source: str  # "public_api" | "mock"
