#!/usr/bin/env python3
"""templates/model_template.html + companies/<종목>/data.js → model.html

종목 작업에서 손으로 쓰는 파일은 data.js 하나다. 엔진은 템플릿에서 오고,
이 스크립트가 둘을 합친다. 엔진을 고치면 모든 종목이 다시 빌드되면서
같은 수정을 받는다 — 종목별로 엔진이 갈라지지 않는 유일한 방법이다.

사용:
    python3 tools/build_model.py companies/samsung-em/data.js
    python3 tools/build_model.py companies/samsung-em/data.js -o /tmp/out.html
"""
from __future__ import annotations

import argparse
import json
import os
import sys

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates",
                        "model_template.html")
DATA_START = "// <<<DATA:START>>>"
DATA_END = "// <<<DATA:END>>>"


def build(data_path: str, template_path: str = TEMPLATE) -> str:
    """데이터 블록을 주입한 완성 HTML 문자열을 돌려준다."""
    with open(template_path, encoding="utf-8") as fh:
        html = fh.read()
    with open(data_path, encoding="utf-8") as fh:
        data = fh.read().strip()
    data += _quarterly_block(data_path)
    data += _costnature_block(data_path)
    data += _prices_block(data_path)

    try:
        head = html.index(DATA_START)
        tail = html.index(DATA_END)
    except ValueError:
        raise SystemExit(
            f"템플릿에 데이터 마커가 없습니다: {template_path}\n"
            f"{DATA_START} / {DATA_END} 두 줄이 모두 있어야 합니다."
        )
    if tail < head:
        raise SystemExit("데이터 마커 순서가 뒤집혀 있습니다.")

    return (
        html[:head]
        + DATA_START
        + "\n"
        + data
        + "\n"
        + html[tail:]
    )



def _quarterly_block(data_path: str) -> str:
    """옆에 quarterly.json이 있으면 QUARTERLY 선언으로 붙인다.

    분기 확정값은 기계가 만든다(tools/build_quarterly.py). 손으로 쓰는 파일에
    넣으면 갱신할 때마다 사람이 수백 개 숫자를 옮겨 적게 된다 — 그 순간
    "data.js가 유일한 수기 파일"이라는 규약이 사람을 해치는 규약이 된다.
    """
    path = os.path.join(os.path.dirname(data_path) or ".", "quarterly.json")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return ("\n\n// ── QUARTERLY — 분기 확정값 (자동 주입) ─────────────────────\n"
            "// 출처: " + str(doc.get("_출처", "")) + "\n"
            "// 갱신: python3 tools/build_quarterly.py " + path + "\n"
            "const QUARTERLY = " + json.dumps(doc, ensure_ascii=False) + ";\n")


def _costnature_block(data_path: str) -> str:
    """옆에 cost_nature.json이 있으면 COSTNATURE 선언으로 붙인다.

    비용의 성격별 분류 주석 — 사업 구조 뷰의 비용 블록이 이것을 읽는다.
    QUARTERLY와 같은 규약: 공시 확정값은 기계가 만들고 빌드가 주입한다.
    화면 표시 전용이며 모델 노드가 아니다 — 게이트 G12가 Σ항목=합계와
    합계 대 (매출−영업이익) 대사를 매 빌드마다 검사한다.
    """
    path = os.path.join(os.path.dirname(data_path) or ".", "cost_nature.json")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return ("\n\n// ── COSTNATURE — 비용 성격별 분류 (자동 주입) ───────────────\n"
            "// 출처: 사업보고서 '비용의 성격별 분류' 주석 (" + path + ")\n"
            "const COSTNATURE = " + json.dumps(doc, ensure_ascii=False) + ";\n")


def _prices_block(data_path: str) -> str:
    """옆에 prices.json이 있으면 PRICES 선언으로 붙인다.

    월간 종가 스냅숏(tools/price_fetch.py) — 실적 대 시총 오버레이·배수 밴드
    차트가 읽는다. 빌드 타임에 박히므로 model.html은 여전히 외부 요청 0건.
    """
    path = os.path.join(os.path.dirname(data_path) or ".", "prices.json")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return ("\n\n// ── PRICES — 월간 종가 스냅숏 (자동 주입) ───────────────────\n"
            "// 갱신: python3 tools/price_fetch.py (" + path + ")\n"
            "const PRICES = " + json.dumps(doc, ensure_ascii=False) + ";\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="모델 HTML 빌드")
    ap.add_argument("data", help="종목 데이터 파일 (data.js)")
    ap.add_argument("-o", "--out",
                    help="출력 경로 (기본: 데이터 파일 옆의 model.html)")
    ap.add_argument("-t", "--template", default=TEMPLATE, help="템플릿 경로")
    args = ap.parse_args(argv)

    out = args.out or os.path.join(os.path.dirname(args.data) or ".", "model.html")
    html = build(args.data, args.template)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"{out} 빌드 완료 ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
