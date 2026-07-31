"use client";

// 장소 검색 모달 (M-01) — 출발지·도착지·즐겨찾기 등록에 공용으로 쓴다.
//
// 호출부(main/page.tsx)는 선택된 좌표를 `"lng,lat"` 문자열로 만들어 보관한다.
// 경로계산 때 지오코딩을 다시 타지 않아 API 호출 1회를 아끼고 정확도도 높다.
import { useEffect, useRef, useState } from "react";
import { searchPlaces } from "@/lib/api";
import type { PlaceResult } from "@/lib/types";

export default function PlaceSearchModal({
  title,
  onSelect,
  onClose,
}: {
  title: string;
  onSelect: (place: PlaceResult) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PlaceResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // ESC 닫기 + 포커스 트랩 + 닫힘 시 이전 포커스 복귀 (WCAG 2.1.1/2.4.3)
  // 마운트 시 1회만 등록 — onClose는 ref로 최신값을 읽어, 부모 리렌더로 포커스가
  // 되돌아가거나 리스너가 재등록되지 않게 한다.
  useEffect(() => {
    const prevFocus = document.activeElement as HTMLElement | null;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusables = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prevFocus?.focus?.();
    };
  }, []);

  async function run() {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setResults(await searchPlaces(query));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="place-search-title"
        className="flex max-h-[80dvh] w-full max-w-[430px] flex-col rounded-t-2xl bg-white"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 p-4">
          <h2 id="place-search-title" className="font-bold text-[var(--byd-primary)]">
            {title} 검색
          </h2>
          <button onClick={onClose} className="-m-2 grid h-11 w-11 place-items-center text-slate-500" aria-label="닫기">
            ✕
          </button>
        </div>

        <div className="flex gap-2 p-4">
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
            placeholder="주소·지명·건물명"
            className="flex-1 rounded-xl border border-slate-200 px-3.5 py-2.5 text-base outline-none focus:border-[var(--byd-accent)]"
          />
          <button
            onClick={run}
            className="rounded-xl bg-[var(--byd-primary)] px-4 text-sm font-semibold text-white"
          >
            검색
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4" aria-live="polite">
          {loading && <p className="p-2 text-sm text-slate-500">검색 중…</p>}
          {error && <p role="alert" className="p-2 text-sm text-red-500">{error}</p>}
          {!loading && !error && results.length === 0 && (
            <p className="p-2 text-sm text-slate-500">
              검색어를 입력하고 검색하세요.
            </p>
          )}
          <ul className="flex flex-col gap-1">
            {results.map((p, i) => (
              <li key={`${p.name}-${i}`}>
                <button
                  onClick={() => onSelect(p)}
                  className="w-full rounded-xl px-3 py-3 text-left hover:bg-slate-50"
                >
                  <p className="text-sm font-medium text-[var(--byd-primary)]">
                    {p.name}
                  </p>
                  <p className="text-xs text-slate-500">{p.address}</p>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
