#!/usr/bin/env python3
"""companies/*/model.html → index.html (워치리스트)

다섯 모델이 파일로 흩어져 있으면 "다음에 뭘 볼까"가 기억에 남는다.
괴리·기대값·비대칭·컨센서스 방향·분기 진행률을 한 장에 놓는다.

숫자는 전부 각 모델을 하네스로 실행해 그 자리에서 읽는다 — 손으로 옮겨
적은 값이 없으므로 모델과 어긋날 수 없다 (리포트 뷰와 같은 규칙).

사용:
    python3 tools/build_index.py            # → index.html
"""
from __future__ import annotations

import datetime
import glob
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import run as run_model  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "index.html")

# design-guide/tokens.js와 같은 값 — 워치리스트도 같은 시각 언어를 쓴다.
C_INK = "#0F0F12"
C_REV = "#1E2185"
C_POS = "#22C55E"
C_NEG = "#DC2626"
C_TXT = "#6B7280"
C_GRID = "#E5E7EB"


def esc(s):
    return html.escape(str(s), quote=True)


def pct(x, digits=0):
    if x is None:
        return "—"
    return f"{'+' if x >= 0 else ''}{x * 100:.{digits}f}%"


def money(v):
    """억원 → 조원 축약 표기."""
    if v is None:
        return "—"
    if abs(v) >= 10000:
        return f"{v / 10000:,.1f}조"
    return f"{v:,.0f}억"


def row_for(path: str) -> dict:
    rep = run_model(path)
    v, yrs, hist_n = rep["values"], rep["YRS"], rep["HIST_N"]
    t = len(yrs) - 1
    mk = rep.get("market") or {}
    memo = rep.get("memo") or {}
    cons = rep.get("consensus") or {}
    meta = rep.get("meta") or {}

    root = None
    for k in ("root",):
        if k in v:
            root = v[k]
    if root is None:  # rootId는 parent 없는 노드 — 관례상 'root'
        raise SystemExit(f"{path}: root 노드를 찾지 못했다")

    fair = root[t]
    mktcap = mk.get("mktcap")
    up = fair / mktcap - 1 if mktcap else None

    # 방법 — 배수법이면 목표배수, 아니면 DCF(WACC)
    if "target_ev_ebitda" in v:
        method = f"EV/EBITDA {v['target_ev_ebitda'][t]:g}배"
    elif "wacc" in v:
        method = f"DCF · WACC {v['wacc'][t] * 100:.1f}%"
    else:
        method = "—"

    # 기대 괴리·상하방 배율 — 시나리오 해는 하네스가 계산해 준다.
    sroots = rep.get("scenarioRoots") or {}
    probs = memo.get("probs")
    ev = rr = None
    if mktcap and sroots:
        ups = {"Base": up}
        for nm, val_ in sroots.items():
            ups[nm] = val_ / mktcap - 1
        hi, lo = max(ups.values()), min(ups.values())
        if hi > 0 and lo < 0:
            rr = hi / -lo
        if probs and all(k in ups for k in probs):
            ev = sum(p * ups[k] for k, p in probs.items())

    # 주주 몫 — 함의 PER·배당수익률
    per = None
    if mktcap and "net_income" in v and v["net_income"][t] > 0:
        per = mktcap / v["net_income"][t]
    dy = None
    if mk.get("price") and "dps" in v and v["dps"][hist_n] > 0:
        dy = v["dps"][hist_n] / mk["price"]

    # 컨센서스 목표가 방향
    consensus = "커버리지 공백"
    if cons.get("targetPrice") and mk.get("price"):
        cu = cons["targetPrice"] / mk["price"] - 1
        n = cons.get("nAnalysts")
        consensus = f"목표가 {pct(cu)}" + (f" ({n}곳)" if n else "")

    # 분기 진행률 — 최신 확정 분기가 속한 해의 누적 매출 대 모델 연간.
    prog = None
    q = rep.get("quarterly") or {}
    quarters = q.get("quarters") or {}
    if quarters:
        keys = sorted(quarters)
        last = keys[-1]
        year, nq = last[:4], int(last[5:])
        acc = 0.0
        ok = True
        for k in keys:
            if k[:4] != year:
                continue
            rec = quarters[k].get("합계") or {}
            if rec.get("매출") is None:
                ok = False
                break
            acc += rec["매출"]
        rev_node = meta.get("revenueNode") or (
            "total_revenue" if "total_revenue" in v else "revenue")
        if ok and year in yrs and rev_node in v:
            plan = v[rev_node][yrs.index(year)]
            if plan:
                prog = {"label": f"{last} 누적", "rate": acc / plan,
                        "pace": nq / 4}

    co_dir = os.path.basename(os.path.dirname(path))
    return {
        "dir": co_dir,
        "brand": meta.get("brand") or co_dir,
        "method": method,
        "asOf": mk.get("asOf", ""),
        "mktcap": mktcap,
        "fair": fair,
        "fairYear": yrs[t],
        "up": up,
        "ev": ev,
        "rr": rr,
        "per": per,
        "dy": dy,
        "consensus": consensus,
        "prog": prog,
    }


