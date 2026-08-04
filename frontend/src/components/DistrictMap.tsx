"use client";

// 지역 충전소 탐색 지도 (S-06) — 시군구 하나의 충전소 전체를 클러스터로 표시한다.
//
// 경로 지도(KakaoMap.tsx)와 분리한 이유: 저쪽은 폴리라인 + 계획된 충전 지점 몇 개를
// 그리는 반면, 여기는 마커가 수백~수천 개다. 클러스터링·표시 정책이 완전히 달라
// 한 컴포넌트에 조건 분기를 넣으면 양쪽 다 읽기 어려워진다.
//
// 클러스터러는 react-kakao-maps-sdk에 내장된 MarkerClusterer를 쓴다 — 신규 의존성 없음.
import { Map, MapMarker, MarkerClusterer, useKakaoLoader } from "react-kakao-maps-sdk";
import type { LatLng, StationSummary } from "@/lib/types";

const KAKAO_KEY = process.env.NEXT_PUBLIC_KAKAO_JS_KEY ?? "";

export default function DistrictMap({
  center,
  stations,
  onSelectStation,
}: {
  center: LatLng;
  stations: StationSummary[];
  onSelectStation: (id: string) => void;
}) {
  if (!KAKAO_KEY) {
    return <ListFallback stations={stations} onSelectStation={onSelectStation} />;
  }
  return (
    <MapView center={center} stations={stations} onSelectStation={onSelectStation} />
  );
}

function MapView({
  center,
  stations,
  onSelectStation,
}: {
  center: LatLng;
  stations: StationSummary[];
  onSelectStation: (id: string) => void;
}) {
  const [loading, error] = useKakaoLoader({ appkey: KAKAO_KEY, libraries: ["clusterer"] });

  if (error) return <p className="p-4 text-sm text-red-500">지도 로드 실패</p>;
  if (loading) return <p className="p-4 text-sm text-slate-500">지도 불러오는 중…</p>;

  return (
    <Map
      center={center}
      level={7}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
    >
      {/* averageCenter: 클러스터 위치를 포함 마커 평균으로 — 격자 중앙보다 실제 분포에 가깝다
          minLevel 5: 그보다 확대하면 개별 마커를 보여준다(충전소를 골라야 하므로) */}
      <MarkerClusterer averageCenter minLevel={5}>
        {stations.map((s) => (
          <MapMarker
            key={s.id}
            position={s.location}
            title={s.name}
            image={{
              src:
                "data:image/svg+xml;base64," +
                (s.charger_types.includes("급속") ? FAST_ICON : SLOW_ICON),
              size: { width: 24, height: 24 },
            }}
            onClick={() => onSelectStation(s.id)}
          />
        ))}
      </MarkerClusterer>
    </Map>
  );
}

// 카카오 키가 없거나 지도를 못 띄우는 환경에서의 목록 폴백.
// "키 없이도 구동"이 이 앱의 설계 원칙이라 탐색 화면도 같은 원칙을 따른다.
function ListFallback({
  stations,
  onSelectStation,
}: {
  stations: StationSummary[];
  onSelectStation: (id: string) => void;
}) {
  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto bg-slate-100 p-3">
      <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-700 ring-1 ring-amber-200">
        NEXT_PUBLIC_KAKAO_JS_KEY 미설정 → 지도 대신 목록으로 표시합니다.
      </div>
      {stations.map((s) => (
        <button
          key={s.id}
          onClick={() => onSelectStation(s.id)}
          className="flex items-center justify-between rounded-xl bg-white p-3 text-left text-sm ring-1 ring-slate-200"
        >
          <span className="min-w-0 flex-1 truncate">{s.name}</span>
          <span className="ml-2 shrink-0 text-xs text-slate-500">
            {s.charger_types.join("·")} · {Math.round(s.max_power_kw)}kW
            {s.free_chargers != null && ` · 여유 ${s.free_chargers}`}
          </span>
        </button>
      ))}
    </div>
  );
}

// 급속=초록 / 완속=회색 원형 번개 (base64 SVG). 색만으로 구분하지 않도록
// 목록·상세에는 항상 "급속"/"완속" 텍스트가 함께 나온다.
const FAST_ICON =
  "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDMyIDMyIj48Y2lyY2xlIGN4PSIxNiIgY3k9IjE2IiByPSIxNCIgZmlsbD0iIzAwYjg5NCIgc3Ryb2tlPSIjZmZmIiBzdHJva2Utd2lkdGg9IjIiLz48cGF0aCBkPSJNMTggN2wtOCAxMWg1bC0xIDcgOC0xMWgtNXoiIGZpbGw9IiNmZmYiLz48L3N2Zz4=";
const SLOW_ICON =
  "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDMyIDMyIj48Y2lyY2xlIGN4PSIxNiIgY3k9IjE2IiByPSIxNCIgZmlsbD0iIzk0YTNiOCIgc3Ryb2tlPSIjZmZmIiBzdHJva2Utd2lkdGg9IjIiLz48cGF0aCBkPSJNMTggN2wtOCAxMWg1bC0xIDcgOC0xMWgtNXoiIGZpbGw9IiNmZmYiLz48L3N2Zz4=";
