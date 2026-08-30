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
    python3 tools/dart_fetch.py costnature <접수번호>     # 비용의 성격별 분류 주석
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


# ── 비용의 성격별 분류 주석 파싱 ────────────────────────────────
# 사업보고서 주석의 "비용의 성격별 분류"(회사에 따라 "영업비용 — 성격별 비용")는
# 영업비용을 원재료·인건비·상각비 같은 성격으로 쪼갠 유일한 공시다.
# 사업 구조 뷰의 비용 블록이 이 표에서 나온다.
#
# DART 뷰어의 XBRL 표는 to_text를 거치면 "라벨 줄 → 값 줄"의 쌍으로 펴진다.
# 그룹 헤더(자식을 거느린 라벨)는 값 줄 없이 다음 라벨이 이어지므로,
# "숫자 줄은 직전 라벨의 값"이라는 규칙 하나로 전체가 풀린다. 라벨 중복
# (합계 행과 그룹 헤더가 같은 이름)이 있으므로 dict가 아니라 순서 있는
# 쌍 목록으로 돌려준다 — 정규화(합계/자식 구분)는 종목 쪽에서 한다.

_CN_TITLE_RE = re.compile(r"비용의 성격별 분류|성격별\s*비용|성격별로 분류")
_CN_UNIT_RE = re.compile(r"\(단위\s*:\s*([^)]+)\)")
_CN_NUM_RE = re.compile(r"^\(?-?[\d,]+\)?$")
_CN_ANCHOR_RE = re.compile(r"제품 및 재공품 등의 변동|재공품 및 제품의 변동|재고자산의 변동")
_CN_PERIOD_RE = re.compile(r"^(당|전)\s*[분반]?\s*기$|^제\s*\d+\s*기(말)?$")
# 성격별 표가 맞는지 확인하는 의미 검사 — 법인세·자본변동 같은 다른 표를 거른다.
# 진짜 성격별 표에는 재료/재고 행과 급여 행과 상각 행이 전부 있다.
_CN_SEMANTIC = (re.compile(r"원재료|매입액|재고자산의 변동|재공품"),
                re.compile(r"급여|인건비"), re.compile(r"상각"))


def _cn_lines(body: str) -> list[str]:
    lines = [ln.strip().rstrip("|").strip() for ln in body.split("\n")]
    return [ln for ln in lines if ln and ln not in ("　", "공시금액")
            and not _CN_UNIT_RE.fullmatch(ln)]


def _cn_pairs(lines: list[str]) -> list[list]:
    """라벨/값 줄 목록을 (라벨, 값) 쌍으로 짝짓는다."""
    pairs, pending = [], None
    for ln in lines:
        if _CN_NUM_RE.fullmatch(ln):
            v = _to_int(ln)
            if pending is not None and v is not None:
                pairs.append([pending, v])
            pending = None
        else:
            pending = ln
    return pairs


def _cn_parse(body: str) -> dict:
    """한 후보 구간을 {기간: [[라벨, 값], ...]}으로 파싱한다.

    표는 두 가지 모양으로 온다.
      A. XBRL 뷰어 — '당기' 헤더 아래 라벨 줄/값 줄 쌍이 이어진다.
      B. 고전 표  — '구 분 | 당 기 | 전 기' 헤더 아래 라벨 + 열 수만큼 값.
    """
    lines = _cn_lines(body)

    # 모양 B — 구분 헤더에 이어 기간 열 이름들이 온다.
    for i, ln in enumerate(lines):
        if not re.fullmatch(r"구\s*분", ln):
            continue
        cols, j = [], i + 1
        while j < len(lines) and _CN_PERIOD_RE.fullmatch(lines[j]):
            cols.append(re.sub(r"\s+", "", lines[j]))
            j += 1
        if not cols:
            continue
        periods = {c: [] for c in cols}
        label, vals = None, []
        for ln2 in lines[j:]:
            if _CN_NUM_RE.fullmatch(ln2):
                vals.append(_to_int(ln2))
                if len(vals) == len(cols) and label:
                    for c, v in zip(cols, vals):
                        periods[c].append([label, v])
                    label, vals = None, []
            else:
                # 다음 주석 제목이 나오면 표가 끝난 것이다.
                if re.match(r"^\d{1,2}[-.]", ln2) and any(periods.values()):
                    break
                label, vals = ln2, []
        return periods

    # 모양 A — 당기/전기 블록. 같은 기간 헤더가 다시 나오면 다음 표가
    # 시작된 것이므로 거기서 멈춘다 — 뒤 표가 앞 표를 덮어쓰면 안 된다.
    periods, cur, buf = {}, None, []
    for ln in lines:
        if ln in ("당기", "전기", "당분기", "전분기"):
            if cur and buf:
                periods[cur] = _cn_pairs(buf)
            if ln in periods:
                cur = None
                break
            cur, buf = ln, []
            continue
        if cur and ("에 대한 기술" in ln or ln.endswith("내역")):
            periods[cur] = _cn_pairs(buf)
            cur, buf = None, []
            if len(periods) >= 2:
                break
            continue
        if cur:
            buf.append(ln)
    if cur and buf:
        periods[cur] = _cn_pairs(buf)
    return periods


def _cn_valid(periods: dict) -> bool:
    rows = [p for v in periods.values() for p in v]
    return (len(rows) >= 6 and
            all(any(rx.search(lb) for lb, _ in rows) for rx in _CN_SEMANTIC))