def cell_pct(x, digits=0):
    if x is None:
        return '<td>—</td>'
    cls = "pos" if x >= 0 else "neg"
    return f'<td class="{cls}">{pct(x, digits)}</td>'


def build() -> str:
    paths = sorted(glob.glob(os.path.join(ROOT, "companies", "*", "model.html")))
    rows = [row_for(p) for p in paths]
    # 기대 괴리(없으면 괴리) 내림차순 — "다음에 볼 것"이 위로 온다.
    rows.sort(key=lambda r: (r["ev"] if r["ev"] is not None else (r["up"] or 0)),
              reverse=True)

    trs = ""
    for r in rows:
        prog = "—"
        if r["prog"]:
            gap = r["prog"]["rate"] - r["prog"]["pace"]
            sign = "+" if gap >= 0 else ""
            prog = (f'{r["prog"]["label"]} {r["prog"]["rate"] * 100:.0f}%'
                    f' <span class="{"pos" if gap >= 0 else "neg"}">'
                    f'({sign}{gap * 100:.0f}%p)</span>')
        trs += (
            '<tr>'
            f'<td class="nm"><a href="companies/{esc(r["dir"])}/model.html">{esc(r["brand"])}</a>'
            f'<div class="sub">{esc(r["method"])} · 관측 {esc(r["asOf"])}</div></td>'
            f'<td>{money(r["mktcap"])}</td>'
            f'<td>{money(r["fair"])}<div class="sub">{esc(r["fairYear"])}</div></td>'
            + cell_pct(r["up"])
            + cell_pct(r["ev"])
        )
        trs += f'<td>{r["rr"]:.1f} : 1</td>' if r["rr"] is not None else '<td>—</td>'
        trs += f'<td>{r["per"]:.1f}배</td>' if r["per"] is not None else '<td>—</td>'
        trs += f'<td>{r["dy"] * 100:.1f}%</td>' if r["dy"] is not None else '<td>—</td>'
        trs += f'<td>{esc(r["consensus"])}</td>'
        trs += f'<td class="prog">{prog}</td>'
        trs += '</tr>'

    today = datetime.date.today().isoformat()
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>투자심사 워치리스트</title>
<style>
  body{{margin:0;background:#F8F8FA;color:{C_INK};
    font:13px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans KR',sans-serif}}
  .wrap{{max-width:1180px;margin:0 auto;padding:36px 24px 60px}}
  h1{{font-size:21px;margin:0 0 4px}}
  .lead{{color:{C_TXT};font-size:12.5px;margin:0 0 22px}}
  table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid {C_GRID};
    border-radius:10px;overflow:hidden}}
  th{{font-size:11px;color:{C_TXT};text-transform:none;font-weight:600;text-align:right;
    padding:10px 12px;border-bottom:1px solid {C_GRID};background:#FBFBFC;white-space:nowrap}}
  th:first-child{{text-align:left}}
  td{{padding:11px 12px;border-bottom:1px solid #F3F4F6;text-align:right;white-space:nowrap;
    font-variant-numeric:tabular-nums}}
  td.nm{{text-align:left}}
  td.nm a{{color:{C_REV};font-weight:700;text-decoration:none;font-size:13.5px}}
  td.nm a:hover{{text-decoration:underline}}
  .sub{{font-size:10.5px;color:#9CA3AF;margin-top:2px}}
  .pos{{color:{C_POS};font-weight:600}}
  .neg{{color:{C_NEG};font-weight:600}}
  td.prog{{font-size:12px}}
  .foot{{margin-top:14px;color:#9CA3AF;font-size:11px;line-height:1.7}}
  tr:hover td{{background:#FAFAFE}}
</style>
</head>
<body>
<div class="wrap">
  <h1>투자심사 워치리스트</h1>
  <p class="lead">숫자는 전부 각 모델(model.html)을 실행해 읽은 값 — 손으로 옮겨 적지 않는다.
    갱신: <b>python3 tools/build_index.py</b> · 생성 {today}</p>
  <table>
    <tr><th>종목</th><th>현재 시총</th><th>적정 시총</th><th>괴리</th>
      <th>기대 괴리*</th><th>상하방 배율</th><th>함의 PER</th><th>배당수익률</th>
      <th>컨센서스 목표가</th><th>분기 진행률</th></tr>
    {trs}
  </table>
  <p class="foot">* 기대 괴리 = 시나리오별 괴리의 확률 가중(확률은 각 모델 MEMO.probs의 [주관] 판단) ·
    상하방 배율 = 최상 시나리오 상방 ÷ 최악 시나리오 하방 ·
    함의 PER = 현재 시총 ÷ 마지막 추정 연도 지배순이익 ·
    배당수익률 = 다음 해 추정 DPS ÷ 현재가 ·
    분기 진행률 = 확정 분기 누적 매출 ÷ 모델 연간 (괄호 안은 선형 대비) ·
    행 순서 = 기대 괴리 내림차순.<br>
    본 자료는 공시·시장 데이터 기반의 내부 검토용이며 투자권유가 아님.</p>
</div>
</body>
</html>
"""


def main() -> int:
    doc = build()
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"{OUT} 생성 ({len(doc):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
