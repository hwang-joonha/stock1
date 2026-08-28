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
