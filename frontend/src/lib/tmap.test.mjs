// T맵 딥링크 자체검증 — 실행: node src/lib/tmap.test.mjs
//
// 테스트 러너를 새로 넣지 않으려고 node:assert만 쓴다(Node 24의 타입 스트리핑으로
// .ts를 그대로 import한다). 검증 대상은 사실상 하나지만 그 하나가 조용히 틀리는
// 종류다: X/Y를 바꿔도 앱은 정상으로 열리고 운전자만 엉뚱한 곳으로 간다.
import assert from "node:assert/strict";
import { tmapUrl } from "./tmap.ts";

// 서울시청 — 경도 126.9784, 위도 37.5667. 둘 다 30~130 범위의 실수라 바꿔 넣어도
// 그럴듯해 보인다. 그래서 눈으로 말고 값으로 확인한다.
const loc = { lat: 37.5667, lng: 126.9784 };
const parse = (u) => new URL(u.replace("tmap://", "https://")).searchParams;

const ios = parse(tmapUrl("서울시청", loc, false));
assert.equal(ios.get("rGoX"), "126.9784", "iOS rGoX는 경도여야 한다");
assert.equal(ios.get("rGoY"), "37.5667", "iOS rGoY는 위도여야 한다");
assert.equal(ios.get("rGoName"), "서울시청");

const and = parse(tmapUrl("서울시청", loc, true));
assert.equal(and.get("goalx"), "126.9784", "Android goalx는 경도여야 한다");
assert.equal(and.get("goaly"), "37.5667", "Android goaly는 위도여야 한다");
assert.equal(and.get("referrer"), "com.skt.Tmap", "Android는 referrer가 필요하다");

// 충전소명에 공백·괄호·&가 흔하다. 중요한 건 "무엇이 인코딩되나"가 아니라
// **원래 이름으로 되돌아오나**다 — 괄호는 쿼리 값에서 적법해 그대로 남는 게 정상이다.
// &는 반드시 인코딩돼야 한다. 안 그러면 뒤 파라미터가 통째로 잘린다.
for (const nm of ["가평(서울)휴게소", "현대 EV 스테이션", "A&B 충전소"]) {
  assert.equal(parse(tmapUrl(nm, loc, false)).get("rGoName"), nm, `이름 복원 실패: ${nm}`);
}
const amp = parse(tmapUrl("A&B 충전소", loc, false));
assert.equal(amp.get("rGoX"), "126.9784", "이름의 &가 뒤 파라미터를 깨뜨렸다");

console.log("OK — T맵 딥링크: X=경도/Y=위도 고정, iOS·Android 파라미터명, 이름 인코딩");
