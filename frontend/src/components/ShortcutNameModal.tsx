"use client";

// 즐겨찾기 이름 입력 (M-02) — 등록 시엔 검색된 장소명을, 수정 시엔 현재 이름을
// 기본값으로 채운다. 이름은 개인 라벨이라 주소와 함께 기기 localStorage에만 남는다.
//
// 네이티브 <dialog>를 쓰면 포커스 트랩·ESC를 브라우저가 처리해 더 짧아지지만,
// 닫힘 통지가 close 이벤트에 묶인다. 이 앱의 주 사용처가 아이폰 홈화면 PWA라
// 검증 못 한 채로 내보내면 첫 저장 후 모달이 다시 안 열려도 알 수 없다 →
// 이미 운영에서 검증된 PlaceSearchModal과 같은 구조(직접 제어)로 맞췄다.
import { useEffect, useRef, useState } from "react";

export default function ShortcutNameModal({
  title,
  initial,
  onSave,
  onDelete,
  onClose,
}: {
  title: string;
  initial: string;
  onSave: (name: string) => void;
  // 이미 등록된 항목을 고칠 때만 온다. 신규 등록 중에는 지울 게 없어 버튼도 없다.
  onDelete?: () => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(initial);
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // ESC 닫기 + 포커스 트랩 + 닫힘 시 이전 포커스 복귀 (WCAG 2.1.1/2.4.3)
  // PlaceSearchModal과 동일한 패턴 — onClose는 ref로 최신값을 읽는다.
  useEffect(() => {
    const prevFocus = document.activeElement as HTMLElement | null;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const f = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, input, [tabindex]:not([tabindex="-1"])'
        );
        if (f.length === 0) return;
        const first = f[0];
        const last = f[f.length - 1];
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

  function submit() {
    const v = name.trim();
    if (!v) return; // 공백만 입력한 경우 — 저장하지 않고 모달도 닫지 않는다
    onSave(v);
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcut-name-title"
        className="flex w-full max-w-[360px] flex-col gap-3 rounded-2xl bg-white p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="shortcut-name-title"
          className="font-bold text-[var(--byd-primary)]"
        >
          {title}
        </h2>
        <input
          autoFocus
          maxLength={12}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="집, 회사, 처가…"
          // text-base(16px) 유지 — 더 작으면 iOS가 입력 시 화면을 확대한다
          className="rounded-xl border border-slate-200 px-3.5 py-2.5 text-base outline-none focus:border-[var(--byd-accent)]"
        />
        <div className="flex gap-2">
          {onDelete && (
            <button
              onClick={() => {
                onDelete();
                onClose();
              }}
              // 텍스트 대비 4.5:1 확보용 red-700 (red-500은 흰 배경에서 미달)
              className="flex-1 rounded-xl bg-red-50 py-2.5 text-sm font-semibold text-red-700 ring-1 ring-red-200"
            >
              삭제
            </button>
          )}
          <button
            onClick={onClose}
            className="flex-1 rounded-xl bg-slate-100 py-2.5 text-sm font-semibold text-slate-600"
          >
            취소
          </button>
          <button
            onClick={submit}
            disabled={!name.trim()}
            className="flex-1 rounded-xl bg-[var(--byd-primary)] py-2.5 text-sm font-semibold text-white disabled:opacity-40"
          >
            저장
          </button>
        </div>
      </div>
    </div>
  );
}
