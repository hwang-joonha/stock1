#!/usr/bin/env python3
"""examples/Tesla의 모델 HTML에서 종목 무관 템플릿을 만든다.

한 번 돌리고 마는 스크립트가 아니다. 예시는 골든 샘플로 고정돼 있으므로,
템플릿을 다시 만들어야 할 때마다 여기서 출발한다. 패치는 전부 정확 문자열
치환이고, 하나라도 적용되지 않으면 즉시 실패한다 — 원본이 바뀌면 조용히
어긋나는 대신 소리를 내야 한다.

적용하는 변경:
  P0-1  PREV(자기노드) 누적 지원 — 연도축 순차 평가로 전환
  P0-2  DEFAULTS_S를 MODEL에서 파생 (중복 데이터 제거)
  P1-1  단위 비종속화 — UNITS 한 곳에서 통화 표기 결정
  P1-2  레거시 노드 id('rev') 하드코딩 제거
  DATA  데이터 블록을 주입 마커로 교체
"""
from __future__ import annotations

import sys

SRC = "examples/Tesla/tesla_revenue_model.html"
OUT = "templates/model_template.html"

DATA_START = "// <<<DATA:START>>>"
DATA_END = "// <<<DATA:END>>>"


class Patcher:
    def __init__(self, text: str):
        self.text = text
        self.applied: list[str] = []

    def sub(self, name: str, old: str, new: str, count: int = 1) -> None:
        found = self.text.count(old)
        if found != count:
            raise SystemExit(
                f"[{name}] 패치 대상이 {count}개여야 하는데 {found}개입니다.\n"
                f"원본이 바뀌었는지 확인하세요.\n--- 찾던 문자열 ---\n{old[:400]}"
            )
        self.text = self.text.replace(old, new)
        self.applied.append(name)


# ─────────────────────────────────────────────────────────────
# P0-1  PREV(자기노드) 누적 — 연도축 순차 평가
#
# 기존 엔진은 수식을 연도 배열 통째로 평가했다. PREV(x)는 배열을 한 칸 미는
# 연산이었고, x가 자기 자신이면 위상정렬이 순환으로 판정해 평가를 거부했다.
# 그래서 누적 잔액·롤포워드를 전부 입력 노드로 하드코딩해야 했다.
#
# 바꾼 방식: 연도를 바깥 루프, 노드를 안쪽 루프로 돌린다. 연도 t를 계산할 때
# t-1은 이미 전부 확정돼 있으므로 PREV는 확정값을 읽는다. 자기참조가 성립한다.
# 위상정렬은 PREV 밖의 참조(hard dep)만 따라가고, PREV 안의 참조(lagged dep)는
# 순서를 강제하지 않는다. 다만 의존성 그래프에는 둘 다 남긴다 —
# "이 값을 바꾸면 무엇이 흔들리는가"에는 시차 참조도 답에 포함돼야 한다.
# ─────────────────────────────────────────────────────────────

OLD_EXTRACT_DEPS = """function extractDeps(ast, set){
  if(!set) set=new Set();
  if(!ast) return set;
  if(ast.kind==='ref') set.add(ast.name);
  if(ast.l) extractDeps(ast.l,set);
  if(ast.r) extractDeps(ast.r,set);
  if(ast.x) extractDeps(ast.x,set);
  if(ast.args) ast.args.forEach(a=>extractDeps(a,set));
  return set;
}"""

NEW_EXTRACT_DEPS = """// 참조를 두 종류로 나눈다.
//   hard   — 같은 연도의 값을 읽는다. 평가 순서를 강제한다.
//   lagged — PREV() 안에 있어 직전 연도의 값을 읽는다. 순서를 강제하지 않는다.
// 이 구분이 자기참조 누적(x = PREV(x) + y)을 순환이 아니게 만든다.
function extractDeps(ast, set, lagged, inPrev){
  if(!set) set=new Set();
  if(!ast) return set;
  let sink = inPrev ? (lagged || set) : set;
  if(ast.kind==='ref') sink.add(ast.name);
  let prev = inPrev || (ast.kind==='fn' && ast.name.toUpperCase()==='PREV');
  if(ast.l) extractDeps(ast.l,set,lagged,inPrev);
  if(ast.r) extractDeps(ast.r,set,lagged,inPrev);
  if(ast.x) extractDeps(ast.x,set,lagged,inPrev);
  if(ast.args) ast.args.forEach(a=>extractDeps(a,set,lagged,prev));
  return set;
}

// ----- 단일 연도 평가 -----
// 값 하나를 돌려준다. env[k]는 길이 YRS.length 배열이고, 연도 t를 계산하는
// 시점에 t-1은 전부 확정돼 있다는 것이 이 함수가 기대는 유일한 전제다.
function evalAstAt(ast, env, t){
  switch(ast.kind){
    case 'num': return ast.val;
    case 'ref': {
      let v=env[ast.name];
      if(v===undefined) throw new Error('미정의 변수: '+ast.name);
      let x=v[t];
      return (typeof x==='number' && isFinite(x)) ? x : 0;
    }
    case 'neg': return -evalAstAt(ast.x,env,t);
    case 'bin': {
      let a=evalAstAt(ast.l,env,t), b=evalAstAt(ast.r,env,t);
      switch(ast.op){
        case '+': return a+b;
        case '-': return a-b;
        case '*': return a*b;
        case '/': return b===0?0:a/b;
      }
      throw new Error('알 수 없는 연산자: '+ast.op);
    }
    case 'cmp': {
      let a=evalAstAt(ast.l,env,t), b=evalAstAt(ast.r,env,t);
      switch(ast.op){
        case '==': return a===b?1:0;
        case '!=': return a!==b?1:0;
        case '<':  return a<b?1:0;
        case '>':  return a>b?1:0;
        case '<=': return a<=b?1:0;
        case '>=': return a>=b?1:0;
      }
      throw new Error('알 수 없는 비교연산자: '+ast.op);
    }
    case 'fn': {
      let fn=ast.name.toUpperCase();
      // PREV만 t를 옮겨 평가한다. 누적이 성립하는 지점.
      if(fn==='PREV'){
        if(ast.args.length!==1) throw new Error('PREV는 1개 인자 필요');
        return t===0 ? 0 : evalAstAt(ast.args[0],env,t-1);
      }
      let args=ast.args.map(a=>evalAstAt(a,env,t));
      switch(fn){
        case 'SUM': return args.reduce((s,x)=>s+x,0);
        case 'MIN': return Math.min.apply(null,args);
        case 'MAX': return Math.max.apply(null,args);
        case 'AVG': return args.reduce((s,x)=>s+x,0)/args.length;
        case 'IF':
          if(args.length!==3) throw new Error('IF는 3개 인자 필요');
          return args[0]?args[1]:args[2];
      }
      throw new Error('미정의 함수: '+ast.name);
    }
  }
  throw new Error('알 수 없는 AST');
}"""

OLD_TOPO_DEPS = """function topoSort(){
  let order=[], visited=new Set(), visiting=new Set();
  function visit(k, path){
    if(visited.has(k)) return;
    if(visiting.has(k)){
      throw new Error('순환 참조: '+[...path,k].join(' → '));
    }
    visiting.add(k);
    let d=MODEL[k];
    // 이전 회차의 오류는 여기서 지운다. 아래 분기 안에서만 지우면
    // computed였다가 input으로 바뀐 노드에 옛 오류가 영원히 남는다.
    if(d) d._error=null;
    if(d && d.type==='computed' && d.formula){
      try{
        if(!d._ast) d._ast=parseFormula(d.formula);
        if(!d._deps) d._deps=extractDeps(d._ast);
        for(let dep of d._deps){
          if(MODEL[dep]) visit(dep, [...path, k]);
        }
        d._error=null;
      } catch(e){
        d._error=e.message;
      }
    }
    visiting.delete(k);
    visited.add(k);
    order.push(k);
  }
  for(let k in MODEL){
    try{ visit(k, []); } catch(e){ if(MODEL[k]) MODEL[k]._error=e.message; }
  }
  return order;
}"""

