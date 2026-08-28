---
name: ic-model
description: 상장 종목의 투자심사 모델을 만든다. 공시(DART) 원문으로 실적을 확정하고, 매출→비용→영업이익→밸류에이션 트리를 세워 인터랙티브 HTML과 수식이 살아있는 Excel을 산출한다. "○○ 투자심사 모델", "○○ 밸류에이션 모델", "○○ 실적 추정 모델" 요청 시 사용.
---

# 투자심사 모델 생성

종목명을 받으면 인터랙티브 추정 모델을 만든다. 보고서를 문서로 쓰지 않는다 —
심사 판단이 모델의 뷰로 들어가므로 보고서와 모델의 숫자가 어긋날 수 없다.

**시작 전에 읽는다**: `framework/modeling_framework.md`, `framework/html_template_spec.md`

---

## 절대 규칙

1. **검색 스니펫으로 라인아이템을 확정하지 않는다.** 이 레포에서 검색이 틀린
   사례가 세 번 있었다 — 삼성전기 FY2021 매출이 71,997억 vs 96,750억(실제),
   FY2022 영업이익이 실제의 68%, 시가총액과 주가가 서로 안 맞음.
   확정값은 `tools/dart_fetch.py`로 공시 원문에서 가져온다.
2. **`[검증대상]`이 남아 있으면 다음 단계로 가지 않는다.**
3. **게이트 실패를 남겨두지 않는다.** G1·G2의 허용 오차는 0이다.
4. **`model.html`을 직접 고치지 않는다.** 빌드 산출물이다. 엔진 수정은
   `tools/make_template.py`에 패치로 넣고 템플릿을 다시 만든다.
5. **없는 데이터를 지어내지 않는다.** 쪼갤 근거가 없으면 거기서 멈춘다.

---

## 절차

### 1. 공시 확정

```bash
python3 tools/dart_fetch.py search <종목명>          # 사업보고서 목록
python3 tools/dart_fetch.py toc <접수번호>           # 목차
python3 tools/dart_fetch.py doc <접수번호> <목차번호> # 본문
```

최근 사업보고서 2~3건이면 5개년이 채워진다. 각 보고서는 3개년을 보여준다.

가져올 것:
- **연결 포괄손익계산서** — 매출액·매출원가·판관비·영업이익
- **영업부문 주석** — 부문별 매출·영업이익·감가상각비 ← 모델의 뼈대
- **연결 재무상태표** — 현금·차입금 (순차입금)
- **연결 현금흐름표** — 유형자산 취득 (CAPEX)
- **주식의 총수** — 발행주식수

확인할 것:
- 부문합 = 연결 매출액인가 (오차 0)
- 소급 재작성이 있었나 (중단영업·회계기준 변경). 있으면 어느 기준을 쓸지
  정하고 `historicals.json`의 `_기준`에 기록한다
- IR 보도자료의 부문 수치는 대개 **분기**다. 연간과 섞지 않는다

원본은 `companies/<종목>/dart_extract.json`에 출처 접수번호와 함께 남긴다.

### 2. 설계 — 숫자보다 구조를 먼저

`01_revenue_methodology.md` / `02_cost_methodology.md` / `03_valuation.md`

각 부문이 **수요 바인딩**인지 **공급 바인딩**인지 먼저 정한다. 이걸 정하지
않으면 생산능력이 남는데 capacity로 물량을 추정하는 실수가 난다.

**공시가 물량을 주지 않으면 실적 구간을 Q×P로 쪼개지 않는다.** 미지수 둘에
식 하나가 되어 어떻게 나누든 근거가 없다. 대신 추정 구간의 성장률을
물량과 단가로 나눈다 — 분석적 가치는 남고 지어낸 숫자는 없다.

### 3. data.js 작성

`templates/model_template.html`의 데이터 블록 스키마를 따른다.
선언 순서: `META` → `YRS`/`HIST_N` → `MARKET`(선택) → `UNITS` → `MODEL` →
`MEMO`(선택) → `SCENARIOS`(선택).

