#!/usr/bin/env python3
"""DART 공시 원문에서 재무 라인아이템을 가져온다.

검색 스니펫은 라인아이템 확정에 쓸 수 없다 — 같은 항목이 출처마다
두 배씩 차이나는 것을 실제로 확인했다. 확정값은 반드시 공시 원문에서 온다.
이 스크립트가 그 경로다.

사용:
    python3 tools/dart_fetch.py search 삼성전기          # 사업보고서 목록
    python3 tools/dart_fetch.py toc <접수번호>            # 목차
    python3 tools/dart_fetch.py doc <접수번호> <목차번호> # 본문 텍스트
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
import time

BASE = "https://dart.fss.or.kr"
CA = "/root/.ccr/ca-bundle.crt"
UA = "Mozilla/5.0"


def _curl(url: str, post: list[str] | None = None, tries: int = 4) -> str:
    """DART는 간헐적으로 연결을 끊는다. 지수 백오프로 재시도한다."""
    cmd = ["curl", "-sS", "--max-time", "60", "--cacert", CA, "-H", f"User-Agent: {UA}"]
    for item in post or []:
        cmd += ["--data-urlencode", item]
    cmd.append(url)
    err = ""
    for attempt in range(tries):
        out = subprocess.run(cmd, capture_output=True)
        if out.returncode == 0 and out.stdout:
            return out.stdout.decode("utf-8", errors="replace")
        err = out.stderr.decode(errors="replace")[:400]
        time.sleep(2 ** attempt)
    raise SystemExit(f"요청 실패({tries}회 재시도): {err}")


def search(name: str, kind: str = "A001",
           start: str = "20200101", end: str = "20301231") -> list[dict]:
    """공시 목록. kind는 A001=사업보고서, A002=반기, A003=분기."""
    body = _curl(f"{BASE}/dsab007/detailSearch.ax", [
        "currentPage=1", "maxResults=30", f"textCrpNm={name}",
        f"publicType={kind}", f"startDate={start}", f"endDate={end}",
    ])
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
        rcp = re.search(r"rcpNo=(\d+)", tr)
        if not rcp:
            continue
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<td.*?>(.*?)</td>", tr, re.S)]
        rows.append({"rcpNo": rcp.group(1), "회사": cells[1] if len(cells) > 1 else "",
                     "보고서": cells[2] if len(cells) > 2 else "",
                     "접수일": cells[4] if len(cells) > 4 else ""})
    return rows


# 뷰어 페이지의 목차는 JS 객체 리터럴로 들어 있다. 정규식으로 필드를 긁는다.
_NODE_RE = re.compile(
    r"node\d+\['text'\]\s*=\s*\"(?P<text>.*?)\";.*?"
    r"node\d+\['dcmNo'\]\s*=\s*\"(?P<dcmNo>\d+)\";\s*"
    r"node\d+\['eleId'\]\s*=\s*\"(?P<eleId>\d+)\";\s*"
    r"node\d+\['offset'\]\s*=\s*\"(?P<offset>\d+)\";\s*"
    r"node\d+\['length'\]\s*=\s*\"(?P<length>\d+)\";\s*"
    r"node\d+\['dtd'\]\s*=\s*\"(?P<dtd>[^\"]+)\";",
    re.S,
)


def toc(rcp_no: str) -> list[dict]:
    """보고서 목차. 각 항목은 본문 조회에 필요한 좌표를 함께 갖는다."""
    page = _curl(f"{BASE}/dsaf001/main.do?rcpNo={rcp_no}")
    out = []
    for m in _NODE_RE.finditer(page):
        d = m.groupdict()
        d["text"] = html.unescape(d["text"]).strip()
        d["rcpNo"] = rcp_no
        out.append(d)
    return out


def document(node: dict) -> str:
    """목차 항목 하나의 본문을 텍스트로 돌려준다."""
    url = (f"{BASE}/report/viewer.do?rcpNo={node['rcpNo']}&dcmNo={node['dcmNo']}"
           f"&eleId={node['eleId']}&offset={node['offset']}"
           f"&length={node['length']}&dtd={node['dtd']}")
    raw = _curl(url)
    return to_text(raw)


def to_text(raw: str) -> str:
    """표 구조를 살려 HTML을 텍스트로 편다.

    재무제표는 표다. 셀 경계를 '|'로 남기지 않으면 숫자가 어느 열의
    어느 연도인지 알 수 없게 된다.
    """
    t = re.sub(r"<(script|style).*?</\1>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"</t[dh]>", " | ", t, flags=re.I)
    t = re.sub(r"</tr>", "\n", t, flags=re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(p|div|table)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = t.replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\| *", " | ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "search":
        for r in search(argv[1]):
            print(f"{r['rcpNo']}  {r['접수일']}  {r['보고서']}")
    elif cmd == "toc":
        for i, n in enumerate(toc(argv[1])):
            print(f"{i:3}  {n['text']}")
    elif cmd == "doc":
        nodes = toc(argv[1])
        print(document(nodes[int(argv[2])]))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
