// ┌──────────────────────────────────────────────────────────────────────┐
// │  골격 파일 — 값이 전부 0이다. 이대로 쓰지 말 것.                        │
// │                                                                      │
// │  01_revenue_methodology.md §4의 Q×P 트리를 실행 가능한 형태로 옮긴 것. │
// │  구조·수식·단위·근거 태그는 확정됐고, 남은 것은 숫자뿐이다.             │
// │                                                                      │
// │  진행 방법                                                            │
// │    1. DATA_REQUEST.md의 항목을 공시 원문에서 확보                      │
// │    2. historicals.json 작성 (게이트 G1의 대사 기준)                    │
// │    3. 이 파일을 data.js로 복사하고 v 배열을 채움                       │
// │    4. build_model.py → validate_model.py                             │
// └──────────────────────────────────────────────────────────────────────┘

const META={
  modelId:'samsung_em_revenue',
  title:'삼성전기 매출 추정 모델',
  brand:'Samsung Electro-Mechanics',
  logo:'S',
};

// 실적 5개년 + 추정 5개년. 실적 연도는 시뮬레이터에서 잠긴다.
const YRS=['2021','2022','2023','2024','2025','2026','2027','2028','2029','2030'];
const HIST_N=5;
const _isFc=i=>i>=HIST_N;

const UNITS={
  money:'억원',
  moneyAbbrev:[{min:10000, div:10000, suffix:'조원', digits:2}],
  scope:'매출 레이어',
  excelMoneyFormat:'_-* #,##0_-;-* #,##0_-;_-* "-"_-;_-@_-',
  excelOneDecimal:['지수','%','배'],
  excelTwoDecimal:['억원/지수','억원/백만대'],
};

// ── 색상: design-guide/tokens.js ─────────────────────────────
//   매출 계열 = primary 램프 / 입력 노드 = primary.500
const _Z=[0,0,0,0,0,0,0,0,0,0];   // 골격이라 전부 0. 채울 자리.

