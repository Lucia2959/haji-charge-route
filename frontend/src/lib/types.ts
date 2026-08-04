// 백엔드 API 응답 타입 — `backend/app/models.py`와 1:1 대응한다.
//
// 자동 생성이 아니라 **수동 동기화**다. 백엔드 모델을 고치면 이 파일도 함께 고쳐야
// 하고, 안 고치면 타입은 통과하는데 런타임에 undefined가 흐르는 조용한 버그가 된다.
// (백엔드가 snake_case를 그대로 내보내므로 필드명을 눈으로 대조할 수 있다.)
//
// `| null`이 붙은 필드는 대부분 "공공 API가 제공하지 않음"을 뜻한다. 화면은 이런
// 값을 렌더에서 제외한다(빈 칸을 표시하지 않는다).

export interface LatLng {
  lat: number;
  lng: number;
}

export interface RoutePlanRequest {
  origin: string;
  destination: string;
  current_charge_pct: number;
  temperature_c: number;
  /** 출발 예정 시각(ISO 8601). 없으면 서버가 '지금'으로 본다. 서버에 저장되지 않는다. */
  depart_at?: string;
}

export interface AltStation {
  station_id: string;
  station_name: string;
  location: LatLng;
  available: boolean;
  status_reason: string;
}

export interface ChargePoint {
  order: number;
  distance_from_origin_km: number;
  station_id: string | null;
  station_name: string | null;
  location: LatLng | null;
  available: boolean | null;
  status_reason: string | null;
  alternative: AltStation | null;
  charge_from_pct: number | null;
  charge_to_pct: number | null;
  charge_kwh: number | null;
  charge_min: number | null;
  /** 출발 후 이 충전소 도착까지 걸리는 시간(분). 혼잡 예측 기준 시각. */
  arrive_after_min: number | null;
  /** 성수기 혼잡 예측. 수집 데이터가 부족하면 null → 화면에 표시하지 않는다. */
  congestion: StationCongestion | null;
}

/**
 * 도착 예정 시각 기준 혼잡 예측.
 *
 * wait_lo~wait_hi를 구간으로 보여주는 이유: 대기시간은 관측값이 아니라
 * 점유 통계에서 유도한 파생 추정치라 분 단위 정밀도를 주장할 근거가 없다.
 * 등급(level)은 **색만으로 표현하지 말고 반드시 텍스트를 함께** 낸다(WCAG AA).
 */
export interface StationCongestion {
  level: "여유" | "보통" | "혼잡";
  wait_min: number; // 계획에 반영된 기대 대기(분)
  wait_lo: number;
  wait_hi: number;
  confidence: "낮음" | "보통" | "높음";
  n_days: number; // 근거가 된 관측일 수
  daytype_fallback: string | null; // "weekend" = 연휴 통계가 없어 주말로 대체
}

export interface CongestionAlternative {
  saved_min: number;
  total_charge_min: number;
  stations: string[]; // 대안 계획의 충전소 이름
  avoided: string[]; // 피한 혼잡 충전소 이름
  note: string;
}

export interface DepartOption {
  offset_h: number; // 기준 대비 시간(음수 = 일찍)
  depart_at: string;
  total_trip_min: number;
  charge_wait_min: number;
  feasible: boolean;
}

/**
 * 출발 시각별 비교.
 *
 * ⚠ **정체 차이는 반영되지 않는다.** 카카오 실시간 교통은 현재 시점만 제공해
 * 미래 출발 시각의 정체를 알 수 없다. 달라지는 것은 충전 대기뿐이다.
 */
export interface DepartOptionsResponse {
  base_depart_at: string;
  options: DepartOption[];
  best_offset_h: number | null;
  note: string;
}

export interface CongestionStretch {
  level: "jam" | "delay"; // 정체 | 지체
  path: LatLng[];
  distance_km: number;
  speed_kmh: number;
  is_highway: boolean;
}

export interface DestinationCharging {
  station_id: string;
  station_name: string;
  note: string;
}

export interface OriginPrecharge {
  required_pct: number; // 출발지 근처에서 이만큼 이상 충전 권장
  reason: string;
  station: AltStation | null; // 출발지 근처 외부인 이용가능 충전소
}

export interface RoutePlanResponse {
  vehicle: string;
  origin: LatLng;
  destination: LatLng;
  total_distance_km: number;
  duration_min: number;
  current_charge_pct: number;
  initial_range_km: number;
  charge_stops_count: number;
  feasible: boolean;
  total_charge_min: number;
  total_trip_min: number;
  plan_method: string;
  destination_charging: DestinationCharging | null;
  origin_precharge: OriginPrecharge | null;
  nominal_range_km: number;
  effective_range_km: number;
  temperature_c: number;
  avg_speed_kmh: number;
  temp_factor: number;
  speed_factor: number;
  highway_km: number;
  local_km: number;
  jam_km: number;
  delay_km: number;
  congestion_extra_kwh: number;
  congestion: CongestionStretch[];
  charge_points: ChargePoint[];
  path: LatLng[];
  data_source: string;
  /** 계획에 반영된 예상 충전 대기 합(분). 수집 데이터가 없으면 null. */
  congestion_wait_min: number | null;
  congestion_alternative: CongestionAlternative | null;
}

/** 지역 탐색 지도(/explore)용 충전소. free_chargers/available은 with_status일 때만 채워진다. */
export interface StationSummary {
  id: string;
  name: string;
  location: LatLng;
  charger_types: string[];
  max_power_kw: number;
  public_access: boolean;
  free_chargers: number | null;
  available: boolean | null;
}

export interface RealtimeCharger {
  charger_no: string;
  charge_type: string; // 충전방식 (급속/완속)
  connector: string | null; // 충전기 커넥터 (DC콤보/차데모/AC3상 등)
  status: string; // 충전 상태: 충전가능 / 충전중 / 운영중지 / 점검중 / 상태미확인
  remaining: string | null;
  power_kw: number; // 충전 출력 (kW)
  unit_price: number; // 단가 (원/kWh)
  price_member: number | null; // 회원가 (원/kWh)
  price_nonmember: number | null; // 비회원가 (원/kWh)
}

export interface PlaceResult {
  name: string;
  address: string;
  location: LatLng;
}

export interface StationDetail {
  id: string;
  name: string;
  location: LatLng;
  charger_types: string[];
  payment_methods: string[]; // 결제 수단 (환경부 로밍 '전기차이음' 등)
  usage_restricted: boolean; // 이용 제한 여부 (limitYn)
  limit_detail: string; // 이용 제한 내용 (거주/관계자/고객 등)
  parking_free: boolean; // 주차 무료 여부 (false면 주차비 발생)
  business_name: string | null; // 사업자명 (busiNm)
  address: string | null; // 설치 주소 (addr + addrDetail)
  use_time: string | null; // 이용 가능 시간 (useTime)
  install_year: string | null; // 설치 연도 (year)
  chargers: RealtimeCharger[];
  data_source: string;
}
