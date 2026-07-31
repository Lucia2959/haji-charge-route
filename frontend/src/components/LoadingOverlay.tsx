"use client";

import { useEffect, useState } from "react";
import { useGlobalLoading } from "@/lib/loading";
import CarLoader from "./CarLoader";

// 경과 시간에 따른 안내. 콜드 상태의 경로계산은 시군구 20여 곳의 충전소 목록을
// 받아오느라 1분 가까이 걸릴 수 있어, 아무 설명이 없으면 멈춘 것처럼 보인다.
const STAGES: [number, string][] = [
  [0, "불러오는 중…"],
  [4000, "실시간 교통·충전소 상태 조회 중…"],
  [12000, "충전 계획 최적화 중… 처음엔 1분까지 걸릴 수 있어요"],
];

// 전역 로딩 오버레이 — 서버호출/화면로딩 동안 회전 차량 로더를 띄운다.
export default function LoadingOverlay() {
  const loading = useGlobalLoading();
  const [label, setLabel] = useState(STAGES[0][1]);

  useEffect(() => {
    if (!loading) {
      setLabel(STAGES[0][1]);
      return;
    }
    const started = Date.now();
    const id = setInterval(() => {
      const el = Date.now() - started;
      const stage = [...STAGES].reverse().find(([at]) => el >= at);
      if (stage) setLabel(stage[1]);
    }, 1000);
    return () => clearInterval(id);
  }, [loading]);

  if (!loading) return null;
  return (
    <div
      // 로딩 중 메인화면 터치/스크롤 차단 + 옅은 배경
      role="status"
      aria-live="polite"
      aria-busy="true"
      onClickCapture={(e) => e.stopPropagation()}
      onTouchStartCapture={(e) => e.stopPropagation()}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(240,244,248,0.55)",
        backdropFilter: "blur(1.5px)",
        pointerEvents: "auto",
        touchAction: "none",
        cursor: "wait",
      }}
    >
      <CarLoader size={44} label={label} />
    </div>
  );
}
