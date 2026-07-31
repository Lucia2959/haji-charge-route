"use client";

import { Map, MapMarker, Polyline, useKakaoLoader } from "react-kakao-maps-sdk";
import type { RoutePlanResponse } from "@/lib/types";

const KAKAO_KEY = process.env.NEXT_PUBLIC_KAKAO_JS_KEY ?? "";

export default function KakaoMap({
  plan,
  onSelectStation,
}: {
  plan: RoutePlanResponse;
  onSelectStation: (id: string) => void;
}) {
  // 키가 없으면 로더를 호출하지 않고 텍스트 폴백을 렌더링
  if (!KAKAO_KEY) {
    return <MapFallback plan={plan} onSelectStation={onSelectStation} />;
  }
  return (
    <MapView plan={plan} onSelectStation={onSelectStation} />
  );
}

function MapView({
  plan,
  onSelectStation,
}: {
  plan: RoutePlanResponse;
  onSelectStation: (id: string) => void;
}) {
  const [loading, error] = useKakaoLoader({ appkey: KAKAO_KEY });

  if (error) return <p className="p-4 text-sm text-red-500">지도 로드 실패</p>;
  if (loading) return <p className="p-4 text-sm text-slate-500">지도 불러오는 중…</p>;

  const center = plan.path[Math.floor(plan.path.length / 2)] ?? plan.origin;

  // 400km 경로는 정점이 8천 개까지 나온다. 그대로 그리면 팬/줌이 버벅이므로
  // 표시용으로만 균등 솎아낸다(줌 12에서 시각적 차이 없음).
  const step = Math.ceil(plan.path.length / 1200);
  const displayPath =
    step > 1 ? plan.path.filter((_, i) => i % step === 0 || i === plan.path.length - 1) : plan.path;

  return (
    <Map
      center={center}
      level={12}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
    >
      <Polyline
        path={displayPath}
        strokeWeight={5}
        strokeColor="#00b894"
        strokeOpacity={0.9}
      />
      {/* 정체=빨강 / 지체=주황 구간을 경로 위에 덧그림 */}
      {plan.congestion.map((c, i) => (
        <Polyline
          key={i}
          path={c.path}
          strokeWeight={6}
          strokeColor={c.level === "jam" ? "#ef4444" : "#f59e0b"}
          strokeOpacity={0.95}
        />
      ))}
      <MapMarker position={plan.origin} title="출발지" />
      <MapMarker position={plan.destination} title="도착지" />
      {plan.charge_points
        .filter((cp) => cp.location)
        .map((cp) => (
          <MapMarker
            key={cp.order}
            position={cp.location!}
            title={cp.station_name ?? "충전 지점"}
            image={{
              src: "data:image/svg+xml;base64," + CHARGE_ICON,
              size: { width: 32, height: 32 },
            }}
            onClick={() => cp.station_id && onSelectStation(cp.station_id)}
          />
        ))}
    </Map>
  );
}

function MapFallback({
  plan,
  onSelectStation,
}: {
  plan: RoutePlanResponse;
  onSelectStation: (id: string) => void;
}) {
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto bg-slate-100 p-4">
      <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-700 ring-1 ring-amber-200">
        NEXT_PUBLIC_KAKAO_JS_KEY 미설정 → 지도 대신 목록으로 표시합니다.
      </div>
      <div className="rounded-xl bg-white p-4 text-sm ring-1 ring-slate-200">
        <p className="font-semibold">
          경로 {plan.total_distance_km}km · 충전 {plan.charge_stops_count}회
        </p>
        <p className="mt-1 text-slate-500">
          출발 ({plan.origin.lat.toFixed(3)}, {plan.origin.lng.toFixed(3)}) →
          도착 ({plan.destination.lat.toFixed(3)}, {plan.destination.lng.toFixed(3)})
        </p>
      </div>
      {plan.charge_points.map((cp) => (
        <button
          key={cp.order}
          onClick={() => cp.station_id && onSelectStation(cp.station_id)}
          disabled={!cp.station_id}
          className="flex items-center justify-between rounded-xl bg-white p-4 text-left ring-1 ring-slate-200 disabled:opacity-60"
        >
          <span>
            <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-[var(--byd-accent)] text-xs font-bold text-white">
              {cp.order}
            </span>
            {cp.station_name ?? "충전 필요 지점"}
          </span>
          <span className="text-xs text-slate-500">
            {cp.distance_from_origin_km}km
          </span>
        </button>
      ))}
    </div>
  );
}

// 초록 원형 번개 아이콘 (base64 SVG)
const CHARGE_ICON =
  "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIzMiIgaGVpZ2h0PSIzMiIgdmlld0JveD0iMCAwIDMyIDMyIj48Y2lyY2xlIGN4PSIxNiIgY3k9IjE2IiByPSIxNCIgZmlsbD0iIzAwYjg5NCIgc3Ryb2tlPSIjZmZmIiBzdHJva2Utd2lkdGg9IjIiLz48cGF0aCBkPSJNMTggN2wtOCAxMWg1bC0xIDcgOC0xMWgtNXoiIGZpbGw9IiNmZmYiLz48L3N2Zz4=";
