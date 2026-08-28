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

NEW_FMT = """// UNITS의 선택 필드는 쓰는 자리마다 기본값을 세운다.
// 초기화 블록 하나로 몰면 그 블록이 이름 없는 구문이라 하네스가 떼어가지 못하고,
// 브라우저에서는 되는데 Excel 빌드(G7)에서만 죽는 상태가 된다.
// 두 번째 종목 KT&G를 태우다 실제로 그 자리에서 걸렸다 — 엔진이 종목 데이터의
// 선택 필드에 의존하고 있었다는 뜻이다.
function _uList(x){ return Array.isArray(x) ? x : []; }

// 통화 노드인가? UNITS.money와 정확히 같은 단위만 축약 대상으로 본다.
function isMoney(u){ return !!u && u===UNITS.money; }
// 큰 통화값 축약. UNITS.moneyAbbrev가 비어 있으면 그냥 fmtSmart로 떨어진다.
function fmtMoney(v){
  if(typeof v!=='number'||!isFinite(v)) return '-';
  let a=Math.abs(v), s=v<0?'-':'';
  let _ab=_uList(UNITS.moneyAbbrev);
  for(let i=0;i<_ab.length;i++){
    let r=_ab[i];
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

NEW_EXCEL_FMT = """  if(isMoney(u))return UNITS.excelMoneyFormat || '_-* #,##0_-;-* #,##0_-;_-* "-"_-;_-@_-';
  if(_uList(UNITS.excelOneDecimal).some(t=>u.includes(t)))return '_-* #,##0.0_-;-* #,##0.0_-;_-* "-"_-;_-@_-';
  if(_uList(UNITS.excelTwoDecimal).some(t=>u.includes(t)))return '_-* #,##0.00_-;-* #,##0.00_-;_-* "-"_-;_-@_-';"""

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
    return h + '<div class="notice">SCENARIOS 미선언 — data.js에 시나리오 프리셋을 둘 것.</div></div>';
  }
  h += '<div class="notice">Base = 초안값 그 자체 · 시뮬레이터 케이스 바에서 전환 시 모델에 적용. ' +
    '시나리오는 <b>[주관] 노드만</b> 변경 — 공시 확정 실적은 전 케이스 동일.</div>';

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
  var self = null, rows = '', lastMkt = null;
  // 시장이 섞여 있으면 구분 행을 넣는다. 환율 없이 비교하려면 배수만 봐야 하고,
  // 시가총액 열은 통화가 달라 나란히 두면 오독을 만든다.
  var multiMkt = PEERS.list.some(function(x){ return x.market && x.market !== PEERS.list[0].market; });
  PEERS.list.forEach(function(p){
    if(p.group === 'self') self = p;
    if(multiMkt && p.market !== lastMkt){
      lastMkt = p.market;
      rows += '<tr class="total"><td colspan="7" style="text-align:left">' +
        esc(p.market || '기타') + '</td></tr>';
    }
    var ev = p.evEbitda || [], per = p.per || [];
    var f = function(x){ return (x === null || x === undefined) ? '—' : x.toFixed(1) + '배'; };
    rows += '<tr' + (p.group === 'self' ? ' class="hl"' : '') + '>' +
      '<td>' + esc(p.name) + '</td>' +
      '<td>' + esc(p.group === 'self' ? '—' : p.group) + '</td>' +
      // 해외 피어는 현지 통화라 원화 축약에 태울 수 없다. 문자열 그대로 보여준다.
      '<td>' + esc(p.mktcap == null ? (p.cap || '—') : fmtMoney(p.mktcap)) + '</td>' +
      '<td>' + f(ev[0]) + '</td><td>' + f(ev[1]) + '</td>' +
      '<td>' + f(per[1]) + '</td>' +
      '<td>' + esc(p.ret1y || '—') + '</td></tr>';
  });
  var note = '<div class="notice">' + esc(PEERS.note || '') +
    ' 기준일 <b>' + esc(PEERS.asOf) + '</b> · ' + esc(PEERS.source || '') + '</div>';
  if(PEERS.missing) note += '<div class="notice">' + esc(PEERS.missing) + '</div>';
  return note + card('피어 그룹 비교', 'EV/EBITDA는 실적(A)과 당해 컨센서스(E)', UNITS.money,
    '<div class="table-wrap"><table class="fm"><tr><th style="text-align:left">종목</th><th>구분</th>' +
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
    esc(MARKET.source || '') + ' — <b>심사 시점에 반드시 갱신</b>.</div>';
}

function renderICOverview(){
  var t = icLastIdx(), h = '<div class="page">';
  h += '<div class="page-head"><div class="eyebrow caps">' + ic('target', 16) +
    ' Investment case</div><h1>투자 개요</h1></div>';
  if(typeof MARKET !== 'object' || !MARKET){
    return h + '<div class="notice">MARKET 미선언 — 시장 대비 비교 불가.</div></div>';
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
  if(im !== null) h += icStat('현재가 함의 배수', im.toFixed(1) + '배',
    YRS[t] + ' EBITDA 기준 EV/EBITDA');
  else if(MODEL.wacc) h += icStat('할인율 (WACC)', (val('wacc', t) * 100).toFixed(1) + '%',
    MODEL.tv_growth ? '영구성장 ' + (val('tv_growth', t) * 100).toFixed(1) + '%' : '');
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
  if(typeof MARKET !== 'object' || !MARKET){
    return h + '<div class="notice">MARKET 미선언 — 시장 대비 비교 불가.</div></div>';
  }
  h += icMarketNote();

  // 배수 민감도는 EBITDA 배수법 모델에서만 뜻이 있다. DCF 모델(ebitda 노드가 없는
  // 트리)에서는 이 카드를 건너뛰고 피어·컨센서스·판단만 보여준다.
  // 두 번째 종목 KT&G를 태우다 이 화면이 통째로 비는 것을 발견했다.
  if(MODEL.ebitda){
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
  }

  // DCF 모델에서는 루트 자체를 연도별로 펼쳐 보여준다.
  if(!MODEL.ebitda){
    var dcf = '';
    for(var k2 = HIST_N; k2 < YRS.length; k2++){
      var f3 = val(rootId(), k2), u4 = f3 / MARKET.mktcap - 1;
      dcf += '<tr' + (k2 === t ? ' class="hl"' : '') + '><td>' + esc(YRS[k2]) + '</td>' +
        '<td>' + esc(fmtV(rootId(), k2)) + '</td>' +
        '<td>' + (MARKET.shares
          ? Math.round(f3 * 1e8 / MARKET.shares).toLocaleString('ko-KR') + '원' : '—') + '</td>' +
        '<td class="' + (u4 >= 0 ? 'pos' : 'neg') + '">' +
          (u4 >= 0 ? '+' : '') + (u4 * 100).toFixed(0) + '%</td></tr>';
    }
    h += card('추정기간별 적정가치', '추정기간이 그 해에 끝난다고 볼 때의 값', UNITS.money,
      '<div class="table-wrap"><table class="fm"><tr><th style="text-align:left">기준 연도</th>' +
      '<th>적정 시가총액</th><th>주당</th><th>현재가 대비</th></tr>' + dcf + '</table></div>');
  }

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
  h += '<div class="notice">본 자료는 공시·시장 데이터 기반의 내부 검토용 모델이며 ' +
    '투자권유가 아님. 모든 수치는 최신 공시로 재확인 요망.</div>';
  return h + '</div>';
}

// MEMO는 판단 텍스트다. data.js에 없으면 없다고 말한다 — 조용히 비우지 않는다.
function icMemoCard(key, title){
  var m = (typeof MEMO === 'object' && MEMO) ? MEMO[key] : null;
  if(!m) return card(title, '', '',
    '<div class="notice">MEMO.' + esc(key) + ' 미선언.</div>');
  return card(title, m.sub || '', '', icPoints(m));
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
/* 본문은 문단이 아니라 항목이다. 층을 기호로 구분한다. */
ul.memo,ul.idea-ul{list-style:none;padding-left:0;margin:0}
ul.memo > li{font-size:12.5px;color:#4B5563;line-height:1.7;margin-bottom:9px;
  padding-left:15px;position:relative}
ul.memo > li:before{content:'▪';position:absolute;left:0;top:-1px;color:#5D68F7;font-size:10px}
ul.memo > li > b,ul.idea-ul > li > b{color:#0F0F12;font-weight:700}
ul.memo ul.sub,ul.idea-ul ul.sub{list-style:none;padding-left:0;margin:5px 0 0}
ul.memo ul.sub > li{font-size:12px;color:#6B7280;line-height:1.65;margin-bottom:3px;
  padding-left:13px;position:relative}
ul.memo ul.sub > li:before{content:'–';position:absolute;left:0;color:#9CA3AF}

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
# IC-4  정성 레이어와 애널리스트 리포트 뷰
#
# 지금까지의 심사 뷰는 "가정을 바꾸면 값이 어떻게 되는가"에 답한다.
# 심사에서 그다음에 오는 질문은 정성적이다 — 무엇을 사는 것인가, 무엇이
# 맞아야 하는가, 틀렸다는 것을 어떻게 알 것인가.
#
#   ic_ideas    투자 아이디어. 아이디어마다 논거·촉매·확인지표·리스크,
#               그리고 **반증 조건**을 함께 적는다. 반증 조건이 없는 아이디어는
#               심사에서 검증할 수 없다 (ic_memo_framework §2).
#   ic_report   위 모든 것을 한 장짜리 리포트로 조판한다. 숫자는 전부 MODEL에서
#               다시 읽으므로 본문과 모델이 어긋날 수 없다. 인쇄·PDF를 전제로
#               @media print 규칙을 함께 둔다.
#
# 문서를 따로 만들지 않는 원칙은 그대로다. 리포트는 산출물이 아니라 뷰다.
# ─────────────────────────────────────────────────────────────

OLD_IC4_ICON = """  'trending-up':'<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',"""
NEW_IC4_ICON = OLD_IC4_ICON + """
  zap:'<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  'book-open':'<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',"""

OLD_IC4_ROUTE = """  if(view === 'ic_scenario') return renderICScenario();"""
NEW_IC4_ROUTE = """  if(view === 'ic_scenario') return renderICScenario();
  if(view === 'ic_ideas') return renderICIdeas();
  if(view === 'ic_report') return renderICReport();"""

