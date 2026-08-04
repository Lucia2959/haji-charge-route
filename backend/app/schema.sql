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

-- 집계는 "이 충전소의 이 기간 세션 전부"를 훑는다.
CREATE INDEX IF NOT EXISTS session_station_start_idx
  ON session (station_id, started_at);

-- 오래된 세션 정리(보관기간 초과분 삭제)용.
CREATE INDEX IF NOT EXISTS session_start_idx ON session (started_at);


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