NEW_TOPO_DEPS = """function topoSort(){
  let order=[], visited=new Set(), visiting=new Set();
  // 이전 회차의 오류는 여기서 한 번에 지운다. 순회 중에 지우면 방금 표시한
  // 순환 오류를 다른 노드의 방문이 되돌려 지운다.
  for(let k in MODEL){ if(MODEL[k]) MODEL[k]._error=null; }
  function visit(k, path){
    if(visited.has(k)) return;
    if(visiting.has(k)){
      let at=path.indexOf(k);
      let cyc=(at<0?path:path.slice(at)).concat(k);
      let err=new Error('순환 참조: '+cyc.join(' → '));
      err.cycle=cyc;   // 고리에 걸린 노드 전부를 호출부에 넘긴다
      throw err;
    }
    visiting.add(k);
    let d=MODEL[k];
    if(d && d.type==='computed' && d.formula){
      try{
        if(!d._ast) d._ast=parseFormula(d.formula);
        if(!d._deps){
          // hard는 set으로, PREV 안의 참조는 lagged로 갈라져 담긴다.
          // 그래서 _deps는 이미 같은 연도 참조만 남는다.
          d._lagged=new Set();
          d._deps=extractDeps(d._ast,new Set(),d._lagged,false);
        }
        for(let dep of d._deps){
          if(MODEL[dep]) visit(dep, [...path, k]);
        }
      } catch(e){
        d._error=e.message;
        // 고리 전체에 표시한다. 한 노드만 표시하면 나머지는
        // 계산되지 않은 0을 정상값처럼 내놓는다.
        if(e.cycle) e.cycle.forEach(x=>{ if(MODEL[x]) MODEL[x]._error=e.message; });
      }
    }
    visiting.delete(k);
    visited.add(k);
    order.push(k);
  }
  for(let k in MODEL){
    try{ visit(k, []); } catch(e){
      if(MODEL[k]) MODEL[k]._error=e.message;
      if(e.cycle) e.cycle.forEach(x=>{ if(MODEL[x]) MODEL[x]._error=e.message; });
    }
  }
  return order;
}"""

OLD_SIMCALC = """  // 평가 순서대로 computed 노드 계산
  for(let k of order){
    let d=MODEL[k];
    if(!d||d.type!=='computed') continue;
    if(!d._ast){
      // 파싱 실패 — 이전 값 유지
      continue;
    }
    try{
      let v=evalAst(d._ast, env);
      env[k]=v;
      d.v=v;
      d._error=null;
    } catch(e){
      d._error=e.message;
      env[k]=d.v;  // 이전 값 유지
    }
  }"""

NEW_SIMCALC = """  // computed 노드의 값 배열을 먼저 깔아둔다. PREV가 t-1을 읽으려면
  // 아직 계산되지 않은 노드에도 자리가 있어야 한다.
  let computed=[];
  for(let k of order){
    let d=MODEL[k];
    if(!d||d.type!=='computed'||!d._ast) continue;
    // topoSort가 이미 잡아낸 노드(파싱 실패·순환)는 평가하지 않는다.
    // env에 자리를 만들어주면 순환이 0으로 조용히 계산돼 버린다.
    if(d._error) continue;
    computed.push(k);
    env[k]=Array(YRS.length).fill(0);
  }
  // 연도가 바깥, 노드가 안쪽. 연도 t를 계산할 때 t-1은 전부 확정돼 있다.
  let failed=new Set();
  for(let t=0;t<YRS.length;t++){
    for(let k of computed){
      if(failed.has(k)) continue;
      let d=MODEL[k];
      try{
        env[k][t]=evalAstAt(d._ast, env, t);
      } catch(e){
        d._error=e.message;
        failed.add(k);
        env[k]=(d.v||Array(YRS.length).fill(0)).slice();  // 이전 값 유지
      }
    }
  }
  for(let k of computed){
    let d=MODEL[k];
    if(failed.has(k)) continue;
    d.v=env[k];
    d._error=null;
  }"""

OLD_CLEAR_CACHE = """  for(let k in MODEL){
    delete MODEL[k]._ast;
    delete MODEL[k]._deps;
  }"""

NEW_CLEAR_CACHE = """  for(let k in MODEL){
    delete MODEL[k]._ast;
    delete MODEL[k]._deps;
    delete MODEL[k]._lagged;
  }"""

# 의존성 그래프에는 시차 참조도 남긴다. 평가 순서에서만 뺀 것이지
# "무엇이 무엇에 영향을 주는가"에서 뺀 것이 아니다.
OLD_GRAPH_DEPS = """    let list=[];
    if(MODEL[k]._deps) MODEL[k]._deps.forEach(x=>{ if(MODEL[x]) list.push(x); });
    g.deps[k]=list;"""

NEW_GRAPH_DEPS = """    let list=[];
    if(MODEL[k]._deps) MODEL[k]._deps.forEach(x=>{ if(MODEL[x]) list.push(x); });
    if(MODEL[k]._lagged) MODEL[k]._lagged.forEach(x=>{
      if(MODEL[x] && list.indexOf(x)<0) list.push(x);
    });
    g.deps[k]=list;"""


# ─────────────────────────────────────────────────────────────
# P0-2  DEFAULTS_S를 MODEL에서 파생
#
# 원본에서 DEFAULTS_S는 MODEL[k].v(입력 노드)의 글자 그대로의 복제본이었다.
# 두 곳에 같은 숫자를 적어두면 언젠가 갈라진다. 파생으로 바꾸면
# "INPUT_KEYS와 DEFAULTS_S의 키가 일치하는가"라는 검사 자체가 필요 없어진다.
# 런타임 편집이 DEFAULTS_S를 갱신하므로 객체 자체는 그대로 둔다.
# ─────────────────────────────────────────────────────────────

OLD_DEFAULTS_HEAD = """// INPUT_KEYS에 등록한 모든 변수가 여기에 있어야 함.
// 결과 변수는 simCalc()이 계산하므로 여기 둘 필요 없음.
// ============================================================
"""

NEW_DEFAULTS_HEAD = """// MODEL에서 자동 파생한다 — 입력 노드의 v가 곧 초안값이다.
// 같은 숫자를 두 곳에 적지 않으므로 둘이 갈라질 수 없다.
// 노드 편집·삭제는 런타임에 이 객체를 직접 갱신한다.
// ============================================================
"""

# 원본의 DEFAULTS_S 리터럴은 통째로 걷어낸다. 남겨두면 종목 데이터가
# 템플릿에 죽은 코드로 따라붙는다.
# 선언 하나로 끝나는 형태를 쓴다. 뒤에 채우는 루프를 두면 이 파일을
# 이름 단위로 떼어가는 도구(extract_engine)가 빈 객체만 가져간다.
DEFAULTS_DERIVED = """const DEFAULTS_S=Object.fromEntries(
  Object.keys(MODEL)
    .filter(k=>MODEL[k].type==='input')
    .map(k=>[k,(MODEL[k].v||[]).slice()])
);"""


# ─────────────────────────────────────────────────────────────
# P1-1  단위 비종속화
#
# 통화 표기가 세 곳에 서로 다른 규칙으로 하드코딩돼 있었다(백만$/십억$/조$,
# 억/백만/만, 그리고 fmtNum의 '원' 분기). 종목이 바뀌면 세 곳을 다 고쳐야 했다.
# UNITS 한 곳으로 모은다.
# ─────────────────────────────────────────────────────────────

OLD_FMT = """function fmtNum(v,u,pct){if(pct)return(v*100).toFixed(1)+'%';if(u==='원'||u==='원/건'||u==='원/대'||u==='원/월'){if(Math.abs(v)>=1e8)return(v/1e8).toFixed(1)+'억';if(Math.abs(v)>=1e4)return(v/1e4).toFixed(0)+'만';return v.toLocaleString('ko-KR')}return fmtSmart(v,pct)}"""

NEW_FMT = """// 통화 노드인가? UNITS.money와 정확히 같은 단위만 축약 대상으로 본다.
function isMoney(u){ return !!u && u===UNITS.money; }
// 큰 통화값 축약. UNITS.moneyAbbrev가 비어 있으면 그냥 fmtSmart로 떨어진다.
function fmtMoney(v){
  if(typeof v!=='number'||!isFinite(v)) return '-';
  let a=Math.abs(v), s=v<0?'-':'';
  for(let i=0;i<UNITS.moneyAbbrev.length;i++){
    let r=UNITS.moneyAbbrev[i];
    if(a>=r.min) return s+(a/r.div).toFixed(r.digits)+r.suffix;
  }
  return fmtSmart(v);
}
function fmtNum(v,u,pct){
  if(pct) return (v*100).toFixed(1)+'%';
  if(isMoney(u)) return fmtMoney(v);
  return fmtSmart(v,pct);
}"""

OLD_BRIDGE_FMT = """  const bfmt=v=>{let a=Math.abs(v),s=v<0?'-':'';if(a>=1e6)return s+(a/1e6).toFixed(1)+'조$'; if(a>=1e3)return s+(a/1e3).toFixed(1)+'십억$'; return s+Math.round(a).toLocaleString()+'백만$'};"""

NEW_BRIDGE_FMT = """  const bfmt=v=>fmtMoney(v);"""

