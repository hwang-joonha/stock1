#!/usr/bin/env python3
"""model.html의 데이터·수식 엔진을 Node에서 실행할 수 있게 감싼다.

브라우저 밖에서 모델을 돌리는 유일한 경로다. validate_model.py가 이걸 써서
검증 게이트를 돌리고, 회귀 비교도 여기서 나온 산출값으로 한다.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile

from extract_engine import extract

# 데이터 블록 마커. 빌드된 모델에서는 이 구간을 통째로 가져온다 —
# 이름 단위로 뽑으면 데이터 파일이 헬퍼 변수를 못 쓰게 된다.
DATA_START = "// <<<DATA:START>>>"
DATA_END = "// <<<DATA:END>>>"

# Node로 옮겨야 하는 최상위 선언. 순서가 곧 파일 순서다.
# 데이터 블록(META/YRS/HIST_N/UNITS/MODEL)은 마커로 따로 가져온다.
ENGINE_NAMES = [
    "DEFAULTS_S",
    "INPUT_KEYS",
    "TREE",
    "GRAPH",
    "buildGraph",
    "graphDeps",
    "buildTree",
    "tokenize",
    "parseFormula",
    "extractDeps",
    "evalAst",
    "evalAstAt",
    "topoSort",
    "simCalc",
    "clearFormulaCache",
    "childrenOf",
    "rootId",
    "isSumOfChildren",
    "unusedInputs",
    "val",
    "isMoney",
    "fmtSmart",
    "astToExcel",
    "_colLetter",
    "_excelNumberFormat",
    "depthOf",
    "pathOf",
]

# 템플릿 세대에만 있는 선언. 패치 전 원본에는 없으므로 없어도 넘어간다.
OPTIONAL_NAMES = {"META", "UNITS", "evalAstAt", "MARKET", "MEMO", "SCENARIOS"}

# 마커가 없는 파일(패치 전 원본)은 이름 단위로 되돌아간다.
LEGACY_DATA_NAMES = ["META", "YRS", "HIST_N", "UNITS", "MODEL"]

# DEFAULTS_S를 SV로 복사하는 한 줄은 원본에서 다른 선언과 같은 줄에 붙어 있어
# 이름 단위로 떼어낼 수 없다. 여기서 다시 쓴다.
_PRELUDE = """
'use strict';
const SV = {}, SR = {};
"""

_EPILOGUE = """
for (const k in DEFAULTS_S) SV[k] = DEFAULTS_S[k].slice();
TREE = buildTree();
GRAPH = buildGraph();
INPUT_KEYS = new Set(Object.keys(MODEL).filter(k => MODEL[k].type === 'input'));
simCalc();

const report = {
  YRS, HIST_N,
  nodes: Object.keys(MODEL).length,
  inputs: [...INPUT_KEYS],
  defaults: Object.keys(DEFAULTS_S),
  values: {},
  errors: {},
  lengths: {},
  descs: {},
  sumNodes: {},
  orphans: [],
  unusedInputs: unusedInputs(),
};
for (const k in MODEL) {
  report.values[k] = MODEL[k].v.slice();
  report.lengths[k] = (MODEL[k].v || []).length;
  report.descs[k] = MODEL[k].desc || '';
  if (MODEL[k]._error) report.errors[k] = MODEL[k]._error;
  // 수식이 자식들의 단순 합인 노드. G2가 이 노드들만 대사한다.
  if (isSumOfChildren(k)) report.sumNodes[k] = childrenOf(k);
}
// 루트에서 부모 링크를 따라 닿지 않는 노드
const reach = {};
(function walk(id) { reach[id] = 1; childrenOf(id).forEach(walk); })(rootId());
report.orphans = Object.keys(MODEL).filter(k => !reach[k]);

