#!/usr/bin/env python3
"""야후 파이낸스에서 월간 종가 시계열을 받아 companies/<종목>/prices.json으로 저장한다.

빌드 타임 스냅숏이다 — model.html은 여전히 외부 요청 0건으로 동작한다.
용도는 차트(실적 대 시총 오버레이, 배수 밴드)이며 모델 노드가 아니다.

야후의 가격은 액면분할·무상증자를 소급 조정한 값이라, 현재 상장주식수를
곱하면 과거 시점의 근사 시가총액이 된다 — 유상증자·자사주 소각으로 주식수가
변한 만큼의 오차는 남으며 _기준에 명시한다.

사용:
    python3 tools/price_fetch.py            # 전 종목
    python3 tools/price_fetch.py samsung-em
"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys

CA = "/root/.ccr/ca-bundle.crt"
TICKERS = {
    "samsung-em": "009150.KS",
    "ktg": "033780.KS",
    "tlb": "356860.KQ",
    "lgd": "034220.KS",
    "sec": "005930.KS",
}
INDEX = "^KS11"          # KOSPI — 시장 대비 상대 성과 차트용
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{t}"
       "?range=10y&interval=1mo&events=div%2Csplit")


def _monthly(ticker: str) -> list[dict]:
    out = subprocess.run(
        ["curl", "-sS", "--max-time", "60", "--cacert", CA,
         "-H", "User-Agent: Mozilla/5.0", URL.format(t=ticker)],
        capture_output=True, check=True)
    doc = json.loads(out.stdout)
    res = doc["chart"]["result"][0]
    stamps = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]

    # 같은 달이 중복되면(마지막 미완성 달) 뒤의 것을 쓴다.
    dedup = {}
    for ts, c in zip(stamps, closes):
        if c is None:
            continue
        d = datetime.datetime.utcfromtimestamp(ts)
        dedup[f"{d.year}-{d.month:02d}"] = round(c, 2)
    return [{"d": k, "c": v} for k, v in sorted(dedup.items())]


def fetch(co: str, kospi: list[dict]) -> None:
    t = TICKERS[co]
    monthly = _monthly(t)

    payload = {
        "_출처": f"Yahoo Finance chart API · {t} + {INDEX}(KOSPI) · 월간 종가(월말) · 수집 "
                + datetime.date.today().isoformat(),
        "_기준": ("액면분할·무상증자 소급 조정 종가. 근사 시가총액 = 종가 × 현재 "
                 "상장주식수 — 유상증자·소각에 따른 주식수 변화분은 오차로 남는다. "
                 "kospi는 시장 대비 상대 성과 차트용 지수 종가. 차트 전용, 모델 비투입."),
        "ticker": t,
        "monthly": monthly,
        "kospi": kospi,
    }
    path = f"companies/{co}/prices.json"
    json.dump(payload, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"{path} — {len(monthly)}개월 ({monthly[0]['d']} ~ {monthly[-1]['d']}) + KOSPI {len(kospi)}개월")


def main(argv: list[str]) -> int:
    kospi = _monthly(INDEX)
    for co in (argv or list(TICKERS)):
        fetch(co, kospi)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
