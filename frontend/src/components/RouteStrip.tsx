"use client";

// 충전 계획 결과를 가로 경로 스트립으로 시각화한다(경로별산출로직.pptx 디자인).
//   출발지 → (구간 소비 −%) → 충전소(도착%→충전%) → … → 목적지(도착%)
// 각 지점의 SoC·누적거리, 구간별 소비/충전 델타를 배터리 색상으로 표현. 가로 스크롤.
import Image from "next/image";
import { Fragment } from "react";
import type { RoutePlanResponse } from "@/lib/types";

type Node =
  | { kind: "origin"; soc: number; km: number }
  | {
      kind: "charge";
      order: number;
      name: string;
      arrive: number;
      depart: number | null;
      km: number;
      available: boolean | null;
      stationId: string | null;
    }
  | { kind: "dest"; soc: number; km: number; name?: string; stationId?: string | null };

// SoC 수준별 색상(초록 여유 / 주황 주의 / 빨강 위험)
function socColor(soc: number) {
  if (soc >= 50) return { fg: "#047857", bg: "#d1fae5", dot: "#10b981" };
  if (soc >= 20) return { fg: "#b45309", bg: "#fef3c7", dot: "#f59e0b" };
  return { fg: "#b91c1c", bg: "#fee2e2", dot: "#ef4444" };
}

function buildNodes(plan: RoutePlanResponse): Node[] {
  const cps = plan.charge_points;
  const nodes: Node[] = [
    { kind: "origin", soc: plan.current_charge_pct, km: 0 },
  ];
  for (const cp of cps) {
    nodes.push({
      kind: "charge",
      order: cp.order,
      name: cp.station_name ?? "충전소",
      arrive: cp.charge_from_pct ?? 0,
      depart: cp.charge_to_pct,
      km: cp.distance_from_origin_km,
      available: cp.available,
      stationId: cp.station_id,
    });
  }
  // 목적지 도착 SoC = 마지막 출발 SoC − 남은거리 소비 (유효거리 기준, 계산근거와 동일)
  const last = cps[cps.length - 1];
  const lastSoc = last ? last.charge_to_pct ?? plan.current_charge_pct : plan.current_charge_pct;
  const lastKm = last ? last.distance_from_origin_km : 0;
  const destSoc =
    plan.effective_range_km > 0
      ? lastSoc - ((plan.total_distance_km - lastKm) / plan.effective_range_km) * 100
      : lastSoc;
  nodes.push({
    kind: "dest",
    soc: Math.max(0, Math.round(destSoc)),
    km: plan.total_distance_km,
    name: plan.destination_charging?.station_name,
    stationId: plan.destination_charging?.station_id,
  });
  return nodes;
}

export default function RouteStrip({
  plan,
  onSelectStation,
}: {
  plan: RoutePlanResponse;
  onSelectStation?: (stationId: string) => void;
}) {
  const nodes = buildNodes(plan);
  // 지점 3개 이하면 화면 폭에 꽉 차게 균등 배치(연결선이 늘어남), 4개 이상은 가로 스크롤
  const compact = nodes.length <= 3;

  return (
    <div className="overflow-hidden rounded-2xl bg-gradient-to-br from-slate-50 to-white ring-1 ring-slate-200">
      <div className="flex items-center gap-2 px-3.5 pt-3">
        <RouteGlyph />
        <span className="text-[11px] font-semibold text-[var(--byd-primary)]">
          경로 · 충전 흐름
        </span>
        <span className="ml-auto text-[10px] text-slate-500">
          총 {plan.total_distance_km}km · 충전 {plan.charge_stops_count}회
        </span>
      </div>

      <div className={compact ? "px-3 pb-3 pt-2" : "overflow-x-auto px-3 pb-3 pt-2"}>
        <div className={`flex items-stretch ${compact ? "" : "min-w-max"}`}>
          {nodes.map((n, i) => (
            <Fragment key={i}>
              {i > 0 && <Segment prev={nodes[i - 1]} cur={n} grow={compact} />}
              <NodeCell node={n} onSelectStation={onSelectStation} />
            </Fragment>
          ))}
        </div>
      </div>
    </div>
  );
}

