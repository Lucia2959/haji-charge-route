import type { MetadataRoute } from "next";

// PWA manifest — 모바일 홈 화면 추가·standalone 실행용. Next가 /manifest.webmanifest로
// 서빙하고 <link rel="manifest">를 자동 주입한다.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "충전 경로 안내",
    short_name: "충전경로",
    description: "BYD 돌핀 전기차 충전 경로 안내 (비공식 개인 테스트)",
    start_url: "/",
    display: "standalone",
    background_color: "#f2f4f7",
    theme_color: "#0a2540",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      // 아이콘은 14% 여백을 둬 maskable 안전영역을 확보했다.
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