# showAssumptions 안의 bfmt는 원본에서 이미 호출부가 없는 죽은 코드였고,
# 통화 축약 규칙이 세 번째로 중복돼 있던 자리이기도 하다. 걷어낸다.
OLD_ASSUM_FMT = """  const bfmt=v=>{
    if(typeof v!=='number')return'-';
    if(v===0)return'-';
    let a=Math.abs(v),s=v<0?'-':'';
    if(a>=1e8)return s+(a/1e8).toFixed(1)+'억';
    if(a>=1e6)return s+(a/1e6).toFixed(1)+'백만';
    if(a>=1e4)return s+(a/1e4).toFixed(1)+'만';
    if(a<1&&a>0)return(v*100).toFixed(1)+'%';
    return v.toLocaleString('ko-KR');
  };
"""

NEW_ASSUM_FMT = ""


# ─────────────────────────────────────────────────────────────
# P1-3  종목 정체성(제목·브랜드·저장키)을 데이터에서 받는다
#
# 원본은 <title>, data-model-id, 사이드바 브랜드에 "테슬라"가 박혀 있었다.
# data.js의 META 하나로 옮긴다. data-model-id는 localStorage 키의 원천이라
# 종목마다 달라야 한다 — 같으면 다른 종목의 편집 상태를 서로 덮어쓴다.
# ─────────────────────────────────────────────────────────────

OLD_HTML_TAG = """<html lang="ko" data-model-id="tesla_revenue">"""
NEW_HTML_TAG = """<html lang="ko">"""

OLD_TITLE = """<title>테슬라 매출 추정 모델 — 캔버스 + 계정 트래킹</title>"""
NEW_TITLE = """<title>추정 모델</title>"""

OLD_BRAND = """        <div class="brand-logo" id="brandLogo">T</div>
        <div style="min-width:0">
          <div class="brand-name" id="brandName">Tesla Revenue Model</div>"""
NEW_BRAND = """        <div class="brand-logo" id="brandLogo"></div>
        <div style="min-width:0">
          <div class="brand-name" id="brandName"></div>"""

OLD_FOOTTITLE = """      <b id="footTitle">2022–2031 · 매출 레이어</b>"""
NEW_FOOTTITLE = """      <b id="footTitle"></b>"""

OLD_MODEL_ID = """const _MODEL_ID=_storageSafeId(document.documentElement.dataset.modelId||document.title+'_'+location.pathname);"""
NEW_MODEL_ID = """// 저장키는 META.modelId에서 나온다. 종목마다 달라야 서로 덮어쓰지 않는다.
const _MODEL_ID=_storageSafeId(META.modelId||document.title+'_'+location.pathname);"""

# 브릿지 제목의 "매출"은 루트가 매출인 모델에서만 맞는 말이다.
OLD_BRIDGE_TITLE = """  title.textContent=YRS[fi]+'년 → '+YRS[ti]+'년 매출 브릿지  ('+(totalDelta>=0?'+':'')+bfmt(totalDelta)+')';"""
NEW_BRIDGE_TITLE = """  let _rootLabel=(MODEL[rootId()]||{}).label||'합계';
  title.textContent=YRS[fi]+'년 → '+YRS[ti]+'년 '+_rootLabel+' 브릿지  ('+(totalDelta>=0?'+':'')+bfmt(totalDelta)+')';"""

OLD_EXCEL_FMT = """  if(['GWh','백만대','천$/대','백만$/GWh','million','bn','십억','백만'].some(t=>u.includes(t)))return '_-* #,##0.0_-;-* #,##0.0_-;_-* "-"_-;_-@_-';
  if(['$/','USD/','배럴','톤'].some(t=>u.includes(t)))return '_-* #,##0.00_-;-* #,##0.00_-;_-* "-"_-;_-@_-';"""

NEW_EXCEL_FMT = """  if(isMoney(u))return UNITS.excelMoneyFormat;
  if(UNITS.excelOneDecimal.some(t=>u.includes(t)))return '_-* #,##0.0_-;-* #,##0.0_-;_-* "-"_-;_-@_-';
  if(UNITS.excelTwoDecimal.some(t=>u.includes(t)))return '_-* #,##0.00_-;-* #,##0.00_-;_-* "-"_-;_-@_-';"""

# 사이드바 각주의 단위 문구도 UNITS에서 나오게 한다.
OLD_FOOTSUB = """      <p id="footSub">단위 백만$ · 실적 4개년 + 추정 6개년</p>"""
NEW_FOOTSUB = """      <p id="footSub"></p>"""

OLD_INITSHELL = "function initShell(){"
NEW_INITSHELL = """// 화면에 종목명·단위·기간을 심는다. 전부 META/UNITS/YRS에서 나온다.
function renderIdentity(){
  document.title=META.title;
  let set=(id,txt)=>{ let el=document.getElementById(id); if(el) el.textContent=txt; };
  set('brandLogo', META.logo);
  set('brandName', META.brand);
  set('footTitle', YRS[0]+'–'+YRS[YRS.length-1]+' · '+UNITS.scope);
  set('footSub', '단위 '+UNITS.money+' · 실적 '+HIST_N+'개년 + 추정 '+
    (YRS.length-HIST_N)+'개년');
}

function initShell(){
  renderIdentity();"""


# ─────────────────────────────────────────────────────────────
# P1-2  레거시 노드 id 하드코딩 제거
#
# 전개/접기 로직에 'rev'라는 옛 노드 id가 박혀 있었다. 루트가 매출이 아닌
# 모델(영업이익 루트 등)에서는 뜻 없는 문자열이다. 루트와 그 직계로 바꾼다.
# ─────────────────────────────────────────────────────────────




# ─────────────────────────────────────────────────────────────
# IC-3  피어 비교 · 시나리오 뷰
#
# 계획서는 심사 뷰 6종을 적었는데 3종으로 합쳐 냈다. Thesis와 리스크는
# 다른 뷰의 카드로 들어가 있어 내용이 빠지지 않았지만, **시나리오는 화면이
# 아예 없었다** — 문서에만 있고 모델에는 없었다. Bull/Base/Bear를 나란히
# 놓고 보는 것이 심사에서 가장 자주 하는 일인데 그게 빠져 있었다.
#
# 피어 비교는 목표배수의 근거를 화면에 붙이는 일이다. 목표배수가 결과를
# 지배하는 가정인데 그 근거가 코드 주석에만 있으면 검증받을 수 없다.
# ─────────────────────────────────────────────────────────────

OLD_IC2_ROUTE = """function renderView(view){
  if(view === 'ic_overview') return renderICOverview();"""

NEW_IC2_ROUTE = """function renderView(view){
  if(view === 'ic_overview') return renderICOverview();
  if(view === 'ic_scenario') return renderICScenario();"""

OLD_IC2_TITLES = """  ic_overview:'투자 개요', ic_valuation:'밸류에이션', ic_verdict:'심사 결론',"""
NEW_IC2_TITLES = """  ic_overview:'투자 개요', ic_valuation:'밸류에이션',
  ic_scenario:'시나리오', ic_verdict:'심사 결론',"""

OLD_IC2_NAV = """      navBtn('ic_valuation', 'trending-up', '밸류에이션') +
      navBtn('ic_verdict', 'file-text', '심사 결론') +"""
NEW_IC2_NAV = """      navBtn('ic_valuation', 'trending-up', '밸류에이션') +
      navBtn('ic_scenario', 'layers', '시나리오',
             (typeof SCENARIOS === 'object' && SCENARIOS)
               ? String(Object.keys(SCENARIOS).length + 1) : '') +
      navBtn('ic_verdict', 'file-text', '심사 결론') +"""

# 시나리오 값은 미리 계산해 둘 수 없다. 케이스마다 SV를 갈아끼우고 다시
# 풀어야 한다. 화면을 그릴 때 그 자리에서 계산하고 원래 상태로 되돌린다.
OLD_IC2_ANCHOR = """function renderICVerdict(){"""

