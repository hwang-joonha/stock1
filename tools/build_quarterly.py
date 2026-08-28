#!/usr/bin/env python3
"""분기·반기·사업보고서의 영업부문정보를 모아 분기 실적 시계열을 만든다.

왜 필요한가. 투자 아이디어의 반증 조건은 전부 분기 단위인데(“패키지 감가상각
증가율이 두 분기 연속…”) 모델의 시간축은 연간이다. 그 불일치를 메우려면
분기 확정값이 모델 옆에 있어야 한다.

한국 정기보고서의 영업부문 주석은 **연초부터의 누적**을 준다.
  분기(3월) 당분기 = 3M · 반기 당반기 = 6M · 분기(9월) 당분기 = 9M · 사업 당기 = 12M
그래서 분기값은 누적의 차분으로 만든다. 차분한 값이 음수로 나오면 그건
누적/비누적을 잘못 짚은 것이므로 조용히 넘기지 않고 실패시킨다.

사용:
    python3 tools/build_quarterly.py companies/samsung-em/quarterly.json
"""
from __future__ import annotations

import json
import sys

import dart_fetch as dart

# (연도, 마감월, 접수번호). 마감월이 누적 기간의 길이다.
REPORTS = [
    (2024,  3, "20240516002024"),
    (2024,  6, "20240814004285"),
    (2024,  9, "20241114002537"),
    (2024, 12, "20250311001190"),
    (2025,  3, "20250515002323"),
    (2025,  6, "20250814004371"),
    (2025,  9, "20251114002848"),
    (2025, 12, "20260310003071"),
    (2026,  3, "20260515002842"),
    (2026,  6, "20260814003805"),
]

SEGS = ["컴포넌트", "패키지솔루션", "광학솔루션", "합계"]
METRICS = ["매출", "감가상각비", "영업이익"]


def _current(blocks: dict) -> dict:
    """'당…'으로 시작하는 블록이 당기다. 없으면 실패시킨다."""
    for label, rows in blocks.items():
        if label.startswith("당"):
            return rows
    raise SystemExit(f"당기 블록 없음: {list(blocks)}")


def main(argv: list[str]) -> int:
    out_path = argv[0] if argv else "companies/samsung-em/quarterly.json"

    cum: dict[tuple[int, int], dict] = {}
    for year, month, rcp in REPORTS:
        print(f"  {year} {month:>2}M  {rcp}", file=sys.stderr)
        cum[(year, month)] = _current(dart.segments(rcp))

    quarters = {}
    for (year, month), rows in sorted(cum.items()):
        prev = cum.get((year, month - 3)) if month > 3 else None
        q = f"{year}Q{month // 3}"
        rec = {}
        for seg in SEGS:
            if seg not in rows:
                continue
            rec[seg] = {}
            for m in METRICS:
                v = rows[seg].get(m)
                if v is None:
                    continue
                if prev is not None:
                    p = prev.get(seg, {}).get(m)
                    if p is None:
                        continue
                    v = v - p
                # 백만원 → 억원
                rec[seg][m] = round(v / 100, 1)
        quarters[q] = rec

    # 검산 — 부문 합이 합계와 맞는가. 오차 0이 아니면 파싱이 틀린 것이다.
    bad = []
    for q, rec in quarters.items():
        for m in METRICS:
            parts = [rec[s][m] for s in SEGS[:-1] if m in rec.get(s, {})]
            tot = rec.get("합계", {}).get(m)
            if tot is None or len(parts) != 3:
                continue
            if abs(sum(parts) - tot) > 0.15:      # 반올림 오차 한도
                bad.append(f"{q} {m}: 부문합 {sum(parts):,.1f} ≠ 합계 {tot:,.1f}")
        for s in SEGS:
            v = rec.get(s, {}).get("매출")
            if v is not None and v <= 0:
                bad.append(f"{q} {s} 매출 {v} — 누적/비누적을 잘못 짚었다")
    if bad:
        for b in bad:
            print("  ✗", b, file=sys.stderr)
        raise SystemExit("검산 실패 — 파일을 쓰지 않는다")

    doc = {
        "_단위": "억원",
        "_출처": "DART 정기보고서 영업부문정보 주석 (연결)",
        "_방법": "정기보고서는 연초부터의 누적을 준다. 분기값은 누적의 차분이다. "
                 "부문합 = 합계 검산을 통과한 값만 기록한다.",
        "_보고서": {f"{y}-{m:02d}": r for y, m, r in REPORTS},
        "quarters": quarters,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    print(f"{out_path} — {len(quarters)}개 분기", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, "tools")
    sys.exit(main(sys.argv[1:]))
