"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import KakaoMap from "@/components/KakaoMap";
import { loadPlan } from "@/lib/api";
import type { RoutePlanResponse } from "@/lib/types";

export default function MapPage() {
  const router = useRouter();
  const [plan, setPlan] = useState<RoutePlanResponse | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setPlan(loadPlan());
    setReady(true);
  }, []);

  if (ready && !plan) {
    return (
      <main className="flex flex-1 flex-col items-center justify-center gap-4 p-6">
        <p className="text-sm text-slate-500">경로 정보가 없습니다.</p>
        <button
          onClick={() => router.push("/main")}
          className="rounded-xl bg-[var(--byd-primary)] px-6 py-3 font-semibold text-white"
        >
          메인으로
        </button>
      </main>
    );
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
        <h1 className="font-bold text-[var(--byd-primary)]">지도보기</h1>
      </header>
      {plan?.data_source === "mock" && (
        <p
          role="alert"
          className="bg-amber-50 px-4 py-2 text-xs font-medium text-amber-700"
        >
          ⚠ 추정 경로입니다. 실제 도로 경로와 다를 수 있습니다.
        </p>
      )}
      <div className="relative flex-1">
        {plan && (
          <KakaoMap
            plan={plan}
            onSelectStation={(id) => router.push(`/stations/${id}`)}
          />
        )}
        {plan && plan.congestion.length > 0 && (
          <div className="absolute left-3 top-3 z-10 rounded-lg bg-white/90 px-3 py-2 text-xs shadow ring-1 ring-slate-200">
            <div className="mb-1 font-semibold text-slate-600">실시간 교통</div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-4 rounded" style={{ background: "#ef4444" }} />
              정체 {plan.jam_km}km
            </div>
            <div className="mt-0.5 flex items-center gap-1.5">
              <span className="inline-block h-2 w-4 rounded" style={{ background: "#f59e0b" }} />
              지체 {plan.delay_km}km
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
