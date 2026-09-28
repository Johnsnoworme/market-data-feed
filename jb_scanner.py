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
from jb_original import legs, kim

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


SECTOR_MAP = {"Information Technology": "Technology", "Healthcare": "Health Care", "Basic Materials": "Materials",
              "Finance": "Financials", "Financial Services": "Financials", "Consumer Cyclical": "Consumer Discretionary",
              "Consumer Defensive": "Consumer Staples", "Telecommunications": "Communication Services",
              "Communication": "Communication Services"}


def norm_sector(x):
    x = (x or "").strip()
    return SECTOR_MAP.get(x, x)


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
            "mtd_pct": round(pct(mclose[t].dropna().iloc[-1], mclose[t].dropna().iloc[-2]), 2) if len(mclose[t].dropna()) > 2 else float("nan"),
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


def fv(t):
    """Finviz 링크 (새 탭). p=d&t= 순서라서 Top 3 티커 태그 자동 추가에는 안 걸림"""
    return f'<a href="https://finviz.com/quote.ashx?p=d&t={t}" target="_blank">{t}</a>'


def row_md(r, extra=None):
    star = (" ⭐" + r["star"]) if r.get("star") else ""
    return (f"| {fv(r['ticker'])}{star} | {r['name']} | {r['sector']} | {r['week_pct']:+.2f}% | "
            f"{r['month_pct']:+.2f}% | {r['rs_vs_qqq']:+.1f}%p |\n")


HEAD = "| 티커 | 회사 | 섹터 | 이번 주 | 1개월 | 지수보다 (13주) |\n| :--- | :--- | :--- | ---: | ---: | ---: |\n"


def table(rows, x, extra_fn):
    if not rows:
        return "이번 주 없음\n"
    md = HEAD + "".join(row_md(r, extra_fn(r)) for r in rows[:SHOW_TOP])
    rest = rows[SHOW_TOP:]
    if rest:
        md += f"\n> [!note]- 나머지 {len(rest)}개 (13주 상대강도 순, 전부 추적 중)\n"
        md += "".join("> " + line + "\n" for line in (HEAD + "".join(row_md(r, extra_fn(r)) for r in rest)).strip().split("\n"))
    return md


def combine(weekly, stars, prev_track):
    """티커 하나당 한 줄로 합치고 점수 매기기 (신호 겹침 + 지수보다 강한 정도 + 주도 섹터 + 연속 등장)"""
    by = {}
    for r in weekly + stars:
        r["sector"] = norm_sector(r.get("sector"))
    for r in weekly:
        e = by.setdefault(r["ticker"], dict(r, sig=[]))
        e["sig"].append("🚗" if r["tier"] == "launch" else "🏁")
    for r in stars:
        e = by.setdefault(r["ticker"], dict(r, sig=[]))
        tag = "⭐" + r["tf"]
        if tag not in e["sig"]:
            e["sig"].append(tag)
    from collections import Counter
    sec = Counter(e["sector"] for e in by.values() if e.get("sector"))
    hot = {k for k, v in sec.most_common(2) if v >= 4}   # 가장 많이 걸린 두 섹터
    for t, e in by.items():
        sc = 0.0
        sc += 3 if "🚗" in e["sig"] else 0
        sc += 2 * sum(1 for x in e["sig"] if x.startswith("⭐"))
        sc += min(max(e["rs_vs_qqq"], 0) / 10, 3)
        sc += 1 if e.get("against_index_weeks", 0) >= 1 else 0
        sc += 1 if e.get("sector") in hot else 0
        pt = prev_track.get(t)
        e["repeat"] = bool(pt and pt.get("status") == "active" and pt.get("last_seen", "") < e.get("_week", "9"))
        sc += 1 if e["repeat"] else 0
        only_learn = e["sig"] == ["🏁"]
        e["score"] = round(sc - (3 if only_learn else 0), 1)
        e["only_learn"] = only_learn
    for r in weekly + stars:
        r["score"] = by[r["ticker"]]["score"]
    return sorted(by.values(), key=lambda e: -e["score"]), sec, hot


