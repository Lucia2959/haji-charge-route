"use client";

// 충전 계산 화면 (S-05) — 충전소 상세에서 고른 충전기 기준 금액·시간 계산.
//
// ⚠ 이 화면의 계산은 백엔드 DP와 **다르다.** 여기는 사용자가 임의로 고른 충전기에
// 대한 단순 정출력 계산(kWh ÷ kW × 60)이고, 백엔드 plan_charging_dp()는 SoC별
// 충전커브(taper)를 반영한다. 고SoC 구간에서 실제 시간은 이 화면 값보다 길어진다.
// 그래서 화면 하단에 "단순 정출력 기준" 고지를 붙였다 — 삭제하지 말 것.
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { loadCharger, type SelectedCharger } from "@/lib/api";
import { CAPACITY_KWH, estimateCharge, toKwh, toPct, type Unit } from "@/lib/charge";

export default function ChargePage() {
  const router = useRouter();
  const [charger, setCharger] = useState<SelectedCharger | null>(null);
  const [ready, setReady] = useState(false);

  const [curVal, setCurVal] = useState("44");
  const [curUnit, setCurUnit] = useState<Unit>("pct");
  const [tgtVal, setTgtVal] = useState("80");
  const [tgtUnit, setTgtUnit] = useState<Unit>("pct");

  useEffect(() => {
    setCharger(loadCharger());
    setReady(true);
  }, []);

  const est = useMemo(() => {
    if (!charger) return null;
    return estimateCharge(
      Number(curVal) || 0,
      curUnit,
      Number(tgtVal) || 0,
      tgtUnit,
      charger
    );
  }, [charger, curVal, curUnit, tgtVal, tgtUnit]);

  // 단위 토글 시 같은 물리량을 유지하도록 값 변환
  function switchUnit(
    val: string,
    from: Unit,
    to: Unit,
    setVal: (s: string) => void,
    setUnit: (u: Unit) => void
  ) {
    if (from === to) return;
    const n = Number(val) || 0;
    const converted = to === "kwh" ? toKwh(n, "pct") : toPct(n, "kwh");
    setVal(converted.toFixed(to === "kwh" ? 2 : 0));
    setUnit(to);
  }

  if (ready && !charger) {
    return (
      <main className="flex flex-1 flex-col items-center justify-center gap-4 p-6">
        <p className="text-sm text-slate-500">선택된 충전기가 없습니다.</p>
        <button
          onClick={() => router.back()}
          className="rounded-xl bg-[var(--byd-primary)] px-6 py-3 font-semibold text-white"
        >
          충전소로 돌아가기
        </button>
      </main>
    );
  }

  return (
    <main className="flex flex-1 flex-col">
      <header className="flex items-center gap-3 border-b border-slate-200 p-4">
        <button onClick={() => router.back()} className="-m-2 grid h-11 w-11 place-items-center text-slate-500" aria-label="뒤로">
          ←
        </button>
        <h1 className="font-bold text-[var(--byd-primary)]">충전 계산</h1>
      </header>

      {charger && est && (
        <div className="flex flex-1 flex-col gap-4 p-5">
          {/* 선택한 충전기 스펙 */}
          <section className="rounded-2xl bg-slate-50 p-4 ring-1 ring-slate-200">
            <p className="text-xs text-slate-500">선택한 충전기</p>
            <p className="font-semibold text-[var(--byd-primary)]">
              {charger.station_name} · {charger.charger_no}번 ({charger.charge_type})
            </p>
            <div className="mt-1 flex gap-4 text-xs text-slate-500">
              <span>출력 {charger.power_kw}kW</span>
              <span>단가 {charger.unit_price}원/kWh</span>
              <span>배터리 {CAPACITY_KWH}kWh</span>
            </div>
          </section>

          {/* 입력 */}
          <ChargeInput
            label="현충전량"
            val={curVal}
            unit={curUnit}
            onVal={setCurVal}
            onUnit={(u) => switchUnit(curVal, curUnit, u, setCurVal, setCurUnit)}
            hint={`= ${
              curUnit === "pct"
                ? `${toKwh(Number(curVal) || 0, "pct").toFixed(2)}kWh`
                : `${toPct(Number(curVal) || 0, "kwh").toFixed(0)}%`
            }`}
          />
          <ChargeInput
            label="예상충전량 (목표)"
            val={tgtVal}
            unit={tgtUnit}
            onVal={setTgtVal}
            onUnit={(u) => switchUnit(tgtVal, tgtUnit, u, setTgtVal, setTgtUnit)}
            hint={`= ${
              tgtUnit === "pct"
                ? `${toKwh(Number(tgtVal) || 0, "pct").toFixed(2)}kWh`
                : `${toPct(Number(tgtVal) || 0, "kwh").toFixed(0)}%`
            }`}
          />

          {/* 결과 */}
          <section className="rounded-2xl bg-white p-4 ring-1 ring-slate-200">
            <ResultRow
              label="예상충전량 (목표)"
              value={`${est.targetPct.toFixed(0)}% (${est.targetKwh.toFixed(2)} kWh)`}
            />
            <ResultRow
              label="충전량 (추가)"
              value={`${est.chargeKwh.toFixed(2)} kWh (${est.chargePct.toFixed(0)}%p)`}
            />
            <ResultRow
              label="충전 금액"
              value={`${Math.round(est.priceWon).toLocaleString()} 원`}
              highlight
            />
            <ResultRow
              label="예상 소요시간 (잔여시간)"
              value={`${est.minutes.toFixed(1)} 분`}
              highlight
            />
          </section>

          {/* 단순 계산·참고값 안내 */}
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-500 ring-1 ring-slate-200">
            단순 정출력 기준 계산입니다. 실제 충전 시간은 배터리 온도·충전 상태(고SoC
            구간 감속)에 따라 달라질 수 있습니다. 단가는 앱 내 참고값입니다.
          </p>

          {/* 계산근거 (잔여시간 하단) */}
          <section className="rounded-2xl bg-slate-900 p-4 text-slate-100">
            <p className="mb-2 text-xs font-semibold text-slate-500">계산근거</p>
            <ul className="flex flex-col gap-1.5 font-mono text-[12px] leading-relaxed">
              {est.formulas.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </main>
  );
}

function ChargeInput({
  label,
  val,
  unit,
  onVal,
  onUnit,
  hint,
}: {
  label: string;
  val: string;
  unit: Unit;
  onVal: (s: string) => void;
  onUnit: (u: Unit) => void;
  hint: string;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-slate-500">{label}</span>
      <div className="flex gap-2">
        <input
          value={val}
          onChange={(e) => onVal(e.target.value)}
          type="number"
          min={0}
          max={unit === "pct" ? 100 : undefined}
          className="flex-1 rounded-xl border border-slate-200 px-3.5 py-2.5 text-base outline-none focus:border-[var(--byd-accent)]"
        />
        <div className="flex overflow-hidden rounded-xl ring-1 ring-slate-200">
          {(["pct", "kwh"] as Unit[]).map((u) => (
            <button
              key={u}
              onClick={() => onUnit(u)}
              aria-pressed={unit === u}
              className={
                unit === u
                  ? "bg-[var(--byd-primary)] px-3 text-xs font-semibold text-white"
                  : "bg-white px-3 text-xs text-slate-500"
              }
            >
              {u === "pct" ? "%" : "kWh"}
            </button>
          ))}
        </div>
      </div>
      <span className="text-[11px] text-slate-500">{hint}</span>
    </label>
  );
}

function ResultRow({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="flex items-center justify-between border-b border-slate-100 py-2 last:border-0">
      <span className="text-sm text-slate-500">{label}</span>
      <span
        className={
          highlight
            ? "text-base font-bold text-[var(--byd-accent)]"
            : "text-sm font-semibold text-[var(--byd-primary)]"
        }
      >
        {value}
      </span>
    </div>
  );
}