OLD_IC4_TITLES = """  ic_scenario:'시나리오', ic_verdict:'심사 결론',"""
NEW_IC4_TITLES = """  ic_scenario:'시나리오', ic_ideas:'투자 아이디어',
  ic_verdict:'심사 결론', ic_report:'심사 리포트',"""

OLD_IC4_NAV = """      navBtn('ic_verdict', 'file-text', '심사 결론') +"""
NEW_IC4_NAV = """      navBtn('ic_ideas', 'zap', '투자 아이디어',
             (typeof MEMO === 'object' && MEMO && MEMO.ideas)
               ? String(MEMO.ideas.length) : '') +
      navBtn('ic_verdict', 'file-text', '심사 결론') +
      navBtn('ic_report', 'book-open', '심사 리포트') +"""

OLD_IC4_ANCHOR = """function renderICVerdict(){"""

NEW_IC4_ANCHOR = """// ── 투자 아이디어 ─────────────────────────────────────────────
// 아이디어는 문장 하나가 아니라 구조다. 논거·촉매·확인지표·리스크가 붙어야
// 분기마다 "이 아이디어가 아직 살아 있는가"를 물을 수 있다. 그리고 반증 조건 —
// 무엇을 보면 틀렸다고 인정할지 — 을 미리 적어두지 않으면 사후에 합리화된다.
function icIdeaCard(d, i){
  var tags = '';
  if(d.horizon)    tags += '<span class="tag">투자기간 ' + esc(d.horizon) + '</span>';
  if(d.conviction) tags += '<span class="tag hi">확신도 ' + esc(d.conviction) + '</span>';
  if(d.tag)        tags += '<span class="tag">' + esc(d.tag) + '</span>';

  var box = function(title, arr){
    if(!arr || !arr.length) return '';
    return '<div class="idea-box"><div class="h">' + esc(title) + '</div>' +
      icList(arr, 'idea-ul') + '</div>';
  };

  var body = '';
  // 최신 확정 분기가 이 아이디어에 무엇을 말하는지. 논거보다 먼저 읽혀야 한다 —
  // 심사에서 묻는 것은 "그때 무슨 생각을 했나"가 아니라 "지금 어떻게 되고 있나"다.
  if(d.update) body += '<div class="idea-upd"><b>진행</b> — ' + esc(icText(d.update)) + '</div>';
  if(d.thesis) body += icList(d.thesis, 'memo');
  var grid = box('촉매', d.catalysts) + box('확인 지표', d.kpis) + box('리스크', d.risks);
  if(grid) body += '<div class="idea-grid">' + grid + '</div>';
  if(d.falsify) body += '<div class="falsify"><b>반증 조건</b> — ' + esc(icText(d.falsify)) + '</div>';

  return '<div class="idea"><div class="idea-head">' +
    '<div class="idea-n">' + (i + 1) + '</div>' +
    '<div style="min-width:0"><p class="idea-title">' + esc(d.title || '(제목 없음)') + '</p>' +
    (tags ? '<div class="idea-tags">' + tags + '</div>' : '') + '</div></div>' +
    '<div class="idea-body">' + body + '</div></div>';
}

function icIdeasBlock(){
  var list = (typeof MEMO === 'object' && MEMO) ? MEMO.ideas : null;
  if(!list || !list.length){
    return '<div class="notice">MEMO.ideas 미선언 — 아이디어마다 ' +
      'title · thesis · catalysts · kpis · risks · falsify 필요.</div>';
  }
  var h = '';
  list.forEach(function(d, i){ h += icIdeaCard(d, i); });
  return h;
}

function renderICIdeas(){
  var h = '<div class="page">';
  h += '<div class="page-head"><div class="eyebrow caps">' + ic('zap', 16) +
    ' Investment case</div><h1>투자 아이디어</h1></div>';
  h += '<div class="notice">아이디어마다 <b>반증 조건</b> 병기 — ' +
    '무엇을 보면 틀렸다고 인정할지 사전에 정하지 않으면 사후 합리화로 귀결.</div>';
  h += icMemoCard('company', '사업 구조와 경쟁 포지션');
  h += icIdeasBlock();
  h += icDebateCard();
  return h + '</div>';
}

// 심사 쟁점 — 한 질문에 찬반을 나란히 둔다. 한쪽만 적으면 그건 논거가 아니라 주장이다.
function icDebateCard(){
  var d = (typeof MEMO === 'object' && MEMO) ? MEMO.debate : null;
  if(!d || !d.length) return '';
  var rows = '';
  d.forEach(function(x){
    rows += '<tr><td style="white-space:normal;min-width:150px">' + esc(x.q) + '</td>' +
      '<td style="white-space:normal">' + esc(x.yes || '') + '</td>' +
      '<td style="white-space:normal">' + esc(x.no || '') + '</td></tr>';
  });
  return card('심사 쟁점', '한 질문에 양쪽을 함께 적는다', '',
    '<div class="table-wrap"><table class="fm"><tr><th style="text-align:left">쟁점</th>' +
    '<th style="text-align:left">그렇다</th><th style="text-align:left">아니다</th></tr>' +
    rows + '</table></div>');
}

// ── 애널리스트 리포트 뷰 ──────────────────────────────────────
// 한 장으로 읽히는 조판. 숫자는 전부 MODEL에서 그 자리에서 다시 읽는다 —
// 본문에 숫자를 손으로 적지 않는 것이 이 뷰의 유일한 규칙이다.
function icYearHead(first){
  var h = '<tr><th style="text-align:left">' + esc(first || '항목') + '</th>';
  for(var i = 0; i < YRS.length; i++){
    h += '<th>' + esc(YRS[i]) + (i < HIST_N ? '' : 'E') + '</th>';
  }
  return h + '</tr>';
}
function icNodeRow(id, label, cls){
  if(!MODEL[id]) return '';
  var r = '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td>' +
    esc(label || MODEL[id].label || id) + '</td>';
  for(var i = 0; i < YRS.length; i++) r += '<td>' + esc(fmtV(id, i)) + '</td>';
  return r + '</tr>';
}
function icCalcRow(label, fn, cls){
  var r = '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td>' + esc(label) + '</td>';
  for(var i = 0; i < YRS.length; i++){
    var v = fn(i);
    r += '<td>' + (v === null ? '—' : esc(v)) + '</td>';
  }
  return r + '</tr>';
}
function icPct(x){ return (x === null || !isFinite(x)) ? null : (x * 100).toFixed(1) + '%'; }
function icYoY(id){
  return function(i){
    if(i === 0 || !MODEL[id]) return null;
    var a = val(id, i - 1);
    return a ? icPct(val(id, i) / a - 1) : null;
  };
}

function icSec(n, title, desc, body){
  return '<section class="rp-sec"><div class="rp-num">' + esc(n) + '</div>' +
    '<h2>' + esc(title) + '</h2>' +
    (desc ? '<p class="desc">' + esc(desc) + '</p>' : '') + body + '</section>';
}
function icMemoBody(key){
  var m = (typeof MEMO === 'object' && MEMO) ? MEMO[key] : null;
  if(!m) return '<div class="notice">MEMO.' + esc(key) + ' 없음</div>';
  return icPoints(m);
}

function renderICReport(){
  var t = icLastIdx();
  var mk = (typeof MARKET === 'object' && MARKET) ? MARKET : null;
  var nm = (typeof META === 'object' && META) ? META : {};
  var h = '<div class="page rp">';

  // 표지
  var up = icUpside(t), fair = val(rootId(), t);
  var fairPS = (mk && mk.shares) ? Math.round(fair * 1e8 / mk.shares) : 0;
  h += '<div class="rp-cover">' +
    '<div style="display:flex;align-items:flex-start;gap:12px">' +
    '<div style="min-width:0"><div class="co">' + esc(nm.brand || nm.title || '투자심사 리포트') + '</div>' +
    '<div class="sub">' + [
      mk ? '시장 관측 기준일 ' + mk.asOf : '',
      '단위 ' + UNITS.money,
      '실적 ' + YRS[0] + '~' + YRS[HIST_N - 1] + ' · 추정 ' + YRS[HIST_N] + '~' + YRS[t],
    ].filter(Boolean).map(esc).join(' · ') + '</div></div>' +
    '<button class="tb-btn rp-print" style="margin-left:auto" onclick="window.print()">인쇄 / PDF</button>' +
    '</div>';
  if(mk){
    h += '<div class="kpi-row" style="margin-top:16px;margin-bottom:0">';
    h += icStat('현재 시가총액', icMoney(mk.mktcap), mk.price.toLocaleString('ko-KR') + '원');
    h += icStat(YRS[t] + ' 적정 시가총액', icMoney(fair),
      fairPS ? '주당 ' + fairPS.toLocaleString('ko-KR') + '원' : '');
    h += icStat('괴리', (up >= 0 ? '+' : '') + (up * 100).toFixed(0) + '%',
      MODEL.target_ev_ebitda ? '목표배수 ' + val('target_ev_ebitda', t).toFixed(0) + '배'
        : (MODEL.wacc ? 'WACC ' + (val('wacc', t) * 100).toFixed(1) + '%' : ''),
      up >= 0 ? 'pos' : 'neg');
    // 배수법 모델에서는 현재가가 함의하는 배수를, DCF 모델에서는 할인율을 보여준다.
    // 없는 개념 자리에 '—'를 띄우면 화면이 고장난 것처럼 읽힌다.
    var im = icImpliedMultiple(t);
    if(im !== null) h += icStat('현재가 함의 배수', im.toFixed(1) + '배', YRS[t] + ' EBITDA 기준');
    else if(MODEL.wacc) h += icStat('할인율 (WACC)', (val('wacc', t) * 100).toFixed(1) + '%',
      MODEL.tv_growth ? '영구성장 ' + (val('tv_growth', t) * 100).toFixed(1) + '%' : '');
    h += '</div>';
  }
  h += '</div>';

  // 1. 요약
  h += icSec('01', '투자 논거 요약', (MEMO && MEMO.thesis) ? MEMO.thesis.sub : '',
    '<div class="card pad">' + icMemoBody('thesis') + '</div>');

  // 2. 사업 구조
  if(typeof MEMO === 'object' && MEMO && MEMO.company){
    h += icSec('02', '사업 구조와 경쟁 포지션', MEMO.company.sub || '',
      '<div class="card pad">' + icMemoBody('company') + '</div>');
  }

  // 3. 실적과 추정
  var rev = MODEL.total_revenue ? 'total_revenue' : rootId();
  var body = icNodeRow(rev, null, 'total') +
    icCalcRow('YoY', icYoY(rev)) +
    icNodeRow('op_profit') +
    icCalcRow('영업이익률', function(i){
      var r = val(rev, i);
      return r ? icPct(val('op_profit', i) / r) : null;
    }) +
    icNodeRow('dep_total') + icNodeRow('ebitda') +
    icCalcRow('EBITDA 마진', function(i){
      var r = val(rev, i);
      return r ? icPct(val('ebitda', i) / r) : null;
    });
  h += icSec('03', '실적과 추정', '실적 ' + YRS[0] + '~' + YRS[HIST_N - 1] +
    '은 공시 확정값 · 이후는 모델 추정 (게이트 G1이 매 빌드마다 대사)',
    card('', '', UNITS.money,
      '<div class="table-wrap"><table class="fm">' + icYearHead() + body + '</table></div>'));

  // 4. 부문별
  if(MODEL.total_revenue){
    // 부문 아래 자식은 대부분 가정변수(성장률·실적 오버라이드)라 리포트에 넣으면
    // 0.0% 행만 늘어난다. 금액 단위의 계산 노드만 편다.
    var moneyKids = function(id){
      return childrenOf(id).filter(function(c){
        return MODEL[c].type !== 'input' && isMoney(MODEL[c].u);
      });
    };
    var seg = childrenOf('total_revenue'), srows = '';
    seg.forEach(function(sid){
      srows += icNodeRow(sid, null, 'total');
      srows += icCalcRow('  YoY', icYoY(sid));
      moneyKids(sid).forEach(function(c){ srows += icNodeRow(c, '  ' + (MODEL[c].label || c)); });
    });
    // 비용은 별도 트리에 있다. 부문 매출만 보여주면 마진 이야기를 할 수 없다.
    if(MODEL.total_cost){
      srows += icNodeRow('total_cost', null, 'total');
      moneyKids('total_cost').forEach(function(c){
        srows += icNodeRow(c, '  ' + (MODEL[c].label || c));
        moneyKids(c).forEach(function(g){
          srows += icNodeRow(g, '    ' + (MODEL[g].label || g));
        });
      });
    }
    if(srows){
      h += icSec('04', '부문별 전개', '매출과 그 아래 원가 구성. 부문 합계는 연결 수치와 오차 0으로 일치한다.',
        card('', '', UNITS.money,
          '<div class="table-wrap"><table class="fm">' + icYearHead('부문') + srows + '</table></div>'));
    }
  }

  // 5. 투자 아이디어
  h += icSec('05', '투자 아이디어', '아이디어마다 반증 조건을 함께 둔다', icIdeasBlock());

  // 6. 밸류에이션
  var vb = '';
  if(mk && MODEL.ebitda){
    var muls = [8, 10, 12, 15, 20, 25, 30], hh = '<tr><th style="text-align:left">목표 EV/EBITDA</th>';
    for(var i2 = HIST_N; i2 < YRS.length; i2++) hh += '<th>' + esc(YRS[i2]) + '</th>';
    hh += '</tr>';
    var bb = '';
    muls.forEach(function(m){
      var cur = MODEL.target_ev_ebitda ? val('target_ev_ebitda', t) : null;
      bb += '<tr' + (cur && Math.abs(cur - m) < 0.01 ? ' class="hl"' : '') + '><td>' + m + '배</td>';
      for(var j = HIST_N; j < YRS.length; j++){
        var nd = MODEL.net_debt ? val('net_debt', j) : 0;
        var u2 = (val('ebitda', j) * m - nd) / mk.mktcap - 1;
        bb += '<td class="' + (u2 >= 0 ? 'pos' : 'neg') + '">' +
          (u2 >= 0 ? '+' : '') + (u2 * 100).toFixed(0) + '%</td>';
      }
      bb += '</tr>';
    });
    vb += card('목표배수 민감도', '칸 값 = 현재 시가총액 대비 괴리. 굵은 행이 현재 가정.', '',
      '<div class="table-wrap"><table class="fm">' + hh + bb + '</table></div>');
  }
  vb += icPeerCard();
  vb += '<div class="card pad">' + icMemoBody('valuation') + '</div>';
  h += icSec('06', '밸류에이션', (MEMO && MEMO.valuation) ? MEMO.valuation.sub : '', vb);

  // 7. 시나리오
  if(typeof SCENARIOS === 'object' && SCENARIOS){
    var want = ['total_revenue', 'op_profit', 'ebitda', rootId()];
    var cs = [{ name:'Base', ov:null }];
    for(var nm2 in SCENARIOS) cs.push({ name:nm2, ov:SCENARIOS[nm2] });
    var rws = '';
    cs.forEach(function(c){
      var sv = icSolve(c.ov, want, t);
      var u3 = mk ? sv[rootId()] / mk.mktcap - 1 : null;
      rws += '<tr' + (c.name === 'Base' ? ' class="hl"' : '') + '><td><b>' + esc(c.name) + '</b></td>' +
        '<td>' + esc(fmtSmart(sv.total_revenue)) + '</td>' +
        '<td>' + esc(fmtSmart(sv.op_profit)) + '</td>' +
        '<td>' + esc(fmtSmart(sv.ebitda)) + '</td>' +
        '<td>' + esc(fmtSmart(sv[rootId()])) + '</td>' +
        (u3 === null ? '<td>—</td>' : '<td class="' + (u3 >= 0 ? 'pos' : 'neg') + '">' +
          (u3 >= 0 ? '+' : '') + (u3 * 100).toFixed(0) + '%</td>') + '</tr>';
    });
    h += icSec('07', '시나리오', YRS[t] + ' 기준 · [주관] 노드만 흔든다',
      card('', '', UNITS.money,
        '<div class="table-wrap"><table class="fm"><tr><th style="text-align:left">시나리오</th>' +
        '<th>매출</th><th>영업이익</th><th>EBITDA</th><th>적정 시총</th><th>현재가 대비</th></tr>' +
        rws + '</table></div>'));
  }

  // 8. 리스크
  h += icSec('08', '리스크와 모니터링',
    '아래 지표가 훼손되면 아이디어가 아니라 논거가 깨진 것이다',
    '<div class="card pad">' + icMemoBody('bear') + '</div>' +
    '<div class="card pad" style="margin-top:12px">' + icMemoBody('risk') + '</div>');

  // 9. 심사 결론
  h += icSec('09', '심사 결론', (MEMO && MEMO.verdict) ? MEMO.verdict.sub : '',
    '<div class="card pad">' + icMemoBody('verdict') + '</div>' +
    ((typeof MEMO === 'object' && MEMO && MEMO.revision)
      ? card('가정 개정 이력', MEMO.revision.sub || '', '', icPoints(MEMO.revision)) : ''));

  // 10. 가정 일람 — 근거 태그와 함께. 무엇이 사실이고 무엇이 판단인지 드러난다.
  var arows = '';
  INPUT_KEYS.forEach(function(k){
    var d = MODEL[k], m = /^\[([^\]]+)\]/.exec(d.desc || '');
    arows += '<tr><td style="white-space:normal">' + esc(d.label || k) + '</td>' +
      '<td>' + esc(m ? m[1] : '—') + '</td>';
    for(var i3 = HIST_N; i3 < YRS.length; i3++){
      arows += '<td>' + esc(fmtNum(val(k, i3), d.u, d.pct)) + '</td>';
    }
    arows += '</tr>';
  });
  var ah = '<tr><th style="text-align:left">가정변수</th><th>근거</th>';
  for(var i4 = HIST_N; i4 < YRS.length; i4++) ah += '<th>' + esc(YRS[i4]) + '</th>';
  ah += '</tr>';
  h += icSec('10', '가정 일람', '추정 구간의 입력값 ' + INPUT_KEYS.length + '개. ' +
    '근거란의 [객관]은 공시·시장 관측, [주관]은 심사자의 판단이다.',
    card('', '', '', '<div class="table-wrap"><table class="fm">' + ah + arows + '</table></div>'));

  h += '<div class="notice" style="margin-top:22px">본 자료는 공시·시장 데이터 기반의 ' +
    '내부 검토용 모델이며 투자권유가 아님. 모든 수치는 이 화면의 모델에서 즉시 ' +
    '계산되므로 가정 변경 시 본문 숫자도 동시 변경됨.</div>';
  return h + '</div>';
}

function renderICVerdict(){"""