def row2(e):
    rep = " 🔁" if e.get("repeat") else ""
    return (f"| {fv(e['ticker'])}{rep} | {e['name']} | {e['sector']} | {e['week_pct']:+.2f}% | {e['month_pct']:+.2f}% | "
            f"{e['rs_vs_qqq']:+.1f}%p | {' '.join(e['sig'])} |\n")


HEAD2 = "| 티커 | 회사 | 섹터 | 이번 주 | 1개월 | 지수보다 (13주) | 신호 |\n| :--- | :--- | :--- | ---: | ---: | ---: | :--- |\n"


def to_md(weekly, stars, idx13, idx1, week_end, universe_n, prev_track=None):
    d = week_end.strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for r in weekly + stars:
        r["_week"] = d
    rows, sec, hot = combine(weekly, stars, prev_track or {})
    top = [e for e in rows if not e["only_learn"]][:SHOW_TOP]
    rest = [e for e in rows if e not in top]
    md = f"# 김종봉 스캐너 — {d} 주간\n\n"
    md += "> 🧭 순서: ① 지수보다 강한 종목 찾기 (이 노트) → ② 8주 모니터링 → ③ 1파 뒤 2파 풀백(주봉·월봉 30~70%)에서 7개 룰 직접 확인 후 진입 (Daily 노트 🔔)\n"
    md += f"> 기준: {d}(금) 뉴욕 종가 · 시총 $10B+ · 검사 {universe_n}개 → 지수보다 강한 종목 {len(rows)}개 (전부 레이더에 기록·추적) · 확정 {now}\n"
    md += f"> 지수 13주: QQQ {idx13['QQQ']:+.2f}% / SPY {idx13['SPY']:+.2f}% · 이번 주: QQQ {idx1['QQQ']:+.2f}% / SPY {idx1['SPY']:+.2f}%\n\n"
    md += "### 🏆 이번 주 핵심 5\n"
    md += "> 점수 = 신호 겹침(🚗 막 출발 +3, ⭐월·⭐주 인텔형 각 +2) + 지수보다 강한 정도(최대 +3) + 지수 하락 주에 상승(+1) + 주도 섹터(+1) + 연속 등장 🔁(+1)\n\n"
    md += (HEAD2 + "".join(row2(e) for e in top)) if top else "이번 주 없음\n"
    if hot:
        md += "\n🔥 **돈이 가장 몰린 섹터**: " + " · ".join(f"{k} {sec[k]}개" for k in sorted(hot, key=lambda k: -sec[k])) + "\n"
    if rest:
        md += f"\n> [!note]- 📡 레이더 전체 {len(rest)}개 (점수 순 · 전부 8주 추적 · 풀백 오면 Daily 알림)\n"
        md += "".join("> " + l + "\n" for l in (HEAD2 + "".join(row2(e) for e in rest)).strip().split("\n"))
    md += "\n> 신호: 🚗 막 출발(1~3주 전 12주선 눌림 후 반등, 12주선 +15% 이내) · ⭐월/⭐주 인텔형(긴 바닥 후 12개월선/12주선 돌파) · 🏁 이미 달린 차(학습용) · 티커를 누르면 Finviz\n"
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


