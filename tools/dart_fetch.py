#!/usr/bin/env python3
"""DART 공시 원문에서 재무 라인아이템을 가져온다.

검색 스니펫은 라인아이템 확정에 쓸 수 없다 — 같은 항목이 출처마다
두 배씩 차이나는 것을 실제로 확인했다. 확정값은 반드시 공시 원문에서 온다.
이 스크립트가 그 경로다.

사용:
    python3 tools/dart_fetch.py search 삼성전기          # 정기보고서 목록
    python3 tools/dart_fetch.py search 삼성전기 분기      # 분기보고서만
    python3 tools/dart_fetch.py toc <접수번호>            # 목차
    python3 tools/dart_fetch.py doc <접수번호> <목차번호> # 본문 텍스트
    python3 tools/dart_fetch.py segments <접수번호>       # 영업부문정보 주석
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


def search(name: str, kind: str = "정기",
           start: str = "20200101", end: str = "20301231") -> list[dict]:
    """공시 목록. kind는 보고서명에 포함될 문자열로 거른다.

    서버 쪽 제약이 둘 있고 둘 다 조용히 빈 목록으로 나타난다.
      - publicType 파라미터를 더 이상 받지 않는다 (2026-08 확인).
      - 조회 기간의 총 건수가 많으면 빈 응답이 온다. 기간을 쪼개면 나온다.
    그래서 거르기는 이쪽에서 하고, 빈 응답이 오면 기간을 반으로 갈라 재시도한다.

    "정기"는 사업·반기·분기보고서를 모두 뜻하는 별칭이다.
    """
    KINDS = {"정기": ("사업보고서", "반기보고서", "분기보고서"),
             "사업": ("사업보고서",), "반기": ("반기보고서",), "분기": ("분기보고서",)}
    want = KINDS.get(kind, (kind,))
    rows, seen = [], set()
    for tr in _search_rows(name, start, end):
        rcp = re.search(r"rcpNo=(\d+)", tr)
        if not rcp or rcp.group(1) in seen:
            continue
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<td.*?>(.*?)</td>", tr, re.S)]
        nm = cells[2] if len(cells) > 2 else ""
        if want and not any(w in nm for w in want):
            continue
        seen.add(rcp.group(1))
        rows.append({"rcpNo": rcp.group(1), "회사": cells[1] if len(cells) > 1 else "",
                     "보고서": nm, "접수일": cells[4] if len(cells) > 4 else ""})
    rows.sort(key=lambda r: r["rcpNo"], reverse=True)
    return rows


def _search_rows(name: str, start: str, end: str, depth: int = 0) -> list[str]:
    """한 기간의 <tr>들. 빈 응답이면 기간을 반으로 갈라 다시 묻는다."""
    body = _curl(f"{BASE}/dsab007/detailSearch.ax", [
        "currentPage=1", "maxResults=100", f"textCrpNm={name}",
        f"startDate={start}", f"endDate={end}",
    ])
    if "rcpNo=" in body:
        return re.findall(r"<tr>(.*?)</tr>", body, re.S)
    if depth >= 3 or start >= end:
        return []
    mid = _mid_date(start, end)
    return (_search_rows(name, start, mid, depth + 1) +
            _search_rows(name, mid, end, depth + 1))


def _mid_date(start: str, end: str) -> str:
    import datetime
    fmt = "%Y%m%d"
    a = datetime.datetime.strptime(start, fmt)
    b = datetime.datetime.strptime(end, fmt)
    return (a + (b - a) / 2).strftime(fmt)


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



# ── 영업부문정보 주석 파싱 ─────────────────────────────────────
# 분기·반기보고서의 "영업부문정보" 주석은 부문별 매출·감가상각·영업이익을
# 한 표에 담는다. 분기 추적에 필요한 것이 정확히 이 표다.
#
# 표는 기간 블록(당분기 / 전분기 / 당반기 / 전반기 …)이 이어 붙은 모양이고,
# 각 블록은 [부문명들] 다음에 [항목명 | 값 | 값 | 값 | 합계] 행이 온다.
# 부문 순서를 헤더에서 읽어야 한다 — 값만 보고 순서를 가정하면 언젠가 틀린다.

_PERIOD_RE = re.compile(r"(당|전)(분기|반기|기)(누적)?(?=\s*\|)")
# 부문 이름이 해에 따라 바뀐다 — 통신모듈 중단영업 분류 전에는 "광학통신솔루션"이었다.
# 표기를 정규화하지 않으면 옛 보고서에서 부문을 못 찾고 조용히 빈 결과가 나온다.
_SEG_RE = re.compile(r"패키지솔루션|컴포넌트|광학[가-힣]*솔루션")
_SEG_CANON = {"패키지솔루션": "패키지솔루션", "컴포넌트": "컴포넌트"}
_SEG_NAMES = ("컴포넌트", "패키지솔루션", "광학솔루션")


def _canon_seg(name: str) -> str:
    return _SEG_CANON.get(name, "광학솔루션")
_METRICS = {
    "수익": "매출", "수익(매출액)": "매출", "매출액": "매출",
    "감가상각비": "감가상각비",
    "무형자산상각비": "무형자산상각비",
    "사용권자산상각비": "사용권자산상각비",
    "영업이익": "영업이익", "영업이익(손실)": "영업이익",
}


def _to_int(tok: str) -> int | None:
    tok = tok.strip().replace(",", "")
    neg = tok.startswith("(") and tok.endswith(")")
    if neg:
        tok = tok[1:-1]
    if not re.fullmatch(r"-?\d+", tok):
        return None
    v = int(tok)
    return -v if neg else v


def segments(rcp_no: str, node_hint: str = "영업부문정보") -> dict:
    """영업부문정보 주석을 {기간: {부문: {항목: 백만원}}}으로 돌려준다.

    값 단위는 공시 그대로 백만원이다. 억원 환산은 호출하는 쪽에서 한다 —
    여기서 환산하면 원문 대사가 불가능해진다.
    """
    nodes = [n for n in toc(rcp_no) if node_hint in n["text"] and "연결" in n["text"]]
    if not nodes:
        nodes = [n for n in toc(rcp_no) if node_hint in n["text"]]
    if not nodes:
        raise SystemExit(f"{rcp_no}: '{node_hint}' 주석을 찾지 못했다")
    text = document(nodes[0])

    # "영업부문에 대한 공시" 이후만 본다. 앞쪽 고객 정보 표에도 숫자가 있다.
    at = text.find("영업부문에 대한 공시")
    body = text[at:] if at >= 0 else text
    # 지역 정보 표가 뒤에 붙는다 — 같은 항목명을 쓰므로 잘라낸다.
    stop = body.find("지역에 대한")
    if stop > 0:
        body = body[:stop]

    marks = [(m.start(), m.group(0)) for m in _PERIOD_RE.finditer(body)]
    out = {}
    for i, (pos, label) in enumerate(marks):
        chunk = body[pos:marks[i + 1][0] if i + 1 < len(marks) else len(body)]
        order = []
        for nm in _SEG_RE.findall(chunk):
            c = _canon_seg(nm)
            if c not in order:
                order.append(c)
        if len(order) < len(_SEG_NAMES):
            continue
        rows = {}
        for raw, key in _METRICS.items():
            m = re.search(re.escape(raw) + r"\s*\|((?:\s*\(?-?[\d,]+\)?\s*\|){%d})"
                          % (len(order) + 1), chunk)
            if not m:
                continue
            vals = [_to_int(x) for x in m.group(1).split("|") if x.strip()]
            if len(vals) != len(order) + 1 or any(v is None for v in vals):
                continue
            for j, seg in enumerate(order):
                rows.setdefault(seg, {})[key] = vals[j]
            rows.setdefault("합계", {})[key] = vals[-1]
        if rows:
            out[label] = rows
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "search":
        for r in search(argv[1], argv[2] if len(argv) > 2 else "정기"):
            print(f"{r['rcpNo']}  {r['접수일']}  {r['보고서']}")
    elif cmd == "toc":
        for i, n in enumerate(toc(argv[1])):
            print(f"{i:3}  {n['text']}")
    elif cmd == "doc":
        nodes = toc(argv[1])
        print(document(nodes[int(argv[2])]))
    elif cmd == "segments":
        import json
        print(json.dumps(segments(argv[1]), ensure_ascii=False, indent=2))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
