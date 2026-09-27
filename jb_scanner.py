"""
김종봉(JB) 스타일 주간 스캐너 v2
- 매주 금요일 뉴욕 장 마감 후 GitHub Actions에서 자동 실행
- 대상: 시가총액 $10B 이상 (미국 전체 상장 대형주 + S&P 500 + 나스닥 100 + 워치리스트 중 $10B+)
- 주간 신호 조건 (주봉, 모두 충족):
  1) 지수보다 강함 : 최근 13주 수익률 > QQQ, SPY 둘 다
  2) 풀백        : 직전 1~6주 사이 저가가 12주 이동평균선 +2% 이내 또는 아래로 내려온 적 있음
  3) 고개 듦      : 이번 주 종가 12주선 위 + 이번 주 상승 + 이번 주 수익률이 지수보다 높음
  4) 유동성      : 최근 4주 하루 평균 거래대금 2천만 달러 이상
- 두 칸으로 나눔:
  🚗 막 출발하는 차 (집중) : 눌림이 1~3주 전 + 12주선 대비 +15% 이내
  🏁 이미 달린 차 (학습용)  : 나머지
- ⭐ 인텔형: 월봉(⭐월)·주봉(⭐주) 두 가지. 긴 바닥 후 12개월선/12주선 위로 돌파 + 13주 수익률이 지수보다 강함 (jb_signals.py)
- 신호가 뜬 종목은 8주 동안 추적 리스트(tracking.json)에 올라가고, jb_pullback.py가 매일 풀백 구간을 계산
- 결과: scanner/jb/YYYY-MM-DD.md, latest.json, index.json, tracking.json
- 이미 같은 날짜 파일이 있으면 다시 쓰지 않음 (기록 보존)
"""
import io
import json
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests
import yfinance as yf

from jb_signals import monthly_star, weekly_star

OUT_DIR = "scanner/jb"
TRACK_PATH = f"{OUT_DIR}/tracking.json"
MA_WEEKS = 12
MA_MONTHS = 12
RS_WEEKS = 13
PULLBACK_LOOKBACK = 6
PULLBACK_BAND = 1.02
LAUNCH_MAX_WEEKS_AGO = 3
LAUNCH_MAX_ABOVE_MA = 15.0
MIN_DOLLAR_VOL_DAY = 20_000_000
MIN_MARKET_CAP = 10_000_000_000
TRACK_DAYS = 56  # 8주
SHOW_TOP = 5                # 칸마다 먼저 보여줄 개수 (나머지는 접어서 전부 기록)
EXCLUDE_WORDS = ("Preferred", "Warrant", " Unit", "Depositary Shares")
INDEXES = ["QQQ", "SPY"]
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def yf_symbol(t):
    return t.strip().upper().replace(".", "-").replace("/", "-")