// 지점(출발/충전/도착) 셀 — 아이콘 + SoC 배지 + 라벨 + 누적거리 + (충전소명 링크)
function NodeCell({
  node,
  onSelectStation,
}: {
  node: Node;
  onSelectStation?: (stationId: string) => void;
}) {
  const soc =
    node.kind === "charge" ? node.arrive : node.soc;
  const c = socColor(soc);
  const label =
    node.kind === "origin"
      ? "출발지"
      : node.kind === "dest"
        ? "목적지"
        : `${node.order}차`;

  return (
    <div className="flex w-[76px] shrink-0 flex-col items-center gap-1 text-center">
      {/* 원형 레이어 없이 아이콘만 표시 */}
      <div className="grid h-11 w-11 place-items-center">
        {node.kind === "origin" && <CarIcon />}
        {node.kind === "dest" && <FlagIcon />}
        {node.kind === "charge" && <BoltIcon />}
      </div>
      <span className="text-[10px] font-semibold text-slate-600">{label}</span>

      {/* SoC 배지 */}
      {node.kind === "charge" ? (
        <span
          className="rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none"
          style={{ color: c.fg, background: c.bg }}
        >
          {node.arrive}→{node.depart ?? "?"}%
        </span>
      ) : (
        <span
          className="rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none"
          style={{ color: c.fg, background: c.bg }}
        >
          {Math.round(soc)}%
        </span>
      )}

      <span className="text-[11px] text-slate-500">{node.km}km</span>

      {/* 충전소명 / 목적지명 — station_id 있으면 클릭 시 상세화면으로 이동 */}
      {(() => {
        const name =
          node.kind === "charge" ? node.name : node.kind === "dest" ? node.name : undefined;
        const stationId =
          node.kind === "charge" || node.kind === "dest" ? node.stationId : undefined;
        if (!name) return null;
        return stationId ? (
          <button
            onClick={() => onSelectStation?.(stationId)}
            title={`${name} 상세 보기`}
            className="max-w-[74px] truncate text-[11px] font-medium text-[var(--byd-primary)] underline decoration-dotted decoration-emerald-400 underline-offset-2 active:scale-[0.98]"
          >
            {name}
          </button>
        ) : (
          <span className="max-w-[74px] truncate text-[11px] text-slate-500" title={name}>
            {name}
          </span>
        );
      })()}
    </div>
  );
}

// 구간 연결선 — 주행 소비 델타(−%) + 충전 델타(+%)를 배터리 색으로 표시.
// grow=true면 flex-1로 늘어나 지점이 화면 폭에 균등 배치된다.
function Segment({ prev, cur, grow }: { prev: Node; cur: Node; grow?: boolean }) {
  const prevSoc = prev.kind === "charge" ? (prev.depart ?? prev.arrive) : prev.soc;
  const curSoc = cur.kind === "charge" ? cur.arrive : cur.soc;
  const drive = Math.round(curSoc - prevSoc); // 음수 = 주행 소비
  const legKm =
    (cur.kind === "origin" ? 0 : cur.km) -
    (prev.kind === "origin" ? 0 : prev.km);

  return (
    <div
      className={`flex flex-col items-center justify-center pb-6 ${
        grow ? "flex-1" : "min-w-[52px]"
      }`}
    >
      {/* 연결선 + 화살촉 */}
      <div className="relative flex h-3 w-full items-center">
        <div className="h-[3px] w-full rounded-full bg-gradient-to-r from-slate-300 to-slate-400" />
        <svg
          className="absolute right-0 -mr-0.5"
          width="7"
          height="9"
          viewBox="0 0 7 9"
          aria-hidden
        >
          <path d="M0 0l6 4.5L0 9z" fill="#94a3b8" />
        </svg>
      </div>
      {/* 주행 소비 델타 칩 */}
      <span
        className="mt-1 rounded-full px-1.5 py-0.5 text-[11px] font-bold leading-none"
        style={{ color: "#b91c1c", background: "#fee2e2" }}
      >
        {drive}%
      </span>
      <span className="mt-0.5 text-[10px] text-slate-500">
        {Math.round(legKm)}km
      </span>
    </div>
  );
}

// ─── 아이콘 (いらすとや / irasutoya.com — 무료 일러스트) ──────────────────
// 출발지 — 자동차(いろいろな色の自動車 · 그린)
function CarIcon() {
  return (
    <Image src="/icons/origin-car.png" alt="" width={38} height={38} aria-hidden />
  );
}

// 충전소 — EV 충전 플러그(電気自動車の充電プラグ)
function BoltIcon() {
  return (
    <Image src="/icons/charger.png" alt="" width={34} height={34} aria-hidden />
  );
}

// 목적지 — 체커 플래그(チェッカーフラッグ)
function FlagIcon() {
  return (
    <Image src="/icons/dest-flag.png" alt="" width={34} height={34} aria-hidden />
  );
}

// 헤더 라우트 글리프
function RouteGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden>
      <circle cx="5" cy="19" r="2.4" fill="none" stroke="var(--byd-accent)" strokeWidth="1.8" />
      <circle cx="19" cy="5" r="2.4" fill="none" stroke="var(--byd-primary)" strokeWidth="1.8" />
      <path
        d="M7 18C13 18 11 6 17 6"
        fill="none"
        stroke="#94a3b8"
        strokeWidth="1.8"
        strokeDasharray="2 2"
        strokeLinecap="round"
      />
    </svg>
  );
}