def update_monthly(weekly, stars, week_end):
    """이달(금요일 날짜 기준 월) 김종봉 스캐너에 나온 종목을 모아 scanner/jb/monthly/YYYY-MM.md 로"""
    ym = week_end.strftime("%Y-%m")
    os.makedirs(f"{OUT_DIR}/monthly", exist_ok=True)
    jp = f"{OUT_DIR}/monthly/{ym}.json"
    data = json.load(open(jp, encoding="utf-8")) if os.path.exists(jp) else {"month": ym, "tickers": {}}
    wk = week_end.strftime("%m/%d")
    for r in list(weekly) + list(stars):
        kind = ("🚗" if r.get("tier") == "launch" else "🏁") if "tier" in r else ("⭐" + r.get("tf", ""))
        e = data["tickers"].setdefault(r["ticker"], {"name": r["name"], "sector": r["sector"], "first": wk, "kinds": [], "weeks": []})
        if kind not in e["kinds"]:
            e["kinds"].append(kind)
        if wk not in e["weeks"]:
            e["weeks"].append(wk)
        e.update(name=r["name"] or e["name"], sector=norm_sector(r["sector"] or e["sector"]), mtd_pct=r.get("mtd_pct"),
                 score=max(e.get("score", 0), r.get("score", 0)),
                 rs_vs_qqq=r["rs_vs_qqq"], last=wk, star_m=e.get("star_m") or ("월" in (r.get("star") or "")))
    data["last_week"] = week_end.strftime("%Y-%m-%d")
    json.dump(data, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    rows = sorted(data["tickers"].items(), key=lambda kv: (-(len(kv[1]["weeks"])), -(kv[1].get("score") or 0), -(kv[1].get("rs_vs_qqq") or 0)))
    focus = [kv for kv in rows if any(k in ("🚗", "⭐월", "⭐주") for k in kv[1]["kinds"])]
    learn = [kv for kv in rows if kv not in focus]
    def line(t, e):
        m = e.get("mtd_pct")
        m = f"{m:+.1f}%" if isinstance(m, (int, float)) and m == m else "—"
        return (f"| {fv(t)}{' ⭐월' if e.get('star_m') else ''} | {e['name']} | {e['sector']} | {' '.join(e['kinds'])} | "
                f"{e['first']} | {len(e['weeks'])}주 | {m} |\n")
    head = "| 티커 | 회사 | 섹터 | 구분 | 처음 뜬 주 | 등장 | 이번 달 |\n| :--- | :--- | :--- | :--- | :--- | ---: | ---: |\n"
    md = f"# 김종봉 스캐너 — {ym} 월간 모음\n\n"
    md += f"> 이달 매주 스캐너(시총 $10B+, 지수보다 강한 종목)에 나온 종목 모음 · 마지막 반영 {data['last_week']}(금) · 이번 달 % = 지난달 말 → 마지막 반영 금요일\n"
    md += "> 여러 주 연속 등장할수록 위 · 티커를 누르면 Finviz\n\n"
    md += "### 🏆 이달 핵심 5 (여러 주 연속 등장 → 주간 점수 순)\n"
    if focus:
        md += head + "".join(line(t, e) for t, e in focus[:5])
        if len(focus) > 5:
            md += f"\n> [!note]- 나머지 {len(focus) - 5}개\n" + "".join("> " + l + "\n" for l in (head + "".join(line(t, e) for t, e in focus[5:])).strip().split("\n"))
    else:
        md += "이번 달 없음\n"
    if learn:
        md += f"\n> [!note]- 🏁 이미 달린 차 (학습용) {len(learn)}개\n" + "".join("> " + l + "\n" for l in (head + "".join(line(t, e) for t, e in learn)).strip().split("\n"))
    open(f"{OUT_DIR}/monthly/{ym}.md", "w", encoding="utf-8").write(md)
    print(f"월간 모음 {ym}: {len(rows)}개")


CREDIBLE_DOLLAR_VOL = 50_000_000   # 믿을 만한 종목: 하루 거래대금 5천만$↑ + 상장 1년↑ (52주)
NEAR_MA = 15.0     # 12주선 대비 +15% 이내 = 아직 멀리 안 감 (오르려는 자리)
MAIN_TOP = 10     # 표에 보여줄 후보 수
LEADERS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "TSLA"]


def kim_scan(daily, names, large):
    """김종봉 원본: 나스닥 최근 조정의 하락 구간에 덜 빠지고 + 반등 구간에 더 오른 종목"""
    wc = daily["Close"].resample("W-FRI").last().dropna(how="all")
    dollar = (daily["Close"] * daily["Volume"]).resample("W-FRI").sum()
    days = daily["Close"].resample("W-FRI").count()
    q = wc["QQQ"].dropna()
    L = legs(q)
    last = q.index[-1]
    rows, lead = [], []
    for t in wc.columns:
        if t in INDEXES:
            continue
        c = wc[t].dropna()
        if len(c) < 30 or c.index[-1] != last:
            continue
        name, sector = names.get(t, ("", ""))
        if any(w in name for w in EXCLUDE_WORDS):
            continue
        k = kim(c, q, L)
        if not k:
            continue
        ma = c.rolling(MA_WEEKS).mean().iloc[-1]
        r = dict(k, ticker=t, name=name, sector=norm_sector(sector),
                 week_pct=round(float(pct(c.iloc[-1], c.iloc[-2])), 2), above_ma12=round(float(pct(c.iloc[-1], ma)), 1),
                 close=round(float(c.iloc[-1]), 2))
        if t in LEADERS:
            lead.append(r)
        dv = dollar[t].reindex(c.index).iloc[-4:].sum() / max(days[t].reindex(c.index).iloc[-4:].sum(), 1)
        if k["pass"] and dv >= CREDIBLE_DOLLAR_VOL and len(c) >= 52:
            rows.append(r)
    def cap_ok(r):
        if r["ticker"] in large:
            return True
        return market_cap(r["ticker"]) >= MIN_MARKET_CAP
    rows = [r for r in rows if cap_ok(r)]
    rows.sort(key=lambda r: -r["score"])
    lead.sort(key=lambda r: LEADERS.index(r["ticker"]))
    return rows, lead, L, q