def read_wiki_tables(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return pd.read_html(io.StringIO(r.text))


def get_sp500():
    info = {}
    try:
        for t in read_wiki_tables("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"):
            if "Symbol" in t.columns and "Security" in t.columns:
                for _, row in t.iterrows():
                    info[yf_symbol(str(row["Symbol"]))] = (str(row["Security"]), str(row.get("GICS Sector", "")))
                break
    except Exception as e:
        print(f"S&P 500 위키 실패: {e}")
    print(f"S&P 500: {len(info)}개")
    return info


def get_ndx():
    info = {}
    try:
        for t in read_wiki_tables("https://en.wikipedia.org/wiki/Nasdaq-100"):
            tick_col = next((c for c in t.columns if str(c) in ("Ticker", "Symbol")), None)
            name_col = next((c for c in t.columns if str(c) in ("Company", "Security")), None)
            if tick_col is not None and name_col is not None and len(t) > 80:
                sec_col = next((c for c in t.columns if "Sector" in str(c)), None)
                for _, row in t.iterrows():
                    info[yf_symbol(str(row[tick_col]))] = (str(row[name_col]), str(row[sec_col]) if sec_col is not None else "")
                break
    except Exception as e:
        print(f"나스닥 100 위키 실패: {e}")
    print(f"나스닥 100: {len(info)}개")
    return info


def get_large_caps():
    """미국 전체 상장 $10B+ (기존 Top 3 스크립트와 같은 Nasdaq 스크리너). 실패하면 빈 dict."""
    try:
        from cloud_market_data import get_large_cap_universe
        u = get_large_cap_universe()
        out = {yf_symbol(k): (v.get("Security", ""), v.get("GICS Sector", "")) for k, v in u.items()}
        print(f"$10B+ 전체 대형주: {len(out)}개")
        return out
    except Exception as e:
        print(f"$10B+ 목록 실패: {e} → 신호 종목만 개별 시총 확인")
        return {}


def get_watchlist():
    tickers = set()
    pat = re.compile(r"quote\.ashx\?t=([A-Z0-9.\-]+)")
    try:
        log = subprocess.run(["git", "log", "--since=60.days", "-p", "--", "Market_Data.md"],
                             capture_output=True, text=True, timeout=60).stdout
        tickers |= set(pat.findall(log))
    except Exception as e:
        print(f"git 기록 읽기 실패: {e}")
    if os.path.isdir("archive"):
        for dp, _, files in os.walk("archive"):
            for f in files:
                if f.endswith(".md"):
                    try:
                        tickers |= set(pat.findall(open(os.path.join(dp, f), encoding="utf-8").read()))
                    except Exception:
                        pass
    if os.path.exists("watchlist.txt"):
        for line in open("watchlist.txt", encoding="utf-8"):
            line = line.split("#")[0].strip()
            if line:
                tickers.add(line.upper())
    tickers = {yf_symbol(t) for t in tickers}
    print(f"워치리스트: {len(tickers)}개")
    return tickers


def download_daily(tickers, period="2y"):
    frames = []
    tickers = list(tickers)
    for i in range(0, len(tickers), 150):
        chunk = tickers[i:i + 150]
        d = yf.download(chunk, period=period, interval="1d", auto_adjust=True,
                        progress=False, group_by="column", threads=True)
        frames.append(d)
    return pd.concat(frames, axis=1)


def pct(a, b):
    try:
        return (a / b - 1) * 100 if b else float("nan")
    except Exception:
        return float("nan")


def market_cap(t):
    try:
        return float(yf.Ticker(t).fast_info["market_cap"] or 0)
    except Exception:
        return 0.0


def scan(daily, names, large_caps):
    close = daily["Close"].resample("W-FRI").last().dropna(how="all")
    low = daily["Low"].resample("W-FRI").min()
    dollar = (daily["Close"] * daily["Volume"]).resample("W-FRI").sum()
    days = daily["Close"].resample("W-FRI").count()
    mclose = daily["Close"].resample("ME").last()
    last = close.index[-1]

    idx13 = {k: pct(close[k].iloc[-1], close[k].iloc[-1 - RS_WEEKS]) for k in INDEXES}
    idx1 = {k: pct(close[k].iloc[-1], close[k].iloc[-2]) for k in INDEXES}
    q_chg = close["QQQ"].pct_change()

    weekly_hits, star_hits = [], []
    for t in close.columns:
        if t in INDEXES:
            continue
        c = close[t].dropna()
        if len(c) < MA_WEEKS + RS_WEEKS + 2 or c.index[-1] != last:
            continue
        ret13 = pct(c.iloc[-1], c.iloc[-1 - RS_WEEKS])
        if not all(ret13 > idx13[k] for k in INDEXES):
            continue  # 지수보다 강하지 않으면 두 목록 모두 제외
        dv = dollar[t].reindex(c.index).iloc[-4:].sum() / max(days[t].reindex(c.index).iloc[-4:].sum(), 1)
        if dv < MIN_DOLLAR_VOL_DAY:
            continue

        ma = c.rolling(MA_WEEKS).mean()
        lo = low[t].reindex(c.index)
        now, prev = c.iloc[-1], c.iloc[-2]
        ret1, ret4 = pct(now, prev), pct(now, c.iloc[-5])
        s_chg = c.pct_change().iloc[-8:]
        against = int(((q_chg.reindex(s_chg.index) < 0) & (s_chg > 0)).sum())
        name, sector = names.get(t, ("", ""))
        if any(w in name for w in EXCLUDE_WORDS):
            continue
        base = {
            "ticker": t, "name": name, "sector": sector,
            "week_pct": round(ret1, 2), "month_pct": round(ret4, 2), "ret13_pct": round(ret13, 2),
            "rs_vs_qqq": round(ret13 - idx13["QQQ"], 2), "rs_vs_spy": round(ret13 - idx13["SPY"], 2),
            "above_ma12_pct": round(pct(now, ma.iloc[-1]), 2), "against_index_weeks": against,
            "close": round(float(now), 2), "avg_dollar_vol_m": round(dv / 1e6, 1),
        }

        # ⭐ 인텔형: 월봉 12개월선 돌파(⭐월) / 주봉 12주선 돌파(⭐주) — 둘 다 긴 바닥 후
        sm = monthly_star(mclose[t])
        sw = weekly_star(c)
        tfs = [x["tf"] for x in (sm, sw) if x]
        base["star"] = "".join(tfs)
        if sm:
            star_hits.append(dict(base, tf="월", star_above_pct=sm["above_ma_pct"], star_base=sm["base"]))
        if sw:
            star_hits.append(dict(base, tf="주", star_above_pct=sw["above_ma_pct"], star_base=sw["base"]))

        # 주간 신호
        if not (now > ma.iloc[-1] and ret1 > 0 and all(ret1 > idx1[k] for k in INDEXES)):
            continue
        win = range(2, PULLBACK_LOOKBACK + 2)
        touched = [w for w in win if lo.iloc[-w] <= ma.iloc[-w] * PULLBACK_BAND]
        if not touched:
            continue
        weeks_ago = min(touched) - 1
        below_close = any(c.iloc[-w] < ma.iloc[-w] for w in win)
        launch = weeks_ago <= LAUNCH_MAX_WEEKS_AGO and base["above_ma12_pct"] <= LAUNCH_MAX_ABOVE_MA
        weekly_hits.append(dict(base, pullback="12주선 아래 종가" if below_close else "12주선 터치",
                                pullback_weeks_ago=weeks_ago, tier="launch" if launch else "learn"))

    # 시총 $10B+ 확인 (대형주 목록에 없으면 개별 확인)
    def cap_ok(r):
        if r["ticker"] in large_caps:
            return True
        cap = market_cap(r["ticker"])
        r["market_cap_b"] = round(cap / 1e9, 1)
        return cap >= MIN_MARKET_CAP
    weekly_hits = [r for r in weekly_hits if cap_ok(r)]
    star_hits = [r for r in star_hits if cap_ok(r)]
    for lst in (weekly_hits, star_hits):
        lst.sort(key=lambda r: r["rs_vs_qqq"], reverse=True)
    return weekly_hits, star_hits, idx13, idx1, last


def fill_names(rows):
    for r in rows:
        if r.get("name"):
            continue
        try:
            inf = yf.Ticker(r["ticker"]).info
            r["name"] = inf.get("shortName") or inf.get("longName") or ""
            r["sector"] = inf.get("sector") or ""
        except Exception:
            pass


def row_md(r, extra):
    star = (" ⭐" + r["star"]) if r.get("star") else ""
    return (f"| {r['ticker']}{star} | {r['name']} | {r['sector']} | {r['week_pct']:+.2f}% | {r['month_pct']:+.2f}% | "
            f"{r['rs_vs_qqq']:+.2f}%p | {r['above_ma12_pct']:+.2f}% | {extra} |\n")


HEAD = "| 티커 | 회사 | 섹터 | 이번 주 | 1개월 | 13주 vs QQQ | 12주선 대비 | {x} |\n| :--- | :--- | :--- | ---: | ---: | ---: | ---: | :--- |\n"


def table(rows, x, extra_fn):
    if not rows:
        return "이번 주 없음\n"
    md = HEAD.format(x=x) + "".join(row_md(r, extra_fn(r)) for r in rows[:SHOW_TOP])
    rest = rows[SHOW_TOP:]
    if rest:
        md += f"\n> [!note]- 나머지 {len(rest)}개 (13주 상대강도 순, 전부 추적 중)\n"
        md += "".join("> " + line + "\n" for line in (HEAD.format(x=x) + "".join(row_md(r, extra_fn(r)) for r in rest)).strip().split("\n"))
    return md


def to_md(weekly, stars, idx13, idx1, week_end, universe_n):
    d = week_end.strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    launch = [r for r in weekly if r["tier"] == "launch"]
    learn = [r for r in weekly if r["tier"] == "learn"]
    md = f"# 김종봉 스캐너 — {d} 주간\n\n"
    md += f"> 기준: {d}(금) 뉴욕 종가 · 시총 $10B+ · 확정 {now} · 검사 {universe_n}개 · 🚗 {len(launch)}개 · 🏁 {len(learn)}개 · ⭐월 {sum(r['tf']=='월' for r in stars)}개 · ⭐주 {sum(r['tf']=='주' for r in stars)}개\n"
    md += f"> 지수 13주: QQQ {idx13['QQQ']:+.2f}% / SPY {idx13['SPY']:+.2f}% · 이번 주: QQQ {idx1['QQQ']:+.2f}% / SPY {idx1['SPY']:+.2f}%\n\n"

    md += "### 🚗 막 출발하는 차 (집중)\n"
    md += "> 지수보다 강함 + 1~3주 전 12주선까지 눌림 + 이번 주 다시 상승 + 12주선 대비 +15% 이내 → 손익비가 맞는 자리 후보\n\n"
    md += table(launch, "눌림", lambda r: f"{r['pullback']} ({r['pullback_weeks_ago']}주 전)")

    stars_m = [r for r in stars if r["tf"] == "월"]
    stars_w = [r for r in stars if r["tf"] == "주"]
    md += "\n### ⭐ 인텔형 — 월봉 (⭐월)\n"
    md += "> 12개월 중 6개월 이상 월봉 12개월선 아래(긴 바닥) → 최근 2개월 안에 위로 돌파(+3%↑) + 13주 수익률이 지수보다 강함\n\n"
    md += table(stars_m, "12개월선 대비 · 바닥 개월", lambda r: f"{r['star_above_pct']:+.2f}% · {r['star_base']}/12")
    md += "\n### ⭐ 인텔형 — 주봉 (⭐주)\n"
    md += "> 26주 중 13주 이상 주봉 12주선 아래(긴 바닥) → 최근 2주 안에 위로 돌파(+2%↑) + 주 +4% 이상 양봉 + 13주 수익률이 지수보다 강함\n\n"
    md += table(stars_w, "12주선 대비 · 바닥 주", lambda r: f"{r['star_above_pct']:+.2f}% · {r['star_base']}/26")

    md += "\n### 🏁 이미 달린 차 (학습용)\n"
    md += "> 신호는 나왔지만 이미 멀리 감 → 손익비가 안 맞음. 차트 공부용으로만\n\n"
    md += table(learn, "눌림", lambda r: f"{r['pullback']} ({r['pullback_weeks_ago']}주 전)")
    md += "\n> 🔔 위 종목(🚗·⭐·🏁)은 8주 동안 추적 → 38.2% · 50% · 61.8% 풀백 구간에 오면 Daily 노트에 알림\n"
    return md


def update_tracking(weekly, stars, week_end):
    track = json.load(open(TRACK_PATH, encoding="utf-8")) if os.path.exists(TRACK_PATH) else {}
    d = week_end.strftime("%Y-%m-%d")
    expires = (week_end + timedelta(days=TRACK_DAYS)).strftime("%Y-%m-%d")
    wk = {r["ticker"]: r for r in weekly}
    seen = set(wk)
    rows = list(weekly)
    for r in stars:
        if r["ticker"] not in seen:
            seen.add(r["ticker"]); rows.append(r)
    for r in rows:
        t = r["ticker"]
        if t in wk:
            kind = ("🚗" if r["tier"] == "launch" else "🏁") + (("⭐" + r["star"]) if r.get("star") else "")
        else:
            kind = "⭐" + r.get("star", "")
        e = track.get(t)
        if e and e.get("status") == "active":
            e["last_seen"], e["expires"], e["kind"] = d, expires, kind
        else:
            track[t] = {"name": r.get("name", ""), "first_seen": d, "last_seen": d,
                        "expires": expires, "kind": kind, "status": "active", "last_zone": ""}
    json.dump(track, open(TRACK_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"추적 리스트: 활성 {sum(1 for v in track.values() if v['status'] == 'active')}개")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    large = get_large_caps()
    sp, ndx = get_sp500(), get_ndx()
    names = {**large, **ndx, **sp}
    wl = get_watchlist()
    universe = set(large) | set(sp) | set(ndx) | wl
    print(f"전체 검사 대상: {len(universe)}개")

    daily = download_daily(universe | set(INDEXES))
    last_day = daily["Close"]["QQQ"].dropna().index[-1]
    week_end = daily["Close"].resample("W-FRI").last().dropna(how="all").index[-1]
    print(f"마지막 거래일: {last_day.date()} / 주봉 기준일: {week_end.date()}")
    if (week_end - last_day).days > 3:
        print("이번 주 데이터가 아직 불완전 → 건너뜀")
        return
    now_ny = pd.Timestamp.now(tz="America/New_York")
    if now_ny.weekday() == 4 and last_day.date() != now_ny.date() and os.environ.get("JB_FORCE") != "1":
        print(f"오늘({now_ny.date()}) 종가가 아직 없음 → 다음 실행에서 다시 시도")
        return

    fname = f"{OUT_DIR}/{week_end.strftime('%Y-%m-%d')}.md"
    if os.path.exists(fname) and os.environ.get("JB_OVERWRITE") != "1":
        print(f"{fname} 이미 있음 → 기록 보존을 위해 다시 쓰지 않음")
        return

    weekly, stars, idx13, idx1, _ = scan(daily, names, large)
    fill_names(weekly + stars)
    for r in weekly + stars:
        r["in_watchlist"] = r["ticker"] in wl
    md = to_md(weekly, stars, idx13, idx1, week_end, len(universe))
    open(fname, "w", encoding="utf-8").write(md)
    payload = {"week_end": week_end.strftime("%Y-%m-%d"), "file": fname,
               "counts": {"launch": sum(r["tier"] == "launch" for r in weekly),
                          "learn": sum(r["tier"] == "learn" for r in weekly), "star": len(stars)},
               "index_ret13": idx13, "index_ret1": idx1, "weekly": weekly, "star": stars,
               "generated_utc": datetime.now(timezone.utc).isoformat()}
    json.dump(payload, open(f"{OUT_DIR}/latest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    idx_path = f"{OUT_DIR}/index.json"
    hist = json.load(open(idx_path)) if os.path.exists(idx_path) else []
    if payload["week_end"] not in hist:
        hist.append(payload["week_end"])
    json.dump(sorted(hist), open(idx_path, "w"), indent=2)
    update_tracking(weekly, stars, week_end)
    print(md)


if __name__ == "__main__":
    main()
