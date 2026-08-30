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
_IS_OP_LABELS = ("영업이익(손실)", "영업이익", "영업손실", "영업손익", "영업이익(손실) 합계")
_IS_COGS_LABELS = ("매출원가",)
# 순이익 행 — 보고서 종류에 따라 당기/분기/반기, 연결 접두, (손실) 접미가 붙는다.
# "…의 귀속"(지배/비지배 배분) 행은 fullmatch가 걸러낸다.
_IS_NI_RE = re.compile(r"^(연결)?\s*(당|분|반)기\s*순\s*(이익|손실)(\(손실\))?$")
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

    def row_value(labels, rx=None):
        for i, ln in enumerate(lines):
            base = ln.split("(주")[0].strip()
            hit = rx.fullmatch(base) if rx is not None else (base in labels)
            if hit:
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
                    loss = base == "영업손실" or ("순손실" in base.replace(" ", ""))
                    return -v if loss and v > 0 else v
        return None

    rev = row_value(_IS_REV_LABELS)
    op = row_value(_IS_OP_LABELS)
    if rev is None or op is None:
        raise SystemExit(f"{rcp_no}: 매출/영업이익 행을 읽지 못했다 (cols={cols})")
    # 매출원가·순이익은 선택 — 없는 공시(예: 성격별 단일 표시)는 None으로 둔다.
    cogs = row_value(_IS_COGS_LABELS)
    ni = row_value(None, _IS_NI_RE)
    return {"rev": rev, "op": op, "cogs": cogs, "ni": ni,
            "unit": unit, "ncols": ncols, "cum_idx": cum_idx}


def islong(rcp_no: str) -> dict:
    """사업보고서 연결 손익계산서의 3개년(당기/전기/전전기) 매출·영업이익.

    장기(10년+) 실적 시계열은 사업보고서 4개(3개년 블록)면 12년이 나온다.
    각 블록은 그 보고서가 공시한 기준 그대로다 — 소급 재작성이 있으면
    블록 경계에서 기준이 갈릴 수 있고, 호출하는 쪽이 문서화한다.
    """
    items = toc(rcp_no)
    nodes = [n for n in items if n["text"].rstrip().endswith("연결재무제표")
             and "주석" not in n["text"]]
    if not nodes:
        raise SystemExit(f"{rcp_no}: 연결재무제표 항목을 찾지 못했다")
    text = document(nodes[0])
    starts = [m.start() for m in re.finditer(r"연결\s*(포괄)?\s*손익계산서", text)]
    body = None
    for s in starts:
        chunk = text[s:s + 15000]
        if re.search(r"영업이익|영업손실", chunk):
            body = chunk
            break
    if body is None:
        raise SystemExit(f"{rcp_no}: 손익계산서 섹션을 찾지 못했다")
    unit_m = re.search(r"\(단위\s*:\s*([^)]+)\)", body)
    unit = unit_m.group(1).strip() if unit_m else "?"
    # 헤더의 "제 N 기 YYYY.MM.DD 부터"에서 연도 열을 읽는다 — 상장 초기
    # 보고서는 2개년만 줄 수 있다 (티엘비 FY2020).
    head_end = unit_m.start() if unit_m else 1500
    years = [int(m.group(1)) for m in re.finditer(
        r"제\s*\d+\s*기\s*(\d{4})\.\d{2}\.\d{2}\s*부터", body[:head_end])]
    ncol = len(years) if years else 3
    lines = [ln.strip().rstrip("|").strip() for ln in body.split("\n")]
    lines = [ln for ln in lines if ln and ln != "　"]

    def row_values(labels):
        for i, ln in enumerate(lines):
            base = ln.split("(주")[0].strip()
            # 옛 보고서는 "Ⅰ.수익(매출액)"처럼 로마숫자 차례가 붙는다.
            base = re.sub(r"^[IVXⅠ-Ⅻ]+\s*[.．]\s*", "", base).strip()
            if base in labels:
                vals = []
                for nxt in lines[i + 1:i + 3 + ncol]:
                    if _IS_NUM_RE.fullmatch(nxt):
                        vals.append(_to_int(nxt))
                        if len(vals) == ncol:
                            break
                    elif vals:
                        break
                if len(vals) == ncol:
                    if base == "영업손실":
                        vals = [-v if v > 0 else v for v in vals]
                    return vals
        return None

    rev = row_values(_IS_REV_LABELS)
    op = row_values(_IS_OP_LABELS)
    if rev is None or op is None:
        raise SystemExit(f"{rcp_no}: {ncol}개년 매출/영업이익 행을 읽지 못했다")
    return {"rev": rev, "op": op, "unit": unit, "years": years or None}


