#!/usr/bin/env python3
"""피어 그룹의 시세·밸류에이션 지표를 한 출처에서 가져온다.

목표배수는 이 모델에서 결과를 가장 크게 좌우하는 가정이다(03_valuation.md §7).
그 근거를 "역사적으로 5~8배"라는 기억이 아니라 **지금 시장이 같은 업종에
매기고 있는 배수**로 대체하기 위한 도구다.

출처를 하나로 고정하는 것이 중요하다. 종목마다 다른 사이트에서 긁으면
EBITDA 정의·기준일이 달라 비교가 성립하지 않는다.

국내는 WISEreport, 해외는 stockanalysis.com에서 받는다. 출처가 둘로 갈리므로
**국내끼리·해외끼리만 배수를 나란히 놓는다.** EBITDA 정의와 기준일이 달라
섞으면 비교가 성립하지 않는다.

--probe 로 출처 도달 여부를 먼저 확인한다. 닿지 않으면 값을 비워 둔다 —
확인하지 못한 숫자를 채우는 것이 이 레포에서 가장 큰 사고다.

사용:
    python3 tools/peer_fetch.py 009150 011070 222800
    python3 tools/peer_fetch.py --json 009150 011070 > peers.json
    python3 tools/peer_fetch.py --probe
    python3 tools/peer_fetch.py --foreign            # 해외 피어
    python3 tools/peer_fetch.py --foreign --json
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


# 해외 피어 후보. MLCC는 무라타·TDK·야게오, FC-BGA는 이비덴·신코덴키가
# 세계 선발주자이므로 목표배수 근거에는 이들이 들어가야 한다. 다만 WISEreport는
# 국내 상장사만 다루고, 아래 출처들은 이 환경의 이그레스 정책이 막고 있다.
# --probe 는 그 사실을 주장이 아니라 관측으로 남긴다.
# 해외 피어. MLCC는 무라타·TDK·야게오, FC-BGA는 이비덴·신코덴키가 세계 선발주자다.
# (거래소, 티커, 표시명, 구분)
FOREIGN = [
    ("tyo", "6981", "무라타",   "MLCC"),
    ("tyo", "6762", "TDK",      "MLCC·부품"),
    ("tpe", "2327", "야게오",    "MLCC"),
    ("tyo", "4062", "이비덴",    "FC-BGA"),
    ("tyo", "6967", "신코덴키",  "FC-BGA"),
]

SA_URL = "https://stockanalysis.com/quote/{}/{}/statistics/"

# 통계 페이지는 지표를 {id:"...",title:"...",value:"..."} 형태로 실어 나른다.
# 화면 텍스트가 아니라 이 구조에서 읽어야 레이아웃이 바뀌어도 견딘다.
_FIELD_RE = r'\{id:"%s",title:"[^"]*",value:"([^"]*)"'
_SUFFIX = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}


def _sa_field(text: str, key: str) -> str | None:
    m = re.search(_FIELD_RE % re.escape(key), text)
    return m.group(1) if m else None


def _sa_scale(v: str | None) -> float | None:
    """'5.91T' → 5.91e12. 통화 단위는 붙지 않는다 — 원문 통화 그대로다."""
    if not v or v in ("n/a", "-"):
        return None
    v = v.replace(",", "").strip()
    mult = _SUFFIX.get(v[-1:].upper())
    if mult:
        v = v[:-1]
    try:
        return float(v) * (mult or 1)
    except ValueError:
        return None


def fetch_foreign(exch: str, ticker: str) -> dict:
    """stockanalysis.com 통계 페이지에서 한 종목의 지표를 뽑는다.

    시가총액은 **현지 통화**다. 원화로 환산하지 않는다 — 환율 기준일이
    하나 더 늘어나면 대사할 것이 하나 더 늘어난다. 비교는 배수로만 한다.
    """
    cmd = ["curl", "-sSL", "--max-time", "40", "--cacert", CA,
           "-H", f"User-Agent: {UA}", SA_URL.format(exch, ticker)]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0 or not out.stdout:
        raise SystemExit(f"{exch}:{ticker} 조회 실패")
    t = out.stdout.decode("utf-8", errors="replace")
    m = re.search(r"<title>(.*?)</title>", t, re.S)
    return {
        "exchange": exch, "ticker": ticker,
        "page_name": html.unescape(m.group(1).split("(")[0].strip()) if m else "",
        "marketcap": _sa_scale(_sa_field(t, "marketcap")),
        "ev": _sa_scale(_sa_field(t, "enterpriseValue")),
        "ebitda": _sa_scale(_sa_field(t, "ebitda")),
        "ev_ebitda": _num(_sa_field(t, "evEbitda")),
        "per": _num(_sa_field(t, "pe")),
        "per_fwd": _num(_sa_field(t, "peForward")),
        "ret_1y": _sa_field(t, "ch1y"),
    }


def foreign(as_json: bool = False) -> int:
    rows = []
    for exch, ticker, name, group in FOREIGN:
        r = fetch_foreign(exch, ticker)
        r["name"], r["group"] = name, group
        rows.append(r)
        time.sleep(0.5)
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    print("%-10s %-12s %-10s %12s %10s %9s %9s %9s" %
          ("티커", "종목", "구분", "시총(현지)", "EV/EBITDA", "PER", "PER(F)", "1Y"))
    print("-" * 92)
    f = lambda x: "-" if x is None else format(x, ",.1f")
    for r in rows:
        cap = "-" if r["marketcap"] is None else "%.2fT" % (r["marketcap"] / 1e12)
        print("%-10s %-12s %-10s %12s %10s %9s %9s %9s" % (
            r["exchange"].upper() + ":" + r["ticker"], r["name"], r["group"],
            cap, f(r["ev_ebitda"]), f(r["per"]), f(r["per_fwd"]), r["ret_1y"] or "-"))
    # 검산 — EV / EBITDA 가 사이트가 준 배수와 맞는가. 어긋나면 파싱이 틀린 것이다.
    for r in rows:
        if r["ev"] and r["ebitda"] and r["ev_ebitda"]:
            calc = r["ev"] / r["ebitda"]
            if abs(calc - r["ev_ebitda"]) / r["ev_ebitda"] > 0.02:
                print("  ✗ %s EV/EBITDA 검산 불일치: 계산 %.2f ≠ 표기 %.2f"
                      % (r["name"], calc, r["ev_ebitda"]))
    return 0


def probe() -> int:
    """해외 출처에 실제로 닿는지 확인한다.

    닿지 않으면 값을 지어내지 않고 비워 둔다 — 그것이 이 레포의 규약이다.
    나중에 정책이 열리면 이 명령이 먼저 그것을 알려준다.
    """
    print("해외 피어 출처 도달 확인")
    print("-" * 60)
    targets = [(n, SA_URL.format(e, t)) for e, t, n, _ in FOREIGN]
    ok = 0
    for name, url in targets:
        r = subprocess.run(
            ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
             "--max-time", "20", "--cacert", CA, "-H", f"User-Agent: {UA}", url],
            capture_output=True)
        code = r.stdout.decode().strip() or "000"
        err = (r.stderr.decode(errors="replace").strip().splitlines() or [""])[-1]
        if code.startswith("2"):
            ok += 1
            print(f"  도달  {name:<10} {url}")
        else:
            print(f"  차단  {name:<10} {code}  {err}")
    print("-" * 60)
    if ok == 0:
        print("전부 차단됐다. PEERS.missing 을 그대로 두고, 값을 채우지 않는다.")
        print("정책을 여는 방법은 companies/<종목>/DATA_REQUEST.md 참조.")
    else:
        print(f"{ok}/{len(targets)} 도달. python3 tools/peer_fetch.py --foreign 으로 수집한다.")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="피어 밸류에이션 지표 수집")
    ap.add_argument("codes", nargs="*", help="종목코드 (예: 009150)")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--probe", action="store_true",
                    help="해외 피어 출처에 닿는지만 확인한다")
    ap.add_argument("--foreign", action="store_true",
                    help="해외 피어를 stockanalysis.com에서 수집한다")
    args = ap.parse_args(argv)

    if args.probe:
        return probe()
    if args.foreign:
        return foreign(args.json)
    if not args.codes:
        ap.error("종목코드가 필요하다 (또는 --probe)")

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