process.stdout.write(JSON.stringify(report));
"""

_EXCEL_EPILOGUE = """
for (const k in DEFAULTS_S) SV[k] = DEFAULTS_S[k].slice();
TREE = buildTree();
GRAPH = buildGraph();
INPUT_KEYS = new Set(Object.keys(MODEL).filter(k => MODEL[k].type === 'input'));
simCalc();

// 계정 트리 순서 — 화면과 같은 순서로 시트를 만든다.
const order = [];
(function walk(id, depth) {
  order.push(id);
  childrenOf(id).forEach(c => walk(c, depth + 1));
})(rootId(), 0);

// 행 배치는 파이썬과 약속된 값이다. 여기서 정하고 수식도 여기서 만든다.
const DATA_ROW0 = 5;                       // 1행부터 4행은 머리말
const rowMap = {};
order.forEach((id, i) => { rowMap[id] = DATA_ROW0 + i; });

const out = {
  YRS, HIST_N, order, rowMap, dataRow0: DATA_ROW0,
  meta: (typeof META === 'object' && META) ? META : {},
  units: (typeof UNITS === 'object' && UNITS) ? UNITS : {},
  nodes: {}, formulas: {},
};
order.forEach(id => {
  const d = MODEL[id];
  out.nodes[id] = {
    label: d.label || id, sub: d.sub || '', unit: d.u || '',
    type: d.type, formula: d.formula || '', desc: d.desc || '',
    pct: d.pct ? 1 : 0, depth: depthOf(id), isSum: isSumOfChildren(id) ? 1 : 0,
    values: (d.v || []).slice(),
    numfmt: _excelNumberFormat(d),
  };
  if (d.type === 'computed' && d._ast) {
    const fs = [];
    for (let t = 0; t < YRS.length; t++) {
      try { fs.push('=' + astToExcel(d._ast, t, rowMap)); }
      catch (e) { fs.push(null); }
    }
    out.formulas[id] = fs;
  }
});
process.stdout.write(JSON.stringify(out));
"""


def data_block(html_path: str) -> str:
    """데이터 블록을 통째로 돌려준다. 마커가 없으면 이름 단위로 뽑는다."""
    with open(html_path, encoding="utf-8") as fh:
        html = fh.read()
    head = html.find(DATA_START)
    tail = html.find(DATA_END)
    if head != -1 and tail > head:
        return html[head + len(DATA_START):tail]
    return extract(html_path, LEGACY_DATA_NAMES, OPTIONAL_NAMES)


def build_script(html_path: str, epilogue: str = _EPILOGUE) -> str:
    """모델 HTML에서 Node 실행용 JS 소스를 만든다."""
    engine = data_block(html_path) + "\n\n" + extract(
        html_path, ENGINE_NAMES, OPTIONAL_NAMES)
    # 선언은 원문 그대로 두되, 재할당이 필요한 것만 let으로 완화한다.
    engine = engine.replace("const SV=", "var _unused_SV=")
    return _PRELUDE + engine + epilogue


def run(html_path: str, epilogue: str = _EPILOGUE) -> dict:
    """모델을 평가하고 노드별 산출값·에러를 담은 dict를 돌려준다."""
    script = build_script(html_path, epilogue)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(script)
        tmp = fh.name
    try:
        proc = subprocess.run(["node", tmp], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("모델 실행 실패:\n" + proc.stderr.strip())
        return json.loads(proc.stdout)
    finally:
        os.unlink(tmp)


def excel_payload(html_path: str) -> dict:
    """Excel 빌드에 필요한 것 일체 — 행 배치, 셀 수식, 값, 서식.

    수식 변환은 JS의 astToExcel이 정본이다. 파이썬에 같은 변환기를 두면
    둘이 갈라지고, 갈라지는 순간 G7 대사가 자기 자신을 검사하게 된다.
    """
    return run(html_path, _EXCEL_EPILOGUE)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("사용법: harness.py <model.html>")
    print(json.dumps(run(sys.argv[1]), ensure_ascii=False, indent=2))