def _fin_text(rcp_no: str) -> str:
    """연결재무제표 본문 항목의 전체 텍스트 (재무상태표~현금흐름표 포함)."""
    items = toc(rcp_no)
    nodes = [n for n in items if n["text"].rstrip().endswith("연결재무제표")
             and "주석" not in n["text"]]
    if not nodes:
        raise SystemExit(f"{rcp_no}: 연결재무제표 항목을 찾지 못했다")
    return document(nodes[0])


def _stmt_rows(rcp_no: str, title_re: str, header_re: str, rows: dict,
               chunk: int = 40000) -> dict:
    """재무제표 하나에서 이름 붙은 행들의 다개년 값을 읽는다.

    title_re로 표를 찾고, header_re로 연도 열을 센다(2개년 표도 받는다).
    rows는 {키: (라벨들…)} — 라벨은 공백 제거·차례(로마숫자 등) 제거 후 비교.
    값이 없는 키는 None. 반환: {키: [연도별 값], 'years': [...], 'unit': ...}
    """
    text = _fin_text(rcp_no)
    m = re.search(title_re, text)
    if m is None:
        raise SystemExit(f"{rcp_no}: {title_re} 표를 찾지 못했다")
    body = text[m.start():m.start() + chunk]
    unit_m = re.search(r"\(단위\s*:\s*([^)]+)\)", body)
    unit = unit_m.group(1).strip() if unit_m else "?"
    head_end = unit_m.start() if unit_m else 1500
    years = [int(y) for y in re.findall(header_re, body[:head_end])]
    ncol = len(years) if years else 3
    lines = [ln.strip().rstrip("|").strip() for ln in body.split("\n")]
    lines = [ln for ln in lines if ln and ln != "　"]

    def row(labels):
        want = {lb.replace(" ", "") for lb in labels}
        for i, ln in enumerate(lines):
            base = ln.split("(주")[0].strip()
            base = re.sub(r"^[IVXⅠ-Ⅻ0-9]+\s*[.．]\s*", "", base).replace(" ", "")
            if base in want:
                vals = []
                for nxt in lines[i + 1:i + 3 + ncol]:
                    if _IS_NUM_RE.fullmatch(nxt):
                        vals.append(_to_int(nxt))
                        if len(vals) == ncol:
                            break
                    elif vals:
                        break
                if len(vals) == ncol:
                    return vals
        return None

    out = {"years": years or None, "unit": unit}
    for key, labels in rows.items():
        out[key] = row(labels)
    return out


def cflong(rcp_no: str) -> dict:
    """연결 현금흐름표의 다개년 영업/투자/재무 현금흐름과 유형자산 취득."""
    r = _stmt_rows(
        rcp_no, r"연결\s*현금흐름표",
        r"제\s*\d+\s*기\s*(\d{4})\.\d{2}\.\d{2}\s*부터",
        {"cfo": ("영업활동현금흐름", "영업활동으로인한현금흐름",
                 "영업활동으로인한순현금흐름", "영업활동순현금흐름"),
         "cfi": ("투자활동현금흐름", "투자활동으로인한현금흐름",
                 "투자활동으로인한순현금흐름", "투자활동순현금흐름"),
         "cff": ("재무활동현금흐름", "재무활동으로인한현금흐름",
                 "재무활동으로인한순현금흐름", "재무활동순현금흐름"),
         "capex": ("유형자산의취득", "유형자산의증가", "유형자산취득")})
    if r["cfo"] is None or r["cfi"] is None or r["cff"] is None:
        raise SystemExit(f"{rcp_no}: 현금흐름표 활동별 행을 읽지 못했다")
    return r


