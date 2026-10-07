"""
2026-10-07 일회용: 지난 Weekly/Monthly 확정 기록 다시 계산
이유: 예전 백업 계산이 Nasdaq 목록을 써서 우선주·유닛(BTSGU, BPYPO, MCHPP, BRKRP, SMCIP)이
      모회사 시가총액으로 $10B+에 섞여 들어감 → Finviz 화면과 다른 결과.
방법: Finviz +Large($10B+) 종목군 + yfinance 종가로 같은 기간 수익률 상위 3개.
"""
import datetime, os
import pandas as pd
import yfinance as yf
import cloud_market_data as c

PERIODS = [("Weekly", "2026-W38", datetime.date(2026, 9, 14), datetime.date(2026, 9, 18)),
           ("Weekly", "2026-W39", datetime.date(2026, 9, 21), datetime.date(2026, 9, 25)),
           ("Weekly", "2026-W40", datetime.date(2026, 9, 28), datetime.date(2026, 10, 2)),
           ("Monthly", "2026-08", datetime.date(2026, 8, 1), datetime.date(2026, 8, 31)),
           ("Monthly", "2026-09", datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))]

info = c.get_finviz_large_cap_universe()
print(f"Finviz +Large 종목 수: {len(info)}")
assert len(info) > 300, "Finviz 목록이 너무 적음"
data = yf.download(list(info), start="2026-07-15", end="2026-10-06", interval="1d",
                   auto_adjust=True, progress=False, threads=True)
close = data["Close"].dropna(how="all")
log = "# 🔁 확정 기록 재계산 (2026-10-07)\n\n> Finviz +Large($10B+) 종목군 + yfinance 종가\n\n"
for kind, name, start, end in PERIODS:
    path = os.path.join("archive", kind.lower(), f"{name}.md")
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    rows, b, f = c.period_top3(close, start, end, info)
    md = c._archive_md(kind, name, rows, b, f, "Finviz +Large($10B+) 종목군 재계산")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(md)
    old_t = [l.split("](")[0][3:] for l in old.splitlines() if l.startswith("| [")]
    log += f"- **{kind} {name}** ({b} → {f}): 이전 {', '.join(old_t) or '-'} → 새 " + \
           ", ".join(f"{t} {v:+.2f}%" for t, _, _, v in rows) + "\n"
    print(name, [r[0] for r in rows])
open(os.path.join("archive", "rebuild_2026-10-07.md"), "w", encoding="utf-8").write(log)
print(log)
