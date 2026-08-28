#!/usr/bin/env python3
"""피어 그룹의 시세·밸류에이션 지표를 한 출처에서 가져온다.

목표배수는 이 모델에서 결과를 가장 크게 좌우하는 가정이다(03_valuation.md §7).
그 근거를 "역사적으로 5~8배"라는 기억이 아니라 **지금 시장이 같은 업종에
매기고 있는 배수**로 대체하기 위한 도구다.

출처를 하나로 고정하는 것이 중요하다. 종목마다 다른 사이트에서 긁으면
EBITDA 정의·기준일이 달라 비교가 성립하지 않는다.

사용:
    python3 tools/peer_fetch.py 009150 011070 222800
    python3 tools/peer_fetch.py --json 009150 011070 > peers.json
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import time

URL = "https://comp.wisereport.co.kr/company/c1010001.aspx?cmp_cd={}"
CA = "/root/.ccr/ca-bundle.crt"
UA = "Mozilla/5.0"


def _fetch(code: str, tries: int = 3) -> tuple[str, str]:
    """(평문, 종목명)을 돌려준다. 종목명은 <title>에서 가져온다."""
    cmd = ["curl", "-sSL", "--max-time", "40", "--cacert", CA,
           "-H", f"User-Agent: {UA}", URL.format(code)]
    for attempt in range(tries):
        out = subprocess.run(cmd, capture_output=True)
        if out.returncode == 0 and out.stdout:
            raw = out.stdout.decode("utf-8", errors="replace")
            m = re.search(r"<title>(.*?)</title>", raw, re.S)
            name = m.group(1).split("-")[0].strip() if m else code
            t = re.sub(r"<(script|style).*?</\1>", " ", raw, flags=re.S | re.I)
            t = re.sub(r"<[^>]+>", " ", t)
            return re.sub(r"\s+", " ", html.unescape(t)), name
        time.sleep(2 ** attempt)
    raise SystemExit(f"{code} 조회 실패")


def _num(s: str | None) -> float | None:
    if not s:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _after(text: str, label: str, pattern: str) -> str | None:
    """label 뒤에서 pattern을 찾는다. 라벨과 값이 떨어져 있는 레이아웃 대응."""
    i = text.find(label)
    if i < 0:
        return None
    m = re.search(pattern, text[i:i + 400])
    return m.group(1) if m else None


def parse(code: str, name: str, text: str) -> dict:
    """한 종목의 지표를 뽑는다. 없는 항목은 None으로 둔다 — 지어내지 않는다."""
    # 펀더멘털 표는 "Fwd. 12M(E)" 머리말 뒤에 온다. 페이지 상단에도 PER/PBR이
    # 한 개씩 있어서, 그 앞부터 찾으면 엉뚱한 값을 집는다.
    base = text.find("Fwd. 12M(E)")
    body = text[base:base + 1200] if base >= 0 else ""

    def triple(label: str) -> list[float | None]:
        m = re.search(re.escape(label) +
                      r"\s+([\d,.]+|N/A)\s+([\d,.]+|N/A)\s+([\d,.]+|N/A)", body)
        if not m:
            return [None, None, None]
        return [_num(m.group(k)) for k in (1, 2, 3)]

    ev = triple("EV/EBITDA")
    per = triple("PER")
    pbr = triple("PBR")

    return {
        "code": code,
        "name": name,
        "price": _num(_after(text, "시세정보", r"([\d,]+)\s*원")),
        "mktcap_eok": _num(_after(text, "시가총액", r"([\d,]+)\s*억원")),
        "shares": _num(_after(text, "발행주식수", r"([\d,]+)\s*주")),
        "ret_1y": _after(text, "수익률 (1M / 3M / 6M / 1Y)",
                         r"[-+][\d.]+%\s*/\s*[-+][\d.]+%\s*/\s*[-+][\d.]+%\s*/\s*([-+][\d.]+%)"),
        "high52": _num(_after(text, "52Weeks 최고/최저", r"([\d,]+)원")),
        "low52": _num(_after(text, "52Weeks 최고/최저", r"[\d,]+원\s*/\s*([\d,]+)원")),
        # [실적, 당해 컨센서스, Fwd 12M]
        "ev_ebitda": ev,
        "per": per,
        "pbr": pbr,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="피어 밸류에이션 지표 수집")
    ap.add_argument("codes", nargs="+", help="종목코드 (예: 009150)")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    args = ap.parse_args(argv)

    rows = []
    for c in args.codes:
        text, name = _fetch(c)
        rows.append(parse(c, name, text))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    print("%-8s %-14s %>10s %18s %16s %9s".replace(">", "") %
          ("코드", "종목", "시총(억)", "EV/EBITDA A/E", "PER A/E", "1Y"))
    print("-" * 78)
    num = lambda x: "-" if x is None else format(x, ",.1f")
    for r in rows:
        ev, per = r["ev_ebitda"], r["per"]
        cap = "-" if r["mktcap_eok"] is None else format(r["mktcap_eok"], ",.0f")
        print("%-8s %-14s %10s %18s %16s %9s" % (
            r["code"], (r["name"] or "?")[:13], cap,
            num(ev[0]) + " / " + num(ev[1]),
            num(per[0]) + " / " + num(per[1]),
            r["ret_1y"] or "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
