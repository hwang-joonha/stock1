#!/usr/bin/env python3
"""연결 (포괄)손익계산서 누적값으로 분기 시계열을 만든다 — 부문 주석이 없거나
부문 분해가 필요 없는 종목용. build_quarterly.py(삼성전기, 부문 주석)의 자매다.

분기값 = 누적의 차분. Q4는 사업보고서 연간값 − 3분기 누적.
연간 합이 historicals(G1 대사 기준)와 일치하는지 종목마다 검사하고
어긋나면 죽는다 — 손익계산서 파싱의 교차검증이다.

사용:
    python3 tools/build_quarterly_is.py ktg tlb lgd sec   # 인자 없으면 전부
"""
from __future__ import annotations

import json
import sys

import dart_fetch as dart

# (연도, 마감월, 접수번호) — 마감월이 누적 기간의 길이. 12월은 사업보고서.
REPORTS = {
    "ktg": [
        (2024, 3, "20240516002242"), (2024, 6, "20240814004243"),
        (2024, 9, "20241114002373"), (2024, 12, "20250318001223"),
        (2025, 3, "20250515002949"), (2025, 6, "20250814004354"),
        (2025, 9, "20251114002334"), (2025, 12, "20260318001422"),
        (2026, 3, "20260515002914"), (2026, 6, "20260814004174"),
    ],
    "tlb": [
        (2024, 3, "20240514000415"), (2024, 6, "20240814000814"),
        (2024, 9, "20241114000391"), (2024, 12, "20250320000811"),
        (2025, 3, "20250515000020"), (2025, 6, "20250812000275"),
        (2025, 9, "20251112000023"), (2025, 12, "20260320000683"),
        (2026, 3, "20260512000147"), (2026, 6, "20260814000485"),
    ],
    "lgd": [
        (2024, 3, "20240516000527"), (2024, 6, "20240814001595"),
        (2024, 9, "20241114001936"), (2024, 12, "20250312000906"),
        (2025, 3, "20250515000488"), (2025, 6, "20250814001668"),
        (2025, 9, "20251114000927"), (2025, 12, "20260311003822"),
        (2026, 3, "20260515000570"), (2026, 6, "20260814001005"),
    ],
    "sec": [
        (2024, 3, "20240516001421"), (2024, 6, "20240814003284"),
        (2024, 9, "20241114002642"), (2024, 12, "20250311001085"),
        (2025, 3, "20250515001922"), (2025, 6, "20250814003156"),
        (2025, 9, "20251114002447"), (2025, 12, "20260310002820"),
        (2026, 3, "20260515002181"), (2026, 6, "20260814003699"),
    ],
    # 삼성전기 — 부문 분해는 build_quarterly.py가 만든다. 여기서는 손익계산서의
    # 매출원가·순이익만 뽑아 기존 quarterly.json의 합계 레코드에 병합한다.
    "samsung-em": [
        (2024, 3, "20240516002024"), (2024, 6, "20240814004285"),
        (2024, 9, "20241114002537"), (2024, 12, "20250311001190"),
        (2025, 3, "20250515002323"), (2025, 6, "20250814004371"),
        (2025, 9, "20251114002848"), (2025, 12, "20260310003071"),
        (2026, 3, "20260515002842"), (2026, 6, "20260814003805"),
    ],
}
MERGE_ONLY = {"samsung-em"}   # 기존 quarterly.json에 새 지표만 병합

# 억원 환산 제수. 손익계산서 단위가 회사마다 다르다.
DIV = {"원": 100000000, "천원": 100000, "백만원": 100}

# historicals의 연간 확정과 대사할 때의 허용오차(억원).
# KT&G historicals가 억원 정수로 반올림돼 있어 크고, 나머지는 환산 잔차 수준.
TOL = {"ktg": 0.8, "tlb": 5e-4, "lgd": 0.02, "sec": 0.02,
       "samsung-em": 0.02}  # 분기값을 4자리로 저장하므로 그 반올림 잔차까지 허용


