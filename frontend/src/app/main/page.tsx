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
import ShortcutNameModal from "@/components/ShortcutNameModal";
import RouteStrip from "@/components/RouteStrip";
import {
  clearAllRouteData,
  getCurrentTemperature,
  getDepartOptions,
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
import type {
  DepartOptionsResponse,
  RoutePlanResponse,
  StationCongestion,
} from "@/lib/types";

// label = 화면에 보이는 이름, value = 계산에 나가는 값("lng,lat" 또는 주소),
// address = 등록·검색 시점의 실제 주소(표시 전용, 없으면 안 보여준다)
type Place = { label: string; value: string; address?: string };

// 즐겨찾기 아이콘(주소는 담지 않는다). 실제 주소는 기기 localStorage에만 저장된다 —
// NEXT_PUBLIC_ 로 두면 빌드 산출물에 주소가 그대로 박혀 배포 시 노출되기 때문.
const SHORTCUT_ICONS = ["🏠", "📍"];

// 출발지 기본값(고정). 화면에서 바꿀 수 있고, '초기화'를 누르면 이 값으로 돌아온다.
// ⚠ 바로 위 정책의 예외 — 이 주소는 번들에 박혀 배포본에서 그대로 읽힌다.
//    노출을 원치 않으면 EMPTY_PLACE로 바꾸고 '＋ 즐겨찾기'로 등록할 것.
const DEFAULT_ORIGIN: Place = { label: "목동서로 100", value: "목동서로 100" };
const EMPTY_PLACE: Place = { label: "", value: "" };

export default function MainPage() {
  const router = useRouter();
  const [origin, setOrigin] = useState<Place>(DEFAULT_ORIGIN);
  // 도착지는 빈칸으로 시작 — 비어 있으면 계산 버튼이 비활성이다
  const [destination, setDestination] = useState<Place>(EMPTY_PLACE);
  const [charge, setCharge] = useState("50");
  const [temp, setTemp] = useState("20");
  const [tempAuto, setTempAuto] = useState(false); // 기상청 자동입력 여부
  // 고속도로 순항속도(선택). 빈 문자열이면 서버에 보내지 않아 실시간 교통속도가 쓰인다.
  const [cruise, setCruise] = useState("");
  // picker: 출발/도착 선택 또는 즐겨찾기 슬롯 지정(shortcut:<index>)
  const [picker, setPicker] = useState<string | null>(null);
  // 즐겨찾기 이름 입력 중인 슬롯. addr가 있으면 신규 등록(방금 고른 장소),
  // null이면 이미 등록된 항목의 이름만 고치는 것이다.
  const [naming, setNaming] = useState<{
    index: number;
    initial: string;
    addr: string | null;
    address?: string;
  } | null>(null);
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

  // 단축 아이콘: 현재 포커스된 칸(출발지/도착지)에 주소 입력.
  // label은 화면 표시용, value만 API로 나간다 — 즐겨찾기 주소는 "lng,lat"이라
  // label까지 그대로 쓰면 사용자가 붙인 이름 대신 좌표가 그대로 보인다.
  // address는 "회사"가 실제로 어디인지 확인할 수 있게 이름 아래에 함께 보여준다.
  function fillActive(value: string, label = value, address?: string) {
    const place = { label, value, address };
    if (active === "origin") setOrigin(place);
    else setDestination(place);
  }

  // 초기화: 도착지·계획을 비우고 출발지는 기본값으로 되돌린다 (세션 저장분도 제거)
  function resetPlaces() {
    setOrigin(DEFAULT_ORIGIN);
    setDestination(EMPTY_PLACE);
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
        // 빈 값이면 아예 보내지 않는다 — 0을 보내면 서버 검증(ge=30)에 걸린다.
        ...(cruise ? { cruise_speed_kmh: Number(cruise) } : {}),
      }),
    onSuccess: (p) => {
      savePlan(p);
      setPlan(p);
      setResultOpen(true); // 계산 직후에는 결과를 펼쳐서 바로 표시
    },
  });

  // 출발 시각 비교(F4). 경로 조회는 서버에서 1회만 하고 DP만 7번 돌리므로
  // 외부 API 호출이 늘지 않는다. 계획과 별개 엔드포인트라 계획 응답을 늦추지 않는다.
  const departMut = useMutation({
    mutationFn: () =>
      getDepartOptions({
        origin: origin.value,
        destination: destination.value,
        current_charge_pct: Number(charge),
        temperature_c: Number(temp),
        // 빈 값이면 아예 보내지 않는다 — 0을 보내면 서버 검증(ge=30)에 걸린다.
        ...(cruise ? { cruise_speed_kmh: Number(cruise) } : {}),
      }),
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
        ...(cruise ? { cruise_speed_kmh: Number(cruise) } : {}),
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
        <div className="flex items-center gap-1">
          {/* 경로와 무관하게 지역 충전소를 훑는 화면. 여행지 도착 후에도 쓴다. */}
          <button
            onClick={() => router.push("/explore")}
            aria-label="지역 충전소 탐색"
            title="지역 충전소 탐색"
            className="rounded-full p-2 text-slate-500 hover:bg-slate-100 hover:text-[var(--byd-primary)]"
          >
            <SearchAreaIcon />
          </button>
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
        </div>
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
                onClick={() => fillActive(s.addr, s.label, s.address)}
              />
              {/* 편집 진입점 하나만 둔다. 삭제(✕)를 칩에 같이 붙였더니 저장이 안 된
                  것처럼 읽혔고, 24px 배지 두 개가 손가락으로 눌리지도 않았다.
                  삭제는 이름 수정 모달 안으로 옮겼다.
                  p-2.5: 보이는 아이콘은 24px로 두고 탭 영역만 44px로 넓힌다
                  (24 + 10*2 = 44 — Apple HIG 최소 44pt / WCAG 2.5.5 AAA).
                  -right-2(8px)는 탭 영역 오른쪽 끝을 gap(8px) 경계에 딱 맞춰
                  옆 칩을 침범하지 않게 한다. 음수 마진을 같이 주면 offset에 더해져
                  10px씩 더 밀려나 초기화 칩을 먹으므로 쓰지 않는다.
                  ring은 흰 배경과의 경계 대비 3:1 확보(WCAG 1.4.11). */}
              <button
                onClick={() =>
                  setNaming({ index: i, initial: s.label, addr: null })
                }
                aria-label={`${s.label} 즐겨찾기 이름 수정·삭제`}
                className="absolute -right-2 -top-2 p-2.5"
              >
                <span
                  aria-hidden
                  className="grid h-6 w-6 place-items-center rounded-full bg-white text-[11px] text-slate-600 ring-1 ring-slate-400"
                >
                  ✎
                </span>
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
            <span aria-hidden className="float-right text-slate-500">🔍</span>
            {origin.label || (
              <span className="text-slate-500">출발지 선택</span>
            )}
            <PlaceAddress place={origin} />
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
            <span aria-hidden className="float-right text-slate-500">🔍</span>
            {destination.label || (
              <span className="text-slate-500">도착지 선택</span>
            )}
            <PlaceAddress place={destination} />
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
          <Field label="고속도로 순항 (km/h)">
            <input
              value={cruise}
              onChange={(e) => setCruise(e.target.value)}
              type="number"
              min={30}
              max={150}
              placeholder="자동"
              className="input"
            />
          </Field>
        </div>
        {tempAuto && (
          <p className="-mt-1 text-[11px] text-slate-500">
            <span aria-hidden>🌡</span> Open-Meteo 기준 출발지 현재 기온 자동입력 (수정 가능)
          </p>
        )}
        <p className="-mt-1 text-[11px] text-slate-500">
          <span aria-hidden>🛣</span> 순항속도는 고속도로·자동차전용 구간에만 적용됩니다(법정 최저~최고 범위로
          조정). 비워두면 실시간 교통속도를 그대로 씁니다. 정체 구간은 입력값과 무관하게
          실제 교통속도로 계산합니다.
        </p>
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
          <span aria-hidden className="text-lg leading-none">
            ⚡
          </span>
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
                {plan.total_distance_km}km · {hourMin(plan.total_trip_min).join("")}{" "}
                · 충전{" "}
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
            <Stat
              label="총 소요"
              value={hourMin(plan.total_trip_min)[0]}
              unit={hourMin(plan.total_trip_min)[1]}
            />
            <Stat
              label="충전예상지점수"
              value={`${plan.charge_stops_count}`}
              unit="회"
              highlight
            />
          </div>
          <p className="mt-1.5 text-center text-[11px] text-slate-500">
            주행 {plan.duration_min}분 + 충전·정차 {plan.total_charge_min}분
            {plan.congestion_wait_min != null &&
              ` (충전 대기 예상 ${plan.congestion_wait_min}분 포함)`}
            {plan.plan_method === "dp" && " · 충전커브 시간최적화(DP)"}
          </p>

          {/* 충전 대기 예측 상태 + 출발 시각 비교.
              수집 초기(2~4주)에는 예측이 안 나오는데, 아무것도 표시하지 않으면
              사용자는 이 기능이 있는지조차 모른다 → 진행 상태를 한 줄로 알린다. */}
          {plan.congestion_status && plan.congestion_status !== "off" && (
            <div className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-[11px] text-slate-600">
              {plan.congestion_status === "ready" ? (
                <>충전 대기 예측 적용 중 · 관측 {plan.congestion_days}일 기준</>
              ) : (
                <>
                  충전 대기 예측: <b>데이터 수집 중</b>
                  {plan.congestion_days ? ` (관측 ${plan.congestion_days}일)` : ""} —
                  평일 약 2주, 주말 약 4주가 모이면 충전소별 혼잡도가 표시됩니다.
                  그때까지는 추측하지 않고 계산에서 제외합니다.
                </>
              )}
            </div>
          )}

          {plan.congestion_status === "ready" && (
            <button
              type="button"
              onClick={() => departMut.mutate()}
              disabled={departMut.isPending}
              className="mt-2 w-full rounded-lg bg-white px-3 py-2 text-xs font-semibold text-[var(--byd-primary)] ring-1 ring-slate-200 disabled:opacity-50"
            >
              {departMut.isPending ? "비교 중…" : "🕒 출발 시각 바꿔서 비교하기"}
            </button>
          )}

          {departMut.isError && (
            <p role="alert" className="mt-2 text-[11px] text-red-600">
              {(departMut.error as Error).message}
            </p>
          )}

          {departMut.data && <DepartTable data={departMut.data} />}

          {/* 혼잡 충전소를 피한 대안. 10분 이상 줄어들 때만 서버가 내려준다. */}
          {plan.congestion_alternative && (
            <div className="mt-3 rounded-lg bg-sky-50 px-3 py-2 text-xs ring-1 ring-sky-200">
              <p className="font-semibold text-sky-800">
                <span aria-hidden>🕒</span> {plan.congestion_alternative.note}
              </p>
              <p className="mt-1 text-sky-700">
                피할 곳: {plan.congestion_alternative.avoided.join(", ")}
              </p>
              {plan.congestion_alternative.stations.length > 0 && (
                <p className="mt-0.5 text-sky-700">
                  대신 이용: {plan.congestion_alternative.stations.join(" → ")}
                </p>
              )}
              <p className="mt-1 text-[10px] text-sky-600">
                충전 대기는 과거 이용 이력으로 추정한 참고값입니다. 실제와 다를 수
                있습니다.
              </p>
            </div>
          )}

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
                          {cp.congestion && (
                            <CongestionBadge c={cp.congestion} />
                          )}
                        </span>
                      </div>
                      {cp.available === false && cp.alternative && (
                        <div className="flex flex-col items-end gap-0.5 rounded-lg bg-emerald-50 px-2 py-1 text-xs">
                          <div className="flex items-center gap-1.5">
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
                          {/* 같은 휴게소라도 사업자가 다르면 이름이 똑같이 나온다.
                              거리·사업자·출력이 있어야 현장에서 구분이 된다. */}
                          <span className="text-[11px] text-slate-500">
                            {cp.alternative.distance_km}km
                            {cp.alternative.business_name &&
                              ` · ${cp.alternative.business_name}`}
                            {cp.alternative.max_power_kw > 0 &&
                              ` · ${cp.alternative.max_power_kw}kW`}
                            {/* 출력이 낮으면 계획보다 오래 걸린다 — 대체소 기준
                                실제 소요를 보여준다. 같으면 표시하지 않는다. */}
                            {cp.alternative.charge_min != null &&
                              cp.alternative.charge_min !== cp.charge_min && (
                                <span
                                  className={
                                    cp.charge_min != null &&
                                    cp.alternative.charge_min > cp.charge_min
                                      ? "font-semibold text-orange-600"
                                      : undefined
                                  }
                                >
                                  {" · 충전 "}
                                  {cp.alternative.charge_min}분
                                </span>
                              )}
                          </span>
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
                  <span>
                    <span aria-hidden>🏁</span> 목적지 충전소
                  </span>
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
                  단일 속도의 계수가 아니라 <b>구간별 실제 속도</b>로 소비를 적산한 뒤
                  역산한 값 → 정체 구간일수록 소비에 더 크게 반영. 참고 평균{" "}
                  <b>{plan.avg_speed_kmh}km/h</b> (총 {plan.total_distance_km}km ÷{" "}
                  {plan.duration_min}분, 실시간 교통 반영)
                </li>
                {/* 사용자 순항속도가 실제로 어떻게 반영됐는지 — 입력값과 적용값을 함께.
                    정체가 있으면 적용값이 입력값보다 낮은 것이 정상이다. */}
                <li className="text-sky-300">
                  ↳ 고속도로·자동차전용 계산속도{" "}
                  <b>{plan.highway_speed_kmh ?? "-"}km/h</b>
                  {plan.cruise_speed_kmh != null ? (
                    <>
                      {" "}(입력 {plan.cruise_speed_kmh}km/h → 법정범위 조정 후 실시간
                      교통속도를 상한으로 적용)
                    </>
                  ) : (
                    <> (순항속도 미입력 → 실시간 교통속도 그대로)</>
                  )}
                  {plan.highway_km > 0 && (
                    <> · 해당 구간 {plan.highway_km}km</>
                  )}
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
              // 장소를 고른 뒤 이름을 직접 정하게 한다(기본값은 검색된 장소명).
              // 실제 저장은 이름 확정 시 — 주소는 이 기기에만 남는다.
              // 이때 실제 주소도 같이 넘긴다. 지금 안 담아두면 나중에 좌표로
              // 되살릴 방법이 없다(역지오코딩 엔드포인트가 없다).
              setNaming({
                index: Number(picker.split(":")[1]),
                initial: p.name,
                addr: value,
                address: p.address,
              });
            } else if (picker === "origin") {
              setOrigin({ label: p.name, value, address: p.address });
            } else {
              setDestination({ label: p.name, value, address: p.address });
            }
            setPicker(null);
          }}
        />
      )}

      {naming && (
        <ShortcutNameModal
          title={naming.addr ? "즐겨찾기 이름" : "이름 수정"}
          initial={naming.initial}
          onClose={() => setNaming(null)}
          // 신규 등록 중(addr 있음)에는 지울 대상이 없다 → 삭제 버튼도 안 나온다
          onDelete={
            naming.addr ? undefined : () => setShortcut(naming.index, null)
          }
          onSave={(label) => {
            // 신규면 방금 고른 주소를, 수정이면 이미 저장된 주소를 그대로 쓴다.
            // 이름만 고칠 때 기존 address를 잃지 않도록 함께 넘긴다.
            const cur = shortcuts[naming.index];
            const addr = naming.addr ?? cur?.addr;
            const address = naming.addr ? naming.address : cur?.address;
            if (addr) setShortcut(naming.index, { label, addr, address });
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
// 출발 시각별 총 소요시간 비교(F4).
//
// ⚠ **정체 차이는 반영되지 않는다.** 카카오 실시간 교통은 현재 시점만 주므로
//    미래 출발 시각의 정체를 알 수 없다. 여기서 달라지는 것은 충전 대기뿐이며,
//    그 사실을 표 아래에 그대로 고지한다(없으면 사용자가 정체까지 계산된 걸로 읽는다).
function DepartTable({ data }: { data: DepartOptionsResponse }) {
  const base = data.options.find((o) => o.offset_h === 0);
  return (
    <div className="mt-2 overflow-hidden rounded-lg ring-1 ring-slate-200">
      <table className="w-full text-[11px]">
        <caption className="sr-only">출발 시각별 예상 총 소요시간 비교</caption>
        <thead className="bg-slate-50 text-slate-500">
          <tr>
            <th scope="col" className="px-2 py-1.5 text-left font-medium">출발</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">총 소요</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">충전 대기</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">기준 대비</th>
          </tr>
        </thead>
        <tbody>
          {data.options.map((o) => {
            const diff = base ? o.total_trip_min - base.total_trip_min : 0;
            const best = data.best_offset_h === o.offset_h;
            return (
              <tr
                key={o.offset_h}
                className={best ? "bg-emerald-50 font-semibold" : "border-t border-slate-100"}
              >
                <th scope="row" className="px-2 py-1.5 text-left font-normal">
                  {o.offset_h === 0
                    ? "지금"
                    : `${o.offset_h > 0 ? "+" : ""}${o.offset_h}시간`}
                  {/* 색만으로 추천을 표시하지 않는다(WCAG) */}
                  {best && <span className="ml-1 text-emerald-700">← 추천</span>}
                </th>
                <td className="px-2 py-1.5 text-right">
                  {o.feasible ? `${o.total_trip_min}분` : "완주 불가"}
                </td>
                <td className="px-2 py-1.5 text-right text-slate-500">
                  {o.charge_wait_min}분
                </td>
                <td className="px-2 py-1.5 text-right">
                  {diff === 0 ? "–" : `${diff > 0 ? "+" : ""}${diff}분`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="bg-slate-50 px-2 py-1.5 text-[10px] text-slate-500">{data.note}</p>
    </div>
  );
}

// 도착 예정 시각 기준 혼잡 예측 배지.
//
// 접근성: 혼잡도를 **색으로만 표현하지 않는다** — 등급 텍스트("혼잡 예상")를 항상
// 함께 낸다. 색약 사용자나 흑백 출력에서 점 색깔만으로는 구분이 안 되기 때문이다.
//
// 대기시간을 "25분"이 아니라 "20~30분" 구간으로 쓰는 이유: 이 값은 관측한 게 아니라
// 점유 통계에서 유도한 추정치라 분 단위 정밀도를 주장할 근거가 없다(docs/07 §9-1).
function CongestionBadge({ c }: { c: StationCongestion }) {
  const color =
    c.level === "혼잡" ? "#ef4444" : c.level === "보통" ? "#f59e0b" : "#10b981";
  return (
    <span
      className="mt-0.5 inline-flex flex-wrap items-center justify-end gap-1 text-[11px]"
      style={{ color }}
    >
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
      {c.level === "혼잡" ? "혼잡 예상" : `충전 대기 ${c.level}`}
      {c.wait_hi > 0 && (
        <span className="text-slate-500">
          · 대기 {c.wait_lo}~{c.wait_hi}분
        </span>
      )}
      {/* slate-400은 흰 배경에서 2.56:1로 WCAG AA(4.5:1) 미달 → 500(4.77:1) */}
      <span className="text-slate-500">
        (신뢰도 {c.confidence}
        {c.daytype_fallback === "weekend" && ", 주말 기준"})
      </span>
    </span>
  );
}

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

// 지역 탐색(돋보기 + 위치 핀)
function SearchAreaIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
      <path
        d="M20 20l-3.5-3.5M11 8v6M8 11h6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
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
    // w-full 필수 — 빈 칸은 이 버튼이 그리드 아이템이라 저절로 늘어나지만, 저장된
    // 칸은 relative 래퍼가 그리드 아이템이 되어 버튼이 fit-content로 줄어든다.
    // 빼면 저장 직후 칩만 작아지고 모서리 배지가 칩 밖으로 떨어져 나간다.
    <button
      onClick={onClick}
      className="flex w-full flex-col items-center gap-1 rounded-xl bg-slate-50 py-2.5 ring-1 ring-slate-200 hover:bg-slate-100 active:scale-[0.98]"
    >
      {/* 아이콘은 장식이다 — aria-hidden이 없으면 스크린리더가 "house 자쿠"로 읽는다 */}
      <span aria-hidden className="text-2xl leading-none">
        {icon}
      </span>
      <span className="text-xs font-medium text-slate-600">{label}</span>
    </button>
  );
}

// 이름 아래 실제 주소 한 줄. "회사"가 어디인지 확인시켜 주는 용도라
// 이름과 같은 문자열이면 중복이니 표시하지 않는다.
// 이 필드가 생기기 전 등록한 즐겨찾기에는 address가 없어 그냥 빠진다.
function PlaceAddress({ place }: { place: Place }) {
  if (!place.address || place.address === place.label) return null;
  return (
    <span className="mt-0.5 block truncate text-xs font-normal text-slate-500">
      {place.address}
    </span>
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

// 분 → [큰 숫자, 작은 단위]. Stat의 (value, unit) 표기(숫자 크게·단위 작게)에 맞춰
// 튜플로 돌려준다. 문자열이 필요하면 두 값을 이어 붙이면 된다("4" + "시간 1분").
//
//   45  → ["45", "분"]        1시간 미만은 분만 쓴다
//   240 → ["4",  "시간"]      정각이면 "0분"을 붙이지 않는다
//   241 → ["4",  "시간 1분"]
function hourMin(min: number): [string, string] {
  const m = Math.max(0, Math.round(min));
  if (m < 60) return [String(m), "분"];
  const rest = m % 60;
  return [String(Math.floor(m / 60)), rest ? `시간 ${rest}분` : "시간"];
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
