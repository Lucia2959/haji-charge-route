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


class AltStation(BaseModel):
    """대체 충전소 (배정 충전소가 사용불가일 때)."""

    station_id: str
    station_name: str
    location: LatLng
    available: bool
    status_reason: str


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
    # 정체·지체 (실시간 교통 기준)
    jam_km: float  # 정체 거리
    delay_km: float  # 지체 거리
    congestion_extra_kwh: float  # 정체·지체로 인한 자유주행 대비 추가 소비(kWh)
    congestion: list[CongestionStretch]  # 지도 색상 표시용 구간
    charge_points: list[ChargePoint]
    path: list[LatLng]  # 지도 폴리라인용 경로 좌표
    data_source: str  # "kakao" | "mock"


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
