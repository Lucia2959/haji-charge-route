import type { Metadata, Viewport } from "next";
import LoadingOverlay from "@/components/LoadingOverlay";
import Providers from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Haji Charge Route",
  description: "BYD 돌핀 전기차 충전 경로 안내",
  // 모바일 웹앱: 홈 화면 추가 시 아이콘·standalone 실행
  appleWebApp: { capable: true, statusBarStyle: "default", title: "충전경로" },
  icons: { apple: "/apple-icon.png" },
};

export const viewport: Viewport = {
  // maximumScale 제거: 저시력 사용자의 모바일 확대를 막지 않는다 (WCAG 1.4.4)
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover", // 노치 대응(standalone)
  themeColor: "#0a2540", // 상태바 색(브랜드 네이비)
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body>
        <Providers>
          <div className="phone-shell">{children}</div>
          <LoadingOverlay />
        </Providers>
      </body>
    </html>
  );
}
