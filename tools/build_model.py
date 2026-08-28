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
