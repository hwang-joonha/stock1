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

# Node로 옮겨야 하는 최상위 선언. 순서가 곧 파일 순서다.
ENGINE_NAMES = [
    "META",
    "YRS",
    "HIST_N",
    "UNITS",
    "MODEL",
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
]

# 템플릿 세대에만 있는 선언. 원본에는 없으므로 없어도 넘어간다.
OPTIONAL_NAMES = {"META", "UNITS", "evalAstAt"}

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


def build_script(html_path: str) -> str:
    """모델 HTML에서 Node 실행용 JS 소스를 만든다."""
    engine = extract(html_path, ENGINE_NAMES, OPTIONAL_NAMES)
    # 선언은 원문 그대로 두되, 재할당이 필요한 것만 let으로 완화한다.
    engine = engine.replace("const SV=", "var _unused_SV=")
    return _PRELUDE + engine + _EPILOGUE


def run(html_path: str) -> dict:
    """모델을 평가하고 노드별 산출값·에러를 담은 dict를 돌려준다."""
    script = build_script(html_path)
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


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("사용법: harness.py <model.html>")
    print(json.dumps(run(sys.argv[1]), ensure_ascii=False, indent=2))
