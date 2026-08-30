#!/usr/bin/env python3
"""사업보고서 3개년 블록을 이어 붙여 장기(10년+) 매출·영업이익 시계열을 만든다.

사이클 차트 전용 — 모델 노드가 아니다. 각 블록은 그 보고서가 공시한 기준
그대로이며(소급 재작성 시 블록 경계에서 기준이 갈릴 수 있음) _기준에 남긴다.
최근 블록(모델 실적 구간과 겹치는 연도)은 historicals와 대사해 어긋나면 죽는다.

사용:
    python3 tools/build_longhist.py            # 전 종목
"""
from __future__ import annotations

import json
import sys

import dart_fetch as dart

# 사업보고서 (회계연도, 접수번호) — 각각 (당기, 전기, 전전기) 3개년을 준다.
REPORTS = {
    "samsung-em": [(2025, "20260310003071"), (2022, "20230307000653"),
                   (2019, "20200330003915"), (2016, "20170331004394")],
    "ktg":        [(2025, "20260318001422"), (2023, "20240320001212"),
                   (2020, "20210311001208"), (2017, "20180402002962")],
    "lgd":        [(2025, "20260311003822"), (2022, "20230313000751"),
                   (2019, "20200330004446"), (2016, "20170331004319")],
    "sec":        [(2025, "20260310002820"), (2022, "20230307000542"),
                   (2019, "20200330003851"), (2016, "20170331004518")],
    # 티엘비는 2021년 상장 — FY2020 사업보고서(기재정정)가 가장 오래된 3개년 블록.
    "tlb":        [(2025, "20260320000683"), (2022, "20230320000695"),
                   (2020, "20210330000008")],
}
# KT&G는 historicals가 FY2023 보고서 기준(재작성)이라 그 보고서의 3개년 블록을
# 쓰고, 빈 해가 없도록 FY2020·FY2017 보고서로 잇는다 (2015~2025, 11년).

DIV = {"원": 100000000, "천원": 100000, "백만원": 100}
TOL = {"ktg": 0.8}  # historicals가 억원 정수인 종목만 크게


def build(co: str) -> None:
    hist = json.load(open(f"companies/{co}/historicals.json", encoding="utf-8"))
    rev_key = "total_revenue" if "total_revenue" in hist else "revenue"
    hyrs = hist["_연도"]
    tol = TOL.get(co, 0.02)

    series: dict[int, tuple[float, float]] = {}
    fin: dict[int, dict] = {}     # 현금흐름·재무상태 — 같은 보고서들에서 온다
    srcs = []
    for fy, rcp in REPORTS[co]:
        print(f"  {co} FY{fy}  {rcp}", file=sys.stderr)
        r = dart.islong(rcp)
        div = DIV[r["unit"]]
        yrs = r["years"] or [fy - k for k in range(len(r["rev"]))]
        for k, y in enumerate(yrs):
            if y in series:
                continue          # 최신 보고서 우선
            series[y] = (r["rev"][k] / div, r["op"][k] / div)
        srcs.append(f"FY{fy} {rcp}")

        # 현금흐름표·재무상태표 — 실패해도 매출·이익 시계열은 산다.
        try:
            cf = dart.cflong(rcp)
            cdiv = DIV[cf["unit"]]
            cyrs = cf["years"] or yrs
            for k, y in enumerate(cyrs):
                rec = fin.setdefault(y, {})
                for key in ("cfo", "cfi", "cff", "capex"):
                    if key not in rec and cf[key] is not None:
                        rec[key] = cf[key][k] / cdiv
        except SystemExit as e:
            print(f"    현금흐름표 생략: {e}", file=sys.stderr)
        try:
            bs = dart.bslong(rcp)
            bdiv = DIV[bs["unit"]]
            byrs = bs["years"] or yrs
            for k, y in enumerate(byrs):
                rec = fin.setdefault(y, {})
                for key in ("liab", "equity"):
                    if key not in rec and bs[key] is not None:
                        rec[key] = bs[key][k] / bdiv
        except SystemExit as e:
            print(f"    재무상태표 생략: {e}", file=sys.stderr)

    years = sorted(series)
    rev = [round(series[y][0], 2) for y in years]
    op = [round(series[y][1], 2) for y in years]

    def fin_col(key):
        return [round(fin[y][key], 2) if y in fin and key in fin[y] else None
                for y in years]

    cfo, cfi, cff = fin_col("cfo"), fin_col("cfi"), fin_col("cff")
    # CAPEX는 유출이라 음수로 공시된다 — 크기로 정규화. FCF = 영업CF − CAPEX.
    capex = [round(abs(v), 2) if v is not None else None for v in fin_col("capex")]
    fcf = [round(a - b, 2) if a is not None and b is not None else None
           for a, b in zip(cfo, capex)]
    liab, equity = fin_col("liab"), fin_col("equity")

    # 모델 실적 구간과 겹치는 연도 대사 — 파싱·기준의 교차검증.
    bad = []
    for y in hyrs:
        yi = years.index(int(y)) if int(y) in [int(x) for x in years] else -1
        if yi < 0:
            continue
        hi = hyrs.index(y)
        for name, node, arr in (("매출", rev_key, rev), ("영업이익", "op_profit", op)):
            want = hist[node][hi]
            if abs(arr[yi] - want) > tol:
                bad.append(f"{y} {name}: longhist {arr[yi]:,.2f} ≠ historicals {want:,.2f}")
    if bad:
        raise SystemExit(f"{co} 대사 실패:\n  " + "\n  ".join(bad))

    out = {
        "_설명": ("장기 매출·영업이익·현금흐름·재무상태 — 사이클/현금흐름/재무현황 "
                 "차트 전용, 모델 비투입."),
        "_단위": "억원",
        "_기준": ("각 사업보고서의 3개년 블록을 그 보고서 공시 기준 그대로 이어 붙임. "
                 "소급 재작성이 있으면 블록 경계(예: 2022↔2023)에서 기준이 갈릴 수 있다. "
                 "모델 실적 구간과 겹치는 연도는 historicals와 대사 통과. "
                 "capex = 유형자산의 취득(크기), fcf = 영업CF − capex. "
                 "liab·equity = 부채총계·자본총계(연말)."),
        "_출처": srcs,
        "years": [str(y) for y in years],
        "rev": rev,
        "op": op,
        "cfo": cfo, "cfi": cfi, "cff": cff, "capex": capex, "fcf": fcf,
        "liab": liab, "equity": equity,
    }
    path = f"companies/{co}/longhist.json"
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{path} — {years[0]}~{years[-1]} ({len(years)}년), 실적 구간 대사 통과")


def main(argv: list[str]) -> int:
    for co in (argv or list(REPORTS)):
        build(co)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
