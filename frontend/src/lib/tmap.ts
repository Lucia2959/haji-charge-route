// T맵 앱 딥링크 — 충전소를 도착지로 넣어 길안내를 띄운다.
//
// 파라미터 이름이 플랫폼마다 다르다. T맵은 공식 스킴 문서를 공개하지 않아
// 커뮤니티 소스 3곳을 교차확인해 맞췄다(2026-08 기준).
//   iOS     : tmap://route?rGoName=&rGoX=경도&rGoY=위도
//   Android : tmap://route?referrer=com.skt.Tmap&goalname=&goalx=경도&goaly=위도
//
// ⚠ 좌표는 WGS84 십진도이고 **X가 경도(lng), Y가 위도(lat)**다.
//   순서를 바꿔도 앱은 멀쩡히 열리고 전혀 다른 곳으로 안내한다 — 조용히 틀리는
//   종류라, 아래 tmap.test.mjs가 이 순서를 고정한다.
import type { LatLng } from "./types";

export const TMAP_STORE_IOS = "https://apps.apple.com/app/id431589174";
export const TMAP_STORE_ANDROID =
  "https://play.google.com/store/apps/details?id=com.skt.tmap.ku";

export function tmapUrl(name: string, loc: LatLng, android: boolean): string {
  // 충전소명은 공백·괄호가 흔하다(예: "가평(서울)휴게소") → 반드시 인코딩
  const n = encodeURIComponent(name);
  return android
    ? `tmap://route?referrer=com.skt.Tmap&goalname=${n}&goalx=${loc.lng}&goaly=${loc.lat}`
    : `tmap://route?rGoName=${n}&rGoX=${loc.lng}&rGoY=${loc.lat}`;
}
