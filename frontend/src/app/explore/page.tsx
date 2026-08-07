"use client";

// 지역 충전소 탐색 화면 (S-06).
//
// 기존 화면들은 전부 '경로'가 있어야 충전소를 볼 수 있었다. 이 화면은 경로와
// 무관하게 시/군/구 단위로 충전소 현황을 훑는다 — 여행지 도착 후, 또는 출발 전에
// "이 동네에 뭐가 있나"를 보는 용도다.
//
// 시군구를 코드로 고르게 하지 않고 **장소 검색으로 좌표를 받아 서버가 역산**한다.
// 전국 시군구 코드표를 앱에 심으면 행정구역 개편 때마다 죽는다(강원 42 → 51).
// 검색 모달·좌표 처리 모두 기존 것을 그대로 쓴다.

import { useRouter } from "next/navigation";
import { useState } from "react";
import DistrictMap from "@/components/DistrictMap";
import PlaceSearchModal from "@/components/PlaceSearchModal";
import { getDistrictStations } from "@/lib/api";
import type { LatLng, StationSummary } from "@/lib/types";

export default function ExplorePage() {
  const router = useRouter();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [place, setPlace] = useState<{ name: string; loc: LatLng } | null>(null);
  const [stations, setStations] = useState<StationSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  // 필터. 앞의 셋은 카탈로그만으로 판정돼 추가 외부 호출이 없다.
  // availableOnly만 실시간 상태 조회를 한 번 더 타므로 기본 꺼둔다.
  const [fastOnly, setFastOnly] = useState(true);
  const [openOnly, setOpenOnly] = useState(true);
  const [minKw, setMinKw] = useState(0);
  const [availableOnly, setAvailableOnly] = useState(false);

  async function load(loc: LatLng, name: string) {
    setError(null);
    try {
      const list = await getDistrictStations({
        lat: loc.lat,
        lng: loc.lng,
        fastOnly,
        openOnly,
        minKw,
        withStatus: availableOnly,
      });
      setPlace({ name, loc });
      setStations(list);
    } catch (e) {
      setError((e as Error).message);
      setStations([]);
    }
  }

  return (
    <main className="flex flex-1 flex-col">
      <header className="flex items-center gap-3 border-b border-slate-200 p-4">
        <button
          onClick={() => router.push("/main")}
          className="-m-2 grid h-11 w-11 place-items-center text-slate-500"
          aria-label="뒤로"
        >
          ←
        </button>
        <h1 className="font-bold text-[var(--byd-primary)]">지역 충전소 탐색</h1>
      </header>

      <div className="flex flex-col gap-3 border-b border-slate-200 p-4">
        <button
          onClick={() => setPickerOpen(true)}
          className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3 text-left text-sm ring-1 ring-slate-200"
        >
          {/* slate-400은 흰 배경에서 2.56:1로 WCAG AA(4.5:1) 미달 → 500(4.77:1) */}
          <span className={place ? "font-medium" : "text-slate-500"}>
            {place ? place.name : "지역을 검색하세요 (예: 강릉시청, 속초해수욕장)"}
          </span>
          <span aria-hidden className="text-slate-500">
            🔍
          </span>
        </button>

        <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
          <legend className="sr-only">충전소 필터</legend>
          <Check label="급속만" checked={fastOnly} onChange={setFastOnly} />
          <Check label="외부인 이용가능" checked={openOnly} onChange={setOpenOnly} />
          <Check
            label="지금 사용가능"
            checked={availableOnly}
            onChange={setAvailableOnly}
          />
          <label className="flex items-center gap-1.5">
            <span className="text-slate-600">최소 출력</span>
            <select
              value={minKw}
              onChange={(e) => setMinKw(Number(e.target.value))}
              className="rounded-lg bg-slate-50 px-2 py-1 ring-1 ring-slate-200"
            >
              <option value={0}>제한 없음</option>
              <option value={50}>50kW 이상</option>
              <option value={100}>100kW 이상</option>
              <option value={200}>200kW 이상</option>
            </select>
          </label>
        </fieldset>

        {place && (
          <button
            onClick={() => load(place.loc, place.name)}
            className="self-start rounded-lg bg-[var(--byd-primary)] px-4 py-2 text-xs font-semibold text-white"
          >
            필터 적용해 다시 조회
          </button>
        )}

        <p aria-live="polite" className="text-xs text-slate-500">
          {error ? (
            <span className="text-red-600">{error}</span>
          ) : place ? (
            `${place.name} 일대 ${stations.length}곳`
          ) : (
            "검색한 위치가 속한 시·군·구 전체를 보여줍니다."
          )}
        </p>
      </div>

      <div className="relative flex-1">
        {place ? (
          <DistrictMap
            center={place.loc}
            stations={stations}
            onSelectStation={(id) => router.push(`/stations/${id}`)}
          />
        ) : (
          <p className="grid h-full place-items-center p-6 text-center text-sm text-slate-500">
            지역을 검색하면 그 시·군·구의 충전소가 지도에 표시됩니다.
          </p>
        )}
      </div>

      {pickerOpen && (
        <PlaceSearchModal
          title="지역 검색"
          onClose={() => setPickerOpen(false)}
          onSelect={(p) => {
            setPickerOpen(false);
            load(p.location, p.name);
          }}
        />
      )}
    </main>
  );
}

function Check({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-1.5">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-[var(--byd-accent)]"
      />
      <span className="text-slate-600">{label}</span>
    </label>
  );
}
