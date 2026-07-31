// 충전 계산 로직 (BYD 돌핀 스탠다드 기준)
// - %↔kWh 변환은 배터리 용량 기준
// - 금액 = 추가 충전량(kWh) × 단가
// - 소요시간 = 추가 충전량(kWh) ÷ 충전기 출력(kW)
import type { SelectedCharger } from "./api";

// BYD 돌핀 스탠다드 배터리 용량 (BYD코리아 공식, LFP 블레이드 사용가능 용량)
// 백엔드 charging.py DOLPHIN_STANDARD.capacity_kwh 와 반드시 같은 값을 유지한다.
export const CAPACITY_KWH = 49.92;

export type Unit = "pct" | "kwh";

export function toKwh(value: number, unit: Unit): number {
  return unit === "pct" ? (CAPACITY_KWH * value) / 100 : value;
}

export function toPct(value: number, unit: Unit): number {
  return unit === "kwh" ? (value / CAPACITY_KWH) * 100 : value;
}

export interface ChargeEstimate {
  currentPct: number;
  currentKwh: number;
  targetPct: number;
  targetKwh: number;
  chargeKwh: number; // 추가 충전량
  chargePct: number;
  priceWon: number;
  minutes: number;
  formulas: string[]; // 계산근거
}

export function estimateCharge(
  currentValue: number,
  currentUnit: Unit,
  targetValue: number,
  targetUnit: Unit,
  charger: SelectedCharger
): ChargeEstimate {
  const currentKwh = toKwh(currentValue, currentUnit);
  const currentPct = toPct(currentValue, currentUnit);
  const targetKwh = toKwh(targetValue, targetUnit);
  const targetPct = toPct(targetValue, targetUnit);

  const chargeKwh = Math.max(0, targetKwh - currentKwh);
  const chargePct = Math.max(0, targetPct - currentPct);
  const priceWon = chargeKwh * charger.unit_price;
  const minutes = charger.power_kw > 0 ? (chargeKwh / charger.power_kw) * 60 : 0;

  const formulas = [
    `예상충전량(목표): ${CAPACITY_KWH}kWh × ${targetPct.toFixed(0)}% = ${targetKwh.toFixed(2)}kWh`,
    `현충전량: ${CAPACITY_KWH}kWh × ${currentPct.toFixed(0)}% = ${currentKwh.toFixed(2)}kWh`,
    `충전량(추가): ${targetKwh.toFixed(2)} − ${currentKwh.toFixed(2)} = ${chargeKwh.toFixed(2)}kWh`,
    `충전 금액: ${chargeKwh.toFixed(2)}kWh × ${charger.unit_price}원/kWh = ${Math.round(priceWon).toLocaleString()}원`,
    `예상 소요시간: ${chargeKwh.toFixed(2)}kWh ÷ ${charger.power_kw}kW × 60 = ${minutes.toFixed(1)}분`,
  ];

  return {
    currentPct,
    currentKwh,
    targetPct,
    targetKwh,
    chargeKwh,
    chargePct,
    priceWon,
    minutes,
    formulas,
  };
}
