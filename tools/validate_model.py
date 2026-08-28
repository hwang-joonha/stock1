#!/usr/bin/env python3
"""모델 HTML 검증 게이트.

Tesla 작업에서 사람이 눈으로 돌리던 검사를 코드로 옮긴 것이다.
전부 통과해야 다음 단계로 넘어간다. 통과하지 못한 게이트는 조용히 넘어가지
않고 이유를 밝힌다 — 아직 구현하지 않은 게이트도 "미구현"이라고 말한다.

사용:
    python3 tools/validate_model.py companies/samsung-em/model.html
    python3 tools/validate_model.py --all
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_engine import main_script  # noqa: E402
from harness import run as run_model  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GOLDEN = os.path.join(HERE, "fixtures", "tesla_golden.json")
TESLA_DATA = os.path.join(HERE, "fixtures", "tesla_data.js")

TOL = 1e-9

# 입력 노드의 desc는 추정 성격을 밝히는 태그로 시작해야 한다.
# 방법론 문서의 객관/주관 구분이 모델 안에서도 유지되게 하는 장치다.
DESC_TAGS = ("[객관]", "[주관]", "[외생]", "[계산]")
_TAG_RE = re.compile(r"^\[(객관|주관|외생|계산)[^\]]*\]")


class Result:
    def __init__(self, gate: str, name: str):
        self.gate = gate
        self.name = name
        self.status = "ok"          # ok | fail | skip
        self.detail = ""

    def fail(self, detail: str) -> "Result":
        self.status = "fail"
        self.detail = detail
        return self

    def skip(self, detail: str) -> "Result":
        self.status = "skip"
        self.detail = detail
        return self

    def ok(self, detail: str = "") -> "Result":
        self.detail = detail
        return self


def _fmt_cells(items: list[str], limit: int = 6) -> str:
    head = ", ".join(items[:limit])
    return head + (f" 외 {len(items) - limit}건" if len(items) > limit else "")


# ── G1 ────────────────────────────────────────────────────────
def g1_historicals(rep: dict, data_dir: str) -> Result:
    """실적 구간 값이 공시 확정값과 일치하는가.

    data_dir/historicals.json이 {노드id: [실적 연도 값...]} 형태로 있으면
    비교한다. 없으면 건너뛰되 건너뛴 사실을 남긴다 — 공시 확정 없이
    다음 단계로 가지 않게 하는 것이 이 게이트의 목적이다.
    """
    r = Result("G1", "실적 구간 공시값 일치")
    path = os.path.join(data_dir, "historicals.json")
    if not os.path.exists(path):
        return r.skip(f"{os.path.relpath(path, ROOT)} 없음 — 공시 확정 전")

    with open(path, encoding="utf-8") as fh:
        expected = json.load(fh)
    # _로 시작하는 키는 출처·단위 메모다. 노드가 아니므로 건너뛴다.
    expected = {k: v for k, v in expected.items() if not k.startswith("_")}
    if not expected:
        return r.skip(f"{os.path.relpath(path, ROOT)}에 대사할 노드가 없음")
    hist_n = rep["HIST_N"]
    bad = []
    for node, vals in expected.items():
        got = rep["values"].get(node)
        if got is None:
            bad.append(f"{node}: 모델에 없음")
            continue
        for i, want in enumerate(vals[:hist_n]):
            if abs(got[i] - want) > max(TOL, abs(want) * 1e-9):
                bad.append(f"{node}@{rep['YRS'][i]} {got[i]:,.3f} ≠ {want:,.3f}")
    if bad:
        return r.fail(_fmt_cells(bad))
    n = sum(len(v[:hist_n]) for v in expected.values())
    return r.ok(f"{len(expected)}개 노드 × 실적 {hist_n}개년 = {n}셀 일치")


# ── G2 ────────────────────────────────────────────────────────
def g2_parent_sum(rep: dict) -> Result:
    """합계형 노드의 값이 자식 합과 같은가."""
    r = Result("G2", "부모 = 자식 합")
    bad = []
    for node, kids in rep["sumNodes"].items():
        for i in range(len(rep["YRS"])):
            total = sum(rep["values"][k][i] for k in kids)
            v = rep["values"][node][i]
            scale = max(1.0, abs(v))
            if abs(total - v) / scale > 1e-6:
                bad.append(f"{node}@{rep['YRS'][i]} {v:,.3f} ≠ {total:,.3f}")
                break
    if bad:
        return r.fail(_fmt_cells(bad))
    if not rep["sumNodes"]:
        return r.ok("합계형 노드 없음")
    return r.ok(f"합계형 {len(rep['sumNodes'])}개 노드 전부 일치")


# ── G3 ────────────────────────────────────────────────────────
def g3_eval_errors(rep: dict) -> Result:
    """평가 오류·순환참조가 없는가."""
    r = Result("G3", "노드 평가 · 순환참조")
    if rep["errors"]:
        return r.fail(_fmt_cells([f"{k}: {v}" for k, v in rep["errors"].items()]))
    return r.ok(f"{rep['nodes']}개 노드 전부 평가 성공")


# ── G4 ────────────────────────────────────────────────────────
def g4_defaults(rep: dict) -> Result:
    """INPUT_KEYS와 DEFAULTS_S가 일치하는가.

    템플릿에서 DEFAULTS_S를 MODEL에서 파생하도록 바꿔 구조적으로 어긋날 수
    없게 됐다. 그래도 확인은 남긴다 — 파생이 깨지면 여기서 잡힌다.
    """
    r = Result("G4", "INPUT_KEYS ↔ DEFAULTS_S")
    only_in = sorted(set(rep["inputs"]) - set(rep["defaults"]))
    only_de = sorted(set(rep["defaults"]) - set(rep["inputs"]))
    if only_in or only_de:
        parts = []
        if only_in:
            parts.append("DEFAULTS_S 누락: " + ", ".join(only_in))
        if only_de:
            parts.append("INPUT_KEYS 누락: " + ", ".join(only_de))
        return r.fail(" / ".join(parts))
    return r.ok(f"입력 {len(rep['inputs'])}개 키 완전 일치")


# ── G5 ────────────────────────────────────────────────────────
def g5_lengths(rep: dict) -> Result:
    """모든 노드의 값 배열 길이가 YRS와 같은가."""
    r = Result("G5", "값 배열 길이 = YRS 길이")
    n = len(rep["YRS"])
    bad = [f"{k}: {ln}개" for k, ln in rep["lengths"].items() if ln != n]
    if bad:
        return r.fail(f"YRS는 {n}개년 — " + _fmt_cells(bad))
    return r.ok(f"{len(rep['lengths'])}개 노드 전부 {n}개년")


# ── G6 ────────────────────────────────────────────────────────
def g6_unused(rep: dict) -> Result:
    """어떤 수식도 참조하지 않는 가정변수가 있는가."""
    r = Result("G6", "미사용 가정변수")
    if rep["unusedInputs"]:
        return r.fail(", ".join(rep["unusedInputs"]) + " — 어떤 계산에도 쓰이지 않음")
    return r.ok("모든 가정변수가 계산에 반영됨")


# ── G7 ────────────────────────────────────────────────────────
def g7_excel(rep: dict) -> Result:
    """HTML 산출값과 Excel 수식 평가값의 셀 단위 대사."""
    r = Result("G7", "HTML ↔ Excel 대사")
    return r.skip("build_excel.py 미구현 — Phase 3에서 연결")


# ── G8 ────────────────────────────────────────────────────────
def g8_structure(html_path: str, rep: dict) -> Result:
    """JS 문법이 유효하고, 루트에서 도달 못 하는 고아 노드가 없는가."""
    r = Result("G8", "JS 문법 · 트리 연결")
    problems = []

    with open(html_path, encoding="utf-8") as fh:
        script = main_script(fh.read())
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(script)
        tmp = fh.name
    try:
        proc = subprocess.run(["node", "--check", tmp],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            first = (proc.stderr.strip().splitlines() or ["문법 오류"])[0]
            problems.append("문법: " + first)
    finally:
        os.unlink(tmp)

    if rep["orphans"]:
        problems.append("루트에서 도달 불가: " + ", ".join(rep["orphans"]))

    if problems:
        return r.fail(" / ".join(problems))
    return r.ok("문법 유효 · 전 노드가 루트에 연결됨")


# ── G9 ────────────────────────────────────────────────────────
def g9_golden() -> Result:
    """엔진이 Tesla 골든 샘플을 그대로 재현하는가.

    템플릿 엔진에 Tesla 데이터를 주입해 빌드하고, 원본 산출값과 비교한다.
    엔진을 고칠 때마다 이 게이트가 회귀를 잡는다.
    """
    r = Result("G9", "Tesla 골든 회귀")
    if not os.path.exists(GOLDEN):
        return r.skip(f"{os.path.relpath(GOLDEN, ROOT)} 없음")

    from build_model import build

    with open(GOLDEN, encoding="utf-8") as fh:
        golden = json.load(fh)

    html = build(TESLA_DATA)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(html)
        tmp = fh.name
    try:
        rep = run_model(tmp)
    finally:
        os.unlink(tmp)

    if rep["errors"]:
        return r.fail("재빌드에서 평가 오류: " + _fmt_cells(list(rep["errors"])))

    bad, worst, cells = [], 0.0, 0
    for node, vals in golden["values"].items():
        got = rep["values"].get(node)
        if got is None:
            bad.append(f"{node}: 재빌드에 없음")
            continue
        for i, want in enumerate(vals):
            cells += 1
            d = abs(got[i] - want)
            worst = max(worst, d)
            if d > TOL:
                bad.append(f"{node}@{golden['YRS'][i]} {got[i]:.6f} ≠ {want:.6f}")
    if bad:
        return r.fail(_fmt_cells(bad))
    return r.ok(f"{cells}셀 재현 · 최대 절대오차 {worst:.1e}")


# ── desc 태그 ─────────────────────────────────────────────────
def g_desc_tags(rep: dict) -> Result:
    """입력 노드의 근거가 추정 성격 태그로 시작하는가."""
    r = Result("G10", "입력 노드 근거 태그")
    bad = []
    for k in rep["inputs"]:
        desc = (rep["descs"].get(k) or "").strip()
        if not desc:
            bad.append(f"{k}: desc 없음")
        elif not _TAG_RE.match(desc):
            bad.append(f"{k}: 태그 없음")
    if bad:
        return r.fail(
            _fmt_cells(bad) + f" — {'/'.join(DESC_TAGS)} 중 하나로 시작해야 함"
        )
    return r.ok(f"입력 {len(rep['inputs'])}개 전부 태그 있음")


def validate(html_path: str, skip_golden: bool = False) -> list[Result]:
    rep = run_model(html_path)
    data_dir = os.path.dirname(os.path.abspath(html_path))
    results = [
        g1_historicals(rep, data_dir),
        g2_parent_sum(rep),
        g3_eval_errors(rep),
        g4_defaults(rep),
        g5_lengths(rep),
        g6_unused(rep),
        g7_excel(rep),
        g8_structure(html_path, rep),
        g_desc_tags(rep),
    ]
    if not skip_golden:
        results.append(g9_golden())
    return results


MARK = {"ok": "PASS", "fail": "FAIL", "skip": "SKIP"}


def report(html_path: str, results: list[Result]) -> bool:
    print(f"\n{os.path.relpath(html_path, ROOT)}")
    print("─" * 78)
    for r in results:
        print(f"  {MARK[r.status]:4}  {r.gate:3} {r.name:22} {r.detail}")
    failed = [r for r in results if r.status == "fail"]
    skipped = [r for r in results if r.status == "skip"]
    print("─" * 78)
    if failed:
        print(f"  실패 {len(failed)}건" + (f" · 미실행 {len(skipped)}건" if skipped else ""))
    else:
        print(f"  전 게이트 통과" + (f" · 미실행 {len(skipped)}건" if skipped else ""))
    return not failed


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="모델 검증 게이트")
    ap.add_argument("model", nargs="*", help="검증할 model.html")
    ap.add_argument("--all", action="store_true",
                    help="companies/*/model.html 전부 검증")
    args = ap.parse_args(argv)

    targets = list(args.model)
    if args.all:
        targets += sorted(glob.glob(os.path.join(ROOT, "companies", "*", "model.html")))
    if not targets:
        ap.error("검증할 모델을 지정하거나 --all을 쓰세요.")

    all_ok = True
    for i, path in enumerate(targets):
        # 골든 회귀는 엔진 검사라 모델마다 반복할 필요가 없다.
        ok = report(path, validate(path, skip_golden=(i > 0)))
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
