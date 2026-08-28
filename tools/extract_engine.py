#!/usr/bin/env python3
"""HTML 모델 파일에서 최상위 JS 선언을 이름으로 뽑아낸다.

model.html은 브라우저에서만 도는 단일 파일이다. 검증을 CI에서 돌리려면
DOM에 손대지 않는 부분 — 데이터와 수식 엔진 — 만 떼어내 Node로 실행해야 한다.
이 모듈이 그 절단면을 담당한다.

사용:
    from extract_engine import extract
    js = extract(html_path, ['YRS', 'MODEL', 'simCalc', ...])
"""
from __future__ import annotations

import re
import sys

# 파일에서 모델 스크립트를 찾는 표지. MODEL 정의가 들어있는 <script>가 본체다.
_SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.S)


def main_script(html: str) -> str:
    """인라인 <script> 본문을 전부 이어붙여 반환한다.

    모델 HTML은 데이터·엔진 스크립트와 뷰 셸 스크립트로 나뉘어 있고,
    최상위 선언이 양쪽에 흩어져 있다. 둘을 합쳐 하나의 검색 대상으로 본다.
    """
    bodies = _SCRIPT_RE.findall(html)
    if not any(re.search(r"^const\s+MODEL\s*=", b, re.M) for b in bodies):
        raise SystemExit("MODEL 선언이 있는 <script> 블록을 찾지 못했습니다.")
    return "\n".join(bodies)


def _skip_noncode(src: str, i: int) -> int | None:
    """i가 주석·문자열의 시작이면 그 끝 다음 인덱스를, 아니면 None을 준다."""
    n = len(src)
    ch = src[i]
    nxt = src[i + 1] if i + 1 < n else ""
    if ch == "/" and nxt == "/":
        end = src.find("\n", i)
        return n if end == -1 else end
    if ch == "/" and nxt == "*":
        end = src.find("*/", i + 2)
        return n if end == -1 else end + 2
    if ch in "\"'`":
        j = i + 1
        while j < n:
            if src[j] == "\\":
                j += 2
                continue
            if src[j] == ch:
                return j + 1
            j += 1
        return n
    return None


def _scan_function(src: str, start: int) -> int:
    """function 선언의 끝 인덱스(배타). 본문 여는 중괄호부터 짝을 맞춘다."""
    i, n = start, len(src)
    depth = 0
    in_body = False
    while i < n:
        skip = _skip_noncode(src, i)
        if skip is not None:
            i = skip
            continue
        ch = src[i]
        if ch == "{":
            in_body = True
            depth += 1
        elif ch == "}":
            depth -= 1
            if in_body and depth == 0:
                return i + 1
        i += 1
    return n


def _scan_assignment(src: str, start: int) -> int:
    """const/let/var 선언의 끝 인덱스(배타). depth 0의 ';' 또는 줄바꿈에서 끊는다."""
    i, n = start, len(src)
    depth = 0
    while i < n:
        skip = _skip_noncode(src, i)
        if skip is not None:
            i = skip
            continue
        ch = src[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and ch == ";":
            return i + 1
        elif depth == 0 and ch == "\n":
            return i
        i += 1
    return n


def _decl_pattern(name: str) -> re.Pattern:
    esc = re.escape(name)
    return re.compile(
        rf"^(?:function\s+{esc}\s*\(|(?:const|let|var)\s+{esc}\s*=)", re.M
    )


def extract(html_path: str, names: list[str],
            optional: set[str] | None = None) -> str:
    """names에 든 최상위 선언을 원문 그대로 이어붙여 돌려준다.

    optional에 든 이름은 없어도 넘어간다. 엔진 세대가 다른 두 파일
    (패치 전 원본과 패치 후 템플릿)을 같은 목록으로 다룰 때 쓴다.
    """
    optional = optional or set()
    with open(html_path, encoding="utf-8") as fh:
        src = main_script(fh.read())

    out: list[str] = []
    missing: list[str] = []
    for name in names:
        m = _decl_pattern(name).search(src)
        if not m:
            if name not in optional:
                missing.append(name)
            continue
        scan = _scan_function if m.group().startswith("function") else _scan_assignment
        out.append(src[m.start(): scan(src, m.start())].rstrip())
    if missing:
        raise SystemExit("선언을 찾지 못했습니다: " + ", ".join(missing))
    return "\n\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("사용법: extract_engine.py <model.html> <이름> [이름...]")
    print(extract(sys.argv[1], sys.argv[2:]))