NEW_IC2_ANCHOR = """// 케이스별로 모델을 다시 풀어 지정한 노드의 값을 읽는다.
// SV를 임시로 갈아끼우므로 반드시 원래대로 되돌린다.
function icSolve(overrides, nodeIds, t){
  var backup = {};
  for(var k in SV) backup[k] = SV[k].slice();
  try{
    if(overrides){
      for(var k2 in overrides){
        if(SV[k2] && overrides[k2].length === YRS.length) SV[k2] = overrides[k2].slice();
      }
    }
    simCalc();
    var out = {};
    nodeIds.forEach(function(id){ out[id] = val(id, t); });
    return out;
  } finally {
    for(var k3 in backup) SV[k3] = backup[k3];
    simCalc();      // 화면에 남은 상태를 원래대로
  }
}

function renderICScenario(){
  var t = icLastIdx(), h = '<div class="page">';
  h += '<div class="page-head"><div class="eyebrow caps">' + ic('layers', 16) +
    ' Investment case</div><h1>시나리오</h1></div>';
  if(typeof SCENARIOS !== 'object' || !SCENARIOS){
    return h + '<div class="notice">SCENARIOS가 data.js에 없습니다.</div></div>';
  }
  h += '<div class="notice">Base는 초안값 그 자체입니다. ' +
    '시뮬레이터 케이스 바에서 전환하면 이 값들이 실제 모델에 적용됩니다. ' +
    '시나리오는 <b>[주관] 노드만</b> 흔듭니다 — 공시 확정 실적은 어느 케이스에서도 같습니다.</div>';

  var want = ['total_revenue', 'op_profit', 'ebitda', rootId()];
  var cases = [{ name:'Base', ov:null }];
  for(var nm in SCENARIOS) cases.push({ name:nm, ov:SCENARIOS[nm] });
  var solved = cases.map(function(c){ return icSolve(c.ov, want, t); });

  var mc = (typeof MARKET === 'object' && MARKET) ? MARKET.mktcap : 0;
  var rows = '';
  cases.forEach(function(c, i){
    var s = solved[i];
    var up = mc ? s[rootId()] / mc - 1 : null;
    var tone = c.name === 'Base' ? ' class="hl"' : '';
    rows += '<tr' + tone + '><td><b>' + esc(c.name) + '</b></td>' +
      '<td>' + esc(fmtSmart(s.total_revenue)) + '</td>' +
      '<td>' + esc(fmtSmart(s.op_profit)) + '</td>' +
      '<td>' + (s.total_revenue ? (s.op_profit / s.total_revenue * 100).toFixed(1) + '%' : '—') + '</td>' +
      '<td>' + esc(fmtSmart(s.ebitda)) + '</td>' +
      '<td>' + esc(fmtSmart(s[rootId()])) + '</td>' +
      (up === null ? '<td>—</td>'
        : '<td class="' + (up >= 0 ? 'pos' : 'neg') + '">' +
          (up >= 0 ? '+' : '') + (up * 100).toFixed(0) + '%</td>') + '</tr>';
  });
  h += card(YRS[t] + ' 시나리오 비교', '굵은 행이 Base(초안값)', UNITS.money,
    '<div class="table-wrap"><table class="fm"><tr><th>시나리오</th><th>매출</th>' +
    '<th>영업이익</th><th>OPM</th><th>EBITDA</th><th>적정 시총</th>' +
    '<th>현재가 대비</th></tr>' + rows + '</table></div>');

  // 무엇을 흔들었는지 — 가정을 감추지 않는다
  var diff = '';
  for(var nm2 in SCENARIOS){
    var ov = SCENARIOS[nm2];
    for(var k in ov){
      var d = MODEL[k];
      if(!d || !DEFAULTS_S[k]) continue;
      diff += '<tr><td>' + esc(nm2) + '</td><td>' + esc(d.label || k) + '</td>' +
        '<td>' + esc(fmtNum(DEFAULTS_S[k][t], d.u, d.pct)) + '</td>' +
        '<td>' + esc(fmtNum(ov[k][t], d.u, d.pct)) + '</td></tr>';
    }
  }
  h += card('시나리오별로 흔든 가정', YRS[t] + ' 기준 · Base 대비', '',
    '<div class="table-wrap"><table class="fm"><tr><th>시나리오</th><th>가정변수</th>' +
    '<th>Base</th><th>시나리오</th></tr>' + diff + '</table></div>');
  return h + '</div>';
}

// 피어 비교 — 목표배수의 근거를 화면에 붙인다.
function icPeerCard(){
  if(typeof PEERS !== 'object' || !PEERS || !PEERS.list) return '';
  var self = null, rows = '';
  PEERS.list.forEach(function(p){
    if(p.group === 'self') self = p;
    var ev = p.evEbitda || [], per = p.per || [];
    var f = function(x){ return (x === null || x === undefined) ? '—' : x.toFixed(1) + '배'; };
    rows += '<tr' + (p.group === 'self' ? ' class="hl"' : '') + '>' +
      '<td>' + esc(p.name) + '</td>' +
      '<td>' + esc(p.group === 'self' ? '—' : p.group) + '</td>' +
      '<td>' + esc(fmtMoney(p.mktcap)) + '</td>' +
      '<td>' + f(ev[0]) + '</td><td>' + f(ev[1]) + '</td>' +
      '<td>' + f(per[1]) + '</td>' +
      '<td>' + esc(p.ret1y || '—') + '</td></tr>';
  });
  var note = '<div class="notice">' + esc(PEERS.note || '') +
    ' 기준일 <b>' + esc(PEERS.asOf) + '</b> · ' + esc(PEERS.source || '') + '</div>';
  return note + card('피어 그룹 비교', 'EV/EBITDA는 실적(A)과 당해 컨센서스(E)', UNITS.money,
    '<div class="table-wrap"><table class="fm"><tr><th>종목</th><th>구분</th>' +
    '<th>시가총액</th><th>EV/EBITDA (A)</th><th>EV/EBITDA (E)</th>' +
    '<th>PER (E)</th><th>1년 수익률</th></tr>' + rows + '</table></div>');
}

function renderICVerdict(){"""

# 밸류에이션 뷰에 피어 카드를 끼운다.
OLD_IC2_VAL = """  h += icMemoCard('valuation', '밸류에이션 판단');
  return h + '</div>';
}"""
NEW_IC2_VAL = """  h += icPeerCard();
  h += icMemoCard('valuation', '밸류에이션 판단');
  return h + '</div>';
}"""

OLD_IC2_ICON = """  target:'<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',"""
NEW_IC2_ICON = OLD_IC2_ICON + """
  scenario:'<polygon points="12 2 2 7 12 12 22 7 12 2"/>',"""

# ─────────────────────────────────────────────────────────────
# P1-4  CDN 의존 제거
#
# 외부 스크립트 3종(Chart.js · xlsx-js-style · JSZip)을 CDN에서 받아 썼다.
# 오프라인·사내망에서 로드가 막히면 내보내기 버튼이 조용히 죽는다.
# 투자심사 자료는 그런 환경에서 열리는 일이 잦다.
#
#   Chart.js   로드만 하고 쓰지 않았다. 차트는 자체 SVG 렌더러다. 삭제.
#   xlsx·JSZip 브라우저 내 Excel 생성에만 쓰였다. Excel 정본을
#              tools/build_excel.py로 옮겼으므로(G7이 대사한다) 삭제.
#
# 결과: model.html이 외부 요청 없이 완전히 동작한다.
# ─────────────────────────────────────────────────────────────

# 웹폰트도 외부 요청이다. 없어도 시스템 한글 폰트로 정상 렌더되므로,
# 폴백 스택을 제대로 세우고 @import를 걷어낸다.
OLD_FONT_IMPORT = """@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap');
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
"""

NEW_FONT_IMPORT = """/* 웹폰트를 받아오지 않는다. 설치돼 있으면 쓰고, 없으면 시스템 한글 폰트로
   떨어진다 — 아래 폴백 스택이 그 역할을 한다. */
"""

OLD_BODY_FONT = """body{font-family:'Pretendard',-apple-system,sans-serif;"""
NEW_BODY_FONT = """body{font-family:'Pretendard','Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',-apple-system,system-ui,sans-serif;"""

OLD_CDN = """<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xlsx-js-style@1.2.0/dist/xlsx.bundle.js"></script>
<script src="https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js"></script>
"""

NEW_CDN = """<!-- 외부 스크립트 없음. 이 파일은 네트워크 없이 완전히 동작한다.
     Excel은 tools/build_excel.py가 만든다 (검증 게이트 G7이 셀 단위로 대사). -->
"""

# Excel 버튼은 남기되, 라이브러리가 없으면 무엇을 해야 하는지 알려준다.
OLD_XLSX_BTN = """  document.getElementById('btnXlsx').onclick = function(){ exportToExcel(); };"""

NEW_XLSX_BTN = """  document.getElementById('btnXlsx').onclick = function(){
    // 브라우저 내 생성 경로는 CDN 라이브러리에 의존해 오프라인에서 죽었다.
    // Excel 정본은 파이프라인이 만든다. 여기서는 그 사실을 알려준다.
    if(typeof XLSX === 'undefined'){
      alert('Excel은 모델과 함께 빌드됩니다.\\n\\n' +
            '  python3 tools/build_excel.py <이 파일 경로>\\n\\n' +
            '같은 폴더의 model.xlsx를 여세요. 수식이 그대로 들어 있고, ' +
            '검증 게이트 G7이 이 화면의 값과 셀 단위로 대사합니다.');
      return;
    }
    exportToExcel();
  };"""

