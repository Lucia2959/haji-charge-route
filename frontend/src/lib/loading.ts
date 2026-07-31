"use client";

// 전역 로딩 카운터 — 서버호출/화면로딩 시 회전 로더 오버레이를 띄운다.
import { useEffect, useState } from "react";

let count = 0;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

export function beginLoading() {
  count += 1;
  emit();
}

export function endLoading() {
  count = Math.max(0, count - 1);
  emit();
}

/** 프로미스 동안 전역 로딩을 표시. 모든 서버호출을 이걸로 감싼다. */
export async function withLoading<T>(p: Promise<T>): Promise<T> {
  beginLoading();
  try {
    return await p;
  } finally {
    endLoading();
  }
}

/** 로딩 중이면 true (짧은 표시 지연으로 깜빡임 방지). */
export function useGlobalLoading(delayMs = 120): boolean {
  const [active, setActive] = useState(count > 0);
  useEffect(() => {
    const update = () => setActive(count > 0);
    listeners.add(update);
    update();
    return () => {
      listeners.delete(update);
    };
  }, []);

  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (active) {
      const t = setTimeout(() => setShown(true), delayMs);
      return () => clearTimeout(t);
    }
    setShown(false);
  }, [active, delayMs]);

  return shown;
}
