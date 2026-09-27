"""
김종봉(JB) 스타일 주간 스캐너
- 매주 금요일 뉴욕 장 마감 후 GitHub Actions에서 자동 실행
- 대상: S&P 500 + 나스닥 100 + 워치리스트(최근 Top 3 등장 종목 + watchlist.txt)
- 조건 (주봉 기준, 모두 충족해야 통과):
  1) 지수보다 강함 : 최근 13주 수익률 > QQQ, SPY 둘 다
  2) 풀백        : 직전 1~6주 사이에 주가가 12주 이동평균선 근처(+2% 이내) 또는 아래로 내려온 적 있음
  3) 고개 듦      : 이번 주 종가가 12주선 위 + 이번 주 상승 + 이번 주 수익률이 지수보다 높음
  4) 유동성      : 최근 4주 평균 거래대금 하루 2천만 달러 이상
- 결과: scanner/jb/YYYY-MM-DD.md (날짜별 기록), scanner/jb/latest.json, scanner/jb/index.json
- 이미 같은 날짜 파일이 있으면 다시 쓰지 않음 (기록 보존)
"""
import io
import json
import os
import re
import subprocess
from datetime import datetime, timezone

import pandas as pd
import requests
import yfinance as yf

OUT_DIR = "scanner/jb"
MA_WEEKS = 12
RS_WEEKS = 13
PULLBACK_LOOKBACK = 6
PULLBACK_BAND = 1.02
MIN_DOLLAR_VOL_DAY = 20_000_000
MAX_RESULTS = 10
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
        print(f"S&P 500 위키 실패: {e} → 백업 CSV 사용")
        try:
            r = requests.get("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv", timeout=30)
            df = pd.read_csv(io.StringIO(r.text))
            for _, row in df.iterrows():
                info[yf_symbol(str(row["Symbol"]))] = (str(row.get("Security", row.get("Name", ""))), str(row.get("GICS Sector", row.get("Sector", ""))))
        except Exception as e2:
            print(f"S&P 500 백업도 실패: {e2}")
    print(f"S&P 500: {len(info)}개")
    return info


def get_ndx():
    info = {}
    try:
        for t in read_wiki_tables("https://en.wikipedia.org/wiki/Nasdaq-100"):
            cols = [str(c) for c in t.columns]
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


def get_watchlist():
    """최근 60일 Market_Data.md 기록 + archive 파일 + watchlist.txt 에 나온 티커"""
    tickers = set()
    pat = re.compile(r"quote\.ashx\?t=([A-Z0-9.\-]+)")
    try:
        log = subprocess.run(["git", "log", "--since=60.days", "-p", "--", "Market_Data.md"],
                             capture_output=True, text=True, timeout=60).stdout
        tickers |= set(pat.findall(log))
    except Exception as e:
        print(f"git 기록 읽기 실패: {e}")
    for root in ("archive", "."):
        if not os.path.isdir(root):
            continue
        for dp, _, files in os.walk(root):
            if ".git" in dp or dp.startswith("./scanner"):
                continue
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


def download_daily(tickers):
    frames = []
    tickers = list(tickers)
    for i in range(0, len(tickers), 150):
        chunk = tickers[i:i + 150]
        d = yf.download(chunk, period="1y", interval="1d", auto_adjust=True,
                        progress=False, group_by="column", threads=True)
        frames.append(d)
    return pd.concat(frames, axis=1)


def weekly(df_daily):
    close = df_daily["Close"].resample("W-FRI").last()
    low = df_daily["Low"].resample("W-FRI").min()
    dollar = (df_daily["Close"] * df_daily["Volume"]).resample("W-FRI").sum()
    days = df_daily["Close"].resample("W-FRI").count()
    return close, low, dollar, days


def pct(a, b):
    return (a / b - 1) * 100 if b and b == b and b != 0 else float("nan")