핵심 관용구:

```js
// 실적은 확정값 그대로, 추정만 굴린다
seg: { formula:'IF(seg_actual > 0, seg_actual, PREV(seg) * (1 + vol_g) * (1 + price_g))' }

// 누적·롤포워드는 PREV 자기참조
ppe: { formula:'PREV(ppe) + capex - depreciation' }

// 상한 체크
qty: { formula:'MIN(demand_a + demand_b, capacity)' }
```

규약:
- 입력 노드 `desc`는 `[객관]`/`[주관]`/`[외생]`/`[계산]`으로 시작 (G10)
- 색은 `design-guide/tokens.js`에서만. 매출=primary 램프, 비용=neutral 램프
- `TREE`·`INPUT_KEYS`·`DEFAULTS_S`·`GRAPH`·`SIM_SECS`는 쓰지 않는다 (자동 파생)
- 음수가 정상인 계정(순차입금 등)은 `allowNegative:1`
- `MARKET`은 시장 관측치다. 가정이 아니므로 `MODEL`에 넣지 않는다

`historicals.json`에 공시 확정값을 적는다. G1이 매 빌드마다 대사한다.

### 4. 빌드와 검증

```bash
python3 tools/build_model.py companies/<종목>/data.js       # → model.html
python3 tools/build_excel.py companies/<종목>/model.html    # → model.xlsx
python3 tools/validate_model.py companies/<종목>/model.html
```

게이트 G1~G10이 전부 통과해야 한다. 하나라도 실패하면 고치고 다시 돌린다.

### 5. 심사 레이어

`MARKET`을 선언하면 사이드바에 Investment case 그룹(투자 개요·밸류에이션·
심사 결론)이 나타난다. `MEMO`에 판단 텍스트를, `SCENARIOS`에 Bull/Bear
프리셋을 넣는다. Base는 초안값 그 자체이므로 케이스로 두지 않는다.

시나리오는 **`[주관]` 노드만 흔든다.** `[객관]`을 흔들면 시나리오가 아니라
다른 모델이다.

---

## 밸류에이션 방법 선택

| 상황 | 방법 |
|---|---|
| 증설 사이클 중이라 FCF 진폭이 큼 | EV/EBITDA 배수법 |
| 현금흐름이 안정적이고 CAPEX 예측 가능 | DCF |
| 어느 쪽이든 | **역산을 함께 낸다** — 현재 가격이 전제하는 실적 |

역산이 목표가 제시보다 심사에 유용할 때가 많다. 특히 주가가 급등해
실적 기반 모델과 가격이 크게 벌어진 종목에서 그렇다.
"적정가가 얼마인가"보다 "지금 가격이 무엇을 전제하는가"가 답할 수 있는 질문이다.

---

## 산출물

```
companies/<종목>/
  01_revenue_methodology.md   설계 — 매출
  02_cost_methodology.md      설계 — 비용
  03_valuation.md             설계 — 밸류에이션·판단
  dart_extract.json           공시 원문 추출값 (출처 포함)
  historicals.json            G1 대사 기준
  data.js                     손으로 쓰는 유일한 파일
  model.html                  빌드 산출물 (외부 요청 없이 동작)
  model.xlsx                  빌드 산출물 (수식 내장)
```

`model.html`을 사용자에게 전달한다. 시뮬레이터에서 가정을 바꾸면
목표가가 즉시 따라 움직인다는 점을 함께 알린다.

---

## 자주 나오는 실수

| 실수 | 결과 |
|---|---|
| IR 보도자료의 분기 수치를 연간으로 씀 | 부문합이 총매출과 안 맞음 (G1이 잡는다) |
| 소급 재작성 기준을 섞음 | 연도 간 비교가 깨짐 |
| 감가상각비를 매출에 연동 | 하강 국면의 이익 훼손을 과소평가 |
| Base에 마진 회복을 embed | Base가 사실상 Bull이 됨 |
| 목표배수 근거를 안 적음 | 결과를 지배하는 가정이 검증 불가 |
