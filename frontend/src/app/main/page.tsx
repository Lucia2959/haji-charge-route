"use client";

// 메인 화면 (S-02) — 앱의 핵심 화면. 입력 → 계산 → 결과 표시를 한 화면에서 처리한다.
//
// 화면 구성(위→아래)
//   헤더(새로고침) · 즐겨찾기 · 입력부 · 계산버튼 · 조건부 배너 · 산출영역(접이식)
//
// 상태 보관 위치
//   sessionStorage(3h) : 검색조건(haji.mainForm), 계획결과(haji.routePlan)
//   localStorage       : 즐겨찾기(haji.shortcuts) ← 개인 주소. 서버·번들에 두지 않는다
//   메모리             : 모달·패널 펼침 여부 등 화면 상태
//
// 마운트 순서가 중요하다: loadForm → loadPlan → loadShortcuts → hydrated=true.
// hydrated 이전에 저장/날씨조회가 돌면 복원값을 기본값으로 덮어쓴다.
//
// 이 파일이 860줄로 커진 것은 알려진 구조 부채다(시스템아키텍처 6장). 결과 표시
// 섹션을 컴포넌트로 분리할 여지가 있으나 동작에는 문제가 없어 그대로 두었다.
import { useMutation } from "@tanstack/react-query";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import PlaceSearchModal from "@/components/PlaceSearchModal";
import RouteStrip from "@/components/RouteStrip";
import {
  clearAllRouteData,
  getCurrentTemperature,
  loadForm,
  loadPlan,
  loadShortcuts,
  planRoute,
  saveForm,
  savePlan,
  saveShortcuts,
  SHORTCUT_SLOTS,
  warmupRoute,
  type ShortcutItem,
} from "@/lib/api";
import type { RoutePlanResponse } from "@/lib/types";

type Place = { label: string; value: string };

// 즐겨찾기 아이콘(주소는 담지 않는다). 실제 주소는 기기 localStorage에만 저장된다 —
// NEXT_PUBLIC_ 로 두면 빌드 산출물에 주소가 그대로 박혀 배포 시 노출되기 때문.
const SHORTCUT_ICONS = ["🏠", "📍"];

// 출발지 기본값(고정). 화면에서 바꿀 수는 있고, '초기화'를 누르면 이 값으로 돌아온다.
//
// ⚠ 위 즐겨찾기 주석과 상반되는 예외다. 이 문자열은 클라이언트 번들에 그대로 박혀
//    배포 URL을 아는 사람은 누구나 읽을 수 있다(NEXT_PUBLIC_ 환경변수로 옮겨도
//    빌드 시 번들에 들어가므로 똑같다). 노출을 원치 않으면 여기서 지우고
//    '＋ 즐겨찾기'로 등록할 것 — 즐겨찾기는 기기 localStorage에만 남는다.
const DEFAULT_ORIGIN = "목동서로 100";