def scan(close, low, dollar, days, idx_close, names):
    results = []
    last = close.index[-1]
    idx_ret13 = {k: pct(idx_close[k].iloc[-1], idx_close[k].iloc[-1 - RS_WEEKS]) for k in INDEXES}
    idx_ret1 = {k: pct(idx_close[k].iloc[-1], idx_close[k].iloc[-2]) for k in INDEXES}
    idx_week_chg = idx_close[INDEXES].pct_change()

    for t in close.columns:
        if t in INDEXES:
            continue
        c = close[t].dropna()
        if len(c) < MA_WEEKS + RS_WEEKS + 2 or c.index[-1] != last:
            continue
        ma = c.rolling(MA_WEEKS).mean()
        lo = low[t].reindex(c.index)
        now, prev = c.iloc[-1], c.iloc[-2]
        ret1 = pct(now, prev)
        ret4 = pct(now, c.iloc[-5])
        ret13 = pct(now, c.iloc[-1 - RS_WEEKS])

        # 1) 지수보다 강함
        if not all(ret13 > idx_ret13[k] for k in INDEXES):
            continue
        # 3) 고개 듦
        if not (now > ma.iloc[-1] and ret1 > 0 and all(ret1 > idx_ret1[k] for k in INDEXES)):
            continue
        # 2) 풀백: 직전 1~6주 중 저가가 12주선 +2% 이내로 내려온 주가 있음
        win = range(2, PULLBACK_LOOKBACK + 2)
        touched = [w for w in win if lo.iloc[-w] <= ma.iloc[-w] * PULLBACK_BAND]
        if not touched:
            continue
        below_close = any(c.iloc[-w] < ma.iloc[-w] for w in win)
        # 4) 유동성
        dv = dollar[t].reindex(c.index).iloc[-4:].sum() / max(days[t].reindex(c.index).iloc[-4:].sum(), 1)
        if dv < MIN_DOLLAR_VOL_DAY:
            continue
        # 참고: 최근 8주 중 '지수(QQQ) 하락 주에 이 종목은 상승'한 횟수 = 김종봉식 역행 강세
        s_chg = c.pct_change().iloc[-8:]
        q_chg = idx_week_chg["QQQ"].reindex(s_chg.index)
        against = int(((q_chg < 0) & (s_chg > 0)).sum())

        name, sector = names.get(t, ("", ""))
        results.append({
            "ticker": t, "name": name, "sector": sector,
            "week_pct": round(ret1, 2), "month_pct": round(ret4, 2),
            "ret13_pct": round(ret13, 2),
            "rs_vs_qqq": round(ret13 - idx_ret13["QQQ"], 2),
            "rs_vs_spy": round(ret13 - idx_ret13["SPY"], 2),
            "above_ma12_pct": round(pct(now, ma.iloc[-1]), 2),
            "pullback": "12주선 아래 종가" if below_close else "12주선 터치",
            "pullback_weeks_ago": min(touched) - 1,
            "against_index_weeks": against,
            "close": round(float(now), 2),
            "avg_dollar_vol_m": round(dv / 1e6, 1),
        })
    results.sort(key=lambda r: r["rs_vs_qqq"], reverse=True)
    return results, idx_ret13, idx_ret1, last


def fill_names(results, names):
    for r in results:
        if r["name"]:
            continue
        try:
            inf = yf.Ticker(r["ticker"]).info
            r["name"] = inf.get("shortName") or inf.get("longName") or ""
            r["sector"] = inf.get("sector") or ""
        except Exception:
            pass


