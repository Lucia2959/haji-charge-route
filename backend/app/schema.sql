-- 충전 혼잡 예측용 스키마 (docs/07-확장설계안-성수기혼잡.md §5)
--
-- 기동 시 1회 실행된다. 마이그레이션 도구(Alembic 등)를 쓰지 않으므로
-- **모든 문장이 IF NOT EXISTS로 멱등해야 한다.** 컬럼을 추가할 때도
-- ALTER TABLE ... ADD COLUMN IF NOT EXISTS 형태로 이 파일에 덧붙인다.

-- 완료된 충전 세션.
-- 공공 API getChargerStatus의 lastTsdt(시작)/lastTedt(종료)에서 적재한다.
-- 점유율을 따로 저장하지 않는 이유: 세션 구간만 있으면 임의 시각의 사용중 대수를
-- 역산할 수 있다(시각 t를 포함하는 세션 수). 표를 하나 줄인다.
CREATE TABLE IF NOT EXISTS session (
  station_id text        NOT NULL,
  charger_id text        NOT NULL,
  started_at timestamptz NOT NULL,
  ended_at   timestamptz NOT NULL,
  PRIMARY KEY (station_id, charger_id, started_at)
);

-- 보조 인덱스를 두지 않는다. 실측(2026-08-04) 결과 이 테이블은 인덱스가 본체보다
-- 훨씬 비싸다 — heap 65 B/행 vs 인덱스 3개 합계 206 B/행.
--
--   session_pkey               76 B/행   ← ON CONFLICT에 필요. 유지
--   session_station_start_idx  76 B/행   ← 삭제. 집계는 어차피 테이블 대부분을 훑는다
--   session_start_idx          54 B/행   ← 삭제. 하루 1회 DELETE에만 쓰였다
--
-- 무료 Postgres 500MB에서 행당 313 B → 141 B는 보관기간이 2배 이상 늘어나는 차이다.
-- 이미 만들어진 DB에서도 지워지도록 DROP을 남겨둔다(멱등).
DROP INDEX IF EXISTS session_station_start_idx;
DROP INDEX IF EXISTS session_start_idx;


-- 충전소별 '관측 시작 시각'.
--
-- 왜 필요한가: 첫 수집 때 상태 피드가 각 충전기의 **직전 세션 1건**을 함께 준다
-- (백필). 그 세션이 일주일 전 것일 수도 있는데, 그렇다고 그 일주일을 관측한 건
-- 아니다 — 그 사이의 다른 세션들은 우리에게 없다. 이걸 구분하지 않으면 과거 구간이
-- 통째로 '한산했음'으로 집계되고, 관측일 수(n_days)도 부풀어 콜드스타트 가드를
-- 그냥 통과해버린다. 실측에서 수집 첫날에 cells_ready가 383개 나왔다.
--
-- 그래서 점유율 집계는 이 시각 이후 구간만 쓴다. 세션 길이 통계(svc_min_med)는
-- 백필분도 유효하므로 그대로 쓴다.
--
-- 충전소 단위로 두는 이유: COLLECT_DISTRICTS를 나중에 넓히면 새로 들어온 충전소는
-- 관측 시작이 그때부터다. 전역 마커 하나로는 이걸 구분하지 못한다.
CREATE TABLE IF NOT EXISTS station_seen (
  station_id    text        PRIMARY KEY,
  first_seen_at timestamptz NOT NULL
);


-- 예측 조회용 집계. 하루 1회 갱신하고, 계획 API는 여기만 읽는다.
-- 계획 1건당 쿼리 1회(IN 절 배치)로 끝나야 응답시간 예산(웜 5초)을 지킬 수 있다.
CREATE TABLE IF NOT EXISTS occupancy_stat (
  station_id  text        NOT NULL,
  daytype     smallint    NOT NULL,  -- 0=평일 1=주말 2=연휴
  hour        smallint    NOT NULL,  -- 0..23 (KST)
  n_days      smallint    NOT NULL,  -- 이 셀을 관측한 서로 다른 날짜 수 → 콜드스타트 판정
  occ_mean    real        NOT NULL,  -- 평균 점유율 0..1
  p_full      real        NOT NULL,  -- 전 충전기 사용중이던 시간 비율 0..1
  svc_min_med real        NOT NULL,  -- 세션 길이 중앙값(분). 대기시간 추정의 측정 입력
  updated_at  timestamptz NOT NULL,
  PRIMARY KEY (station_id, daytype, hour)
);