def build(co: str) -> None:
    hist = json.load(open(f"companies/{co}/historicals.json", encoding="utf-8"))
    rev_key = "total_revenue" if "total_revenue" in hist else "revenue"
    yrs = hist["_연도"]

    cum: dict[tuple[int, int], dict] = {}
    for year, month, rcp in REPORTS[co]:
        print(f"  {co} {year} {month:>2}M  {rcp}", file=sys.stderr)
        r = dart.iscum(rcp)
        div = DIV[r["unit"]]
        cum[(year, month)] = {
            "매출": r["rev"] / div, "영업이익": r["op"] / div,
            # 매출원가·순이익(전체 — 지배·비지배 배분 전)은 이익률 차트 전용.
            "매출원가": r["cogs"] / div if r["cogs"] is not None else None,
            "순이익": r["ni"] / div if r["ni"] is not None else None,
        }

    quarters = {}
    for (year, month), rows in sorted(cum.items()):
        prev = cum.get((year, month - 3)) if month > 3 else None
        q = f"{year}Q{month // 3}"
        rec = {}
        for k in ("매출", "영업이익", "매출원가", "순이익"):
            if rows[k] is None or (prev and prev[k] is None):
                continue
            v = rows[k] - (prev[k] if prev else 0)
            # 매출원가는 XBRL 부호(비용 음수)로 공시하는 회사가 있다(KT&G) —
            # 성격상 양수인 값이므로 크기로 정규화한다.
            rec[k] = round(abs(v) if k == "매출원가" else v, 4)
        quarters[q] = {"합계": rec}

    # 연간 대사 — 4분기 합 = historicals 확정값.
    for y in ("2024", "2025"):
        if y not in yrs:
            continue
        yi = yrs.index(y)
        for k, node in (("매출", rev_key), ("영업이익", "op_profit")):
            s = sum(quarters[f"{y}Q{n}"]["합계"][k] for n in range(1, 5))
            want = hist[node][yi]
            if abs(s - want) > TOL[co]:
                raise SystemExit(f"{co} {y} {k}: 분기합 {s:,.4f} ≠ 연간 {want:,.4f}")

    path = f"companies/{co}/quarterly.json"
    if co in MERGE_ONLY:
        # 부문 기반 quarterly.json에 매출원가·순이익만 병합. 매출·영업이익은
        # 부문 주석 합계가 정본 — 손익계산서 값과의 차이가 있으면 죽는다.
        doc = json.load(open(path, encoding="utf-8"))
        for q, qrec in quarters.items():
            rec = qrec["합계"]
            base = doc["quarters"].get(q, {}).get("합계")
            if base is None:
                raise SystemExit(f"{co} {q}: 기존 quarterly.json에 없는 분기")
            # 부문 주석은 백만원 반올림, 손익계산서는 원 단위 — 0.1억까지 허용.
            if abs(base["매출"] - rec["매출"]) > 0.1:
                raise SystemExit(f"{co} {q} 매출: 손익계산서 {rec['매출']:,.4f} ≠ 부문합 {base['매출']:,.4f}")
            for k in ("매출원가", "순이익"):
                if k in rec:
                    base[k] = rec[k]
        doc["_방법"] = doc.get("_방법", "") + " 매출원가·순이익은 손익계산서 누적 차분 병합(build_quarterly_is.py)."
        json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{path} 병합 — 매출원가·순이익 {len(quarters)}개 분기")
        return

    out = {
        "_단위": "억원",
        "_출처": "DART 정기보고서 연결 (포괄)손익계산서 — 누적의 차분",
        "_방법": ("분기값 = 누적 차분, Q4 = 사업보고서 연간 − 3분기 누적. "
                 "4분기 합 = historicals 연간 확정값 대사를 통과해야 저장된다. "
                 "부문 분해 없음(합계만) — 부문 주석 기반은 build_quarterly.py. "
                 "매출원가·순이익(전체 기준)은 이익률 차트 전용."),
        "_보고서": [f"{y}-{m:02d} {r}" for y, m, r in REPORTS[co]],
        "quarters": quarters,
    }
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{path} 생성 — {len(quarters)}개 분기, 연간 대사 통과")


def main(argv: list[str]) -> int:
    for co in (argv or list(REPORTS)):
        build(co)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