# 심사 결론 뷰에도 아이디어를 얹는다 (결론 → 근거 순으로 읽히도록)
OLD_IC4_VERDICT = """  h += icMemoCard('verdict', '투자의견');
  h += icMemoCard('bull', '상방 논리');"""
NEW_IC4_VERDICT = """  h += icMemoCard('verdict', '투자의견');
  // 가정을 바꿨다면 무엇을 왜 바꿨는지가 결론과 같은 자리에 있어야 한다.
  // 이 기록이 없으면 모델이 주가를 뒤쫓아도 아무도 알 수 없다.
  h += icMemoCard('revision', '가정 개정 이력');
  h += icDebateCard();
  h += icMemoCard('bull', '상방 논리');"""

OLD_IC4_STYLE = """ul.memo li{font-size:13px;color:#4B5563;line-height:1.75;margin-bottom:6px}"""

NEW_IC4_STYLE = """ul.memo li{font-size:13px;color:#4B5563;line-height:1.75;margin-bottom:6px}

/* 투자 아이디어 카드 */
.idea{border:1px solid #E5E5E8;border-radius:10px;background:#FFFFFF;margin-bottom:12px;overflow:hidden}
.idea-head{display:flex;gap:10px;align-items:flex-start;padding:13px 15px;
  border-bottom:1px solid #F3F4F6;background:#F9FAFB}
.idea-n{width:22px;height:22px;border-radius:6px;background:#1E2185;color:#FFFFFF;
  font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
.idea-title{font-size:13px;font-weight:700;color:#0F0F12;margin:0;line-height:1.45}
.idea-tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.tag{font-size:9.5px;color:#4B5563;background:#F3F4F6;border-radius:999px;padding:2px 8px;font-weight:700}
.tag.hi{background:#EDF3FF;color:#1E2185}
.idea-body{padding:13px 15px}
.idea-body p{font-size:12.5px;color:#374151;line-height:1.75;margin:0 0 12px}
.idea-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
.idea-box .h{font-size:9.5px;font-weight:700;letter-spacing:.04em;color:#6B7280;margin-bottom:5px}
.idea-box ul{margin:0;padding-left:15px}
.idea-box li{font-size:11.5px;color:#4B5563;line-height:1.65;margin-bottom:5px;
  padding-left:12px;position:relative;list-style:none}
.idea-box li:before{content:'▪';position:absolute;left:0;top:-1px;color:#A1B8FF;font-size:9px}
.idea-box ul.sub > li{font-size:11px;color:#6B7280;padding-left:11px;margin-bottom:2px}
.idea-box ul.sub > li:before{content:'–';color:#9CA3AF;font-size:11px;top:0}
.falsify{margin-top:14px;padding:10px 12px;border-radius:6px;background:#F9FAFB;
  border:1px solid #E5E7EB;border-left:3px solid #DC2626;font-size:11.5px;color:#4B5563;line-height:1.7}
.falsify b{color:#DC2626}

/* 애널리스트 리포트 */
.rp{max-width:960px;margin:0 auto}
.rp-cover{border:1px solid #E5E5E8;border-radius:10px;background:#FFFFFF;padding:20px 22px}
.rp-cover .co{font-family:'Outfit',system-ui,sans-serif;font-size:22px;font-weight:600;
  letter-spacing:-.03em;color:#0F0F12}
.rp-cover .sub{font-size:10.5px;color:#6B7280;margin-top:5px;line-height:1.6}
.rp-sec{margin-top:26px}
.rp-num{font-size:9.5px;font-weight:700;color:#5D68F7;letter-spacing:.12em}
.rp-sec > h2{font-family:'Outfit',system-ui,sans-serif;font-size:15px;font-weight:600;
  margin:3px 0 3px;color:#0F0F12;letter-spacing:-.02em}
.rp-sec > p.desc{font-size:10.5px;color:#6B7280;margin:0 0 11px;line-height:1.6}
.rp-sec .card{margin-bottom:0}

/* 인쇄 — 리포트 뷰를 그대로 종이/PDF로 넘긴다. 셸은 전부 걷어낸다. */
@media print{
  .sidebar,#scrim,.topbar,#treePanel,.rp-print,.modal,.legend{display:none !important}
  .app,.main,.stage,.stage-main{display:block !important;height:auto !important;overflow:visible !important}
  #docView{display:block !important;overflow:visible !important;height:auto !important;
    padding:0 !important;background:#FFFFFF !important}
  .rp{max-width:none}
  .card,.idea,.rp-sec{break-inside:avoid;page-break-inside:avoid}
  .kpi-row{break-inside:avoid}
  table.fm th{position:static !important}
  table.fm th:first-child,table.fm td:first-child{position:static !important}
  .table-wrap{overflow:visible !important}
  a[href]:after{content:''}
  @page{margin:14mm}
}"""