def to_md(results, total_hits, idx_ret13, idx_ret1, week_end, universe_n):
    d = week_end.strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = f"# 김종봉 스캐너 — {d} 주간\n\n"
    md += f"> 기준: {d}(금) 뉴욕 종가 · 주봉 · 확정 시각 {now} · 검사 종목 {universe_n}개 · 통과 {total_hits}개\n"
    md += f"> 지수 13주 수익률: QQQ {idx_ret13['QQQ']:+.2f}% / SPY {idx_ret13['SPY']:+.2f}% · 이번 주: QQQ {idx_ret1['QQQ']:+.2f}% / SPY {idx_ret1['SPY']:+.2f}%\n\n"
    md += "조건: ① 13주 수익률이 QQQ·SPY보다 높음 ② 최근 1~6주 사이 12주선까지 눌림 ③ 이번 주 12주선 위 + 상승 + 지수보다 강함 ④ 하루 거래대금 2천만$+\n\n"
    if not results:
        md += "**이번 주 조건을 모두 통과한 종목이 없습니다.**\n"
        return md
    md += "| 티커 | 회사 | 섹터 | 이번 주 | 1개월 | 13주 vs QQQ | 12주선 대비 | 눌림 | 역행강세(8주) |\n"
    md += "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | :--- | ---: |\n"
    for r in results:
        md += (f"| {r['ticker']} | {r['name']} | {r['sector']} | {r['week_pct']:+.2f}% | {r['month_pct']:+.2f}% | "
               f"{r['rs_vs_qqq']:+.2f}%p | {r['above_ma12_pct']:+.2f}% | {r['pullback']} ({r['pullback_weeks_ago']}주 전) | {r['against_index_weeks']}회 |\n")
    if total_hits > len(results):
        md += f"\n(통과 {total_hits}개 중 13주 상대강도 상위 {len(results)}개만 표시)\n"
    return md


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    sp, ndx = get_sp500(), get_ndx()
    names = {**ndx, **sp}
    wl = get_watchlist()
    universe = set(sp) | set(ndx) | wl
    print(f"전체 검사 대상: {len(universe)}개")

    daily = download_daily(universe | set(INDEXES))
    close, low, dollar, days = weekly(daily)
    close = close.dropna(how="all")
    week_end = close.index[-1]
    # 금요일 장 마감 전이거나 데이터가 덜 들어왔으면 중단 (다음 실행에서 다시 시도)
    last_day = daily["Close"]["QQQ"].dropna().index[-1]
    print(f"마지막 거래일: {last_day.date()} / 주봉 기준일: {week_end.date()}")
    if (week_end - last_day).days > 3:
        print("이번 주 데이터가 아직 불완전 → 건너뜀")
        return
    # 금요일(뉴욕)에 실행됐는데 오늘 종가가 아직 안 들어왔으면 건너뜀 (목요일 종가로 주봉을 만드는 실수 방지)
    now_ny = pd.Timestamp.now(tz="America/New_York")
    if now_ny.weekday() == 4 and last_day.date() != now_ny.date() and os.environ.get("JB_FORCE") != "1":
        print(f"오늘({now_ny.date()}) 종가가 아직 없음 → 다음 실행에서 다시 시도")
        return

    fname = f"{OUT_DIR}/{week_end.strftime('%Y-%m-%d')}.md"
    if os.path.exists(fname):
        print(f"{fname} 이미 있음 → 기록 보존을 위해 다시 쓰지 않음")
        return

    results, idx13, idx1, _ = scan(close, low, dollar, days, close, names)
    total = len(results)
    results = results[:MAX_RESULTS]
    fill_names(results, names)
    for r in results:
        r["in_watchlist"] = r["ticker"] in wl
    md = to_md(results, total, idx13, idx1, week_end, len(universe))
    open(fname, "w", encoding="utf-8").write(md)
    payload = {"week_end": week_end.strftime("%Y-%m-%d"), "file": fname, "total_hits": total,
               "index_ret13": idx13, "index_ret1": idx1, "results": results,
               "generated_utc": datetime.now(timezone.utc).isoformat()}
    json.dump(payload, open(f"{OUT_DIR}/latest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    idx_path = f"{OUT_DIR}/index.json"
    hist = json.load(open(idx_path)) if os.path.exists(idx_path) else []
    if payload["week_end"] not in hist:
        hist.append(payload["week_end"])
    json.dump(sorted(hist), open(idx_path, "w"), indent=2)
    print(md)


if __name__ == "__main__":
    main()