# ─────────────────────────────────────────────────────────────
# P1-5  모바일에서 사이드바가 열리지 않던 결함
#
# 폭 1100px 이하에서 사이드바는 transform:translateX(-100%)로 화면 밖에
# 밀려나고, 그것을 되돌릴 유일한 수단인 ☰ 버튼에는 인라인 style="display:none"이
# 박혀 있었다. 그 인라인 스타일을 걷어내는 코드가 어디에도 없다.
# 결과적으로 좁은 화면에서는 사이드바 전체 — 트리와 투자심사 그룹 — 에
# 도달할 방법이 없었다. 뷰는 존재하는데 갈 수가 없는 상태였다.
#
# 고치는 방법: 버튼의 표시 여부를 인라인이 아니라 CSS 미디어쿼리가 정하게 한다.
# 여는 수단이 생겼으니 닫는 수단도 함께 둔다 (스크림 탭 · 항목 선택 시 자동 닫힘).
# ─────────────────────────────────────────────────────────────

OLD_MEDIA = """@media (max-width:1100px){
  .app{grid-template-columns:1fr}
  .sidebar{position:fixed;left:0;top:0;bottom:0;width:272px;transform:translateX(-100%);
    transition:transform .25s}
  .sidebar.open{transform:none}
  .grid.two{grid-template-columns:minmax(0,1fr)}
}"""

NEW_MEDIA = """/* ☰ 는 좁은 화면에서만 의미가 있다. 표시 여부를 인라인 style이 아니라
   여기서 정한다 — 인라인으로 숨기면 미디어쿼리가 되살릴 수 없다. */
#menuBtn{display:none}
#scrim{display:none;position:fixed;inset:0;background:rgba(15,23,42,.38);
  z-index:39;opacity:0;transition:opacity .25s}
#scrim.show{display:block;opacity:1}

@media (max-width:1100px){
  .app{grid-template-columns:1fr}
  .sidebar{position:fixed;left:0;top:0;bottom:0;width:272px;transform:translateX(-100%);
    transition:transform .25s;z-index:40;box-shadow:0 0 32px rgba(15,23,42,.18)}
  .sidebar.open{transform:none}
  .grid.two{grid-template-columns:minmax(0,1fr)}
  #menuBtn{display:inline-flex}
  /* 툴바 버튼이 화면 폭을 넘으면 줄바꿈 대신 가로로 밀어 본다 */
  .topbar{overflow-x:auto;scrollbar-width:none}
  .topbar::-webkit-scrollbar{display:none}
  .crumb{min-width:0}
  #docView{padding:16px 14px 60px}
  /* .notice는 flex라 좁은 폭에서 <b> 조각이 한 글자씩 접힌다.
     좌우 배치가 목적이었으니 좌우가 없으면 그냥 본문처럼 흘려보낸다. */
  .notice{display:block}
  .kpi-row{grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}
}"""

OLD_MENUBTN = '<button class="tb-btn" id="menuBtn" style="display:none" title="\uba54\ub274">\u2630</button>'
NEW_MENUBTN = '<button class="tb-btn" id="menuBtn" title="\uba54\ub274" aria-label="\uba54\ub274" aria-expanded="false">\u2630</button>'

OLD_ASIDE_END = """  </aside>

  <div class="main">"""

NEW_ASIDE_END = """  </aside>
  <div id="scrim"></div>

  <div class="main">"""

OLD_MENU_JS = """  document.getElementById('menuBtn').onclick = function(){ document.getElementById('sidebar').classList.toggle('open'); };"""

NEW_MENU_JS = """  document.getElementById('menuBtn').onclick = function(){ setDrawer(!document.getElementById('sidebar').classList.contains('open')); };
  document.getElementById('scrim').onclick = function(){ setDrawer(false); };
  document.addEventListener('keydown', function(e){ if(e.key === 'Escape') setDrawer(false); });"""

OLD_GO_TAIL = """  buildSidebar();
}"""

NEW_GO_TAIL = """  buildSidebar();
  setDrawer(false);   // \uc881\uc740 \ud654\uba74\uc5d0\uc11c\ub294 \ud56d\ubaa9\uc744 \uace0\ub974\uba74 \uc11c\ub78d\uc774 \ube44\ucf1c\uc57c \ubcf8\ubb38\uc774 \ubcf4\uc778\ub2e4
}

// \uc0ac\uc774\ub4dc\ubc14 \uc11c\ub78d. \ub113\uc740 \ud654\uba74\uc5d0\uc11c\ub294 \uc0ac\uc774\ub4dc\ubc14\uac00 \ud56d\uc0c1 \ubcf4\uc774\ubbc0\ub85c \uc544\ubb34 \uc77c\ub3c4 \ud558\uc9c0 \uc54a\ub294\ub2e4.
function setDrawer(open){
  var sb = document.getElementById('sidebar'), sc = document.getElementById('scrim'),
      mb = document.getElementById('menuBtn');
  if(!sb || !sc) return;
  sb.classList.toggle('open', !!open);
  sc.classList.toggle('show', !!open);
  if(mb) mb.setAttribute('aria-expanded', open ? 'true' : 'false');
}"""


# ─────────────────────────────────────────────────────────────
# IC  투자심사 뷰
#
# 심사 보고서를 별도 문서로 만들지 않는다. 문서로 뽑는 순간 모델과 어긋나고,
# "가정을 바꾸면 목표가가 얼마가 되나"에 답할 수 없게 된다. 엔진에 이미
# 뷰 라우팅이 있으므로 그룹 하나를 더한다 (ic_memo_framework §1).
#
# 데이터는 두 곳에서 온다.
#   MODEL   계산되는 모든 수치 — 슬라이더를 움직이면 즉시 따라 움직인다
#   MEMO    판단·서술 (data.js에 선언). 모델 수치와 섞지 않는다
# 둘 중 하나가 없으면 해당 뷰는 조용히 비지 않고 없다고 말한다.
# ─────────────────────────────────────────────────────────────

OLD_NEG = """  var negs = [];
  Object.keys(MODEL).forEach(function(k){
    for(var t = 0; t < HIST_N; t++){ if(val(k, t) < 0){ negs.push((MODEL[k].label || k) + ' @' + YRS[t]); break; } }
  });"""

NEW_NEG = """  // 음수가 정상인 계정이 있다 — 순차입금(순현금), 영업손실 등.
  // 노드에 allowNegative를 달면 이 검사에서 빠진다.
  var negs = [];
  Object.keys(MODEL).forEach(function(k){
    if(MODEL[k].allowNegative) return;
    for(var t = 0; t < HIST_N; t++){ if(val(k, t) < 0){ negs.push((MODEL[k].label || k) + ' @' + YRS[t]); break; } }
  });"""

OLD_RENDER_VIEW = """function renderView(view){
  if(view === 'summary') return renderSummary();"""

NEW_RENDER_VIEW = """function renderView(view){
  if(view === 'ic_overview') return renderICOverview();
  if(view === 'ic_valuation') return renderICValuation();
  if(view === 'ic_verdict') return renderICVerdict();
  if(view === 'summary') return renderSummary();"""

OLD_VIEW_TITLES = """var VIEW_TITLES = { canvas:'전체 캔버스', summary:'요약 대시보드', assumptions:'가정·근거',"""
NEW_VIEW_TITLES = """var VIEW_TITLES = { canvas:'전체 캔버스', summary:'요약 대시보드', assumptions:'가정·근거',
  ic_overview:'투자 개요', ic_valuation:'밸류에이션', ic_verdict:'심사 결론',"""

# 사이드바에 Investment case 그룹 추가
OLD_SIDEBAR_CTRL = """  html += '<div class="nav-group"><div class="nav-caption">Model control</div>' +"""
NEW_SIDEBAR_CTRL = """  // Investment case — MARKET이 선언된 모델에서만 뜬다.
  if(typeof MARKET === 'object' && MARKET){
    html += '<div class="nav-group"><div class="nav-caption">Investment case</div>' +
      navBtn('ic_overview', 'target', '투자 개요', icUpsideLabel()) +
      navBtn('ic_valuation', 'trending-up', '밸류에이션') +
      navBtn('ic_verdict', 'file-text', '심사 결론') +
      '</div>';
  }

  html += '<div class="nav-group"><div class="nav-caption">Model control</div>' +"""

OLD_IC_ANCHOR = """// ── 가정·근거 페이지 ──"""