# ─────────────────────────────────────────────────────────────
# IC-5  분기 추적 · 모니터링 · 자동 민감도 · 컨센서스 · 숫자 인용
#
# 네 가지 공백을 메운다.
#
#   1) 아이디어의 반증 조건은 전부 분기 단위인데 모델의 시간축은 연간이다.
#      QUARTERLY(공시 확정 분기값)를 옆에 두고 대조한다.
#   2) 확인지표를 사람이 눈으로 좇게 두면 분기마다 잊는다. ideas[].track에
#      기계가 읽을 형태로 적고 화면이 계산한다.
#   3) 어느 가정이 결과를 지배하는지 손으로 고르고 있었다. 전 입력을 흔들어
#      정렬해 보여준다 — 토네이도.
#   4) 컨센서스가 MEMO 산문에만 있었다. CONSENSUS 블록으로 꺼내 모델과의
#      괴리를 화면이 계산하게 한다.
#
# 그리고 산문 안의 숫자가 모델과 어긋나는 것을 구조적으로 막는다.
# MEMO 텍스트에 {{node@연도}} 를 쓰면 그 자리에서 모델값으로 치환된다.
# 게이트 G11이 인용이 해석되는지 검사한다.
# ─────────────────────────────────────────────────────────────

OLD_IC5_ICON = """  'book-open':'<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',"""
NEW_IC5_ICON = OLD_IC5_ICON + """
  activity:'<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  filter:'<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',"""

OLD_IC5_ROUTE = """  if(view === 'ic_ideas') return renderICIdeas();"""
NEW_IC5_ROUTE = """  if(view === 'ic_ideas') return renderICIdeas();
  if(view === 'ic_monitor') return renderICMonitor();
  if(view === 'ic_sens') return renderICSensitivity();"""

OLD_IC5_TITLES = """  ic_scenario:'시나리오', ic_ideas:'투자 아이디어',"""
NEW_IC5_TITLES = """  ic_scenario:'시나리오', ic_ideas:'투자 아이디어',
  ic_monitor:'분기 모니터링', ic_sens:'민감도',"""

OLD_IC5_NAV = """      navBtn('ic_verdict', 'file-text', '심사 결론') +"""
NEW_IC5_NAV = """      navBtn('ic_monitor', 'activity', '분기 모니터링',
             (typeof QUARTERLY === 'object' && QUARTERLY && QUARTERLY.quarters)
               ? String(Object.keys(QUARTERLY.quarters).length) : '') +
      navBtn('ic_sens', 'filter', '민감도') +
      navBtn('ic_verdict', 'file-text', '심사 결론') +"""

OLD_IC5_ANCHOR = """// ── 투자 아이디어 ─────────────────────────────────────────────"""

