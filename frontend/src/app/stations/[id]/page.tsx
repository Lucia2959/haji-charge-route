"use client";

// 충전소 상세 화면 (S-04) — 실시간 충전기 상태.
//
// 표시 원칙: 공공 API가 주지 않는 값(잔여시간·회원요금 등)은 빈 값으로 두지 않고
// **섹션 자체를 렌더에서 제외**한다. 빈 칸이 있으면 "데이터가 있는데 못 읽었다"로
// 오해되기 때문. `data_source` 표기로 실데이터/mock을 항상 구분해 보여준다.
import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import CarLoader from "@/components/CarLoader";
import { getStation, saveCharger } from "@/lib/api";
import { TMAP_STORE_ANDROID, TMAP_STORE_IOS, tmapUrl } from "@/lib/tmap";
import type { LatLng, RealtimeCharger } from "@/lib/types";

export default function StationPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["station", id],
    queryFn: () => getStation(id),
    // 실시간 충전현황 10초마다 갱신. 백엔드 상태캐시가 20초라 실제 외부 API 호출은
    // 20초에 1회다 → 폴링 자체는 저렴하지만, 화면을 열어둔 채 방치하면 20초당
    // 1회씩 계속 쿼터를 쓴다(운영이슈 I-S04).
    refetchInterval: 10_000,
  });

  return (
    <main className="flex flex-1 flex-col">
      <header className="flex items-center gap-3 border-b border-slate-200 p-4">
        <button onClick={() => router.back()} className="-m-2 grid h-11 w-11 place-items-center text-slate-500" aria-label="뒤로">
          ←
        </button>
        <h1 className="font-bold text-[var(--byd-primary)]">충전소 상세</h1>
      </header>

      <div className="flex flex-1 flex-col gap-4 p-5">
        {isLoading && (
          <div className="flex justify-center py-16">
            <CarLoader size={48} label="불러오는 중…" />
          </div>
        )}
        {isError && (
          <p className="text-sm text-red-500">{(error as Error).message}</p>
        )}

        {data && (
          <>
            {data.data_source === "mock" && (
              <p
                role="alert"
                className="rounded-lg bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700 ring-1 ring-amber-200"
              >
                ⚠ 테스트용 mock 데이터입니다. 실제 충전소 상태가 아닙니다.
              </p>
            )}

            <section>
              <p className="text-xs text-slate-500">충전소명</p>
              <h2 className="text-xl font-bold text-[var(--byd-primary)]">
                {data.name}
              </h2>
            </section>

            <TmapButton name={data.name} location={data.location} />

            <Row label="충전기 타입">
              <div className="flex gap-2">
                {data.charger_types.map((t) => (
                  <span
                    key={t}
                    className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </Row>

            <Row label="결제 수단">
              <div className="flex flex-wrap gap-2">
                {data.payment_methods.map((c) => (
                  <span
                    key={c}
                    className="rounded-lg bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200"
                  >
                    {c}
                  </span>
                ))}
              </div>
            </Row>

            <Row label="이용">
              <span className="text-sm font-semibold">
                {data.usage_restricted
                  ? data.limit_detail || "이용 제한 있음"
                  : "제한 없음"}
              </span>
            </Row>

            <Row label="주차">
              <span
                className={
                  data.parking_free
                    ? "text-sm font-semibold text-emerald-600"
                    : "text-sm font-semibold text-amber-600"
                }
              >
                {data.parking_free ? "무료" : "유료 (주차비 발생)"}
              </span>
            </Row>

            {data.business_name && (
              <Row label="사업자명">
                <span className="text-sm font-semibold">{data.business_name}</span>
              </Row>
            )}

            {/* 설치 정보 — 값이 있는 항목만 표시 */}
            {(data.address || data.install_year || data.use_time) && (
              <Row label="설치 정보">
                <div className="flex flex-col gap-1 text-sm">
                  {data.address && (
                    <div className="flex gap-2">
                      <span className="w-16 shrink-0 text-slate-500">주소</span>
                      <span className="font-medium">{data.address}</span>
                    </div>
                  )}
                  {data.install_year && (
                    <div className="flex gap-2">
                      <span className="w-16 shrink-0 text-slate-500">설치연도</span>
                      <span className="font-medium">{data.install_year}년</span>
                    </div>
                  )}
                  {data.use_time && (
                    <div className="flex gap-2">
                      <span className="w-16 shrink-0 text-slate-500">이용시간</span>
                      <span className="font-medium">{data.use_time}</span>
                    </div>
                  )}
                </div>
              </Row>
            )}

            {/* 충전요금 (회원가/비회원가) — 요금 정보가 있을 때만 표시 */}
            <PriceSection chargers={data.chargers} />

            <section className="mt-1">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-semibold text-slate-500">
                  공공데이터 기준 충전기 상태
                </p>
                <span className="text-[10px] text-slate-500">10초마다 재조회</span>
              </div>
              <div className="overflow-x-auto rounded-xl ring-1 ring-slate-200">
                <table className="w-full min-w-[420px] text-sm">
                  <caption className="sr-only">
                    충전기별 번호, 커넥터, 충전방식, 충전 상태, 잔여시간
                  </caption>
                  <thead className="bg-slate-50 text-xs text-slate-500">
                    <tr>
                      <th className="p-2.5 text-left font-medium">번호</th>
                      <th className="p-2.5 text-left font-medium">커넥터</th>
                      <th className="p-2.5 text-left font-medium">충전방식</th>
                      <th className="p-2.5 text-center font-medium">충전 상태</th>
                      <th className="p-2.5 text-right font-medium">잔여시간</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.chargers.map((c) => {
                      const selectCharger = () => {
                        saveCharger({
                          station_name: data.name,
                          charger_no: c.charger_no,
                          charge_type: c.charge_type,
                          power_kw: c.power_kw,
                          unit_price: c.unit_price,
                        });
                        router.push("/charge");
                      };
                      return (
                      <tr
                        key={c.charger_no}
                        tabIndex={0}
                        role="button"
                        aria-label={`${c.charger_no}번 충전기 선택 (${c.charge_type}, ${c.status})`}
                        onClick={selectCharger}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            selectCharger();
                          }
                        }}
                        className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 focus:bg-slate-100 focus:outline-2 focus:outline-[var(--byd-accent)]"
                      >
                        <td className="p-2.5">{c.charger_no}</td>
                        <td className="p-2.5">{c.connector ?? "-"}</td>
                        <td className="p-2.5">{c.charge_type}</td>
                        <td className="p-2.5 text-center">
                          <span className={statusClass(c.status)}>{c.status}</span>
                        </td>
                        <td className="p-2.5 text-right text-slate-500">
                          {c.remaining ?? "-"}
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11px] text-slate-500">
                충전기를 선택하면 단순 출력 기준의 예상 금액·시간을 계산합니다.
              </p>
              <p className="mt-2 text-[10px] text-slate-500">
                데이터 출처:{" "}
                {data.data_source === "public_api"
                  ? "공공데이터포털 한국환경공단 전기차 충전소 정보"
                  : "테스트용 mock 데이터"}
              </p>
            </section>
          </>
        )}
      </div>
    </main>
  );
}

// T맵 길안내 연결 — 이 충전소를 도착지로 넣어 T맵 앱을 띄운다.
// URL 조립·좌표 순서는 lib/tmap.ts에 있고 tmap.test.mjs가 고정한다.
function TmapButton({ name, location }: { name: string; location: LatLng }) {
  // 앱 밖으로 나가는 이동이라 button+JS가 아니라 a[href]로 둔다. 스크린리더가
  // '링크'로 읽고, URL이 DOM에 남아 좌표가 맞는지 눈으로 확인된다.
  // UA 판정은 클라이언트에서만 가능하므로 마운트 후에 정한다(SSR 불일치 방지).
  const [android, setAndroid] = useState(false);
  useEffect(() => setAndroid(/android/i.test(navigator.userAgent)), []);

  // 미설치 안내는 타이머로 감지하지 않고 항상 띄워둔다. iOS는 스킴을 열 때 확인
  // 대화상자를 띄우는데 그동안 페이지가 hidden이 되지 않아, 시간 기반 감지는
  // 설치돼 있는데도 "미설치"라고 잘못 말한다.
  return (
    <section className="flex flex-col gap-1.5">
      <a
        href={tmapUrl(name, location, android)}
        className="w-full rounded-xl bg-[var(--byd-primary)] py-3 text-center text-sm font-semibold text-white active:scale-[0.99]"
      >
        T맵으로 길안내
      </a>
      <p className="text-[11px] text-slate-500">
        T맵이 열리지 않으면 앱이 설치되어 있지 않습니다.{" "}
        <a
          href={android ? TMAP_STORE_ANDROID : TMAP_STORE_IOS}
          className="underline decoration-dotted underline-offset-2"
        >
          설치하기
        </a>
      </p>
    </section>
  );
}

// 충전요금(회원/비회원) — 요금 정보가 있는 충전방식만, 방식별로 한 줄씩 표시.
// 공공 API는 요금 미제공이라 대개 숨겨지고, 데이터가 있을 때만 렌더한다.
function PriceSection({ chargers }: { chargers: RealtimeCharger[] }) {
  const byType = new Map<string, RealtimeCharger>();
  for (const c of chargers) {
    if ((c.price_member != null || c.price_nonmember != null) && !byType.has(c.charge_type)) {
      byType.set(c.charge_type, c);
    }
  }
  const rows = Array.from(byType.values());
  if (rows.length === 0) return null;

  return (
    <Row label="충전요금 (원/kWh)">
      <div className="flex flex-col gap-2">
        {rows.map((c) => (
          <div key={c.charge_type} className="flex items-center gap-2 text-sm">
            <span className="w-10 shrink-0 font-medium">{c.charge_type}</span>
            {c.price_member != null && (
              <span className="rounded-lg bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">
                회원 {c.price_member.toLocaleString()}
              </span>
            )}
            {c.price_nonmember != null && (
              <span className="rounded-lg bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                비회원 {c.price_nonmember.toLocaleString()}
              </span>
            )}
          </div>
        ))}
      </div>
    </Row>
  );
}

// 충전 상태별 색상: 충전가능=초록, 충전중=주황, 그 외(운영중지/점검중/미확인)=회색
function statusClass(status: string): string {
  const base = "rounded-full px-2 py-0.5 text-xs";
  if (status === "충전가능") return `${base} bg-emerald-50 text-emerald-600`;
  if (status === "충전중") return `${base} bg-amber-50 text-amber-600`;
  return `${base} bg-slate-100 text-slate-500`;
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-1.5">
      <p className="text-xs text-slate-500">{label}</p>
      {children}
    </section>
  );
}
