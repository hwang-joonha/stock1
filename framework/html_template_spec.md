# HTML 템플릿 사양

`templates/model_template.html`의 계약. 종목 작업에서 손으로 쓰는 것은
`data.js` 하나이고, 이 문서는 그 파일이 지켜야 할 규칙이다.

---

## 1. 빌드

```
templates/model_template.html  +  companies/<종목>/data.js
        └─ 엔진 (약 4,000줄, 종목 무관)   └─ 데이터 (약 150줄)
                          ↓  tools/build_model.py
              companies/<종목>/model.html
```

```bash
python3 tools/build_model.py companies/samsung-em/data.js
python3 tools/validate_model.py companies/samsung-em/model.html
```

**model.html을 직접 고치지 않는다.** 빌드 산출물이라 다음 빌드에 덮인다.
엔진을 고칠 일이면 `tools/make_template.py`에 패치를 추가하고 템플릿을 다시 만든다.
그래야 모든 종목이 같은 수정을 받는다.

---

## 2. data.js 구조

템플릿의 `// <<<DATA:START>>>` ~ `// <<<DATA:END>>>` 구간에 그대로 주입된다.
아래 5개 선언이 순서대로 있어야 한다.

### 2.1 META

```js
const META={
  modelId:'samsung_em_revenue',   // localStorage 저장키의 원천
  title:'삼성전기 매출 추정 모델',   // 브라우저 탭 제목
  brand:'Samsung Electro-Mechanics',
  logo:'S',                        // 사이드바 로고 글자
};
```

`modelId`는 **종목마다 반드시 달라야 한다.** 같으면 서로의 편집 상태를 덮어쓴다.

### 2.2 YRS · HIST_N

```js
const YRS=['2021','2022','2023','2024','2025','2026','2027','2028','2029','2030'];
const HIST_N=5;            // 앞 5개가 실적. 이후는 추정.
const _isFc=i=>i>=HIST_N;
```

모든 `MODEL[k].v`의 길이가 `YRS.length`와 같아야 한다 (게이트 G5).

### 2.3 UNITS

```js
const UNITS={
  money:'억원',
  moneyAbbrev:[{min:10000, div:10000, suffix:'조원', digits:2}],
  scope:'매출 레이어',
  excelMoneyFormat:'_-* #,##0_-;-* #,##0_-;_-* "-"_-;_-@_-',
  excelOneDecimal:['만개','억개','천대','GWh'],
  excelTwoDecimal:['/개','/대','원/'],
};
```

| 키 | 뜻 |
|---|---|
| `money` | 통화 단위 문자열. `MODEL[k].u`가 이 값과 **정확히 같으면** 통화 노드로 본다 |
| `moneyAbbrev` | 큰 값 축약. `min` 이상이면 `div`로 나누고 `suffix`를 붙인다. 내림차순으로 |
| `scope` | 사이드바 각주의 모델 범위 한 줄 |
| `excel*` | Excel 숫자 서식 배정 규칙 |

통화 표기가 여기 한 곳에서만 결정된다. 화면·차트·Excel이 같은 규칙을 쓴다.

### 2.4 MODEL

노드 하나의 스키마:

```js
node_id: {
  label:'표시명',            // 필수
  sub:'부제',               // 트리 노드 두 번째 줄 (computed 권장)
  parent:'부모id' | null,    // null은 루트 하나뿐
  type:'input' | 'computed',
  formula:'수식 문자열',      // computed만
  v:[...],                  // 길이 YRS.length. input은 값, computed는 0으로 채워둠
  u:'억원',                  // 단위
  desc:'[주관] 근거...',      // 필수. 태그로 시작 (게이트 G10)
  c:'#5D68F7',              // 차트 색
  pct:1,                    // 비율로 표기할 때
  bg:'#..', fg:'#..', sfg:'#..', bdr:'#..',   // 트리 노드 스타일 (computed)
}
```

색은 `design-guide/tokens.js`에서만 가져온다. 임의 hex 금지.

### 2.5 파생되는 것 — 쓰지 않는다