def bslong(rcp_no: str) -> dict:
    """연결 재무상태표의 부채총계·자본총계 (당기말·전기말 …)."""
    r = _stmt_rows(
        rcp_no, r"연결\s*재무상태표",
        r"제\s*\d+\s*기(?:말|초)?\s*(\d{4})\.\d{2}\.\d{2}\s*현재",
        {"liab": ("부채총계",), "equity": ("자본총계",)})
    if r["liab"] is None or r["equity"] is None:
        raise SystemExit(f"{rcp_no}: 재무상태표 부채·자본총계 행을 읽지 못했다")
    return r


_RG_HEADINGS = ("지역에 대한 공시", "지역별 공시", "지역별 매출", "지역별 수익",
                "지역별 정보", "지역별 외부고객으로부터의 수익")
_RG_REVROW = ("수익(매출액)", "매출액", "매출", "순매출액", "영업수익", "외부고객으로부터의 수익")
_RG_TOTAL = ("합계", "계", "총계", "지역 합계", "기업 전체 총계")
_RG_SKIP = ("　", "지역", "구분")


def region(rcp_no: str) -> dict:
    """영업부문 주석의 지역별 매출 — 당기/전기 두 해.

    두 형태를 받는다.
      A) XBRL 행형: 지역 헤더들 … '수익(매출액)' … 숫자 N개(마지막이 합계).
         중첩 헤더(국내>내수/수출)는 말단이 뒤에 오므로 뒤에서 N-1개가 말단.
      B) 고전 열형: '지역 | 당기 | 전기' 행 나열, 합계 행으로 끝.
    반환: {'cur': {지역: 값}, 'prev': {...}, 'cur_total', 'prev_total', 'unit'}
    실패는 SystemExit — 호출 쪽이 종목 단위로 건너뛴다.
    """
    items = toc(rcp_no)
    nodes = [n for n in items if "연결재무제표 주석" in n["text"]]
    if not nodes:
        raise SystemExit(f"{rcp_no}: 연결재무제표 주석을 찾지 못했다")
    text = document(nodes[0])

    def parse_block(seg: list[str]) -> tuple[dict, float] | None:
        # 행형 — 수익 라벨 앞의 헤더 토큰, 뒤의 숫자들(마지막이 합계).
        # 첫 후보 행이 검증에 실패하면 다음 후보 행을 계속 시도한다.
        for i, ln in enumerate(seg):
            base = ln.split("(주")[0].strip()
            if base not in _RG_REVROW:
                continue
            vals = []
            for nxt in seg[i + 1:]:
                if _IS_NUM_RE.fullmatch(nxt):
                    vals.append(_to_int(nxt))
                elif vals:
                    break
            if len(vals) < 3:
                continue
            # Σ말단 = 합계가 성립해야 유효한 표다 — 아니면 다른 표를 잡은 것.
            # 빈 셀(소계 열)이 끼는 변형은 이름 매핑이 안전하지 않아 받지 않는다.
            if abs(sum(vals[:-1]) - vals[-1]) > max(2, abs(vals[-1]) * 1e-6):
                continue
            heads = [h for h in seg[:i]
                     if not _IS_NUM_RE.fullmatch(h) and h not in _RG_SKIP
                     and not h.startswith("(단위") and "합계" not in h
                     and not re.search(r"^[당전][분반]?\s*기$", h)]
            # 중첩 헤더 — 부모(국내/외국)가 먼저 오고 말단이 뒤따른다.
            # 부모 수 k = 헤더 수 − 말단 수. 외국 쪽 부모부터 걷어낸다
            # (자식 없는 국내는 그 자체가 말단인 경우가 있다 — LGD).
            k = len(heads) - (len(vals) - 1)
            if k < 0:
                continue
            for parent in ("외국", "해외", "국외", "국내"):
                while k > 0 and parent in heads:
                    heads.remove(parent)
                    k -= 1
            if k > 0:
                heads = heads[k:]
            # 조정 열(연결조정 등)이 낀 표는 소계 빈 셀 때문에 이름 매핑이
            # 한 칸씩 밀릴 수 있다 — 통째로 거부한다 (삼성전기 FY2024에서 실제 발생).
            if any("조정" in h or "소재지" in h for h in heads):
                continue
            return dict(zip(heads, vals[:-1])), vals[-1]
        return None

    # 표 후보 — 제목의 모든 등장 위치를 순서대로 시도한다. 첫 등장이
    # 산문(참조 문장)이거나 다른 표일 수 있다 (LGD·KT&G에서 실제로 그랬다).
    spots = []
    for hd in _RG_HEADINGS:
        for m in re.finditer(re.escape(hd), text):
            spots.append(m.start())
    spots.sort()
    for at in spots:
        chunk = text[at:at + 8000]
        lines = [ln.strip().rstrip("|").strip() for ln in chunk.split("\n")]
        lines = [ln for ln in lines if ln]
        unit = "?"
        for ln in lines:
            m2 = re.match(r"\(단위\s*:\s*([^)]+)\)", ln)
            if m2:
                unit = m2.group(1).strip()
                break

        # A) 행형 — 당기/전기 블록 각각에서 수익 행을 찾는다.
        cur_at = prev_at = -1
        for i, ln in enumerate(lines):
            if re.fullmatch(r"당\s*기", ln) and cur_at < 0:
                cur_at = i
            elif re.fullmatch(r"전\s*기", ln) and cur_at >= 0:
                prev_at = i
                break
        if cur_at >= 0 and prev_at > cur_at:
            cur = parse_block(lines[cur_at:prev_at])
            prev = parse_block(lines[prev_at:])
            if cur and prev:
                return {"cur": cur[0], "cur_total": cur[1],
                        "prev": prev[0], "prev_total": prev[1], "unit": unit}

        # B) 열형 — '구분 | 당기 | 전기' 행 나열, 합계 행으로 끝 (티엘비).
        cur_d, prev_d = {}, {}
        i = 0
        while i < len(lines) - 2:
            nm, a, b = lines[i], lines[i + 1], lines[i + 2]
            if (not _IS_NUM_RE.fullmatch(nm) and _IS_NUM_RE.fullmatch(a)
                    and _IS_NUM_RE.fullmatch(b) and not nm.startswith("(단위")):
                nm2 = nm.split("(주")[0].strip().replace(" ", "")
                if nm2 in ("합계", "계", "총계", "지역합계"):
                    ct, pt = _to_int(a), _to_int(b)
                    ok = (cur_d and abs(sum(cur_d.values()) - ct) <= max(2, abs(ct) * 1e-6)
                          and abs(sum(prev_d.values()) - pt) <= max(2, abs(pt) * 1e-6)
                          and not any("조정" in n or "소재지" in n for n in cur_d))
                    if ok:
                        return {"cur": cur_d, "cur_total": ct,
                                "prev": prev_d, "prev_total": pt, "unit": unit}
                    break
                if nm2 not in _RG_SKIP and not re.fullmatch(r"[당전][분반]?기", nm2):
                    cur_d[nm2] = _to_int(a)
                    prev_d[nm2] = _to_int(b)
                i += 3
                continue
            i += 1
    raise SystemExit(f"{rcp_no}: 지역별 표 형태를 해석하지 못했다")


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