def kim_md(rows, lead, L, q, week_end, universe_n):
    d = week_end.strftime("%Y-%m-%d")
    near = [r for r in rows if r["above_ma12"] <= NEAR_MA]
    qd, qu = (L["trough"] / L["peak"] - 1) * 100, (q.iloc[-1] / L["trough"] - 1) * 100
    head = "| 티커 | 회사 | 섹터 | 이번 주 | 나스닥 저점 이후 |\n| :--- | :--- | :--- | ---: | ---: |\n"
    def line(r):
        return (f"| {fv(r['ticker'])}{' 🔥' if r['fire'] else ''} | {r['name']} | {r['sector']} | "
                f"{r['week_pct']:+.1f}% | {r['up']:+.1f}% |\n")
    md = f"# 김종봉 스캐너 — {d} 주간\n\n"
    md += (f"> 나스닥 기준: {L['peak_d'].strftime('%m/%d')} 고점 → {L['trough_d'].strftime('%m/%d')} 저점 **{qd:+.1f}%** → 지금 **저점 대비 {qu:+.1f}%**\n")
    md += (f"> 하락 구간에 나스닥보다 **덜 빠지고** + 반등 구간에 **더 오른** 종목 중, 아직 멀리 안 간(12주선 +15% 이내) 강한 순 **최대 {SHOW_TOP}개** "
           f"· 시총 $10B+ · 상장 1년↑ · 하루 거래대금 5천만$↑ · 🔥 = 하락 구간에 오히려 오름\n\n")
    if lead:
        win = [r["ticker"] for r in lead if r["pass"]]
        md += "👑 **대장주**: " + " · ".join(f"{r['ticker']} {'✅' if r['pass'] else '❌'}" for r in lead)
        md += f" → {'지수보다 강한 대장이 있어 시장은 상승 쪽' if win else '대장이 지수를 못 이김 → 비중 절반'}\n\n"
    md += head + "".join(line(r) for r in near[:SHOW_TOP]) if near else "이번 주 없음 (기준을 넘는 종목이 없어요)\n"
    md += "\n> 여기 나온 종목만 8주 추적 → 풀백(30~70%)이 오면 Daily 노트 🔔 '김종봉 후보' 칸 · 진입은 7개 룰 직접 확인 · 티커를 누르면 Finviz\n"
    return md


