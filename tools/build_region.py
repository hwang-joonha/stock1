#!/usr/bin/env python3
"""사업보고서 주석의 지역별 매출을 이어 붙여 regions.json을 만든다.

화면 전용, 모델 비투입 — 사업 구조 뷰의 지역별 매출 카드가 읽는다.
각 사업보고서는 당기/전기 두 해를 주므로 보고서 3건이면 5개년이 나온다.
Σ지역 = 합계와, 합계 = historicals 연결 매출(겹치는 연도) 대사를 통과해야
저장된다. 지역 라벨은 그 보고서 공시 그대로 — 해에 따라 라벨이 바뀌면
그대로 별도 열이 된다(_기준에 명시).

지역별 공시가 없는 종목은 파일을 만들지 않는다 — 화면은 조용히 빠진다.

사용:
    python3 tools/build_region.py            # 전 종목
"""
from __future__ import annotations

import json
import sys

import dart_fetch as dart

# (회계연도, 접수번호) — 당기/전기 = fy, fy-1. 최신 보고서 우선.
REPORTS = {
    "samsung-em": [(2025, "20260310003071"), (2024, "20250311001190"),
                   (2022, "20230307000653")],
    "ktg":        [(2025, "20260318001422"), (2024, "20250318001223"),
                   (2023, "20240320001212")],
    "lgd":        [(2025, "20260311003822"), (2024, "20250312000906"),
                   (2022, "20230313000751")],
    "sec":        [(2025, "20260310002820"), (2024, "20250311001085"),
                   (2022, "20230307000542")],
    "tlb":        [(2025, "20260320000683"), (2024, "20250320000811"),
                   (2022, "20230320000695")],
}

DIV = {"원": 100000000, "천원": 100000, "백만원": 100}
TOL = {"ktg": 0.8}   # historicals가 억원 정수인 종목만 크게


def build(co: str) -> bool:
    hist = json.load(open(f"companies/{co}/historicals.json", encoding="utf-8"))
    rev_key = "total_revenue" if "total_revenue" in hist else "revenue"
    hyrs = hist["_연도"]
    tol = TOL.get(co, 0.02)

    by_year: dict[int, dict] = {}
    totals: dict[int, float] = {}
    srcs = []
    for fy, rcp in REPORTS[co]:
        print(f"  {co} FY{fy}  {rcp}", file=sys.stderr)
        try:
            r = dart.region(rcp)
        except SystemExit as e:
            print(f"    건너뜀: {e}", file=sys.stderr)
            continue
        div = DIV[r["unit"]]
        for y, block, tot in ((fy, r["cur"], r["cur_total"]),
                              (fy - 1, r["prev"], r["prev_total"])):
            if y in by_year or not block:
                continue
            by_year[y] = {k: v / div for k, v in block.items()}
            if tot is not None:
                totals[y] = tot / div
        srcs.append(f"FY{fy} {rcp}")

    if not by_year:
        print(f"  {co}: 지역별 공시 없음 — regions.json 생략", file=sys.stderr)
        return False

    # 대사 — Σ지역 = 합계, 합계 = historicals 연결 매출(겹치는 연도).
    bad = []
    for y, block in sorted(by_year.items()):
        s = sum(block.values())
        if y in totals and abs(s - totals[y]) > max(tol, abs(totals[y]) * 1e-6):
            bad.append(f"{y}: Σ지역 {s:,.2f} ≠ 표 합계 {totals[y]:,.2f}")
        if str(y) in hyrs:
            want = hist[rev_key][hyrs.index(str(y))]
            if abs(totals.get(y, s) - want) > max(tol, abs(want) * 1e-6):
                bad.append(f"{y}: 지역 합계 {totals.get(y, s):,.2f} ≠ 연결 매출 {want:,.2f}")
    if bad:
        raise SystemExit(f"{co} 지역 대사 실패:\n  " + "\n  ".join(bad))

    years = sorted(by_year)
    regions: list[str] = []
    for y in years:                     # 등장 순서 유지 — 최신 보고서의 순서 우선
        for k in by_year[y]:
            if k not in regions:
                regions.append(k)
    rev = {rg: [round(by_year[y].get(rg), 2) if rg in by_year[y] else None
                for y in years] for rg in regions}

    out = {
        "_설명": "지역별 매출 — 사업 구조 뷰 전용, 모델 비투입.",
        "_단위": "억원",
        "_기준": ("사업보고서 주석 '지역에 대한 공시'의 당기/전기를 이어 붙임. "
                 "지역 라벨은 각 보고서 공시 그대로 — 해에 따라 바뀌면 별도 열로 남는다. "
                 "Σ지역 = 합계, 합계 = 연결 매출(겹치는 연도) 대사 통과."),
        "_출처": srcs,
        "years": [str(y) for y in years],
        "regions": regions,
        "rev": rev,
    }
    path = f"companies/{co}/regions.json"
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{path} — {years[0]}~{years[-1]} ({len(years)}년) · 지역 {len(regions)}개")
    return True


def main(argv: list[str]) -> int:
    rc = 0
    for co in (argv or list(REPORTS)):
        try:
            build(co)
        except SystemExit as e:      # 한 종목의 실패가 다음 종목을 막지 않는다
            print(e, file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