def costnature(rcp_no: str) -> dict:
    """성격별 비용 주석을 {기간: [[라벨, 값], ...]}으로 돌려준다.

    값 단위는 공시 그대로다(unit 필드 참조 — 천원/백만원이 회사마다 다르다).
    환산은 호출하는 쪽에서 한다.

    제목이 회계정책 산문에도 나오므로 후보 위치를 전부 시도하고,
    파싱 결과가 성격별 표답게 생겼는지(_cn_valid)로 판정한다.
    옛 보고서는 제목 없이 영업이익 주석 안에 표만 들어 있다 —
    관용 첫 행(재공품 변동)을 앵커로 쓰는 폴백이 그 경우를 받는다.
    """
    items = toc(rcp_no)
    nodes = [n for n in items if "성격별" in n["text"] and "연결" in n["text"]]
    if not nodes:
        nodes = [n for n in items if "연결재무제표 주석" in n["text"]]
    if not nodes:
        nodes = [n for n in items if "성격별" in n["text"]]
    if not nodes:
        raise SystemExit(f"{rcp_no}: 성격별 비용 주석을 찾지 못했다")
    text = document(nodes[0])

    starts = [m.start() for m in _CN_TITLE_RE.finditer(text)]
    starts += [max(0, m.start() - 150) for m in _CN_ANCHOR_RE.finditer(text)]
    for start in starts:
        body = text[start:start + 8000]
        periods = _cn_parse(body)
        if _cn_valid(periods):
            unit_m = _CN_UNIT_RE.search(body)
            return {"rcpNo": rcp_no,
                    "unit": unit_m.group(1).strip() if unit_m else "?",
                    "periods": periods}
    raise SystemExit(f"{rcp_no}: 성격별 비용 표를 파싱하지 못했다")


# ── 연결 손익계산서 누적값 추출 ────────────────────────────────
# 분기·반기보고서의 연결 (포괄)손익계산서에서 당기 누적 매출·영업이익을
# 뽑는다. 부문 주석이 없는(단일 부문) 회사의 분기 시계열은 이 경로로 만든다.
# 표 헤더의 '3개월'/'누적' 열 배치를 읽어 누적 열의 위치를 정한다 —
# 1분기 보고서는 3개월=누적이라 열이 하나뿐인 경우가 있다.

_IS_REV_LABELS = ("매출액", "매출", "수익(매출액)", "영업수익")
_IS_OP_LABELS = ("영업이익(손실)", "영업이익", "영업손실")
_IS_NUM_RE = re.compile(r"^\(?-?[\d,]+\)?$")


def iscum(rcp_no: str) -> dict:
    """{'rev': 누적 매출, 'op': 누적 영업이익, 'unit': 단위} — 당기 기준."""
    items = toc(rcp_no)
    nodes = [n for n in items if n["text"].rstrip().endswith("연결재무제표")
             and "주석" not in n["text"]]
    if not nodes:
        raise SystemExit(f"{rcp_no}: 연결재무제표 항목을 찾지 못했다")
    text = document(nodes[0])

    # 손익계산서 섹션 — 회사에 따라 '연결 손익계산서'와 '연결 포괄손익계산서'가
    # 나뉘거나 하나로 합쳐져 있다. 영업이익 행이 들어 있는 첫 섹션을 쓴다.
    starts = [m.start() for m in re.finditer(r"연결\s*(포괄)?\s*손익계산서", text)]
    body = None
    for s in starts:
        chunk = text[s:s + 12000]
        if re.search(r"영업이익|영업손실", chunk):
            body = chunk
            break
    if body is None:
        raise SystemExit(f"{rcp_no}: 손익계산서 섹션을 찾지 못했다")

    unit_m = re.search(r"\(단위\s*:\s*([^)]+)\)", body)
    unit = unit_m.group(1).strip() if unit_m else "?"

    lines = [ln.strip().rstrip("|").strip() for ln in body.split("\n")]
    lines = [ln for ln in lines if ln and ln != "　"]

    # 헤더의 3개월/누적 토큰 — 첫 계정 행이 나오기 전까지만 읽는다.
    cols, seen_acct = [], False
    for ln in lines:
        if ln in ("3개월", "누적"):
            cols.append(ln)
        elif any(ln.startswith(lb) for lb in _IS_REV_LABELS) and not _IS_NUM_RE.fullmatch(ln):
            break
    ncols = len(cols) if cols else 2          # 헤더 없으면 당기|전기 2열로 가정
    cum_idx = cols.index("누적") if "누적" in cols else 0

    def row_value(labels):
        for i, ln in enumerate(lines):
            base = ln.split("(주")[0].strip()
            if base in labels:
                vals = []
                for nxt in lines[i + 1:i + 1 + ncols + 2]:
                    if _IS_NUM_RE.fullmatch(nxt):
                        vals.append(_to_int(nxt))
                        if len(vals) == ncols:
                            break
                    elif vals:
                        break
                if len(vals) >= cum_idx + 1:
                    v = vals[cum_idx]
                    return -v if base == "영업손실" and v > 0 else v
        return None

    rev = row_value(_IS_REV_LABELS)
    op = row_value(_IS_OP_LABELS)
    if rev is None or op is None:
        raise SystemExit(f"{rcp_no}: 매출/영업이익 행을 읽지 못했다 (cols={cols})")
    return {"rev": rev, "op": op, "unit": unit, "ncols": ncols, "cum_idx": cum_idx}


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
    elif cmd == "costnature":
        import json
        print(json.dumps(costnature(argv[1]), ensure_ascii=False, indent=2))
    elif cmd == "iscum":
        import json
        print(json.dumps(iscum(argv[1]), ensure_ascii=False))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
