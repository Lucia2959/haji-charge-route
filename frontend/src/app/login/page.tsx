"use client";

// 로그인 화면 (S-01) — **실제 인증은 없다.** 진입 연출과 고지 역할이다.
//
// BYD 로고를 쓰는 이상 공식 앱으로 오인될 여지가 있어, "비공식 개인 테스트 앱"
// 고지를 화면에 둔다. 이 문구는 삭제하지 말 것(품질처리내역 A-11).
import Image from "next/image";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();

  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-10 px-8">
      <div className="flex flex-col items-center gap-4">
        <div className="flex h-28 w-28 items-center justify-center rounded-3xl bg-white shadow-md ring-1 ring-slate-200">
          <Image src="/bydLogo.png" alt="BYD" width={88} height={88} priority />
        </div>
        <h1 className="text-xl font-bold text-[var(--byd-primary)]">
          충전 경로 안내
        </h1>
        <p className="text-sm text-slate-500">BYD 돌핀 스탠다드 기준 참고 계산</p>
        <p className="text-[11px] text-slate-500">비공식 개인 테스트 앱</p>
      </div>

      <button
        onClick={() => router.push("/main")}
        className="w-full max-w-xs rounded-xl bg-[var(--byd-primary)] py-4 text-base font-semibold text-white active:scale-[0.99]"
      >
        시작하기
      </button>
    </main>
  );
}