NEW_IC5_ANCHOR = """// ── 분기 확정값 ───────────────────────────────────────────────
// QUARTERLY는 공시 원문에서 기계가 만든다(tools/build_quarterly.py).
// 모델의 시간축은 연간이므로 이 값들은 모델에 들어가지 않는다 — 옆에 두고
// "모델이 그린 경로 위를 실제로 걷고 있는가"를 묻는 데만 쓴다.
function qHas(){ return typeof QUARTERLY === 'object' && QUARTERLY && QUARTERLY.quarters; }
function qKeys(){ return qHas() ? Object.keys(QUARTERLY.quarters).sort() : []; }
function qYear(k){ return parseInt(k.slice(0, 4), 10); }

// 파생 지표까지 여기서 낸다. 기타비용 = 매출 − 영업이익 − 감가상각비 로,
// 모델의 비용 분해와 같은 정의다 (02_cost_methodology).
function qVal(k, seg, metric){
  if(!qHas()) return null;
  var rec = QUARTERLY.quarters[k];
  if(!rec || !rec[seg]) return null;
  var r = rec[seg], rev = r['매출'], op = r['영업이익'], dep = r['감가상각비'];
  if(metric === '영업이익률') return (rev ? op / rev : null);
  if(metric === '기타비용률') return (rev != null && op != null && dep != null && rev)
    ? (rev - op - dep) / rev : null;
  var v = r[metric];
  return v === undefined ? null : v;
}
// 전년 동기 대비. 분기 데이터에서 계절성을 걷어내는 최소한의 장치다.
function qYoY(k, seg, metric){
  var prev = (qYear(k) - 1) + k.slice(4);
  var a = qVal(prev, seg, metric), b = qVal(k, seg, metric);
  return (a && isFinite(a) && a !== 0) ? b / a - 1 : null;
}
function qFmt(metric, v){
  if(v === null || v === undefined || !isFinite(v)) return '—';
  if(metric === '영업이익률' || metric === '기타비용률') return (v * 100).toFixed(1) + '%';
  return fmtSmart(v);
}

// ── 모니터링 뷰 ───────────────────────────────────────────────
function renderICMonitor(){
  var h = '<div class="page">';
  h += '<div class="page-head"><div class="eyebrow caps">' + ic('activity', 16) +
    ' Investment case</div><h1>분기 모니터링</h1></div>';
  if(!qHas()){
    return h + '<div class="notice">분기 확정값(QUARTERLY) 미선언 — ' +
      'tools/build_quarterly.py 로 생성해 data.js 옆에 quarterly.json 으로 두면 화면 활성화.</div></div>';
  }
  var ks = qKeys(), last = ks[ks.length - 1];
  h += '<div class="notice">' + esc(QUARTERLY._출처 || '') +
    ' · 최신 확정 <b>' + esc(last) + '</b> · 단위 ' + esc(QUARTERLY._단위 || '') +
    ' — 모델에 투입되지 않는 값. 모델이 그린 경로 위를 실제로 걷고 있는지 대조 용도.</div>';

  h += icYtdCard(last);
  h += icQuarterTable(ks);
  h += icTrackCards(ks);
  return h + '</div>';
}

// 진행률 — 당해 누적 실적이 모델 연간 추정의 몇 %인가.
// 선형 기준(분기 수/4)과 나란히 놓아야 "앞서 있다/뒤처져 있다"를 말할 수 있다.
function icYtdCard(last){
  var y = qYear(last), n = parseInt(last.slice(5), 10);
  var yi = YRS.indexOf(String(y));
  if(yi < 0) return '';
  var ks = qKeys().filter(function(k){ return qYear(k) === y; });
  var rows = '', pace = n / 4;
  [['매출', 'total_revenue'], ['영업이익', 'op_profit']].forEach(function(pair){
    var metric = pair[0], id = pair[1];
    if(!MODEL[id]) return;
    var ytd = 0, ok = true;
    ks.forEach(function(k){ var v = qVal(k, '합계', metric); if(v === null) ok = false; else ytd += v; });
    if(!ok) return;
    var plan = val(id, yi), rate = plan ? ytd / plan : null;
    var gap = rate === null ? null : rate - pace;
    rows += '<tr><td>' + esc(metric) + '</td>' +
      '<td>' + esc(fmtSmart(ytd)) + '</td>' +
      '<td>' + esc(fmtSmart(plan)) + '</td>' +
      '<td>' + (rate === null ? '—' : (rate * 100).toFixed(0) + '%') + '</td>' +
      '<td class="' + (gap >= 0 ? 'pos' : 'neg') + '">' +
        (gap === null ? '—' : (gap >= 0 ? '+' : '') + (gap * 100).toFixed(0) + '%p') + '</td></tr>';
  });
  // EBITDA는 노드 정의(감가상각비만)와 같은 방식으로 분기에서도 만든다.
  if(MODEL.ebitda){
    var e = 0, ok2 = true;
    ks.forEach(function(k){
      var op = qVal(k, '합계', '영업이익'), dp = qVal(k, '합계', '감가상각비');
      if(op === null || dp === null) ok2 = false; else e += op + dp;
    });
    if(ok2){
      var plan2 = val('ebitda', yi), rate2 = plan2 ? e / plan2 : null;
      var gap2 = rate2 === null ? null : rate2 - pace;
      rows += '<tr class="total"><td>EBITDA</td><td>' + esc(fmtSmart(e)) + '</td>' +
        '<td>' + esc(fmtSmart(plan2)) + '</td>' +
        '<td>' + (rate2 === null ? '—' : (rate2 * 100).toFixed(0) + '%') + '</td>' +
        '<td class="' + (gap2 >= 0 ? 'pos' : 'neg') + '">' +
          (gap2 === null ? '—' : (gap2 >= 0 ? '+' : '') + (gap2 * 100).toFixed(0) + '%p') +
        '</td></tr>';
    }
  }
  return card(y + ' 진행률 — 누적 실적 대 모델 추정',
    n + '개 분기 확정 · 선형 기준 ' + (pace * 100).toFixed(0) + '%', UNITS.money,
    '<div class="table-wrap"><table class="fm"><tr><th style="text-align:left">항목</th>' +
    '<th>누적 실적</th><th>모델 연간</th><th>진행률</th><th>선형 대비</th></tr>' +
    rows + '</table></div>');
}

function icQuarterTable(ks){
  var head = '<tr><th style="text-align:left">항목</th>';
  ks.forEach(function(k){ head += '<th>' + esc(k) + '</th>'; });
  head += '</tr>';
  var body = '';
  var line = function(label, seg, metric, cls){
    var r = '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td>' + esc(label) + '</td>';
    ks.forEach(function(k){ r += '<td>' + esc(qFmt(metric, qVal(k, seg, metric))) + '</td>'; });
    return r + '</tr>';
  };
  body += line('매출', '합계', '매출', 'total');
  body += line('영업이익', '합계', '영업이익');
  body += line('영업이익률', '합계', '영업이익률');
  ['컴포넌트', '패키지솔루션', '광학솔루션'].forEach(function(seg){
    var rec = QUARTERLY.quarters[ks[ks.length - 1]];
    if(!rec || !rec[seg]) return;
    body += line(seg + ' 매출', seg, '매출', 'total');
    body += line('  영업이익률', seg, '영업이익률');
    body += line('  기타비용률', seg, '기타비용률');
    body += line('  감가상각비', seg, '감가상각비');
  });
  return card('분기 확정 실적', '공시 원문 · 누적의 차분으로 만든 분기값', UNITS.money,
    '<div class="table-wrap"><table class="fm">' + head + body + '</table></div>');
}

// 아이디어별 확인지표. ideas[].track 이 있으면 화면이 계산한다.
function icTrackCards(ks){
  var list = (typeof MEMO === 'object' && MEMO) ? MEMO.ideas : null;
  if(!list || !list.length) return '';
  var h = '';
  list.forEach(function(d, i){
    if(!d.track || !d.track.length) return;
    var rows = '';
    d.track.forEach(function(t){
      var cells = '';
      ks.slice(-6).forEach(function(k){
        var v = t.kind === 'yoy' ? qYoY(k, t.seg, t.metric) : qVal(k, t.seg, t.metric);
        cells += '<td>' + (t.kind === 'yoy'
          ? (v === null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(0) + '%')
          : esc(qFmt(t.metric, v))) + '</td>';
      });
      // 방향 판정 — 최근 값이 직전 값 대비 좋은 쪽으로 움직였는가
      var a = t.kind === 'yoy' ? qYoY(ks[ks.length - 2], t.seg, t.metric)
                               : qVal(ks[ks.length - 2], t.seg, t.metric);
      var b = t.kind === 'yoy' ? qYoY(ks[ks.length - 1], t.seg, t.metric)
                               : qVal(ks[ks.length - 1], t.seg, t.metric);
      var mark = '—', cls = '';
      if(a !== null && b !== null && a !== b){
        var up = b > a, good = (t.good === 'down') ? !up : up;
        mark = (up ? '▲' : '▼');
        cls = good ? 'pos' : 'neg';
      }
      rows += '<tr><td style="white-space:normal">' + esc(t.label) + '</td>' + cells +
        '<td class="' + cls + '">' + mark + '</td></tr>';
    });
    var head = '<tr><th style="text-align:left">확인 지표</th>';
    ks.slice(-6).forEach(function(k){ head += '<th>' + esc(k) + '</th>'; });
    head += '<th>방향</th></tr>';
    h += card('아이디어 ' + (i + 1) + ' — ' + (d.title || ''),
      d.falsify ? '반증 조건 — ' + d.falsify : '', '',
      '<div class="table-wrap"><table class="fm">' + head + rows + '</table></div>');
  });
  return h;
}

// ── 자동 민감도 (토네이도) ────────────────────────────────────
// 어느 가정이 결과를 지배하는지 손으로 고르지 않는다. 전 입력을 같은 폭으로
// 흔들어 루트 변화를 정렬한다. 추정 구간만 흔든다 — 실적은 확정값이다.
function icSensitivity(pct){
  var t = icLastIdx(), base = val(rootId(), t), out = [];
  INPUT_KEYS.forEach(function(k){
    var d = MODEL[k];
    if(!d || !DEFAULTS_S[k]) return;
    var shift = function(sign){
      var arr = SV[k].slice();
      for(var i = HIST_N; i < YRS.length; i++) arr[i] = arr[i] * (1 + sign * pct);
      var ov = {}; ov[k] = arr;
      var r = icSolve(ov, [rootId()], t);
      return r[rootId()];
    };
    var up = shift(1), dn = shift(-1);
    if(!isFinite(up) || !isFinite(dn)) return;
    out.push({ key:k, label:d.label || k, up:up - base, dn:dn - base,
               span:Math.abs(up - dn) });
  });
  out.sort(function(a, b){ return b.span - a.span; });
  return { base:base, rows:out };
}

function renderICSensitivity(){
  var h = '<div class="page">';
  h += '<div class="page-head"><div class="eyebrow caps">' + ic('filter', 16) +
    ' Investment case</div><h1>민감도</h1></div>';
  var PCT = 0.10;
  h += '<div class="notice">가정변수를 각각 <b>±' + (PCT * 100).toFixed(0) + '%</b> ' +
    '흔들어 ' + esc(YRS[icLastIdx()]) + ' ' + esc(MODEL[rootId()].label || rootId()) +
    ' 변화 기준 정렬. 추정 구간만 변경 — 실적은 확정값. ' +
    '<b>위쪽 몇 개가 이 모델의 실질적 가정</b>.</div>';

  var r = icSensitivity(PCT), max = r.rows.length ? r.rows[0].span : 1;
  var rows = '';
  r.rows.slice(0, 14).forEach(function(x){
    // 막대는 충격의 방향이 아니라 **결과의 방향**으로 눕힌다. 비용률처럼
    // 올리면 값이 내려가는 변수가 있어서, 충격 방향으로 그리면 왼쪽 막대가
    // 상승을 뜻하는 화면이 된다.
    var lo = Math.min(x.up, x.dn), hi = Math.max(x.up, x.dn);
    var wl = max ? Math.round(Math.max(0, -lo) / max * 100) : 0;
    var wr = max ? Math.round(Math.max(0, hi) / max * 100) : 0;
    var pctUp = r.base ? x.up / r.base : 0, pctDn = r.base ? x.dn / r.base : 0;
    rows += '<tr><td style="white-space:normal">' + esc(x.label) + '</td>' +
      '<td><div class="tor"><div class="tor-l"><span style="width:' + wl + '%"></span></div>' +
      '<div class="tor-r"><span style="width:' + wr + '%"></span></div></div></td>' +
      '<td class="' + (pctDn >= 0 ? 'pos' : 'neg') + '">' +
        (pctDn >= 0 ? '+' : '') + (pctDn * 100).toFixed(1) + '%</td>' +
      '<td class="' + (pctUp >= 0 ? 'pos' : 'neg') + '">' +
        (pctUp >= 0 ? '+' : '') + (pctUp * 100).toFixed(1) + '%</td></tr>';
  });
  h += card('가정변수 영향도',
    '막대 왼쪽은 불리한 쪽, 오른쪽은 유리한 쪽. 값은 ' +
    (MODEL[rootId()].label || rootId()) + ' 대비 변화율.', '',
    '<div class="table-wrap"><table class="fm"><tr><th style="text-align:left">가정변수</th>' +
    '<th style="text-align:center">불리 ← → 유리</th>' +
    '<th>−' + (PCT * 100).toFixed(0) + '% 적용</th>' +
    '<th>+' + (PCT * 100).toFixed(0) + '% 적용</th></tr>' + rows + '</table></div>');
  return h + '</div>';
}

// ── 컨센서스 ─────────────────────────────────────────────────
// 시장이 무엇을 전제하는지는 목표가만큼 중요하다. 산문에 적어두면 갱신될 때
// 본문만 낡는다. 블록으로 꺼내 화면이 괴리를 계산하게 한다.
function icConsensusCard(){
  if(typeof CONSENSUS !== 'object' || !CONSENSUS || !CONSENSUS.items) return '';
  var rows = '';
  CONSENSUS.items.forEach(function(it){
    var yi = YRS.indexOf(String(it.year));
    var mine = (yi >= 0 && MODEL[it.node]) ? val(it.node, yi) : null;
    var gap = (mine && it.value) ? it.value / mine - 1 : null;
    rows += '<tr><td>' + esc(it.year) + ' ' +
      esc(MODEL[it.node] ? (MODEL[it.node].label || it.node) : it.node) + '</td>' +
      '<td>' + esc(fmtSmart(it.value)) + '</td>' +
      '<td>' + (mine === null ? '—' : esc(fmtSmart(mine))) + '</td>' +
      '<td class="' + (gap >= 0 ? 'neg' : 'pos') + '">' +
        (gap === null ? '—' : (gap >= 0 ? '+' : '') + (gap * 100).toFixed(0) + '%') +
      '</td></tr>';
  });
  return card('컨센서스 대비', '괴리 = 컨센서스 ÷ 본 모델 − 1. 양수면 시장이 더 낙관적이다.',
    UNITS.money,
    '<div class="table-wrap"><table class="fm"><tr><th style="text-align:left">항목</th>' +
    '<th>컨센서스</th><th>본 모델</th><th>괴리</th></tr>' + rows + '</table></div>' +
    '<div class="notice" style="margin:12px 0 0">기준일 <b>' + esc(CONSENSUS.asOf || '') +
    '</b> · ' + esc(CONSENSUS.source || '') + '</div>');
}

// ── 항목 렌더러 ──────────────────────────────────────────────
// 서술형 문단은 심사 자료에서 읽히지 않는다. 본문은 두 층의 항목으로 적는다.
//   '문자열'             → ▪ 한 줄
//   {t:'주제', d:[...]}   → ▪ 주제(굵게) 아래 – 근거들
// 층은 데이터 쪽에서 나누고, 화면은 그 층을 그대로 보여준다.
function icList(arr, cls){
  if(typeof arr === 'string') arr = [arr];
  if(!arr || !arr.length) return '';
  var b = '<ul class="' + cls + '">';
  arr.forEach(function(x){
    if(typeof x === 'string'){ b += '<li>' + esc(icText(x)) + '</li>'; return; }
    b += '<li><b>' + esc(icText(x.t || '')) + '</b>';
    if(x.d && x.d.length){
      b += '<ul class="sub">';
      x.d.forEach(function(y){ b += '<li>' + esc(icText(y)) + '</li>'; });
      b += '</ul>';
    }
    b += '</li>';
  });
  return b + '</ul>';
}
function icPoints(m){
  var b = '';
  if(m.lead) b += '<p class="lead">' + esc(icText(m.lead)) + '</p>';
  b += icList(m.points, 'memo');
  return b;
}

// ── 산문 속 숫자를 모델에서 읽는다 ─────────────────────────────
// {{node@2030}} 은 그 자리에서 모델값으로 치환된다. 산문에 숫자를 박아두면
// 가정을 바꿨을 때 본문만 옛 숫자로 남는다 — 그것을 문법으로 막는다.
// 해석되지 않는 인용은 게이트 G11이 잡는다.
function icText(s){
  if(typeof s !== 'string' || s.indexOf('{{') < 0) return s;
  return s.replace(/\\{\\{\\s*([A-Za-z_][A-Za-z0-9_]*)\\s*@\\s*(\\d{4})\\s*(?:\\|\\s*(\\w+))?\\s*\\}\\}/g,
    function(all, id, year, fmt){
      var i = YRS.indexOf(year);
      if(i < 0 || !MODEL[id]) return all;      // 해석 실패는 그대로 남긴다
      if(fmt === 'money') return icMoney(val(id, i));
      if(fmt === 'raw') return String(Math.round(val(id, i)));
      return fmtV(id, i);
    });
}

// ── 투자 아이디어 ─────────────────────────────────────────────"""