NEW_IC_ANCHOR = """// ══ 투자심사 뷰 ═══════════════════════════════════════════════
// 아래 세 뷰의 숫자는 전부 MODEL에서 나온다. 시뮬레이터에서 가정을 바꾸면
// 목표가와 상승여력이 그 자리에서 따라 움직인다.

// 마지막 추정 연도 인덱스
function icLastIdx(){ return YRS.length - 1; }

// 적정가치와 현재 시총의 괴리. 모델 루트가 시가총액일 때만 뜻이 있다.
function icUpside(t){
  if(typeof MARKET !== 'object' || !MARKET || !MARKET.mktcap) return null;
  var fair = val(rootId(), t);
  if(!fair) return null;
  return fair / MARKET.mktcap - 1;
}
function icUpsideLabel(){
  var u = icUpside(icLastIdx());
  return u === null ? '' : (u >= 0 ? '+' : '') + (u * 100).toFixed(0) + '%';
}
// 현재 시총이 함의하는 EV/EBITDA 배수 — 역산.
// "적정가가 얼마인가"보다 "지금 가격이 무엇을 전제하는가"가 심사에서 더 유용하다.
function icImpliedMultiple(t){
  if(typeof MARKET !== 'object' || !MARKET || !MODEL.ebitda) return null;
  var e = val('ebitda', t);
  if(!e) return null;
  var nd = MODEL.net_debt ? val('net_debt', t) : 0;
  return (MARKET.mktcap + nd) / e;
}

// fmtMoney는 축약할 때 이미 단위를 붙인다(예: "10.35조원"). 그 뒤에 UNITS.money를
// 다시 붙이면 "조원억원"이 된다. 축약되지 않았을 때만 단위를 붙인다.
function icMoney(v){
  var s = fmtMoney(v);
  return /[가-힣]$/.test(s) ? s : s + UNITS.money;
}

function icStat(label, value, sub, tone){
  return '<div class="kpi' + (tone ? ' ' + tone : '') + '">' +
    '<div class="k">' + esc(label) + '</div>' +
    '<div class="v">' + esc(value) + '</div>' +
    (sub ? '<div class="s">' + esc(sub) + '</div>' : '') + '</div>';
}

function icMarketNote(){
  if(typeof MARKET !== 'object' || !MARKET) return '';
  return '<div class="notice">시장 관측치 기준일 <b>' + esc(MARKET.asOf) + '</b> · ' +
    esc(MARKET.source || '') + ' — 심사 시점에 반드시 갱신할 것.</div>';
}

function renderICOverview(){
  var t = icLastIdx(), h = '<div class="page">';
  h += '<div class="page-head"><div class="eyebrow caps">' + ic('target', 16) +
    ' Investment case</div><h1>투자 개요</h1></div>';
  if(typeof MARKET !== 'object' || !MARKET){
    return h + '<div class="notice">MARKET 블록이 없어 시장 대비 비교를 할 수 없습니다.</div></div>';
  }
  h += icMarketNote();

  var fair = val(rootId(), t), up = icUpside(t), im = icImpliedMultiple(t);
  var fairPS = MARKET.shares ? fair * 1e8 / MARKET.shares : 0;

  h += '<div class="kpi-row">';
  h += icStat('현재 시가총액', icMoney(MARKET.mktcap),
    MARKET.price.toLocaleString('ko-KR') + '원 × ' + MARKET.shares.toLocaleString('ko-KR') + '주');
  h += icStat(YRS[t] + ' 적정 시가총액', icMoney(fair),
    '주당 ' + Math.round(fairPS).toLocaleString('ko-KR') + '원');
  h += icStat('괴리', (up >= 0 ? '+' : '') + (up * 100).toFixed(0) + '%',
    up >= 0 ? '적정가치가 현재가를 상회' : '현재가가 적정가치를 상회',
    up >= 0 ? 'pos' : 'neg');
  h += icStat('현재가 함의 배수', im ? im.toFixed(1) + '배' : '—',
    YRS[t] + ' EBITDA 기준 EV/EBITDA');
  h += '</div>';

  // 연도별 적정가치 vs 현재 시총
  var rows = '';
  for(var i = HIST_N; i < YRS.length; i++){
    var f2 = val(rootId(), i), u2 = icUpside(i), m2 = icImpliedMultiple(i);
    rows += '<tr><td>' + esc(YRS[i]) + '</td>' +
      '<td>' + esc(fmtV('ebitda', i)) + '</td>' +
      '<td>' + esc(fmtV(rootId(), i)) + '</td>' +
      '<td class="' + (u2 >= 0 ? 'pos' : 'neg') + '">' + (u2 >= 0 ? '+' : '') + (u2 * 100).toFixed(0) + '%</td>' +
      '<td>' + (m2 ? m2.toFixed(1) + '배' : '—') + '</td></tr>';
  }
  h += card('추정 연도별 적정가치', '현재 시가총액 ' + icMoney(MARKET.mktcap) + ' 고정 비교',
    UNITS.money,
    '<div class="table-wrap"><table class="fm"><tr><th>연도</th><th>EBITDA</th>' +
    '<th>적정 시총</th><th>괴리</th><th>현재가 함의 배수</th></tr>' + rows + '</table></div>');

  h += icMemoCard('thesis', '투자 논거');
  return h + '</div>';
}

function renderICValuation(){
  var t = icLastIdx(), h = '<div class="page">';
  h += '<div class="page-head"><div class="eyebrow caps">' + ic('trending-up', 16) +
    ' Investment case</div><h1>밸류에이션</h1></div>';
  if(typeof MARKET !== 'object' || !MARKET || !MODEL.ebitda){
    return h + '<div class="notice">MARKET 또는 ebitda 노드가 없어 밸류에이션을 계산할 수 없습니다.</div></div>';
  }
  h += icMarketNote();

  // 배수 민감도 — 목표배수 × 추정연도
  var muls = [8, 10, 12, 15, 20, 25, 30];
  var head = '<tr><th>목표 EV/EBITDA</th>';
  for(var i = HIST_N; i < YRS.length; i++) head += '<th>' + esc(YRS[i]) + '</th>';
  head += '</tr>';
  var body = '';
  muls.forEach(function(m){
    var cur = MODEL.target_ev_ebitda ? val('target_ev_ebitda', t) : null;
    body += '<tr' + (cur && Math.abs(cur - m) < 0.01 ? ' class="hl"' : '') + '><td>' + m + '배</td>';
    for(var i = HIST_N; i < YRS.length; i++){
      var nd = MODEL.net_debt ? val('net_debt', i) : 0;
      var fair = val('ebitda', i) * m - nd;
      var up = fair / MARKET.mktcap - 1;
      body += '<td class="' + (up >= 0 ? 'pos' : 'neg') + '">' +
        (up >= 0 ? '+' : '') + (up * 100).toFixed(0) + '%</td>';
    }
    body += '</tr>';
  });
  h += card('목표배수 민감도', '칸 값 = 현재 시가총액 대비 괴리. 굵은 행이 현재 가정.', '',
    '<div class="table-wrap"><table class="fm">' + head + body + '</table></div>');

  // 역산 — 현재 가격이 무엇을 전제하는가
  var need = [];
  [8, 12, 15, 20].forEach(function(m){
    var nd = MODEL.net_debt ? val('net_debt', t) : 0;
    var reqE = (MARKET.mktcap + nd) / m;
    var gap = reqE / val('ebitda', t);
    need.push('<tr><td>' + m + '배</td><td>' + esc(icMoney(reqE)) + '</td>' +
      '<td>' + gap.toFixed(2) + '배</td></tr>');
  });
  h += card('역산 — 현재 가격이 전제하는 것',
    '현재 시가총액을 정당화하려면 ' + YRS[t] + '에 필요한 EBITDA', UNITS.money,
    '<div class="table-wrap"><table class="fm"><tr><th>목표배수 가정</th>' +
    '<th>필요 EBITDA</th><th>모델 대비</th></tr>' + need.join('') + '</table></div>');

  h += icMemoCard('valuation', '밸류에이션 판단');
  return h + '</div>';
}

function renderICVerdict(){
  var h = '<div class="page">';
  h += '<div class="page-head"><div class="eyebrow caps">' + ic('file-text', 16) +
    ' Investment case</div><h1>심사 결론</h1></div>';
  h += icMemoCard('verdict', '투자의견');
  h += icMemoCard('bull', '상방 논리');
  h += icMemoCard('bear', '하방 논리');
  h += icMemoCard('risk', '리스크와 모니터링 지표');
  h += '<div class="notice">본 자료는 공시·시장 데이터를 바탕으로 한 내부 검토용 모델이며 ' +
    '투자권유가 아닙니다. 모든 수치는 최신 공시로 재확인하십시오.</div>';
  return h + '</div>';
}

// MEMO는 판단 텍스트다. data.js에 없으면 없다고 말한다 — 조용히 비우지 않는다.
function icMemoCard(key, title){
  var m = (typeof MEMO === 'object' && MEMO) ? MEMO[key] : null;
  if(!m) return card(title, '', '',
    '<div class="notice">MEMO.' + esc(key) + ' 가 data.js에 없습니다.</div>');
  var body = '';
  if(m.lead) body += '<p class="lead">' + esc(m.lead) + '</p>';
  if(m.points && m.points.length){
    body += '<ul class="memo">';
    m.points.forEach(function(x){ body += '<li>' + esc(x) + '</li>'; });
    body += '</ul>';
  }
  return card(title, m.sub || '', '', body);
}

// ── 가정·근거 페이지 ──"""