`TREE` · `INPUT_KEYS` · `DEFAULTS_S` · `GRAPH` · `SIM_SECS`는 전부 `MODEL`에서
자동으로 만들어진다. data.js에 적지 않는다.

특히 `DEFAULTS_S`는 원본 엔진에서 `MODEL[k].v`의 복제본을 손으로 적는 구조였고,
둘이 갈라질 위험이 있었다. 지금은 파생이라 갈라질 수 없다.

---

## 3. 수식 문법

```
산술      + - * / ( )
비교      == != < > <= >=
함수      SUM(a,b,...)  MIN  MAX  AVG  IF(조건,참,거짓)  PREV(x)
변수      다른 노드의 id
```

- 평가는 **연도별**로 이뤄진다. 모든 값은 길이 `YRS.length` 배열이다.
- `0`으로 나누면 예외가 아니라 `0`이 된다. 의도한 동작이다 —
  분모가 0인 연도 하나 때문에 모델 전체가 멈추지 않게.

### 3.1 PREV — 시차 참조

`PREV(x)`는 직전 연도의 `x`를 읽는다. 첫 연도에서는 `0`이다.

**자기 자신을 참조해도 된다.** 이것이 누적·롤포워드를 표현하는 방법이다.

```js
installed_base: { formula:'PREV(installed_base) + additions' }
net_debt:       { formula:'PREV(net_debt) + capex - ocf' }
ppe:            { formula:'PREV(ppe) + capex - depreciation' }
```

엔진은 연도를 바깥 루프로 돌린다. 연도 `t`를 계산할 때 `t-1`은 이미
전부 확정돼 있으므로 자기참조가 성립한다.

같은 노드를 시차와 동시에 참조하는 것도 된다: `additions + PREV(additions)`.

### 3.2 순환참조는 여전히 오류다

`a = b + 1` / `b = a + 1`처럼 같은 연도 안에서 도는 것은 순환참조다.
엔진이 검출해 고리에 걸린 **모든** 노드에 오류를 표시하고, 그 노드들을
평가에서 제외한다. 검증 게이트 G3가 잡는다.

시차 참조(`PREV`)와 순환참조의 차이는 시간 방향이다.
전자는 과거를 읽고, 후자는 자기 자신을 같은 시점에 읽는다.

---

## 4. 엔진이 제공하는 것

data.js만 채우면 아래가 전부 따라온다.

| 기능 | 설명 |
|---|---|
| 캔버스 트리 | pan · zoom · 노드 드래그 · 인라인 편집 · 분해 · 삭제 |
| 요약 대시보드 | 구성요소 추이 차트, 구성비, 계정 요약표 |
| 계정별 페이지 | 노드마다 값·근거·기여도·자식 분해 |
| 가정·근거 | 입력 노드 일람, 근거 모달 |
| 전체 테이블 | P&L 형태, 실적/추정 밴드 구분 |
| 검증·이슈 | 평가 오류·정합·미사용 변수 |
| 시뮬레이터 | 드라이버 슬라이더, 실적 연도 잠금, 케이스 저장 |
| 내보내기 | IR JSON · 수식이 살아있는 Excel |
| 영속화 | localStorage 자동 저장, 초안 되돌리기 |

---

## 5. 알려진 제약

| 항목 | 내용 |
|---|---|
| CDN 의존 | Excel·JSON 내보내기가 외부 스크립트 3종에 의존한다. 오프라인·사내망에서 버튼이 죽는다. Phase 3에서 인라인 번들로 해결 예정 |
| Chart.js | 로드하지만 쓰지 않는다. 차트는 자체 SVG 렌더러. 제거 대상 |
| 구성비 표시 | 루트가 뺄셈인 트리(영업이익 = 매출 − 비용)에서 자식 구성비가 100%를 넘는다. 합계 트리를 전제한 계산이라 Phase 2에서 손봐야 한다 |
| Excel 생성 이중화 | 브라우저 내 생성과 `build_excel.py`가 각각 존재. 한쪽을 정본으로 정해야 한다 |
