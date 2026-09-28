"""
Top 3 풀백 추적 (8주) — 매일 뉴욕 장 마감 후
- 대상: Daily Top 3 (Market_Data.md 기록), Weekly Top 3 (archive/weekly), Monthly Top 3 (archive/monthly)
- 신호일부터 8주 동안, 1파(오르기 시작한 저점 → 신호 후 최고가) 대비 지금 얼마나 되돌렸는지 계산
  - Daily·Weekly Top 3 : 주봉 기준 (저점은 고점 전 13주 / 26주 안)
  - Monthly Top 3     : 월봉 기준 (저점은 고점 전 12개월 안)
- 30~70% 되돌림 = 🔔 풀백 구간 (어떤 가격이든), 70% 이탈(종가) = ⚠️ 종료, 신호 후 계속 신고가 = 🚀
- 결과: top3/follow/YYYY-MM-DD.md, top3/follow/latest.md
"""
import json
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf

OUT = "top3/follow"
DAYS = 56
PAT = re.compile(r'quote\.ashx\?t=([A-Z0-9.\-]+)"[^>]*>[^<]*</a>\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*([+\-][0-9.]+%)')


def fv(t):
    return f'<a href="https://finviz.com/quote.ashx?p=w&t={t}" target="_blank">{t}</a>'


def section(md, title):
    m = re.search(r"## " + re.escape(title) + r"\n(.*?)(?:\n## |\Z)", md, re.S)
    return m.group(1) if m else ""


def daily_signals():
    out = {}
    shas = subprocess.run(["git", "log", "--format=%H", f"--since={DAYS + 14}.days", "--", "Market_Data.md"],
                          capture_output=True, text=True).stdout.split()
    for sha in shas:
        md = subprocess.run(["git", "show", f"{sha}:Market_Data.md"], capture_output=True, text=True).stdout
        m = re.search(r"마지막 업데이트: (\d{4}-\d{2}-\d{2}) (\d{2})", md)
        if not m:
            continue
        ts = pd.Timestamp(m.group(1) + " " + m.group(2) + ":00", tz="UTC").tz_convert("America/New_York")
        day = ts.normalize() - (pd.Timedelta(days=1) if ts.hour < 16 else pd.Timedelta(0))
        while day.weekday() >= 5:
            day -= pd.Timedelta(days=1)
        d = day.strftime("%Y-%m-%d")
        for t, name, sector, chg in PAT.findall(section(md, "Daily Top 3")):
            out.setdefault((t, "D", d), {"name": name.strip(), "sector": sector.strip(), "chg": chg})
    return out


def archive_signals(sub, kind):
    out = {}
    if not os.path.isdir(f"archive/{sub}"):
        return out
    for f in sorted(os.listdir(f"archive/{sub}")):
        md = open(f"archive/{sub}/{f}", encoding="utf-8").read()
        m = re.search(r"→ (\d{4}-\d{2}-\d{2})", md)
        if not m:
            continue
        for t, name, sector, chg in PAT.findall(md):
            out.setdefault((t, kind, m.group(1)), {"name": name.strip(), "sector": sector.strip(), "chg": chg})
    return out


def zone(r):
    if r < 0:
        return (False, "🚀 신고가 (풀백 전)", 0)
    if r < 30:
        return (False, "🟢 고점 근처 (0~30%)", 1)
    if r < 38.2:
        return (True, "🔔 30~38.2%", 2)
    if r < 50:
        return (True, "🔔 38.2~50%", 3)
    if r < 61.8:
        return (True, "🔔 50~61.8%", 4)
    if r <= 70:
        return (True, "🔔 61.8~70% (마지막 방어선)", 5)
    return (False, "⚠️ 70% 이탈 → 종료", 8)