const MODEL={

  // ═══ 루트 ═══════════════════════════════════════════════════
  root: {
    label:'삼성전기 총매출', sub:'컴포넌트 + 광학통신 + 패키지',
    parent:null, type:'computed',
    formula:'component_total + optics_total + package_total',
    v:_Z.slice(), u:'억원',
    desc:'3개 사업부문 합계. 부문 간 내부거래 제거액이 별도 공시되면 노드를 추가한다.',
    bg:'#1E2185', fg:'#FFFFFF', sfg:'#A1B8FF',
  },

  // ═══ ① 컴포넌트 — 수요 바인딩 ═══════════════════════════════
  // MLCC 중심. 전방 수요가 상한을 정하되 생산능력으로 캡을 건다.
  // 믹스(전장·서버 비중)가 이 부문의 핵심 — 같은 수량도 믹스가 오르면 매출이 오른다.
  component_total: {
    label:'① 컴포넌트', sub:'출하지수 × 단가지수',
    parent:'root', type:'computed', formula:'comp_qty_index * comp_asp',
    v:_Z.slice(), u:'억원', c:'#3332D0',
    desc:'MLCC·인덕터 등 수동부품. 전방 IT·전장·서버 수요에 묶인다.',
    bg:'#3332D0', fg:'#FFFFFF', sfg:'#C5D5FF',
  },
  comp_qty_index: {
    label:'출하지수', sub:'전방 수요 합 (CAPA 캡)',
    parent:'component_total', type:'computed',
    formula:'MIN(demand_it + demand_auto + demand_server, comp_capacity)',
    v:_Z.slice(), u:'지수', c:'#5D68F7',
    desc:'세 전방 시장의 수요 기여를 더하고 생산능력으로 캡을 건다. '
        +'수요 바인딩 부문이지만 AI·서버용 고용량 제품은 공급 바인딩으로 '
        +'전환될 수 있어 상한 체크가 필요하다.',
    bg:'#EDF3FF', fg:'#1E2185', sfg:'#5D68F7', bdr:'#A1B8FF',
  },
  demand_it: {
    label:'IT 수요 기여', parent:'comp_qty_index', type:'input',
    v:_Z.slice(), u:'지수', c:'#5D68F7',
    desc:'[주관·시나리오] 스마트폰·PC 전방 수요. 재고 사이클에 민감하며 '
        +'구조적 성장은 제한적. 출처: 산업 출하 통계.',
  },
  demand_auto: {
    label:'전장 수요 기여', parent:'comp_qty_index', type:'input',
    v:_Z.slice(), u:'지수', c:'#5D68F7',
    desc:'[주관] 전장용 수요. 대당 MLCC 탑재량 상승이 구조적 성장축이라 '
        +'IT 대비 변동이 작다. 전기차·ADAS 침투율에 연동.',
  },
  demand_server: {
    label:'서버·AI 수요 기여', parent:'comp_qty_index', type:'input',
    v:_Z.slice(), u:'지수', c:'#5D68F7',
    desc:'[주관·시나리오] 서버·AI 가속기용 고용량 제품. 상방 변동이 가장 큰 '
        +'요인이며 데이터센터 CAPEX에 연동. 상/하한 분리 필수.',
  },
  comp_capacity: {
    label:'생산능력 상한', parent:'comp_qty_index', type:'input',
    v:_Z.slice(), u:'지수', c:'#7C91FD',
    desc:'[객관] 부산·필리핀·톈진 생산능력을 지수로 환산. 수요 합계가 이 값을 '
        +'넘으면 캡이 걸린다. 출처: 증설 공시.',
  },
  comp_asp: {
    label:'단가지수', sub:'기본가 × 믹스 프리미엄',
    parent:'component_total', type:'computed',
    formula:'price_it * (1 + mix_auto_server * mix_premium)',
    v:_Z.slice(), u:'억원/지수', c:'#7C91FD',
    desc:'범용 IT 가격에 고부가 믹스 프리미엄을 얹는다. 믹스가 오르면 '
        +'매출과 마진이 함께 오르므로 비용 레이어와 공유하는 드라이버다.',
    bg:'#EDF3FF', fg:'#1E2185', sfg:'#7C91FD', bdr:'#C5D5FF',
  },
  price_it: {
    label:'IT 범용 단가', parent:'comp_asp', type:'input',
    v:_Z.slice(), u:'억원/지수', c:'#7C91FD',
    desc:'[주관] 범용 제품 기준 단가. 공급과잉 국면에서 하락 압력을 받는다.',
  },
  mix_auto_server: {
    label:'전장·서버 비중', parent:'comp_asp', type:'input',
    v:_Z.slice(), u:'%', pct:1, c:'#7C91FD',
    desc:'[주관] 컴포넌트 매출 중 전장·서버향 비중. 매출과 비용 양쪽에 '
        +'영향을 주는 공유 드라이버 — 한 번만 추정하고 참조한다. '
        +'출처: IR 발표 비중.',
  },
  mix_premium: {
    label:'고부가 프리미엄', parent:'comp_asp', type:'input',
    v:_Z.slice(), u:'배', c:'#A1B8FF',
    desc:'[주관] 전장·서버 제품의 범용 대비 단가 배수 초과분. '
        +'비중 100%일 때의 ASP 상승폭을 뜻한다.',
  },

  // ═══ ② 광학통신솔루션 — 수요 바인딩 (고객사 종속) ════════════
  // 물량 × 점유율이 곱으로 들어가 변동성이 증폭된다.
  // Bear 시나리오에서 가장 크게 흔들리는 부문.
  optics_total: {
    label:'② 광학통신솔루션', sub:'출하량 × 모듈 ASP',
    parent:'root', type:'computed', formula:'optics_units * optics_asp',
    v:_Z.slice(), u:'억원', c:'#3332D0',
    desc:'카메라모듈·통신모듈. 주요 고객사 스마트폰 물량에 종속돼 top-down이 '
        +'유일하게 타당하다.',
    bg:'#3332D0', fg:'#FFFFFF', sfg:'#C5D5FF',
  },
  optics_units: {
    label:'모듈 출하량', sub:'고객사 물량 × 점유율',
    parent:'optics_total', type:'computed',
    formula:'customer_volume * share_in_customer',
    v:_Z.slice(), u:'백만대', c:'#5D68F7',
    desc:'두 주관 변수의 곱이라 변동성이 증폭된다. 시나리오에서 두 변수를 '
        +'같은 방향으로 흔들면 과장되므로 상관을 고려해 조정한다.',
    bg:'#EDF3FF', fg:'#1E2185', sfg:'#5D68F7', bdr:'#A1B8FF',
  },
  customer_volume: {
    label:'고객사 물량', parent:'optics_units', type:'input',
    v:_Z.slice(), u:'백만대', c:'#5D68F7',
    desc:'[주관·시나리오] 주요 고객사 스마트폰 출하량. 상/하한 분리 필수.',
  },
  share_in_customer: {
    label:'고객사 내 점유율', parent:'optics_units', type:'input',
    v:_Z.slice(), u:'%', pct:1, c:'#5D68F7',
    desc:'[주관·시나리오] 경쟁사와 물량을 분할한다. 경쟁사 진입이 '
        +'이 부문 최대 하방 위험.',
  },
  optics_asp: {
    label:'모듈 ASP', sub:'기본가 × 사양 프리미엄',
    parent:'optics_total', type:'computed',
    formula:'optics_asp_base * (1 + spec_adoption * spec_premium)',
    v:_Z.slice(), u:'억원/백만대', c:'#7C91FD',
    desc:'고화소·폴디드줌·OIS 등 고사양 채용이 ASP를 끌어올린다.',
    bg:'#EDF3FF', fg:'#1E2185', sfg:'#7C91FD', bdr:'#C5D5FF',
  },
  optics_asp_base: {
    label:'기본 모듈 단가', parent:'optics_asp', type:'input',
    v:_Z.slice(), u:'억원/백만대', c:'#7C91FD',
    desc:'[주관] 표준 사양 모듈 단가.',
  },
  spec_adoption: {
    label:'고사양 채용률', parent:'optics_asp', type:'input',
    v:_Z.slice(), u:'%', pct:1, c:'#7C91FD',
    desc:'[주관] 고화소·줌 모듈 비중. 신제품 스펙에 연동.',
  },
  spec_premium: {
    label:'고사양 프리미엄', parent:'optics_asp', type:'input',
    v:_Z.slice(), u:'배', c:'#A1B8FF',
    desc:'[주관] 고사양 모듈의 표준 대비 단가 배수 초과분.',
  },

  // ═══ ③ 패키지솔루션 — 공급 바인딩 ═══════════════════════════
  // 수요가 공급을 앞서는 국면이라 증설된 만큼 판다.
  // pkg_capacity가 PREV 자기참조 누적이다 — Phase 0에서 엔진을 고친 이유.
  package_total: {
    label:'③ 패키지솔루션', sub:'생산능력 × 가동률 × 단가',
    parent:'root', type:'computed',
    formula:'pkg_capacity * pkg_utilization * pkg_price',
    v:_Z.slice(), u:'억원', c:'#3332D0',
    desc:'FC-BGA·FC-CSP 등 반도체 패키지기판. 서버·AI용 고부가 기판은 수요가 '
        +'공급을 앞서 증설이 곧 매출이다.',
    bg:'#3332D0', fg:'#FFFFFF', sfg:'#C5D5FF',
  },
  pkg_capacity: {
    label:'생산능력', sub:'전년 능력 + 증설',
    parent:'package_total', type:'computed',
    formula:'PREV(pkg_capacity) + capex_addition',
    v:_Z.slice(), u:'지수', c:'#5D68F7',
    desc:'[계산] 누적 생산능력. 전년 능력에 당해 증설분을 더한다. '
        +'첫 연도 값은 capex_addition에 기초 능력을 포함시켜 표현한다. '
        +'같은 증설 일정이 비용 레이어의 감가상각 롤포워드로 이어진다.',
    bg:'#EDF3FF', fg:'#1E2185', sfg:'#5D68F7', bdr:'#A1B8FF',
  },
  capex_addition: {
    label:'증설 반영분', parent:'pkg_capacity', type:'input',
    v:_Z.slice(), u:'지수', c:'#5D68F7',
    desc:'[객관] 당해 양산 개시된 증설 능력. 첫 연도에는 기초 생산능력을 '
        +'포함한다. 비용 레이어의 CAPEX·감가상각과 공유하는 드라이버. '
        +'출처: 증설 투자 공시.',
  },
  pkg_utilization: {
    label:'가동률', parent:'package_total', type:'input',
    v:_Z.slice(), u:'%', pct:1, c:'#7C91FD',
    desc:'[주관·시나리오] 램프업 곡선. 신규 라인은 양산 초기 가동률이 낮다. '
        +'매출과 단위 고정비 배부 양쪽에 영향을 주는 공유 드라이버.',
  },
  pkg_price: {
    label:'단가지수', sub:'기본가 × FC-BGA 프리미엄',
    parent:'package_total', type:'computed',
    formula:'pkg_price_base * (1 + mix_fcbga * fcbga_premium)',
    v:_Z.slice(), u:'억원/지수', c:'#7C91FD',
    desc:'서버·AI용 FC-BGA 비중이 오르면 블렌디드 단가가 오른다.',
    bg:'#EDF3FF', fg:'#1E2185', sfg:'#7C91FD', bdr:'#C5D5FF',
  },
  pkg_price_base: {
    label:'기본 기판 단가', parent:'pkg_price', type:'input',
    v:_Z.slice(), u:'억원/지수', c:'#7C91FD',
    desc:'[주관] 범용 기판 기준 단가.',
  },
  mix_fcbga: {
    label:'FC-BGA 비중', parent:'pkg_price', type:'input',
    v:_Z.slice(), u:'%', pct:1, c:'#7C91FD',
    desc:'[주관] 패키지솔루션 매출 중 서버·AI용 FC-BGA 비중. '
        +'출처: IR 발표 비중.',
  },
  fcbga_premium: {
    label:'FC-BGA 프리미엄', parent:'pkg_price', type:'input',
    v:_Z.slice(), u:'배', c:'#A1B8FF',
    desc:'[주관] 고부가 기판의 범용 대비 단가 배수 초과분.',
  },
};