def save_picks(rows, week_end):
    """Weekly에 보여준 종목 = 8주 풀백 추적 대상"""
    p = f"{OUT_DIR}/picks.json"
    picks = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    d = week_end.strftime("%Y-%m-%d")
    for r in rows:
        picks[r["ticker"]] = {"date": d, "name": r["name"], "sector": r["sector"]}
    json.dump(picks, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def update_tracking_kim(rows, week_end):
    track = json.load(open(TRACK_PATH, encoding="utf-8")) if os.path.exists(TRACK_PATH) else {}
    d = week_end.strftime("%Y-%m-%d")
    expires = (week_end + timedelta(days=TRACK_DAYS)).strftime("%Y-%m-%d")
    for r in rows:
        kind = "🎯" if r["above_ma12"] <= NEAR_MA else "🎯↑"
        e = track.get(r["ticker"])
        if e and e.get("status") == "active":
            e["last_seen"], e["expires"] = d, max(e["expires"], expires)
            if "👀" in e.get("kind", "") and "👀" not in kind:
                kind += "👀"
            e["kind"] = kind
        else:
            track[r["ticker"]] = {"name": r["name"], "first_seen": d, "last_seen": d, "expires": expires,
                                  "kind": kind, "status": "active", "last_zone": ""}
    json.dump(track, open(TRACK_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"추적 리스트: 활성 {sum(1 for v in track.values() if v['status'] == 'active')}개")


def update_monthly_kim(rows, week_end):
    ym = week_end.strftime("%Y-%m")
    os.makedirs(f"{OUT_DIR}/monthly", exist_ok=True)
    jp = f"{OUT_DIR}/monthly/{ym}.json"
    data = json.load(open(jp, encoding="utf-8")) if os.path.exists(jp) else {"month": ym, "tickers": {}}
    data.setdefault("version", 3)
    if data.get("version") != 3:
        data = {"month": ym, "tickers": {}, "version": 3}
    wk = week_end.strftime("%m/%d")
    for r in rows:
        e = data["tickers"].setdefault(r["ticker"], {"name": r["name"], "sector": r["sector"], "first": wk, "weeks": []})
        if wk not in e["weeks"]:
            e["weeks"].append(wk)
        e.update(last=wk, score=float(r["score"]), up=float(r["up"]), near=bool(r["above_ma12"] <= NEAR_MA))
    data["last_week"] = week_end.strftime("%Y-%m-%d")
    json.dump(data, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    items = sorted(data["tickers"].items(), key=lambda kv: (-len(kv[1]["weeks"]), -kv[1].get("score", 0)))
    head = "| 티커 | 회사 | 섹터 | 처음 뜬 주 | 등장 |\n| :--- | :--- | :--- | :--- | ---: |\n"
    line = lambda t, e: f"| {fv(t)} | {e['name']} | {e['sector']} | {e['first']} | {len(e['weeks'])}주 |\n"
    md = f"# 김종봉 스캐너 — {ym} 월간 모음\n\n"
    md += f"> 이달 매주 Weekly 노트 김종봉 후보(주 최대 5개)에 나온 종목 · 마지막 반영 {data['last_week']}(금) · 여러 주 연속 등장할수록 위\n\n"
    md += f"### 🏆 이달 핵심 5\n" + (head + "".join(line(t, e) for t, e in items[:5]) if items else "이번 달 없음\n")
    open(f"{OUT_DIR}/monthly/{ym}.md", "w", encoding="utf-8").write(md)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    large = get_large_caps()
    sp, ndx = get_sp500(), get_ndx()
    names = {**large, **ndx, **sp}
    wl = get_watchlist()
    universe = set(large) | set(sp) | set(ndx) | wl | set(LEADERS)
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

    rows, lead, L, q = kim_scan(daily, names, large)
    fill_names(rows)
    md = kim_md(rows, lead, L, q, week_end, len(universe))
    open(fname, "w", encoding="utf-8").write(md)
    payload = {"week_end": week_end.strftime("%Y-%m-%d"), "file": fname, "method": "김종봉 원본",
               "nasdaq_leg": {"peak": L["peak_d"].strftime("%Y-%m-%d"), "trough": L["trough_d"].strftime("%Y-%m-%d")},
               "counts": {"candidates": len(rows), "near": sum(r["above_ma12"] <= NEAR_MA for r in rows)},
               "leaders": lead, "candidates": rows, "generated_utc": datetime.now(timezone.utc).isoformat()}
    json.dump(payload, open(f"{OUT_DIR}/latest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
    idx_path = f"{OUT_DIR}/index.json"
    hist = json.load(open(idx_path)) if os.path.exists(idx_path) else []
    if payload["week_end"] not in hist:
        hist.append(payload["week_end"])
    json.dump(sorted(hist), open(idx_path, "w"), indent=2)
    shown = [r for r in rows if r["above_ma12"] <= NEAR_MA][:SHOW_TOP]
    save_picks(shown, week_end)
    update_tracking_kim(shown, week_end)
    update_monthly_kim(shown, week_end)
    print(md)


if __name__ == "__main__":
    main()