# MEMO 텍스트가 화면에 나가는 모든 경로에 인용 치환을 건다.




OLD_IC5_DEBATE = """    rows += '<tr><td style="white-space:normal;min-width:150px">' + esc(x.q) + '</td>' +
      '<td style="white-space:normal">' + esc(x.yes || '') + '</td>' +
      '<td style="white-space:normal">' + esc(x.no || '') + '</td></tr>';"""
NEW_IC5_DEBATE = """    rows += '<tr><td style="white-space:normal;min-width:150px">' + esc(icText(x.q)) + '</td>' +
      '<td style="white-space:normal">' + esc(icText(x.yes || '')) + '</td>' +
      '<td style="white-space:normal">' + esc(icText(x.no || '')) + '</td></tr>';"""

# 밸류에이션 뷰에 컨센서스 카드
OLD_IC5_VAL = """  h += icPeerCard();
  h += icMemoCard('valuation', '밸류에이션 판단');"""
NEW_IC5_VAL = """  h += icConsensusCard();
  h += icPeerCard();
  h += icMemoCard('valuation', '밸류에이션 판단');"""

# 리포트에도 — 밸류에이션 섹션과 모니터링 섹션
OLD_IC5_RPVAL = """  vb += icPeerCard();
  vb += '<div class="card pad">' + icMemoBody('valuation') + '</div>';"""
NEW_IC5_RPVAL = """  vb += icConsensusCard();
  vb += icPeerCard();
  vb += '<div class="card pad">' + icMemoBody('valuation') + '</div>';"""

OLD_IC5_RPRISK = """  // 8. 리스크
  h += icSec('08', '리스크와 모니터링',"""
NEW_IC5_RPRISK = """  // 7.5 분기 진행 상황 — 모델 경로 위를 걷고 있는가
  if(qHas()){
    var lastQ = qKeys()[qKeys().length - 1];
    h += icSec('07b', '분기 진행 상황',
      '공시 확정 분기값 대 모델 연간 추정 · 최신 확정 ' + lastQ,
      icYtdCard(lastQ) + icQuarterTable(qKeys().slice(-6)));
  }

  // 8. 리스크
  h += icSec('08', '리스크와 모니터링',"""

OLD_IC5_STYLE = """.falsify b{color:#DC2626}"""
NEW_IC5_STYLE = """.falsify b{color:#DC2626}

/* 토네이도 막대 — 좌우 대칭으로 한 행에 음/양을 함께 둔다 */
.tor{display:flex;align-items:center;gap:2px;min-width:180px}
.tor-l,.tor-r{flex:1;display:flex;height:11px}
.tor-l{justify-content:flex-end}
.tor-l span{background:#9CA3AF;border-radius:2px 0 0 2px;display:block;height:100%}
.tor-r span{background:#5D68F7;border-radius:0 2px 2px 0;display:block;height:100%}

/* 아이디어의 최신 진행 상황 — 논거보다 먼저 눈에 들어와야 한다 */
.idea-upd{margin:0 0 12px;padding:10px 12px;border-radius:6px;background:#EDF3FF;
  border:1px solid #C5D5FF;border-left:3px solid #1E2185;font-size:11.5px;
  color:#1E2185;line-height:1.7}
.idea-upd b{color:#1E2185}"""

# ─────────────────────────────────────────────────────────────
# IC-6  가독성 — 차트 · 강조 · 타이포 위계
#
# 심사 자료는 회의 중에 훑는다. 숫자를 표로만 주면 추세가 안 보이고,
# 전부 같은 굵기로 주면 무엇이 결론인지 알 수 없다. 셋을 더한다.
#
#   차트  외부 라이브러리 없이 인라인 SVG로 그린다. model.html의 외부 요청
#         0건 규약을 지켜야 하므로 선택지가 이것뿐이다. 세 종류면 충분하다 —
#         세로 막대(추세) · 가로 막대(순위) · 100% 스택(구성).
#   강조  본문에 **굵게** 를 쓴다. 이스케이프 뒤에 변환하므로 데이터가
#         HTML을 주입할 수는 없다.
#   위계  섹션 제목 · 카드 제목 · 본문 · 근거의 크기와 색을 네 단으로 벌린다.
# ─────────────────────────────────────────────────────────────

OLD_IC6_ANCHOR = """// ── 항목 렌더러 ──────────────────────────────────────────────"""

