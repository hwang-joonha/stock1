# 투자심사 모델링 레포

주식 종목의 투자심사 보고서를, 문서가 아니라 **인터랙티브 추정 모델**로 만든다.
심사 판단(밸류에이션·시나리오·투자의견)이 모델의 뷰로 들어가므로
보고서와 모델의 숫자가 어긋날 수 없다.

현재 대상: **삼성전기 (009150)** · 단위 **억원**

---

## 구조

```
framework/          규약 문서 — 먼저 읽는다
  modeling_framework.md    Q×P 분해 · 객관/주관 · 검증 게이트
  html_template_spec.md    data.js 스키마 · 수식 문법 · 엔진 계약
  ic_memo_framework.md     투자심사 판단 레이어
  excel_spec.md            Excel 산출 규격
design-guide/
  tokens.js           색·타이포 단일 출처. 임의 hex 금지
templates/
  model_template.html 엔진 (약 4,000줄, 종목 무관)
tools/
  make_template.py    예시 → 템플릿 재생성 (엔진 패치가 여기 산다)
  build_model.py      템플릿 + data.js → model.html
  validate_model.py   검증 게이트
  harness.py          모델을 Node에서 평가 (브라우저 없이)
  extract_engine.py   HTML에서 JS 선언 추출
  fixtures/           Tesla 회귀 고정 데이터·골든값
companies/<종목>/
  data.js             손으로 쓰는 유일한 파일
  historicals.json    공시 확정값 (G1 대사용)
  model.html          빌드 산출물
examples/Tesla/       골든 샘플. 손대지 않는다
```

---

## 작업 흐름

```bash
# 1. 데이터 편집
vi companies/samsung-em/data.js

# 2. 빌드
python3 tools/build_model.py companies/samsung-em/data.js

# 3. 검증 — 전 게이트 통과해야 함
python3 tools/validate_model.py companies/samsung-em/model.html
```

엔진을 고칠 때:

```bash
vi tools/make_template.py          # 패치를 추가한다
python3 tools/make_template.py     # 템플릿 재생성
python3 tools/validate_model.py --all   # G9가 Tesla 회귀를 잡는다
```

---

## 규칙

**`model.html`을 직접 고치지 않는다.** 빌드 산출물이라 다음 빌드에 덮인다.
엔진 수정은 `tools/make_template.py`에 패치로 넣는다 — 그래야 모든 종목이
같은 수정을 받는다.

**`examples/Tesla/`를 수정하지 않는다.** 엔진을 고칠 때마다 Tesla 산출값이
그대로 재현되는지가 회귀 기준이다 (게이트 G9, 200셀 오차 0).

**`TREE`·`INPUT_KEYS`·`DEFAULTS_S`·`GRAPH`·`SIM_SECS`를 손으로 쓰지 않는다.**
전부 `MODEL`에서 파생된다.

**색은 `design-guide/tokens.js`에서만 가져온다.** 매출 계열은 primary 램프,
비용 계열은 neutral 램프. 섞지 않는다.

**게이트 실패를 남겨두고 다음 단계로 가지 않는다.** G1·G2의 허용 오차는 0이다.

---

## 진행 상황

| Phase | 내용 | 상태 |
|---|---|---|
| 0 | 엔진 정비 — 템플릿 추출, P0 결함 수정, 검증 게이트 | 완료 |
| 1 | 매출 레이어 — 삼성전기 3개 부문 Q×P | 예정 |
| 2 | 비용 · 영업이익 | 예정 |
| 3 | 밸류에이션 · 심사 뷰 · Excel · 스킬화 | 예정 |

### Phase 0에서 고친 것

| 등급 | 내용 |
|---|---|
| P0 | `PREV(자기노드)` 누적 지원 — 연도축 순차 평가로 전환. 감가상각 롤포워드·누적 잔액이 가능해졌다 |
| P0 | 순환참조 검출 복원 — 고리에 걸린 전 노드에 표시 |
| P0 | `DEFAULTS_S`를 `MODEL`에서 파생 — 중복 데이터 제거 |
| P1 | 단위 비종속화 — `UNITS` 한 곳에서 통화 표기 결정 (억원 적용) |
| P1 | 레거시 노드 id 하드코딩 제거 |
| P1 | 종목 정체성을 `META`로 분리 — 제목·브랜드·저장키 |

### 남은 결함

| 등급 | 내용 |
|---|---|
| P1 | CDN 3종 의존 — 오프라인에서 Excel·JSON 버튼이 죽는다 (Phase 3) |
| P1 | Excel 생성 경로 이중화 — 정본을 정해야 한다 (Phase 3) |
| P2 | 구성비 표시가 합계 트리를 전제 — 뺄셈 루트에서 100%를 넘는다 (Phase 2) |
| P2 | Chart.js를 로드만 하고 쓰지 않는다 — 제거 대상 |
