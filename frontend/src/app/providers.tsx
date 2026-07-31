"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export default function Providers({ children }: { children: React.ReactNode }) {
  // 기본값(retry 3)은 402(사용량 초과)·404에도 4회를 재시도해 쿼터를 더 태운다.
  // 실패는 1회만 재시도하고, 사용량초과/없음 응답은 즉시 포기한다.
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 10_000,
            retry: (count, err) =>
              count < 1 && !/(402|404|사용량)/.test(String((err as Error)?.message)),
          },
        },
      })
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
