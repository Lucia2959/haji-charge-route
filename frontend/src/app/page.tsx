import { redirect } from "next/navigation";

// 루트 진입점. PWA manifest의 start_url이 "/"이므로 홈 화면 아이콘으로 실행하면
// 여기로 들어온다 → 로그인(시작) 화면으로 넘긴다.
export default function Home() {
  redirect("/login");
}