NEW_IC6_ANCHOR = """// ── 인라인 SVG 차트 ───────────────────────────────────────────
// 외부 라이브러리를 쓰지 않는다. model.html은 외부 요청 0건이 규약이고,
// 그 규약이 있어야 사내망·오프라인 심사장에서 파일 하나로 열린다.
// viewBox만 주고 width는 CSS가 100%로 잡으므로 인쇄·모바일에서 같이 줄어든다.

var ICV = { rev:'#1E2185', rev2:'#5D68F7', cost:'#6B7280', pos:'#22C55E',
            neg:'#DC2626', grid:'#E5E7EB', text:'#6B7280', ink:'#0F0F12',
            band:'#F8F8FA', ramp:['#1E2185','#3332D0','#5D68F7','#7C91FD','#A1B8FF'] };

function icSvg(w, h, body){
  return '<svg class="icv" viewBox="0 0 ' + w + ' ' + h + '" ' +
    'preserveAspectRatio="xMidYMid meet" role="img">' + body + '</svg>';
}
function _t(x, y, s, size, color, anchor, weight){
  return '<text x="' + x + '" y="' + y + '" font-size="' + (size || 9) + '" ' +
    'fill="' + (color || ICV.text) + '" text-anchor="' + (anchor || 'middle') + '"' +
    (weight ? ' font-weight="' + weight + '"' : '') + '>' + esc(String(s)) + '</text>';
}
function _niceMax(v){
  if(!(v > 0)) return 1;
  var e = Math.pow(10, Math.floor(Math.log(v) / Math.LN10));
  var m = v / e;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * e;
}

// 세로 막대 — 연도별 추세. 두 번째 계열은 선으로 겹쳐 그린다(비율 축).
// histN을 주면 추정 구간에 음영을 깔아 실적과 눈으로 구분된다.
function icSvgBars(labels, values, opts){
  opts = opts || {};
  var W = 720, H = opts.height || 200, L = 44, R = opts.line ? 40 : 12, T = 16, B = 26;
  var iw = W - L - R, ih = H - T - B;
  var max = _niceMax(Math.max.apply(null, values.concat([0])));
  var n = labels.length, step = iw / n, bw = Math.min(38, step * 0.56);
  var g = '';

  if(opts.histN != null && opts.histN < n){
    var x0 = L + step * opts.histN;
    g += '<rect x="' + x0.toFixed(1) + '" y="' + T + '" width="' + (L + iw - x0).toFixed(1) +
         '" height="' + ih + '" fill="' + ICV.band + '"/>';
    g += _t(x0 + 3, T + 10, '추정', 8.5, '#9CA3AF', 'start');
  }
  for(var k = 0; k <= 4; k++){
    var y = T + ih - ih * k / 4;
    g += '<line x1="' + L + '" y1="' + y.toFixed(1) + '" x2="' + (L + iw) +
         '" y2="' + y.toFixed(1) + '" stroke="' + ICV.grid + '" stroke-width="1"/>';
    g += _t(L - 6, y + 3, fmtSmart(max * k / 4), 8.5, '#9CA3AF', 'end');
  }
  values.forEach(function(v, i){
    var h = Math.max(1, ih * (v / max)), x = L + step * i + (step - bw) / 2;
    var fc = (opts.histN != null && i >= opts.histN) ? ICV.rev2 : ICV.rev;
    g += '<rect x="' + x.toFixed(1) + '" y="' + (T + ih - h).toFixed(1) + '" width="' +
         bw.toFixed(1) + '" height="' + h.toFixed(1) + '" fill="' + fc + '" rx="2"/>';
    if(n <= 12) g += _t(x + bw / 2, T + ih - h - 4, fmtSmart(v), 8.5, ICV.ink, 'middle', 600);
    g += _t(x + bw / 2, H - 8, labels[i], 8.5);
  });

  if(opts.line && opts.line.length === n){
    var lmax = _niceMax(Math.max.apply(null, opts.line)), pts = [];
    opts.line.forEach(function(v, i){
      pts.push((L + step * i + step / 2).toFixed(1) + ',' +
               (T + ih - ih * (v / lmax)).toFixed(1));
    });
    g += '<polyline points="' + pts.join(' ') + '" fill="none" stroke="' + ICV.neg +
         '" stroke-width="1.6"/>';
    pts.forEach(function(p){
      var xy = p.split(',');
      g += '<circle cx="' + xy[0] + '" cy="' + xy[1] + '" r="2.4" fill="' + ICV.neg + '"/>';
    });
    g += _t(L + iw + 6, T + 8, opts.lineLabel || '', 8.5, ICV.neg, 'start', 700);
    g += _t(L + iw + 6, T + 19, (lmax * 100).toFixed(0) + '%', 8.5, '#9CA3AF', 'start');
  }
  return icSvg(W, H, g);
}

// 가로 막대 — 순위 비교. 음수도 받는다(0 기준 좌우).
function icSvgHBars(rows, opts){
  opts = opts || {};
  var W = 720, rowH = 22, T = 8, B = 6, L = opts.labelW || 120, R = 56;
  var H = T + B + rows.length * rowH, iw = W - L - R;
  var vals = rows.map(function(r){ return r.value; });
  var lo = Math.min(0, Math.min.apply(null, vals)), hi = Math.max(0, Math.max.apply(null, vals));
  var span = (hi - lo) || 1, zero = L + iw * (0 - lo) / span;
  var g = '';
  if(lo < 0) g += '<line x1="' + zero.toFixed(1) + '" y1="' + T + '" x2="' + zero.toFixed(1) +
                  '" y2="' + (H - B) + '" stroke="' + ICV.grid + '"/>';
  rows.forEach(function(r, i){
    var y = T + i * rowH, bh = 12;
    var x1 = L + iw * (Math.min(0, r.value) - lo) / span;
    var x2 = L + iw * (Math.max(0, r.value) - lo) / span;
    g += _t(L - 8, y + bh - 2, r.label, 9.5, r.strong ? ICV.ink : ICV.text, 'end',
            r.strong ? 700 : 400);
    g += '<rect x="' + x1.toFixed(1) + '" y="' + (y + 2) + '" width="' +
         Math.max(1, x2 - x1).toFixed(1) + '" height="' + bh + '" rx="2" fill="' +
         (r.color || (r.value < 0 ? ICV.neg : ICV.rev)) + '"/>';
    g += _t(W - R + 6, y + bh - 2, r.text != null ? r.text : fmtSmart(r.value),
            9.5, ICV.ink, 'start', r.strong ? 700 : 500);
  });
  return icSvg(W, H, g);
}

// 100% 스택 — 구성비 추이. 색은 매출 램프에서만 가져온다.
function icSvgStack(labels, series){
  var W = 720, H = 178, L = 8, R = 96, T = 10, B = 26;
  var iw = W - L - R, ih = H - T - B, n = labels.length;
  var step = iw / n, bw = Math.min(46, step * 0.62), g = '';
  for(var i = 0; i < n; i++){
    var tot = 0;
    series.forEach(function(sr){ tot += Math.abs(sr.values[i]); });
    var acc = 0, x = L + step * i + (step - bw) / 2;
    series.forEach(function(sr, k){
      var frac = tot ? Math.abs(sr.values[i]) / tot : 0, h = ih * frac;
      var y = T + ih - acc - h;
      g += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) +
           '" height="' + h.toFixed(1) + '" fill="' + ICV.ramp[k % ICV.ramp.length] + '"/>';
      if(frac > 0.08) g += _t(x + bw / 2, y + h / 2 + 3, (frac * 100).toFixed(0) + '%',
                              8.5, '#FFFFFF', 'middle', 700);
      acc += h;
    });
    g += _t(x + bw / 2, H - 8, labels[i], 8.5);
  }
  series.forEach(function(sr, k){
    var y = T + 6 + k * 15;
    g += '<rect x="' + (W - R + 4) + '" y="' + (y - 8) + '" width="9" height="9" rx="2" fill="' +
         ICV.ramp[k % ICV.ramp.length] + '"/>';
    g += _t(W - R + 18, y, sr.name, 9, ICV.text, 'start');
  });
  return icSvg(W, H, g);
}

function icChartCard(title, sub, svg){
  return card(title, sub || '', '', '<div class="chart-box">' + svg + '</div>');
}

// ── 항목 렌더러 ──────────────────────────────────────────────"""

# 본문 강조 — **굵게**. 이스케이프 뒤에 변환하므로 데이터가 태그를 주입할 수 없다.
OLD_IC6_RICH = """function icList(arr, cls){
  if(typeof arr === 'string') arr = [arr];
  if(!arr || !arr.length) return '';
  var b = '<ul class="' + cls + '">';
  arr.forEach(function(x){
    if(typeof x === 'string'){ b += '<li>' + esc(icText(x)) + '</li>'; return; }
    b += '<li><b>' + esc(icText(x.t || '')) + '</b>';
    if(x.d && x.d.length){
      b += '<ul class="sub">';
      x.d.forEach(function(y){ b += '<li>' + esc(icText(y)) + '</li>'; });
      b += '</ul>';
    }
    b += '</li>';
  });
  return b + '</ul>';
}
function icPoints(m){
  var b = '';
  if(m.lead) b += '<p class="lead">' + esc(icText(m.lead)) + '</p>';
  b += icList(m.points, 'memo');
  return b;
}"""

NEW_IC6_RICH = """// 본문 강조. **굵게** 만 받는다 — 이스케이프한 뒤에 변환하므로
// 데이터가 태그를 주입할 수 없다. 마크다운을 흉내내지 않는 이유는,
// 심사 자료에서 필요한 강조가 "이 숫자가 결론이다" 하나뿐이기 때문이다.
function icRich(s){
  return esc(icText(s)).replace(/\\*\\*([^*]+)\\*\\*/g, '<b class="hl-b">$1</b>');
}
function icList(arr, cls){
  if(typeof arr === 'string') arr = [arr];
  if(!arr || !arr.length) return '';
  var b = '<ul class="' + cls + '">';
  arr.forEach(function(x){
    if(typeof x === 'string'){ b += '<li>' + icRich(x) + '</li>'; return; }
    b += '<li><b>' + icRich(x.t || '') + '</b>';
    if(x.d && x.d.length){
      b += '<ul class="sub">';
      x.d.forEach(function(y){ b += '<li>' + icRich(y) + '</li>'; });
      b += '</ul>';
    }
    b += '</li>';
  });
  return b + '</ul>';
}
function icPoints(m){
  var b = '';
  if(m.lead) b += '<p class="lead">' + icRich(m.lead) + '</p>';
  b += icList(m.points, 'memo');
  return b;
}"""

OLD_IC6_FALS = """  if(d.update) body += '<div class="idea-upd"><b>진행</b> — ' + esc(icText(d.update)) + '</div>';"""
NEW_IC6_FALS = """  if(d.update) body += '<div class="idea-upd"><b>진행</b> — ' + icRich(d.update) + '</div>';"""

OLD_IC6_FALS2 = """  if(d.falsify) body += '<div class="falsify"><b>반증 조건</b> — ' + esc(icText(d.falsify)) + '</div>';"""
NEW_IC6_FALS2 = """  if(d.falsify) body += '<div class="falsify"><b>반증 조건</b> — ' + icRich(d.falsify) + '</div>';"""

OLD_IC6_DEB = """    rows += '<tr><td style="white-space:normal;min-width:150px">' + esc(icText(x.q)) + '</td>' +
      '<td style="white-space:normal">' + esc(icText(x.yes || '')) + '</td>' +
      '<td style="white-space:normal">' + esc(icText(x.no || '')) + '</td></tr>';"""
NEW_IC6_DEB = """    rows += '<tr><td class="q" style="white-space:normal;min-width:140px">' + icRich(x.q) + '</td>' +
      '<td style="white-space:normal">' + icRich(x.yes || '') + '</td>' +
      '<td style="white-space:normal">' + icRich(x.no || '') + '</td></tr>';"""

# 리포트에 차트를 끼운다.
OLD_IC6_RP3 = """  h += icSec('03', '실적과 추정', '실적 ' + YRS[0] + '~' + YRS[HIST_N - 1] +
    '은 공시 확정값 · 이후는 모델 추정 (게이트 G1이 매 빌드마다 대사)',
    card('', '', UNITS.money,
      '<div class="table-wrap"><table class="fm">' + icYearHead() + body + '</table></div>'));"""
NEW_IC6_RP3 = """  var opmSeries = YRS.map(function(_, i){
    var r0 = val(rev, i); return r0 ? val('op_profit', i) / r0 : 0;
  });
  h += icSec('03', '실적과 추정', '실적 ' + YRS[0] + '~' + YRS[HIST_N - 1] +
    '은 공시 확정값 · 이후는 모델 추정 (게이트 G1이 매 빌드마다 대사)',
    icChartCard(MODEL[rev].label + ' 추이', '막대 = ' + MODEL[rev].label +
      ' · 선 = 영업이익률 · 음영 구간이 추정',
      icSvgBars(YRS, YRS.map(function(_, i){ return val(rev, i); }),
        { histN:HIST_N, line:opmSeries, lineLabel:'OPM' })) +
    card('', '', UNITS.money,
      '<div class="table-wrap"><table class="fm">' + icYearHead() + body + '</table></div>'));"""

