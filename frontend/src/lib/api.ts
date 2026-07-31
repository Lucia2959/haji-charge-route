import { withLoading } from "./loading";
import type {
  PlaceResult,
  RoutePlanRequest,
  RoutePlanResponse,
  StationDetail,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// 배포 사고 방지: https 페이지에서 http 백엔드를 부르면 Safari가 mixed content로
// 전부 차단하고, localhost는 아이폰에서 자기 자신을 가리켜 100% 실패한다.
// NEXT_PUBLIC_API_BASE는 빌드 시 주입되므로 설정을 빠뜨리면 런타임에 조용히 깨진다.
if (typeof window !== "undefined" && window.location.protocol === "https:") {
  if (API_BASE.startsWith("http://") || API_BASE.includes("localhost")) {
    console.error(
      `[설정 오류] NEXT_PUBLIC_API_BASE=${API_BASE} — https 배포에서는 https 백엔드 주소여야 합니다.`
    );
  }
}

// 서버가 준 detail을 화면 메시지로 그대로 노출한다.
//   402 → "사용량이 초과하였습니다"(무료제한/과금), 429 → "요청이 너무 많습니다"(호출제한).
// detail이 없으면 상태코드별 한국어 문구로 폴백.
async function errText(res: Response, fallback: string): Promise<string> {
  try {
    const d = await res.json();
    if (d && typeof d.detail === "string" && d.detail) return d.detail;
  } catch {
    // JSON 본문이 아니면 폴백
  }
  // 402 = 외부 API 일일 사용량 '소진'(오늘은 회복 안 됨)
  // 429 = 단시간 과다호출(잠시 후 풀림) — 둘을 섞으면 사용자가 오해한다
  if (res.status === 402) return "사용량이 초과하였습니다";
  if (res.status === 429) return "요청이 몰리고 있습니다. 잠시 후 다시 시도해 주세요.";
  if (res.status >= 500) return `${fallback} — 서버 오류입니다. 잠시 후 다시 시도해 주세요.`;
  return `${fallback} (${res.status})`;
}

// 모든 서버호출의 공통 진입점. 타임아웃이 없으면 백엔드 무응답 시 무한 대기가 되고,
// fetch 실패는 "Failed to fetch" 영어 원문이 그대로 화면에 노출된다 → 한국어로 변환.
const TIMEOUT_MS = 20_000;

// 백엔드 공유 시크릿(설정된 경우). 번들에 노출되므로 사람 대상 인증이 아니라,
// URL을 모르는 봇·스캐너가 백엔드를 직접 두드려 외부 API 쿼터를 태우는 것을 막는 용도.
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";

async function req(url: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (API_TOKEN) headers.set("X-Haji-Key", API_TOKEN);
  try {
    return await fetch(url, {
      ...init,
      headers,
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (e) {
    const name = (e as Error)?.name;
    if (name === "TimeoutError" || name === "AbortError") {
      throw new Error("서버 응답이 20초를 넘었습니다. 잠시 후 다시 시도해 주세요.");
    }
    throw new Error("서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.");
  }
}

export async function searchPlaces(query: string): Promise<PlaceResult[]> {
  return withLoading(
    (async () => {
      const res = await req(
        `${API_BASE}/api/places/search?query=${encodeURIComponent(query)}`
      );
      if (!res.ok) throw new Error(await errText(res, "장소 검색 실패"));
      return res.json();
    })()
  );
}

export async function planRoute(
  body: RoutePlanRequest
): Promise<RoutePlanResponse> {
  return withLoading(
    (async () => {
      const res = await req(`${API_BASE}/api/route/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await errText(res, "경로 계산 실패"));
      return res.json();
    })()
  );
}

export async function getCurrentTemperature(
  query: string
): Promise<number | null> {
  try {
    const res = await req(
      `${API_BASE}/api/weather/current?query=${encodeURIComponent(query)}`
    );
    if (!res.ok) return null;
    const d = (await res.json()) as { temperature_c: number | null };
    return d.temperature_c;
  } catch {
    return null;
  }
}

export async function getStation(id: string): Promise<StationDetail> {
  const res = await req(`${API_BASE}/api/stations/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(await errText(res, "충전소 조회 실패"));
  return res.json();
}

// 세션 저장은 만료 시각을 함께 기록해, 오래된 위치·경로 데이터가 남지 않게 한다.
const STORE_TTL_MS = 3 * 60 * 60 * 1000; // 3시간

// Safari 프라이빗 브라우징·쿠키 차단·잠금 모드에서는 sessionStorage 접근 자체가
// SecurityError를 던진다. 감싸지 않으면 마운트 시점에 화면 전체가 죽으므로,
// 저장소를 못 쓰면 조용히 포기하고 메모리 상태만으로 동작하게 한다.
function saveWithTs<T>(key: string, value: T) {
  try {
    sessionStorage.setItem(key, JSON.stringify({ t: Date.now(), v: value }));
  } catch {
    // 저장 불가(프라이빗 모드·용량 초과) — 이번 세션은 메모리로만 유지
  }
}

function removeSafe(key: string) {
  try {
    sessionStorage.removeItem(key);
  } catch {
    // 저장소 자체를 못 쓰는 환경
  }
}

function loadWithTs<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { t: number; v: T };
    if (!parsed || typeof parsed.t !== "number") {
      removeSafe(key); // 구버전/손상 데이터 제거
      return null;
    }
    if (Date.now() - parsed.t > STORE_TTL_MS) {
      removeSafe(key); // 만료
      return null;
    }
    return parsed.v;
  } catch {
    removeSafe(key);
    return null;
  }
}

// 메인 → 지도 화면으로 계획 결과를 전달하기 위한 세션 저장소
const PLAN_KEY = "haji.routePlan";

export function savePlan(plan: RoutePlanResponse) {
  saveWithTs(PLAN_KEY, plan);
}

export function loadPlan(): RoutePlanResponse | null {
  return loadWithTs<RoutePlanResponse>(PLAN_KEY);
}

export function clearPlan() {
  removeSafe(PLAN_KEY);
}

// 메인 화면 검색조건(출발/도착/현충전량/기온) 유지 — 다른 화면 다녀와도 초기화 방지
const FORM_KEY = "haji.mainForm";

export interface MainFormState {
  origin: { label: string; value: string };
  destination: { label: string; value: string };
  charge: string;
  temp: string;
  tempAuto: boolean;
  active: "origin" | "destination";
}

export function saveForm(s: MainFormState) {
  saveWithTs(FORM_KEY, s);
}

export function loadForm(): MainFormState | null {
  return loadWithTs<MainFormState>(FORM_KEY);
}

export function clearForm() {
  removeSafe(FORM_KEY);
}

// 충전소 상세 → 충전 계산 화면으로 선택한 충전기 스펙을 전달
const CHARGER_KEY = "haji.selectedCharger";

export interface SelectedCharger {
  station_name: string;
  charger_no: string;
  charge_type: string;
  power_kw: number;
  unit_price: number;
}

export function saveCharger(c: SelectedCharger) {
  saveWithTs(CHARGER_KEY, c);
}

export function loadCharger(): SelectedCharger | null {
  return loadWithTs<SelectedCharger>(CHARGER_KEY);
}

export function clearCharger() {
  removeSafe(CHARGER_KEY);
}

/** 앱 초기화 시 저장된 경로·검색·충전기 데이터를 모두 삭제. */
export function clearAllRouteData() {
  clearPlan();
  clearForm();
  clearCharger();
}

// 즐겨찾기(집·회사 등) — 개인 위치정보다.
// NEXT_PUBLIC_ 환경변수로 두면 빌드 시 클라이언트 번들에 문자열로 박혀, 배포 URL만
// 알면 누구나 주소를 읽을 수 있다. 그래서 번들·서버 어디에도 두지 않고 사용자 기기의
// localStorage에만 저장한다(세션이 아니라 기기에 남아야 하므로 localStorage).
const SHORTCUT_KEY = "haji.shortcuts";
export const SHORTCUT_SLOTS = 2;

export interface ShortcutItem {
  label: string;
  addr: string; // "lng,lat" 또는 주소 문자열
}

export function loadShortcuts(): (ShortcutItem | null)[] {
  const empty = Array<ShortcutItem | null>(SHORTCUT_SLOTS).fill(null);
  try {
    const raw = localStorage.getItem(SHORTCUT_KEY);
    if (!raw) return empty;
    const arr = JSON.parse(raw) as (ShortcutItem | null)[];
    if (!Array.isArray(arr)) return empty;
    return empty.map((_, i) =>
      arr[i] && typeof arr[i]?.addr === "string" ? arr[i] : null
    );
  } catch {
    return empty;
  }
}

export function saveShortcuts(list: (ShortcutItem | null)[]) {
  try {
    localStorage.setItem(SHORTCUT_KEY, JSON.stringify(list));
  } catch {
    // 저장 불가(프라이빗 모드) — 이번 실행에만 유지
  }
}
