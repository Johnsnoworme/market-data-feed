"""
Top 3 풀백 추적 (8주) — 매일 뉴욕 장 마감 후
- 대상: Daily Top 3 (Market_Data.md 기록), Weekly Top 3 (archive/weekly), Monthly Top 3 (archive/monthly)
- 신호일부터 8주 동안, 1파(오르기 시작한 저점 → 신호 후 최고가) 대비 지금 얼마나 되돌렸는지 계산
  - Daily·Weekly Top 3 : 주봉 기준 (저점은 고점 전 13주 / 26주 안)
  - Monthly Top 3     : 월봉 기준 (저점은 고점 전 12개월 안)
- 30~70% 되돌림 = 🔔 풀백 구간 (어떤 가격이든), 70% 이탈(종가) = ⚠️ 종료, 신호 후 계속 신고가 = 🚀
- 김종봉 후보(scanner/jb/picks.json, 주봉 26주), 소셜 아비트리지(social/shown.json, 주봉 13주)도 출처별로 따로 추적
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


def json_signals(path, kind):
    """김종봉 picks.json {t: {date,...}} / 소셜 shown.json {t: date}"""
    if not os.path.exists(path):
        return {}
    out = {}
    for t, v in json.load(open(path, encoding="utf-8")).items():
        d = v["date"] if isinstance(v, dict) else v
        out[(t, kind, d)] = {"name": v.get("name", "") if isinstance(v, dict) else "", "sector": "", "chg": ""}
    return out


# 📡 소셜 아비트리지는 2026-09-28 멈춤 (백테스트 결과). 다시 켜려면 아래 SRC와 sig에 "S" 추가
SRC = {"T": ("🏆 내 Top 3", ("D", "W", "M")), "J": ("🧭 김종봉 후보", ("J",))}
LAB = {"D": "Daily", "W": "Weekly", "M": "Monthly", "J": "주간", "S": "일간"}


def main():
    os.makedirs(OUT, exist_ok=True)
    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    sig = {**daily_signals(), **archive_signals("weekly", "W"), **archive_signals("monthly", "M"),
           **json_signals("scanner/jb/picks.json", "J")}
    sig = {k: v for k, v in sig.items() if (today - pd.Timestamp(k[2])).days <= DAYS}
    tickers = sorted({k[0].replace(".", "-") for k in sig})
    if not tickers:
        print("추적할 종목 없음")
        return
    d = yf.download(tickers + ["QQQ"], period="3y", interval="1d", auto_adjust=True, progress=False, group_by="column")
    last = d["Close"]["QQQ"].dropna().index[-1]
    from ny_session import require_fresh
    require_fresh(last, "Top 3 풀백 추적")  # 그날 종가가 없으면 저장하지 않고 종료 (2026-10-05)
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
            H, Lo, back = h.resample("W-FRI").max(), l.resample("W-FRI").min(), (26 if kind in ("W", "J") else 13)
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
        src = next(k for k, v in SRC.items() if kind in v[1])
        rows.append({"ticker": t, "kind": kind, "src": src, "date": sd, "name": info["name"], "sector": info["sector"], "chg": info["chg"],
                     "close": round(close, 2), "high": round(hi, 2), "low": round(lo, 2), "retr": round(retr, 1),
                     "zone": zname, "alert": alert, "order": order, "lv": lv,
                     "weeks": (today - s).days // 7, "since": round((close / float(c[c.index <= s].iloc[-1]) - 1) * 100, 1) if (c.index <= s).any() else None})
    # 출처별로, 같은 티커가 여러 번 뜨면 가장 최근 신호 하나만 (D·W·M 표시는 합침)
    by = {}
    for r in sorted(rows, key=lambda r: r["date"]):
        key = (r["src"], r["ticker"])
        prev = by.get(key)
        kinds = (prev["kinds"] if prev else set()) | {r["kind"]}
        by[key] = dict(r, kinds=kinds)
    rows = list(by.values())
    kinds_txt = lambda r: "·".join(LAB[k] for k in ("D", "W", "M", "J", "S") if k in r["kinds"])
    ny = last.strftime("%Y-%m-%d")
    head = "| 티커 | 신호 | 신호일 | 구간 | 되돌림 | 종가 | 30% ~ 70% 가격 (50%) | 신호일 이후 |\n| :--- | :--- | :--- | :--- | ---: | ---: | :--- | ---: |\n"
    def line(r):
        since = "" if r["since"] is None else f"{r['since']:+.1f}%"
        return (f"| {fv(r['ticker'])} | {kinds_txt(r)} | {r['date'][5:]} ({r['weeks']}주 전) | {r['zone']} | {r['retr']:.0f}% | "
                f"{r['close']} | {r['lv'][30]} ~ {r['lv'][70]} ({r['lv'][50]}) | {since} |\n")
    all_live = [r for r in rows if r["alert"]]
    md = f"# 🔔 풀백 추적 — {ny} 뉴욕 종가 (8주)\n\n"
    md += (f"> 🏆 내 Top 3 · 🧭 김종봉 후보 — 뜬 날부터 8주 추적 · **풀백 구간(30~70%) 총 {len(all_live)}개** "
           f"· 1파 = 오르기 시작한 저점 → 신호 후 최고가 · 티커 = Finviz 주봉\n")
    for src, (title, _) in SRC.items():
        rs = [r for r in rows if r["src"] == src]
        live = sorted([r for r in rs if r["alert"]], key=lambda r: (-r["order"], r["date"]))
        wait = sorted([r for r in rs if not r["alert"] and r["order"] < 8], key=lambda r: -r["retr"])
        done = [r for r in rs if r["order"] == 8]
        md += f"\n### {title} — 추적 {len(rs)}개 · 풀백 {len(live)}개\n"
        if not rs:
            md += "추적 중인 종목이 없어요.\n"
            continue
        if live:
            md += head + "".join(line(r) for r in live[:10])
            if len(live) > 10:
                md += f"\n> [!note]- 나머지 풀백 {len(live) - 10}개\n" + "".join("> " + x + "\n" for x in (head + "".join(line(r) for r in live[10:])).strip().split("\n"))
        else:
            md += "오늘 풀백 구간(30~70%)에 있는 종목이 없어요.\n"
        if wait:
            md += f"\n> [!note]- 대기 {len(wait)}개 (아직 30% 전 또는 신고가 · 📏 = 1파가 8% 미만이라 알림 제외)\n> " + ", ".join(f"{r['ticker']} {max(r['retr'], 0):.0f}%{' 📏' if r['zone'].startswith('📏') else ''}" for r in wait) + "\n"
        if done:
            md += "\n⚠️ 70% 이탈로 종료: " + ", ".join(r["ticker"] for r in done) + "\n"
    md += "\n> 알림 = '지켜볼 자리'. 진입은 7개 룰을 차트로 직접 확인 · 옵션: 9~12개월 ATM, +100% 익절 / 6개월 안 정리, 종가 70% 이탈 = 정리 ([[2026-09-28 레이더 백테스트 보고서]])\n"
    open(f"{OUT}/{ny}.md", "w", encoding="utf-8").write(md)
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    json.dump({"ny_date": ny, "rows": [dict(r, kinds=sorted(r["kinds"])) for r in rows],
               "generated_utc": datetime.now(timezone.utc).isoformat()},
              open(f"{OUT}/latest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(md)


if __name__ == "__main__":
    main()