export default function MainPage() {
  const router = useRouter();
  const [origin, setOrigin] = useState<Place>({
    label: DEFAULT_ORIGIN,
    value: DEFAULT_ORIGIN,
  });
  // 도착지는 빈칸으로 시작한다 — 비어 있으면 계산 버튼이 비활성이라
  // 사용자가 목적지를 고르기 전에 실수로 계산이 나가지 않는다.
  const [destination, setDestination] = useState<Place>({
    label: "",
    value: "",
  });
  const [charge, setCharge] = useState("50");
  const [temp, setTemp] = useState("20");
  const [tempAuto, setTempAuto] = useState(false); // 기상청 자동입력 여부
  // picker: 출발/도착 선택 또는 즐겨찾기 슬롯 지정(shortcut:<index>)
  const [picker, setPicker] = useState<string | null>(null);
  const [shortcuts, setShortcuts] = useState<(ShortcutItem | null)[]>(() =>
    Array<ShortcutItem | null>(SHORTCUT_SLOTS).fill(null)
  );
  const [active, setActive] = useState<"origin" | "destination">("origin"); // 포커스된 칸
  const [plan, setPlan] = useState<RoutePlanResponse | null>(null);
  const [resultOpen, setResultOpen] = useState(false); // 산출영역 펼침 여부(기본 접힘=아이콘)
  const [detailOpen, setDetailOpen] = useState(false); // 상세보기(충전소 목록) 토글
  const [basisOpen, setBasisOpen] = useState(false); // 산출근거(계산근거) 토글

  const [hydrated, setHydrated] = useState(false); // 세션 복원 완료 여부
  const skipWeather = useRef(false); // 복원 직후 1회 날씨 자동조회 스킵(복원 기온 유지)

  // 마운트 시 세션에 저장된 검색조건·계획을 복원 (다른 화면 다녀와도 유지)
  useEffect(() => {
    const f = loadForm();
    if (f) {
      setOrigin(f.origin);
      setDestination(f.destination);
      setCharge(f.charge);
      setTemp(f.temp);
      setTempAuto(f.tempAuto);
      setActive(f.active);
      skipWeather.current = true; // 복원한 기온을 날씨조회가 덮어쓰지 않도록
    }
    const p = loadPlan();
    if (p) setPlan(p);
    setShortcuts(loadShortcuts()); // 즐겨찾기는 기기(localStorage)에서만 읽는다
    setHydrated(true);
    // 복원된 경로가 있으면 충전소 캐시를 미리 데운다(백그라운드). 계산 버튼을 누를
    // 때쯤이면 캐시가 채워져 있어 대기가 크게 줄어든다.
    if (f?.origin.value && f?.destination.value) {
      warmupRoute(f.origin.value, f.destination.value);
    }
  }, []);

  // 즐겨찾기 슬롯 지정/삭제 — 주소는 기기에만 저장
  function setShortcut(index: number, item: ShortcutItem | null) {
    setShortcuts((prev) => {
      const next = [...prev];
      next[index] = item;
      saveShortcuts(next);
      return next;
    });
  }

  // 단축 아이콘: 현재 포커스된 칸(출발지/도착지)에 주소 입력
  function fillActive(address: string) {
    const place = { label: address, value: address };
    if (active === "origin") setOrigin(place);
    else setDestination(place);
  }

  // 초기화: 도착지·계획을 비우고 출발지는 기본값으로 되돌린다 (세션 저장분도 제거).
  // 출발지를 빈칸으로 두면 '고정 출발지'라는 의도와 어긋나므로 DEFAULT_ORIGIN을 복원한다.
  function resetPlaces() {
    setOrigin({ label: DEFAULT_ORIGIN, value: DEFAULT_ORIGIN });
    setDestination({ label: "", value: "" });
    setActive("origin");
    setPlan(null);
    setResultOpen(false);
    clearAllRouteData();
  }

  // 출발지가 바뀌면 실황 기온을 자동 조회 (실패 시 기존 값 유지)
  useEffect(() => {
    if (!hydrated) return; // 복원 완료 전에는 조회 안 함
    if (skipWeather.current) {
      skipWeather.current = false; // 복원 직후 1회는 스킵(복원 기온 유지)
      return;
    }
    if (!origin.value) return;
    let cancelled = false;
    getCurrentTemperature(origin.value).then((t) => {
      if (!cancelled && t != null) {
        setTemp(String(Math.round(t)));
        setTempAuto(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [origin.value, hydrated]);

  // 검색조건 변경 시 세션에 저장 (복원 완료 후에만)
  useEffect(() => {
    if (!hydrated) return;
    saveForm({ origin, destination, charge, temp, tempAuto, active });
  }, [hydrated, origin, destination, charge, temp, tempAuto, active]);

  const [refreshCooldown, setRefreshCooldown] = useState(false); // 새로고침 연타 방지
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      planRoute({
        origin: origin.value,
        destination: destination.value,
        current_charge_pct: Number(charge),
        temperature_c: Number(temp),
      }),
    onSuccess: (p) => {
      savePlan(p);
      setPlan(p);
      setResultOpen(true); // 계산 직후에는 결과를 펼쳐서 바로 표시
    },
  });

  // 새로고침: 그 시각 기준으로 온도·경로·충전소 상태를 전부 다시 통신.
  // route/plan 엔드포인트가 실시간 경로(directions)+충전소 상태를 함께 조회하므로,
  // 온도만 실황으로 재조회한 뒤 경로를 재계산하면 셋 다 갱신된다.
  async function handleRefresh() {
    if (!plan || refreshCooldown || !origin.value || !destination.value) return;
    setRefreshCooldown(true); // 8초 쿨다운 — 버튼 연타로 외부 API 호출 폭증 방지
    setRefreshError(null);
    const cooldown = setTimeout(() => setRefreshCooldown(false), 8000);

    try {
      // 출발지 실황 기온 재조회 (실패 시 기존 값 유지)
      let t = temp;
      const fresh = await getCurrentTemperature(origin.value);
      if (fresh != null) {
        t = String(Math.round(fresh));
        setTemp(t);
        setTempAuto(true);
      }

      // 재조회한 기온으로 경로·충전소 상태를 현 시각 기준 재계산
      const updated = await planRoute({
        origin: origin.value,
        destination: destination.value,
        current_charge_pct: Number(charge),
        temperature_c: Number(t),
      });
      setPlan(updated);
      savePlan(updated);
    } catch (e) {
      // 실패를 조용히 삼키면 사용자는 '눌렀는데 아무 일도 안 남'을 겪는다 → 표시하고
      // 쿨다운도 즉시 풀어 바로 재시도할 수 있게 한다.
      setRefreshError((e as Error).message);
      clearTimeout(cooldown);
      setRefreshCooldown(false);
    }
  }

  return (
    <main className="flex flex-1 flex-col gap-5 p-5">
      <header className="flex items-start justify-between pt-2">
        <div>
          <h1 className="text-lg font-bold text-[var(--byd-primary)]">
            충전 경로 계획
          </h1>
          <p className="text-xs text-slate-500">BYD 돌핀 스탠다드 기준</p>
        </div>
        {plan && (
          <button
            onClick={handleRefresh}
            disabled={refreshCooldown}
            aria-label="충전소 상태 새로고침"
            title="충전소 상태 새로고침"
            className="rounded-full p-2 text-slate-500 hover:bg-slate-100 hover:text-[var(--byd-primary)] disabled:opacity-40"
          >
            <RefreshIcon />
          </button>
        )}
      </header>

      {/* 즐겨찾기: 채워진 칸은 탭하면 현재 포커스된 입력칸에 넣고, 빈 칸은 탭해서 등록.
          주소는 이 기기에만 저장된다(서버·번들에 남지 않음). */}
      <div className="grid grid-cols-3 gap-2 border-b border-slate-200 pb-4">
        {shortcuts.map((s, i) =>
          s ? (
            <div key={i} className="relative">
              <Shortcut
                icon={SHORTCUT_ICONS[i] ?? "📍"}
                label={s.label}
                onClick={() => fillActive(s.addr)}
              />
              <button
                onClick={() => setShortcut(i, null)}
                aria-label={`${s.label} 즐겨찾기 삭제`}
                className="absolute -right-1 -top-1 grid h-6 w-6 place-items-center rounded-full bg-slate-200 text-[11px] text-slate-600 hover:bg-slate-300"
              >
                ✕
              </button>
            </div>
          ) : (
            <Shortcut
              key={i}
              icon="＋"
              label="즐겨찾기"
              onClick={() => setPicker(`shortcut:${i}`)}
            />
          )
        )}
        <Shortcut icon="↺" label="초기화" onClick={resetPlaces} />
      </div>

      <div className="flex flex-col gap-3">
        <Field label="출발지">
          <button
            onClick={() => {
              setActive("origin");
              setPicker("origin");
            }}
            className={`input text-left ${active === "origin" ? "input-active" : ""}`}
          >
            {origin.label || (
              <span className="text-slate-500">출발지 선택</span>
            )}
            <span className="float-right text-slate-500">🔍</span>
          </button>
        </Field>
        <Field label="도착지">
          <button
            onClick={() => {
              setActive("destination");
              setPicker("destination");
            }}
            className={`input text-left ${
              active === "destination" ? "input-active" : ""
            }`}
          >
            {destination.label || (
              <span className="text-slate-500">도착지 선택</span>
            )}
            <span className="float-right text-slate-500">🔍</span>
          </button>
        </Field>
        <div className="flex gap-3 [&>label]:flex-1">
          <Field label="현충전량 (%)">
            <input
              value={charge}
              onChange={(e) => setCharge(e.target.value)}
              type="number"
              min={0}
              max={100}
              className="input"
            />
          </Field>
          <Field label="기온 (°C)">
            <input
              value={temp}
              onChange={(e) => {
                setTemp(e.target.value);
                setTempAuto(false);
              }}
              type="number"
              min={-40}
              max={60}
              className="input"
            />
          </Field>
        </div>
        {tempAuto && (
          <p className="-mt-1 text-[11px] text-slate-500">
            🌡 Open-Meteo 기준 출발지 현재 기온 자동입력 (수정 가능)
          </p>
        )}
      </div>

      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending || !origin.value || !destination.value}
        className="rounded-xl bg-[var(--byd-accent-strong)] py-3.5 font-semibold text-white disabled:opacity-60"
      >
        {mutation.isPending ? "계산 중…" : "충전 계획 계산"}
      </button>

      {mutation.isError && (
        <p role="alert" className="text-sm text-red-600">
          {(mutation.error as Error).message}
        </p>
      )}

      {refreshError && (
        <p role="alert" className="text-sm text-red-600">
          새로고침 실패 — {refreshError}
        </p>
      )}

      {plan?.data_source === "mock" && (
        <p
          role="alert"
          className="rounded-lg bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700 ring-1 ring-amber-200"
        >
          ⚠ 실제 도로 경로를 찾지 못해 추정 경로(mock)로 계산했습니다. 충전소·거리
          결과가 실제와 다를 수 있습니다.
        </p>
      )}

      {plan?.origin_precharge && (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-xl bg-orange-50 px-3.5 py-3 ring-1 ring-orange-200"
        >
          <span className="text-lg leading-none">⚡</span>
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-semibold text-orange-700">
              출발 전 {plan.origin_precharge.required_pct}% 이상 충전 권장
            </span>
            <span className="text-[12px] leading-relaxed text-orange-600">
              {plan.origin_precharge.reason}
            </span>
            {plan.origin_precharge.station && (
              <button
                onClick={() =>
                  router.push(`/stations/${plan.origin_precharge!.station!.station_id}`)
                }
                className="mt-1.5 flex items-center gap-1.5 self-start rounded-lg bg-white px-2.5 py-1.5 text-[12px] ring-1 ring-orange-200 hover:bg-orange-50"
              >
                <span className="text-slate-500">출발지 근처</span>
                <span className="font-semibold text-[var(--byd-primary)] underline decoration-dotted decoration-emerald-400 underline-offset-2">
                  {plan.origin_precharge.station.station_name}
                </span>
                <span className="text-emerald-700">
                  · {plan.origin_precharge.station.status_reason}
                </span>
                <span className="text-slate-500">›</span>
              </button>
            )}
          </div>
        </div>
      )}

      {plan && (
        <section className="overflow-hidden rounded-2xl bg-slate-50 ring-1 ring-slate-200">
          {/* 산출영역 헤더: 아이콘 + 요약. 클릭 시 아래 본문이 탑다운으로 슬라이딩 */}
          <button
            type="button"
            onClick={() => setResultOpen((o) => !o)}
            aria-expanded={resultOpen}
            aria-controls="route-result-panel"
            className="flex w-full items-center gap-3 p-4 text-left"
          >
            <span
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-lg"
              style={{ background: "rgba(0,184,148,0.12)" }}
            >
              📊
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-[var(--byd-primary)]">
                충전 계획 결과
              </span>
              <span className="block text-[11px] text-slate-500">
                {plan.total_distance_km}km · {plan.total_trip_min}분 · 충전{" "}
                {plan.charge_stops_count}회
              </span>
            </span>
            <Chevron open={resultOpen} />
          </button>

          {/* 슬라이딩 컨테이너: grid-rows 0fr→1fr 로 위에서 아래로 펼쳐짐 */}
          {/* 접힘(0fr)은 시각적으로만 감추므로, 내부 버튼이 탭 순서·스크린리더에 남지
              않도록 inert/aria-hidden으로 함께 비활성화한다. */}
          <div
            id="route-result-panel"
            aria-hidden={!resultOpen}
            inert={!resultOpen || undefined}
            style={{
              display: "grid",
              gridTemplateRows: resultOpen ? "1fr" : "0fr",
              transition: "grid-template-rows 300ms ease-out",
            }}
          >
            <div style={{ overflow: "hidden" }}>
              <div className="px-4 pb-4">
                <div className="grid grid-cols-3 gap-2 text-center">
                  <Stat label="총 거리" value={`${plan.total_distance_km}`} unit="km" />
            <Stat label="총 소요" value={`${plan.total_trip_min}`} unit="분" />
            <Stat
              label="충전예상지점수"
              value={`${plan.charge_stops_count}`}
              unit="회"
              highlight
            />
          </div>
          <p className="mt-1.5 text-center text-[11px] text-slate-500">
            주행 {plan.duration_min}분 + 충전·정차 {plan.total_charge_min}분
            {plan.plan_method === "dp" && " · 충전커브 시간최적화(DP)"}
          </p>

          {!plan.feasible && (
            <p
              role="alert"
              className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700 ring-1 ring-red-200"
            >
              ⚠ 현재 충전량과 경로상 충전 인프라로는 목적지까지 안전하게 완주하기
              어렵습니다. 출발 전 충전을 권장합니다.
            </p>
          )}

          {/* 경로 흐름 시각화 (출발지 차량 → 충전소 → 목적지, SoC·구간소비) */}
          <div className="mt-4">
            <RouteStrip
              plan={plan}
              onSelectStation={(id) => router.push(`/stations/${id}`)}
            />
          </div>

          {/* 지도보기 · 상세보기 · 산출근거 (메인화면레이아웃.pptx) */}
          <div className="mt-4 grid grid-cols-3 gap-2">
            <ActionBtn
              icon={<MapPinIcon />}
              label="지도보기"
              onClick={() => router.push("/map")}
            />
            <ActionBtn
              icon={<GlassesIcon />}
              label="상세보기"
              expanded={detailOpen}
              controls="detail-panel"
              onClick={() => setDetailOpen((o) => !o)}
            />
            <ActionBtn
              icon={<MathIcon />}
              label="산출근거"
              expanded={basisOpen}
              controls="basis-panel"
              onClick={() => setBasisOpen((o) => !o)}
            />
          </div>

          {/* 상세보기: 충전소 목록 + 목적지 충전소 + 완주 경고 */}
          {detailOpen && (
            <div id="detail-panel" className="mt-3">
              {plan.charge_points.length > 0 && (
                <ul className="flex flex-col gap-2.5 text-sm">
                  {plan.charge_points.map((cp) => (
                    <li key={cp.order} className="flex flex-col gap-1">
                      <div className="flex items-start justify-between gap-2">
                        <span className="whitespace-nowrap text-slate-500">
                          {cp.order}차 ({cp.distance_from_origin_km}km)
                        </span>
                        <span className="flex flex-col items-end">
                          {cp.station_id ? (
                            <StationLink
                              name={cp.station_name ?? "충전소"}
                              onClick={() =>
                                router.push(`/stations/${cp.station_id}`)
                              }
                            />
                          ) : (
                            <span className="font-medium">
                              {cp.station_name ?? "경로상 충전 필요"}
                            </span>
                          )}
                          {cp.charge_to_pct != null && (
                            <span className="text-[11px] text-slate-500">
                              {cp.charge_from_pct}→{cp.charge_to_pct}% · {cp.charge_min}분
                              {cp.charge_kwh != null && ` · ${cp.charge_kwh}kWh`}
                            </span>
                          )}
                          {cp.station_id && (
                            <AvailBadge
                              available={cp.available}
                              reason={cp.status_reason}
                            />
                          )}
                        </span>
                      </div>
                      {cp.available === false && cp.alternative && (
                        <div className="flex items-center justify-end gap-1.5 rounded-lg bg-emerald-50 px-2 py-1 text-xs">
                          <span className="text-slate-500">↳ 대체</span>
                          <StationLink
                            name={cp.alternative.station_name}
                            onClick={() =>
                              router.push(
                                `/stations/${cp.alternative!.station_id}`
                              )
                            }
                          />
                          <AvailBadge
                            available={cp.alternative.available}
                            reason={cp.alternative.status_reason}
                          />
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}

              {plan.destination_charging && (
                <button
                  onClick={() =>
                    router.push(`/stations/${plan.destination_charging!.station_id}`)
                  }
                  className="mt-3 flex w-full flex-wrap items-center gap-x-2 gap-y-0.5 rounded-lg bg-sky-50 px-3 py-2 text-left text-xs text-sky-700 hover:bg-sky-100"
                >
                  <span>🏁 목적지 충전소</span>
                  <span className="font-medium">
                    {plan.destination_charging.station_name}
                  </span>
                  <span className="text-sky-500">
                    · {plan.destination_charging.note}
                  </span>
                  <span className="ml-auto text-sky-400">상세 ›</span>
                </button>
              )}

            </div>
          )}

          {/* 산출근거: 계산근거 (외부환경 보정 · 경로기반 추천) */}
          {basisOpen && (
            <div
              id="basis-panel"
              className="mt-3 overflow-hidden rounded-xl bg-slate-900 text-slate-100"
            >
              <ul className="flex flex-col gap-1 p-3.5 font-mono text-[11px] leading-relaxed">
                <li>
                  유효거리 = 정격 {plan.nominal_range_km}km × 온도{" "}
                  {plan.temp_factor.toFixed(2)}(={plan.temperature_c}°C) × 속도{" "}
                  {plan.speed_factor.toFixed(2)} = <b>{plan.effective_range_km}km</b>
                </li>
                <li className="text-slate-500">
                  ↳ 소비전력 = 구간별 실제속도(공기저항)·온도(공조 저속↑)·회생 반영 ·
                  고속도로 {plan.highway_km}km / 일반도로 {plan.local_km}km
                </li>
                <li className="text-slate-500">
                  ↳ 속도 {plan.speed_factor.toFixed(2)} = 유효거리 ÷ (정격×온도) 등가값.
                  총평균이 아니라 <b>구간별 실제 교통속도</b>(카카오)로 소비를 적산 → 정체
                  구간일수록 소비에 더 크게 반영. 참고 평균{" "}
                  <b>{plan.avg_speed_kmh}km/h</b> (총 {plan.total_distance_km}km ÷{" "}
                  {plan.duration_min}분, 실시간 교통 반영)
                </li>
                {(plan.jam_km > 0 || plan.delay_km > 0) && (
                  <li className="text-amber-300">
                    ↳ 정체 {plan.jam_km}km · 지체 {plan.delay_km}km → 추가 소비{" "}
                    <b>{plan.congestion_extra_kwh}kWh</b> (저속일수록 공조·전장 시간
                    소모↑)
                  </li>
                )}
                <li>
                  현충전량 도달가능 = ({plan.current_charge_pct}% − 안전 10%) ×{" "}
                  {plan.effective_range_km}/100 = <b>{plan.initial_range_km}km</b>
                </li>
                <li>
                  충전 후 도달가능 = (80% − 10%) × {plan.effective_range_km}/100 ={" "}
                  {((plan.effective_range_km * 70) / 100).toFixed(1)}km
                </li>
                <li className="text-slate-500">
                  → {plan.plan_method === "dp"
                    ? "충전커브 기반 DP로 '어느 충전소·몇 %'까지 충전할지 최적화 (총 시간 최소·도달 보장)"
                    : "도달 범위 내 '가장 멀리 갈 수 있는' 충전소 선택 (greedy·도달 보장)"}
                </li>
              </ul>
            </div>
          )}

          {/* 참고 계산 고지 */}
          <p className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-[11px] leading-relaxed text-slate-500">
            이 결과는 차량 스펙·날씨·공공 충전소 데이터·근사 충전 커브를 바탕으로 한
            참고 계산입니다. 실제 주행 가능 거리와 충전 가능 여부는 도로·날씨·배터리
            상태·현장 상황에 따라 달라질 수 있습니다.
          </p>
              </div>
            </div>
          </div>
        </section>
      )}

      <style jsx>{`
        :global(.input) {
          width: 100%;
          border-radius: 0.75rem;
          border: 1px solid #e2e8f0;
          padding: 0.75rem 0.9rem;
          /* 16px 미만이면 iOS Safari가 포커스 시 화면을 강제 확대한다(되돌아오지 않음) */
          font-size: 1rem;
          outline: none;
        }
        :global(.input:focus) {
          border-color: var(--byd-accent);
        }
        :global(.input-active) {
          border-color: var(--byd-accent);
          box-shadow: 0 0 0 2px rgba(0, 184, 148, 0.25);
        }
      `}</style>

      {picker && (
        <PlaceSearchModal
          title={
            picker === "origin"
              ? "출발지"
              : picker === "destination"
                ? "도착지"
                : "즐겨찾기 등록"
          }
          onClose={() => setPicker(null)}
          onSelect={(p) => {
            const value = `${p.location.lng},${p.location.lat}`;
            if (picker.startsWith("shortcut:")) {
              // 즐겨찾기 등록 — 주소는 이 기기에만 저장된다
              setShortcut(Number(picker.split(":")[1]), {
                label: p.name,
                addr: value,
              });
            } else if (picker === "origin") {
              setOrigin({ label: p.name, value });
            } else {
              setDestination({ label: p.name, value });
            }
            setPicker(null);
          }}
        />
      )}
    </main>
  );
}

// 결과 하단 액션 버튼 (지도보기·상세보기·산출근거). expanded면 눌린 상태(네이비).
// expanded/controls를 주면 아래 패널을 여닫는 disclosure 버튼으로 동작(스크린리더에
// '무엇이 펼쳐졌는지' 전달). 지도보기처럼 화면 이동만 하는 버튼은 둘 다 생략한다.
function ActionBtn({
  icon,
  label,
  expanded,
  controls,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  expanded?: boolean;
  controls?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={expanded}
      aria-controls={expanded !== undefined ? controls : undefined}
      className={`flex flex-col items-center gap-1.5 rounded-xl py-3 ring-1 transition active:scale-[0.98] ${
        expanded
          ? "bg-[var(--byd-primary)] text-white ring-[var(--byd-primary)]"
          : "bg-white text-[var(--byd-primary)] ring-slate-200 hover:bg-slate-50"
      }`}
    >
      {icon}
      <span className="text-xs font-semibold">{label}</span>
    </button>
  );
}

// 액션 버튼 아이콘 (いらすとや / irasutoya.com — 무료 일러스트)
// 지도보기 — 맵 핀(マップピン)
function MapPinIcon() {
  return <Image src="/icons/map.png" alt="" width={28} height={28} aria-hidden />;
}

// 상세보기 — 검색 돋보기(検索虫眼鏡)
function GlassesIcon() {
  return <Image src="/icons/detail.png" alt="" width={28} height={28} aria-hidden />;
}

// 산출근거 — 전자계산기(電卓)
function MathIcon() {
  return <Image src="/icons/calc.png" alt="" width={28} height={28} aria-hidden />;
}

// 산출영역 펼침/접힘 표시용 셰브론 (열리면 아래로 회전)
function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      className="shrink-0 text-slate-500 transition-transform duration-300"
      style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
    >
      <path
        d="M6 9l6 6 6-6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// 충전소 이름 — 하이라이트 + 클릭 시 충전소 상세로 이동
function StationLink({
  name,
  onClick,
}: {
  name: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title="충전소 상세 보기"
      className="rounded bg-emerald-50 px-1 font-semibold text-[var(--byd-primary)] underline decoration-emerald-400 decoration-dotted underline-offset-2 hover:bg-emerald-100 active:scale-[0.98]"
    >
      {name}
    </button>
  );
}

// 사용가능/불가 상태 아이콘 (초록/빨강/회색 점 + 사유)
function AvailBadge({
  available,
  reason,
}: {
  available: boolean | null;
  reason: string | null;
}) {
  const color =
    available == null
      ? "#94a3b8"
      : available
        ? "#10b981"
        : "#ef4444";
  const text =
    available == null ? reason ?? "확인불가" : available ? "사용가능" : reason ?? "사용불가";
  return (
    <span className="mt-0.5 inline-flex items-center gap-1 text-[11px]" style={{ color }}>
      <span
        aria-hidden
        style={{
          width: 8,
          height: 8,
          borderRadius: "9999px",
          background: color,
          display: "inline-block",
        }}
      />
      {text}
    </span>
  );
}

function RefreshIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M20 11a8 8 0 1 0-.9 4.5M20 5v4h-4"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Shortcut({
  icon,
  label,
  onClick,
}: {
  icon: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col items-center gap-1 rounded-xl bg-slate-50 py-2.5 ring-1 ring-slate-200 hover:bg-slate-100 active:scale-[0.98]"
    >
      <span className="text-2xl leading-none">{icon}</span>
      <span className="text-xs font-medium text-slate-600">{label}</span>
    </button>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-slate-500">{label}</span>
      {children}
    </label>
  );
}

function Stat({
  label,
  value,
  unit,
  highlight,
}: {
  label: string;
  value: string;
  unit: string;
  highlight?: boolean;
}) {
  return (
    <div>
      <div className="text-[11px] text-slate-500">{label}</div>
      <div
        className={
          highlight
            ? "text-2xl font-bold text-[var(--byd-accent)]"
            : "text-2xl font-bold text-[var(--byd-primary)]"
        }
      >
        {value}
        <span className="ml-0.5 text-xs font-normal text-slate-500">
          {unit}
        </span>
      </div>
    </div>
  );
}
