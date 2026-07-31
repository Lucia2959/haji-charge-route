"use client";

import { useGlobalLoading } from "@/lib/loading";
import CarLoader from "./CarLoader";

// 전역 로딩 오버레이 — 서버호출/화면로딩 동안 회전 차량 로더를 띄운다.
export default function LoadingOverlay() {
  const loading = useGlobalLoading();
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
      <CarLoader size={44} label="불러오는 중…" />
    </div>
  );
}