def main():
    os.makedirs(OUT, exist_ok=True)
    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    sig = {**daily_signals(), **archive_signals("weekly", "W"), **archive_signals("monthly", "M")}
    sig = {k: v for k, v in sig.items() if (today - pd.Timestamp(k[2])).days <= DAYS}
    tickers = sorted({k[0].replace(".", "-") for k in sig})
    if not tickers:
        print("추적할 Top 3 없음")
        return
    d = yf.download(tickers + ["QQQ"], period="3y", interval="1d", auto_adjust=True, progress=False, group_by="column")
    last = d["Close"]["QQQ"].dropna().index[-1]
    rows = []
    for (t, kind, sd), info in sig.items():
        y = t.replace(".", "-")
        if y not in d["Close"].columns:
            continue
        c, h, l = d["Close"][y].dropna(), d["High"][y].dropna(), d["Low"][y].dropna()
        if c.empty:
            continue
        s = pd.Timestamp(sd)
        if kind == "M":
            H, Lo, back = h.resample("ME").max(), l.resample("ME").min(), 12
            start = s.to_period("M").to_timestamp("M")
        else:
            H, Lo, back = h.resample("W-FRI").max(), l.resample("W-FRI").min(), (13 if kind == "D" else 26)
            start = s - pd.Timedelta(days=s.weekday()) + pd.Timedelta(days=4)
        hw = H[H.index >= start]
        if hw.empty:
            continue
        hd, hi = hw.idxmax(), float(hw.max())
        lw = Lo[Lo.index <= hd].iloc[-back:]
        lo = float(lw.min())
        if hi <= lo:
            continue
        close = float(c.iloc[-1])
        retr = (hi - close) / (hi - lo) * 100
        alert, zname, order = zone(retr)
        if (hi / lo - 1) < 0.08 and order < 8:   # 1파가 8%도 안 되면 풀백 %가 의미 없음
            alert, zname, order = (False, "📏 1파 작음 (8% 미만)", 1)
        lv = {k: round(hi - (hi - lo) * k / 100, 2) for k in (30, 50, 70)}
        rows.append({"ticker": t, "kind": kind, "date": sd, "name": info["name"], "sector": info["sector"], "chg": info["chg"],
                     "close": round(close, 2), "high": round(hi, 2), "low": round(lo, 2), "retr": round(retr, 1),
                     "zone": zname, "alert": alert, "order": order, "lv": lv,
                     "weeks": (today - s).days // 7, "since": round((close / float(c[c.index <= s].iloc[-1]) - 1) * 100, 1) if (c.index <= s).any() else None})
    # 같은 티커가 여러 번 뜨면 가장 최근 신호 하나만 (D·W·M 표시는 합침)
    by = {}
    for r in sorted(rows, key=lambda r: r["date"]):
        prev = by.get(r["ticker"])
        kinds = (prev["kinds"] if prev else set()) | {r["kind"]}
        by[r["ticker"]] = dict(r, kinds=kinds)
    rows = list(by.values())
    lab = {"D": "Daily", "W": "Weekly", "M": "Monthly"}
    kinds_txt = lambda r: "·".join(lab[k] for k in ("D", "W", "M") if k in r["kinds"])
    live = sorted([r for r in rows if r["alert"]], key=lambda r: (-r["order"], r["date"]))
    wait = sorted([r for r in rows if not r["alert"] and r["order"] < 8], key=lambda r: -r["retr"])
    done = [r for r in rows if r["order"] == 8]
    ny = last.strftime("%Y-%m-%d")
    head = "| 티커 | Top 3 | 신호일 | 구간 | 되돌림 | 종가 | 30% ~ 70% 가격 (50%) | 신호일 이후 |\n| :--- | :--- | :--- | :--- | ---: | ---: | :--- | ---: |\n"
    def line(r):
        since = "" if r["since"] is None else f"{r['since']:+.1f}%"
        return (f"| {fv(r['ticker'])} | {kinds_txt(r)} | {r['date'][5:]} ({r['weeks']}주 전) | {r['zone']} | {r['retr']:.0f}% | "
                f"{r['close']} | {r['lv'][30]} ~ {r['lv'][70]} ({r['lv'][50]}) | {since} |\n")
    md = f"# 🔔 Top 3 풀백 추적 — {ny} 뉴욕 종가\n\n"
    md += f"> 최근 8주 Daily·Weekly·Monthly Top 3 {len(rows)}개 추적 · **풀백 구간(30~70%) {len(live)}개** · 1파 = 오르기 시작한 저점 → 신호 후 최고가 · 티커 = Finviz 주봉\n\n"
    if live:
        md += head + "".join(line(r) for r in live[:10])
        if len(live) > 10:
            md += f"\n> [!note]- 나머지 풀백 {len(live) - 10}개\n" + "".join("> " + x + "\n" for x in (head + "".join(line(r) for r in live[10:])).strip().split("\n"))
    else:
        md += "오늘 풀백 구간(30~70%)에 있는 Top 3 종목이 없어요.\n"
    if wait:
        md += f"\n> [!note]- 대기 {len(wait)}개 (아직 30% 전 또는 신고가)\n> " + ", ".join(f"{r['ticker']} {max(r['retr'], 0):.0f}%" for r in wait) + "\n"
    if done:
        md += "\n⚠️ 70% 이탈로 종료: " + ", ".join(r["ticker"] for r in done) + "\n"
    md += "\n> 알림 = '지켜볼 자리'. 진입은 7개 룰을 차트로 직접 확인\n"
    open(f"{OUT}/{ny}.md", "w", encoding="utf-8").write(md)
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    json.dump({"ny_date": ny, "rows": [dict(r, kinds=sorted(r["kinds"])) for r in rows],
               "generated_utc": datetime.now(timezone.utc).isoformat()},
              open(f"{OUT}/latest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(md)


if __name__ == "__main__":
    main()