OLD_IC6_RP4 = """    if(srows){
      h += icSec('04', '부문별 전개', '매출과 그 아래 원가 구성. 부문 합계는 연결 수치와 오차 0으로 일치한다.',
        card('', '', UNITS.money,
          '<div class="table-wrap"><table class="fm">' + icYearHead('부문') + srows + '</table></div>'));
    }"""
NEW_IC6_RP4 = """    if(srows){
      var mixSeries = seg.map(function(sid){
        return { name:MODEL[sid].label || sid,
                 values:YRS.map(function(_, i){ return val(sid, i); }) };
      });
      h += icSec('04', '부문별 전개',
        '매출과 그 아래 원가 구성 · 부문 합계는 연결 수치와 오차 0으로 일치',
        icChartCard('부문 구성비', '100% 스택 · ' + YRS[0] + '~' + YRS[HIST_N - 1] +
          ' 실적, 이후 모델 추정', icSvgStack(YRS, mixSeries)) +
        card('', '', UNITS.money,
          '<div class="table-wrap"><table class="fm">' + icYearHead('부문') + srows + '</table></div>'));
    }"""

# 피어 카드에 가로 막대
OLD_IC6_PEER = """  var note = '<div class="notice">' + esc(PEERS.note || '') +"""
NEW_IC6_PEER = """  // 표만 주면 순위가 눈에 안 들어온다. 같은 값을 막대로 한 번 더 보여준다.
  var bars = PEERS.list.filter(function(p){ return p.evEbitda && p.evEbitda[0] != null; })
    .sort(function(a, b){ return b.evEbitda[0] - a.evEbitda[0]; })
    .map(function(p){
      return { label:p.name + (p.market ? ' (' + p.market + ')' : ''),
               value:p.evEbitda[0], strong:p.group === 'self',
               color:p.group === 'self' ? ICV.rev : (p.market === '해외' ? ICV.rev2 : ICV.cost),
               text:p.evEbitda[0].toFixed(1) + '배' };
    });
  var barCard = bars.length ? icChartCard('EV/EBITDA 순위',
    '실적(TTM) 기준 · 굵은 행이 본 종목', icSvgHBars(bars)) : '';

  var note = '<div class="notice">' + esc(PEERS.note || '') +"""

OLD_IC6_PEER2 = """  return note + card('피어 그룹 비교', 'EV/EBITDA는 실적(A)과 당해 컨센서스(E)', UNITS.money,"""
NEW_IC6_PEER2 = """  return note + barCard + card('피어 그룹 비교', 'EV/EBITDA는 실적(A)과 당해 컨센서스(E)', UNITS.money,"""

# 시나리오 뷰에 가로 막대
OLD_IC6_SCEN = """  h += card(YRS[t] + ' 시나리오 비교', '굵은 행이 Base(초안값)', UNITS.money,"""
NEW_IC6_SCEN = """  var mc0 = (typeof MARKET === 'object' && MARKET) ? MARKET.mktcap : 0;
  if(mc0){
    h += icChartCard(YRS[t] + ' 적정 시가총액 — 현재가 대비', '0% 선이 현재 시가총액',
      icSvgHBars(cases.map(function(c, i){
        var u0 = solved[i][rootId()] / mc0 - 1;
        return { label:c.name, value:u0 * 100, strong:c.name === 'Base',
                 color:u0 >= 0 ? ICV.pos : ICV.neg,
                 text:(u0 >= 0 ? '+' : '') + (u0 * 100).toFixed(0) + '%' };
      }), { labelW:70 }));
  }
  h += card(YRS[t] + ' 시나리오 비교', '굵은 행이 Base(초안값)', UNITS.money,"""

# 분기 추이 차트
OLD_IC6_QT = """  return card('분기 확정 실적', '공시 원문 · 누적의 차분으로 만든 분기값', UNITS.money,
    '<div class="table-wrap"><table class="fm">' + head + body + '</table></div>');"""
NEW_IC6_QT = """  var qRev = ks.map(function(k){ return qVal(k, '합계', '매출') || 0; });
  var qOpm = ks.map(function(k){ return qVal(k, '합계', '영업이익률') || 0; });
  return icChartCard('분기 매출과 영업이익률', '막대 = 매출 · 선 = 영업이익률',
      icSvgBars(ks, qRev, { line:qOpm, lineLabel:'OPM', height:190 })) +
    card('분기 확정 실적', '공시 원문 · 누적의 차분으로 만든 분기값', UNITS.money,
    '<div class="table-wrap"><table class="fm">' + head + body + '</table></div>');"""

# 민감도 뷰도 막대로
OLD_IC6_SENS = """  h += card('가정변수 영향도',"""
NEW_IC6_SENS = """  h += icChartCard('영향도 순위', '유리한 쪽 변화폭 기준 · 위쪽이 결과를 지배하는 가정',
    icSvgHBars(r.rows.slice(0, 10).map(function(x){
      var hi2 = Math.max(x.up, x.dn), pc = r.base ? hi2 / r.base : 0;
      return { label:x.label, value:pc * 100, color:ICV.rev2,
               text:(pc >= 0 ? '+' : '') + (pc * 100).toFixed(1) + '%' };
    }), { labelW:150 }));
  h += card('가정변수 영향도',"""

OLD_IC6_STYLE = """.rp-sec .card{margin-bottom:0}"""
NEW_IC6_STYLE = """.rp-sec .card{margin-bottom:12px}
.rp-sec .card:last-child{margin-bottom:0}

/* 차트 — viewBox만 주고 폭은 여기서 잡는다. 인쇄·모바일에서 같이 줄어든다. */
.icv{width:100%;height:auto;display:block}
.chart-box{padding:2px 0}

/* 강조 — 본문에서 결론에 해당하는 조각 하나만 굵게 */
.hl-b{color:#0F0F12;font-weight:700}
ul.memo ul.sub > li .hl-b{color:#374151}

/* 타이포 위계 — 섹션 제목 > 카드 제목 > 본문 > 근거 */
.rp-sec > h2{font-size:17px;letter-spacing:-.03em;color:#0F0F12}
.rp-num{font-size:10px;letter-spacing:.14em}
.rp .section-head h2{font-size:13.5px}
.rp .section-head p{font-size:10px}
.rp p.lead{font-size:13px;color:#1F2937;line-height:1.75;margin-bottom:12px}
.rp ul.memo > li{font-size:12.5px}
.rp ul.memo ul.sub > li{font-size:11.5px}
table.fm td.q{font-weight:700;color:#0F0F12}"""

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
    p.sub("IC-4 아이콘", OLD_IC4_ICON, NEW_IC4_ICON)
    p.sub("IC-4 뷰 라우팅", OLD_IC4_ROUTE, NEW_IC4_ROUTE)
    p.sub("IC-4 뷰 제목", OLD_IC4_TITLES, NEW_IC4_TITLES)
    p.sub("IC-4 사이드바", OLD_IC4_NAV, NEW_IC4_NAV)
    p.sub("IC-4 아이디어·리포트 구현", OLD_IC4_ANCHOR, NEW_IC4_ANCHOR)
    p.sub("IC-4 심사 결론에 쟁점", OLD_IC4_VERDICT, NEW_IC4_VERDICT)
    p.sub("IC-4 스타일·인쇄", OLD_IC4_STYLE, NEW_IC4_STYLE)
    p.sub("IC-5 아이콘", OLD_IC5_ICON, NEW_IC5_ICON)
    p.sub("IC-5 뷰 라우팅", OLD_IC5_ROUTE, NEW_IC5_ROUTE)
    p.sub("IC-5 뷰 제목", OLD_IC5_TITLES, NEW_IC5_TITLES)
    p.sub("IC-5 사이드바", OLD_IC5_NAV, NEW_IC5_NAV)
    p.sub("IC-5 모니터링·민감도·인용 구현", OLD_IC5_ANCHOR, NEW_IC5_ANCHOR)
    p.sub("IC-5 인용 치환 (쟁점)", OLD_IC5_DEBATE, NEW_IC5_DEBATE)
    p.sub("IC-5 밸류에이션에 컨센서스", OLD_IC5_VAL, NEW_IC5_VAL)
    p.sub("IC-5 리포트에 컨센서스", OLD_IC5_RPVAL, NEW_IC5_RPVAL)
    p.sub("IC-5 리포트에 분기 진행", OLD_IC5_RPRISK, NEW_IC5_RPRISK)
    p.sub("IC-5 토네이도 스타일", OLD_IC5_STYLE, NEW_IC5_STYLE)
    p.sub("IC-6 차트 렌더러", OLD_IC6_ANCHOR, NEW_IC6_ANCHOR)
    p.sub("IC-6 강조 문법", OLD_IC6_RICH, NEW_IC6_RICH)
    p.sub("IC-6 진행 강조", OLD_IC6_FALS, NEW_IC6_FALS)
    p.sub("IC-6 반증 강조", OLD_IC6_FALS2, NEW_IC6_FALS2)
    p.sub("IC-6 쟁점 강조", OLD_IC6_DEB, NEW_IC6_DEB)
    p.sub("IC-6 리포트 §3 차트", OLD_IC6_RP3, NEW_IC6_RP3)
    p.sub("IC-6 리포트 §4 차트", OLD_IC6_RP4, NEW_IC6_RP4)
    p.sub("IC-6 피어 막대", OLD_IC6_PEER, NEW_IC6_PEER)
    p.sub("IC-6 피어 막대 배치", OLD_IC6_PEER2, NEW_IC6_PEER2)
    p.sub("IC-6 시나리오 막대", OLD_IC6_SCEN, NEW_IC6_SCEN)
    p.sub("IC-6 분기 차트", OLD_IC6_QT, NEW_IC6_QT)
    p.sub("IC-6 민감도 막대", OLD_IC6_SENS, NEW_IC6_SENS)
    p.sub("IC-6 타이포·차트 스타일", OLD_IC6_STYLE, NEW_IC6_STYLE)
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
