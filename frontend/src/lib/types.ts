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