# 심사 뷰 스타일
OLD_STYLE_ANCHOR = """/* 근거 / 노트 */"""
NEW_STYLE_ANCHOR = """/* 투자심사 뷰 */
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-bottom:18px}
.kpi{background:#FFFFFF;border:1px solid #E5E5E8;border-radius:10px;padding:14px 16px}
.kpi .k{font-size:11px;color:#6B7280;letter-spacing:.04em;margin-bottom:6px}
.kpi .v{font-size:22px;font-weight:700;color:#0F0F12;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.kpi .s{font-size:11px;color:#9CA3AF;margin-top:4px}
.kpi.pos .v{color:#1E7A48}
.kpi.neg .v{color:#DC2626}
td.pos{color:#1E7A48;font-weight:600}
td.neg{color:#DC2626;font-weight:600}
table.fm tr.hl td{background:#EDF3FF;font-weight:700}
p.lead{font-size:14px;color:#374151;line-height:1.7;margin:0 0 10px}
ul.memo{margin:0;padding-left:18px}
ul.memo li{font-size:13px;color:#4B5563;line-height:1.75;margin-bottom:6px}

/* 근거 / 노트 */"""

# target 아이콘 추가 (Feather)
OLD_ICON = """  'file-text':'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/>',"""
NEW_ICON = OLD_ICON + """
  target:'<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  'trending-up':'<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',"""



# ─────────────────────────────────────────────────────────────
# IC-2  시나리오 프리셋
#
# 엔진에 케이스 저장·전환이 이미 있다. Bull/Base/Bear는 새 기능이 아니라
# 프리셋을 미리 올려두는 일이다 (ic_memo_framework §3).
# Base는 초안값 그 자체이므로 케이스로 두지 않는다 — "기본값" 버튼이 곧 Base다.
# ─────────────────────────────────────────────────────────────

OLD_CASES = """let _cases={}; // {name: {sv: deep copy of SV}}"""

NEW_CASES = """let _cases={}; // {name: {sv: deep copy of SV}}

// data.js가 SCENARIOS를 선언하면 케이스로 미리 올린다. 각 시나리오는
// 덮어쓸 입력만 적으면 되고, 나머지는 초안값(Base)을 그대로 쓴다.
// [주관] 노드만 흔드는 것이 규약이다 — [객관]을 흔들면 다른 모델이 된다.
function seedScenarios(){
  if(typeof SCENARIOS !== 'object' || !SCENARIOS) return;
  for(let name in SCENARIOS){
    let snap={};
    for(let k in DEFAULTS_S) snap[k]=DEFAULTS_S[k].slice();
    let ov=SCENARIOS[name];
    for(let k in ov){ if(snap[k] && ov[k].length===YRS.length) snap[k]=ov[k].slice(); }
    _cases[name]=snap;
  }
}
seedScenarios();"""

# ─────────────────────────────────────────────────────────────
# P2  구성비 계산이 합계 트리를 전제하던 문제
#
# 부모값 대비 비중은 부모가 자식의 합일 때만 구성비다. 루트가 뺄셈인 모델
# (영업이익 = 매출 − 비용)에서는 자식 비중이 100%를 넘어 뜻 없는 숫자가 된다.
# 합계 트리가 아니면 자식 절대값 합을 분모로 쓰고 카드 제목도 바꾼다.
# ─────────────────────────────────────────────────────────────

OLD_MIX = """  var mixRows = '';
  var tot = val(r, t);
  kids.forEach(function(k){
    var v = val(k, t), sh = tot ? v / tot : 0;"""

NEW_MIX = """  var mixRows = '';
  // 합계 트리에서만 부모값이 구성비의 분모가 된다. 뺄셈 루트에서는
  // 자식 절대값 합을 쓴다 — 그러지 않으면 비중이 100%를 넘는다.
  var mixIsSum = isSumOfChildren(r);
  var tot = mixIsSum ? val(r, t)
    : kids.reduce(function(s, k){ return s + Math.abs(val(k, t)); }, 0);
  kids.forEach(function(k){
    var v = val(k, t), sh = tot ? v / tot : 0;"""

OLD_MIX_TITLE = """  h += card(YRS[t] + ' 구성비', '', MODEL[r].u || '',"""
NEW_MIX_TITLE = """  h += card(YRS[t] + (mixIsSum ? ' 구성비' : ' 구성 (절대값 기준)'), '', MODEL[r].u || '',"""


OLD_TOGGLE_ALL = """function toggleAll(open){nodeOffsets={};function walk(n){if(canToggle(n)){if(open)openSet.add(n.id);else if(n.id!=='root'&&n.id!=='rev')openSet.delete(n.id)}if(n.children)n.children.forEach(walk)}walk(TREE);if(!open){openSet.add('root');openSet.add('rev')}fitAll()}"""

NEW_TOGGLE_ALL = """function toggleAll(open){
  nodeOffsets={};
  // 접을 때도 루트와 그 직계는 남긴다. 빈 화면이 되지 않게.
  let keep=new Set([TREE.id].concat((TREE.children||[]).map(c=>c.id)));
  function walk(n){
    if(canToggle(n)){
      if(open) openSet.add(n.id);
      else if(!keep.has(n.id)) openSet.delete(n.id);
    }
    if(n.children) n.children.forEach(walk);
  }
  walk(TREE);
  if(!open) keep.forEach(id=>openSet.add(id));
  fitAll();
}"""

OLD_OPENSET = """let openSet=new Set(['root'].concat(Object.keys(MODEL).filter(k=>MODEL[k].parent==='root')));"""
NEW_OPENSET = """// 처음엔 루트와 그 직계만 펼친다. 루트 id는 MODEL에서 찾는다(하드코딩 금지).
let openSet=(function(){
  let root=Object.keys(MODEL).find(k=>MODEL[k].parent==null)||Object.keys(MODEL)[0];
  return new Set([root].concat(Object.keys(MODEL).filter(k=>MODEL[k].parent===root)));
})();"""


# ─────────────────────────────────────────────────────────────
# DATA  데이터 블록을 주입 마커로 교체
#
# 종목별로 바뀌는 것은 시간축·단위·노드 정의뿐이다. 그 구간을 마커로 감싸
# build_model.py가 갈아끼울 수 있게 한다. 템플릿 자체에는 최소 예제를 넣어
# 파일 하나만 열어도 스키마를 읽을 수 있게 둔다.
# ─────────────────────────────────────────────────────────────

PLACEHOLDER = """// 아래는 스키마를 보여주기 위한 최소 예제다.
// 실제 모델은 companies/<종목>/data.js를 build_model.py로 주입해 만든다.

// META — 종목 정체성. modelId는 localStorage 저장키의 원천이라
// 종목마다 반드시 달라야 한다. 같으면 서로의 편집 상태를 덮어쓴다.
const META={
  modelId:'example_model',
  title:'예제 추정 모델',
  brand:'Example Model',
  logo:'E',
};

// YRS — 시간축. 실적 연도를 앞에, 추정 연도를 뒤에 둔다.
// 모든 MODEL[k].v의 길이가 YRS.length와 같아야 한다.
const YRS=['2022','2023','2024','2025','2026','2027'];
const HIST_N=4;            // 실적(확정) 연도 수. 이후는 추정(Forecast).
const _isFc=i=>i>=HIST_N;  // i번째 연도가 추정이면 true

// UNITS — 표기 규약. 통화 단위를 바꾸려면 여기만 고친다.
//   money        통화 노드의 단위 문자열. MODEL[k].u가 이 값과 같으면 통화로 본다.
//   moneyAbbrev  큰 값 축약 규칙. min 이상이면 div로 나누고 suffix를 붙인다(내림차순).
//   scope        사이드바 각주에 쓸 모델 범위 한 줄.
const UNITS={
  money:'억원',
  moneyAbbrev:[{min:10000, div:10000, suffix:'조원', digits:2}],
  scope:'예제 모델',
  excelMoneyFormat:'_-* #,##0_-;-* #,##0_-;_-* "-"_-;_-@_-',
  excelOneDecimal:['GWh','천대','백만대','만개','억개'],
  excelTwoDecimal:['/개','/대','/kg','배럴','톤'],
};

// MODEL — 노드 단일 저장소. 트리 구조와 수식 그래프를 함께 담는다.
//   label   표시명                    parent  부모 노드 id (root만 null)
//   type    'input' | 'computed'      formula computed 노드의 수식 문자열
//   v       길이 YRS.length 값 배열    u       단위 문자열
//   desc    추정 근거 — [객관]/[주관]/[외생] 태그로 시작한다
//   c       차트 색      pct 1이면 비율로 표기
//   bg/fg/sfg/bdr  트리 노드 스타일 (computed만)
//
// 수식 문법: + - * / ( )  ==  !=  <  >  <=  >=
//            SUM(a,b,..)  MIN  MAX  AVG  IF(c,t,e)  PREV(x)
// PREV(x)는 직전 연도의 x를 읽는다. 자기 자신을 참조해도 된다 —
//   installed: {formula:'PREV(installed) + additions'} 같은 누적이 성립한다.
const MODEL={
  root: {
    label:'영업이익', sub:'매출 − 비용',
    parent:null, type:'computed', formula:'revenue - cost',
    v:[0,0,0,0,0,0], u:'억원',
    desc:'예제 루트 노드.',
    bg:'#1E2185', fg:'#FFFFFF', sfg:'#A1B8FF',
  },
  revenue: {
    label:'매출', sub:'물량 × 단가',
    parent:'root', type:'computed', formula:'qty * price',
    v:[0,0,0,0,0,0], u:'억원', c:'#3332D0',
    desc:'예제 계산 노드. Q×P 분해.',
    bg:'#3332D0', fg:'#FFFFFF', sfg:'#C5D5FF',
  },
  qty: {
    label:'물량',
    parent:'revenue', type:'input',
    v:[100,110,120,130,140,150], u:'만개', c:'#5D68F7',
    desc:'[주관] 예제 입력 노드. 실적 4개년 + 추정 2개년.',
  },
  price: {
    label:'단가',
    parent:'revenue', type:'input',
    v:[10,10.5,11,11.2,11.5,11.8], u:'억원/만개', c:'#7C91FD',
    desc:'[객관] 예제 입력 노드.',
  },
  cost: {
    label:'비용',
    parent:'root', type:'input',
    v:[700,780,850,900,960,1020], u:'억원', c:'#9C4A1B',
    desc:'[주관] 예제 입력 노드. 실제 모델에서는 원가 트리로 분해한다.',
  },
};"""


def _cut_data_region(text: str) -> str:
    """YRS 선언 앞 주석부터 MODEL 리터럴 끝까지를 마커+예제로 교체한다."""
    from extract_engine import _scan_assignment

    start = text.index("// YRS — 시간축")
    model_at = text.index("const MODEL={", start)
    end = _scan_assignment(text, model_at)
    return (
        text[:start]
        + DATA_START
        + "\n"
        + PLACEHOLDER
        + "\n"
        + DATA_END
        + text[end:]
    )


def main() -> None:
    with open(SRC, encoding="utf-8") as fh:
        p = Patcher(fh.read())

    p.sub("P0-1 extractDeps/evalAstAt", OLD_EXTRACT_DEPS, NEW_EXTRACT_DEPS)
    p.sub("P0-1 topoSort hard deps", OLD_TOPO_DEPS, NEW_TOPO_DEPS)
    p.sub("P0-1 simCalc 연도축 평가", OLD_SIMCALC, NEW_SIMCALC)
    p.sub("P0-1 clearFormulaCache", OLD_CLEAR_CACHE, NEW_CLEAR_CACHE)
    p.sub("P0-1 graphDeps lagged", OLD_GRAPH_DEPS, NEW_GRAPH_DEPS)
    p.sub("P0-2 DEFAULTS_S 주석", OLD_DEFAULTS_HEAD, NEW_DEFAULTS_HEAD)
    # 리터럴 본체는 이름으로 찾아 통째로 걷어낸다.
    from extract_engine import _scan_assignment

    at = p.text.index("const DEFAULTS_S={")
    p.text = p.text[:at] + DEFAULTS_DERIVED + p.text[_scan_assignment(p.text, at):]
    p.applied.append("P0-2 DEFAULTS_S 리터럴 제거")
    p.sub("P1-1 fmtNum/fmtMoney", OLD_FMT, NEW_FMT)
    p.sub("P1-1 bridge bfmt", OLD_BRIDGE_FMT, NEW_BRIDGE_FMT)
    p.sub("P1-1 assumptions bfmt 제거", OLD_ASSUM_FMT, NEW_ASSUM_FMT)
    p.sub("P1-1 excel 숫자서식", OLD_EXCEL_FMT, NEW_EXCEL_FMT)
    p.sub("P1-1 footSub 마크업", OLD_FOOTSUB, NEW_FOOTSUB)
    p.sub("P1-4 웹폰트 @import 제거", OLD_FONT_IMPORT, NEW_FONT_IMPORT)
    p.sub("P1-4 본문 폰트 폴백", OLD_BODY_FONT, NEW_BODY_FONT)
    p.sub("P1-4 CDN 스크립트 제거", OLD_CDN, NEW_CDN)
    p.sub("P1-4 Excel 버튼 안내", OLD_XLSX_BTN, NEW_XLSX_BTN)
    p.sub("P1-5 모바일 미디어쿼리", OLD_MEDIA, NEW_MEDIA)
    p.sub("P1-5 ☰ 인라인 숨김 제거", OLD_MENUBTN, NEW_MENUBTN)
    p.sub("P1-5 스크림 엘리먼트", OLD_ASIDE_END, NEW_ASIDE_END)
    p.sub("P1-5 서랍 열고 닫기", OLD_MENU_JS, NEW_MENU_JS)
    p.sub("P1-5 항목 선택 시 닫기", OLD_GO_TAIL, NEW_GO_TAIL)
    p.sub("IC-2 시나리오 프리셋", OLD_CASES, NEW_CASES)
    p.sub("IC 음수 허용 플래그", OLD_NEG, NEW_NEG)
    p.sub("IC 뷰 라우팅", OLD_RENDER_VIEW, NEW_RENDER_VIEW)
    p.sub("IC 뷰 제목", OLD_VIEW_TITLES, NEW_VIEW_TITLES)
    p.sub("IC 사이드바 그룹", OLD_SIDEBAR_CTRL, NEW_SIDEBAR_CTRL)
    p.sub("IC 뷰 구현", OLD_IC_ANCHOR, NEW_IC_ANCHOR)
    p.sub("IC 스타일", OLD_STYLE_ANCHOR, NEW_STYLE_ANCHOR)
    p.sub("IC 아이콘", OLD_ICON, NEW_ICON)
    p.sub("IC-3 시나리오 라우팅", OLD_IC2_ROUTE, NEW_IC2_ROUTE)
    p.sub("IC-3 뷰 제목", OLD_IC2_TITLES, NEW_IC2_TITLES)
    p.sub("IC-3 사이드바", OLD_IC2_NAV, NEW_IC2_NAV)
    p.sub("IC-3 시나리오·피어 구현", OLD_IC2_ANCHOR, NEW_IC2_ANCHOR)
    p.sub("IC-3 밸류에이션에 피어 카드", OLD_IC2_VAL, NEW_IC2_VAL)
    p.sub("P2 구성비 분모", OLD_MIX, NEW_MIX)
    p.sub("P2 구성비 제목", OLD_MIX_TITLE, NEW_MIX_TITLE)
    p.sub("P1-2 toggleAll", OLD_TOGGLE_ALL, NEW_TOGGLE_ALL)
    p.sub("P1-2 openSet 초기화", OLD_OPENSET, NEW_OPENSET)
    p.sub("P1-3 html 태그", OLD_HTML_TAG, NEW_HTML_TAG)
    p.sub("P1-3 title", OLD_TITLE, NEW_TITLE)
    p.sub("P1-3 브랜드 마크업", OLD_BRAND, NEW_BRAND)
    p.sub("P1-3 footTitle 마크업", OLD_FOOTTITLE, NEW_FOOTTITLE)
    p.sub("P1-3 저장키 META.modelId", OLD_MODEL_ID, NEW_MODEL_ID)
    p.sub("P1-3 브릿지 제목", OLD_BRIDGE_TITLE, NEW_BRIDGE_TITLE)
    p.sub("P1-3 renderIdentity", OLD_INITSHELL, NEW_INITSHELL)

    p.text = _cut_data_region(p.text)
    p.applied.append("DATA 데이터 블록 → 주입 마커")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(p.text)

    print(f"{OUT} 생성 — 패치 {len(p.applied)}건")
    for name in p.applied:
        print("  ✓", name)


if __name__ == "__main__":
    sys.exit(main())
