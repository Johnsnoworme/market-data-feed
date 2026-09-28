"""
📡 소셜 아비트리지 + 🔧 병목 레이더 (크리스 카밀로 방식) — 매일 뉴욕 장 마감 후
하루 최대 2개. 기준을 못 넘으면 "오늘 없음" (억지로 만들지 않음).

1) 관심 급증 — 아래 출처 중 2개 이상
   - 레딧 언급 급증 (ApeWisdom: 언급 10회↑ + 24시간 전보다 2배↑, 또는 순위 20계단↑ 상승해 100위 안)
   - StockTwits 인기 종목 목록에 오름
   - 위키피디아 회사 페이지 조회수 급증 (최근 3일 평균 ≥ 이전 30일 평균 × 2, 하루 300회↑)
   - 🔧 공시 병목 표현 증가 (SEC 8-K·10-Q·10-K: "공급 부족·생산능력 제약·매진·리드타임·수주잔고" 최근 90일 > 이전 90일)
2) 가격이 막 움직이기 시작 — 5일 수익률 > 0 이고 나스닥보다 높음, 최근 3일 거래량 ≥ 20일 평균 × 1.5, 종가 > 20일선,
   1개월 +50% 이상은 제외(늦음), 최근 5일 중 하루 +40% 이상 급등은 제외(펌프 방지)
3) 안전 — 시총 $2B↑, 주가 $5↑, 하루 거래대금 2천만$↑
4) 실적이 좋아지는 방향 — 최근 분기 EPS가 1년 전 분기보다 높음(적자 축소 포함), 매출 1년 전보다 증가, 주식 수 1년 +10% 이내
   🔧 진짜 병목 = 공시 병목 표현 증가 + 매출총이익률 1년 전보다 상승
5) 점수 순 최대 2개. 최근 8주 안에 이미 보여준 종목은 다시 안 보여줌 (기준을 계속 넘는 나머지는 다음 날 나옴)
결과: social/daily/YYYY-MM-DD.md, social/latest.md, social/shown.json
"""
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests
import yfinance as yf

OUT = "social"
MIN_CAP = 2_000_000_000
MAX_PICKS = 2
UA = {"User-Agent": "market-data-feed research (github.com/Johnsnoworme/market-data-feed)"}
PHRASES = ["supply constrained", "capacity constrained", "demand exceeds supply", "sold out",
           "extended lead times", "record backlog", "supply shortage", "on allocation"]


def fv(t):
    return f'<a href="https://finviz.com/quote.ashx?p=d&t={t}" target="_blank">{t}</a>'


def get(url, **kw):
    hd = kw.pop("headers", UA)
    for i in range(3):
        try:
            r = requests.get(url, headers=hd, timeout=30, **kw)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        time.sleep(2 + i * 3)
    return None


def universe():
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
         "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
    r = requests.get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true", headers=h, timeout=30)
    out = {}
    for x in r.json()["data"]["rows"]:
        try:
            cap = float(x.get("marketCap") or 0)
        except ValueError:
            continue
        s = (x.get("symbol") or "").strip()
        if s and "^" not in s and "/" not in s and cap >= MIN_CAP:
            out[s.replace(".", "-")] = {"cap": cap, "name": x.get("name") or s, "sector": x.get("sector") or ""}
    return out


def clean_name(n):
    n = re.sub(r"\b(Common Stock|Class [A-C]|Ordinary Shares?|American Depositary Shares?|ADS|Inc\.?|Corp\.?|Corporation|Holdings?|Ltd\.?|plc|N\.V\.|S\.A\.|Co\.?|Group|Company)\b", "", n, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"[,()]", " ", n)).strip()


# ---------- 관심 출처 ----------
def reddit_spikes():
    out = {}
    for p in range(1, 6):
        r = get(f"https://apewisdom.io/api/v1.0/filter/all-stocks/page/{p}")
        if not r:
            break
        for x in r.json().get("results", []):
            m, m0 = int(x.get("mentions") or 0), int(x.get("mentions_24h_ago") or 0)
            rk, rk0 = int(x.get("rank") or 999), int(x.get("rank_24h_ago") or 999)
            if (m >= 10 and m >= 2 * max(m0, 1)) or (rk <= 100 and rk0 - rk >= 20):
                out[x["ticker"].replace(".", "-")] = f"레딧 언급 {m}회 (하루 전 {m0}회)"
    return out


def stocktwits_trending():
    r = get("https://api.stocktwits.com/api/2/trending/symbols.json")
    return {s["symbol"].replace(".", "-"): "StockTwits 인기 종목" for s in (r.json().get("symbols", []) if r else [])}


def edgar_bottleneck(cik2t):
    """최근 90일 vs 이전 90일, 병목 표현이 나온 공시 수"""
    today = datetime.now(timezone.utc).date()
    windows = {"now": (today - timedelta(days=90), today), "prev": (today - timedelta(days=180), today - timedelta(days=91))}
    cnt = {"now": {}, "prev": {}}
    for ph in PHRASES:
        for w, (a, b) in windows.items():
            for frm in (0, 100, 200):
                r = get(f"https://efts.sec.gov/LATEST/search-index?q=%22{requests.utils.quote(ph)}%22&dateRange=custom"
                        f"&startdt={a}&enddt={b}&forms=8-K,10-Q,10-K&from={frm}")
                if not r:
                    break
                hits = r.json().get("hits", {}).get("hits", [])
                for h in hits:
                    for cik in h.get("_source", {}).get("ciks", []):
                        t = cik2t.get(str(int(cik)))
                        if t:
                            cnt[w].setdefault(t, set()).add(h.get("_id", "").split(":")[0])
                if len(hits) < 100:
                    break
                time.sleep(0.3)
    out = {}
    for t, docs in cnt["now"].items():
        n, p = len(docs), len(cnt["prev"].get(t, ()))
        if n >= 2 and n > p:
            out[t] = f"공시 속 공급 부족·생산능력 제약 표현 {p}→{n}건"
    return out


def cik_map():
    r = get("https://www.sec.gov/files/company_tickers.json")
    return {str(v["cik_str"]): v["ticker"].replace(".", "-") for v in (r.json().values() if r else [])}


def wiki_spike(t, name, cache):
    title = cache.get(t)
    if title is None:
        r = get("https://en.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "format": "json",
                                                               "srsearch": clean_name(name) + " company", "srlimit": 1})
        res = r.json().get("query", {}).get("search", []) if r else []
        title = res[0]["title"] if res else ""
        cache[t] = title
    if not title:
        return None
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=34)
    r = get(f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
            f"{requests.utils.quote(title.replace(' ', '_'), safe='')}/daily/{start:%Y%m%d}/{end:%Y%m%d}")
    if not r:
        return None
    v = [i["views"] for i in r.json().get("items", [])]
    if len(v) < 20:
        return None
    recent, base = sum(v[-3:]) / 3, sum(v[:-3]) / max(len(v) - 3, 1)
    if recent >= 300 and recent >= 2 * max(base, 1):
        return f"위키피디아 조회 {recent / max(base, 1):.1f}배"
    return None


# ---------- 실적 ----------
def fundamentals(t):
    try:
        q = yf.Ticker(t).quarterly_income_stmt
    except Exception:
        return None
    if q is None or q.empty or q.shape[1] < 5:
        return None
    q = q.loc[:, sorted(q.columns, reverse=True)]
    def row(*names):
        for n in names:
            if n in q.index:
                return q.loc[n]
        return None
    eps, rev = row("Diluted EPS", "Basic EPS"), row("Total Revenue", "Operating Revenue")
    gp, sh = row("Gross Profit"), row("Diluted Average Shares", "Basic Average Shares")
    if eps is None or rev is None or pd.isna(eps.iloc[0]) or pd.isna(eps.iloc[4]):
        return None
    e0, e4, r0, r4 = float(eps.iloc[0]), float(eps.iloc[4]), float(rev.iloc[0]), float(rev.iloc[4])
    s_ok = True
    if sh is not None and not pd.isna(sh.iloc[0]) and not pd.isna(sh.iloc[4]) and sh.iloc[4]:
        s_ok = float(sh.iloc[0]) / float(sh.iloc[4]) - 1 <= 0.10
    gm_up = None
    if gp is not None and not pd.isna(gp.iloc[0]) and not pd.isna(gp.iloc[4]) and r0 and r4:
        gm_up = float(gp.iloc[0]) / r0 > float(gp.iloc[4]) / r4
    improving = e0 > e4 and r0 > r4 and s_ok
    if e0 > 0 >= e4:
        tag = "EPS 흑자 전환"
    elif e0 < 0:
        tag = "적자 축소" if e0 > e4 else "적자 확대"
    else:
        tag = f"EPS {e4:.2f}→{e0:.2f}"
    return {"ok": improving, "tag": tag, "rev_g": (r0 / r4 - 1) * 100 if r4 else None, "gm_up": gm_up, "shares_ok": s_ok}


def main():
    os.makedirs(f"{OUT}/daily", exist_ok=True)
    uni = universe()
    print(f"시총 $2B+ 종목: {len(uni)}개")
    shown = json.load(open(f"{OUT}/shown.json", encoding="utf-8")) if os.path.exists(f"{OUT}/shown.json") else {}
    cache = json.load(open(f"{OUT}/wiki_map.json", encoding="utf-8")) if os.path.exists(f"{OUT}/wiki_map.json") else {}

    src = {}
    for name, fn in (("reddit", reddit_spikes), ("stocktwits", stocktwits_trending)):
        try:
            for t, why in fn().items():
                if t in uni:
                    src.setdefault(t, {})[name] = why
        except Exception as e:
            print(name, "실패", e)
    try:
        for t, why in edgar_bottleneck(cik_map()).items():
            if t in uni:
                src.setdefault(t, {})["edgar"] = why
    except Exception as e:
        print("edgar 실패", e)
    print(f"관심 출처 1개 이상: {len(src)}개")
    price_ok = []
    if not src:
        pool = []
    else:
        d = yf.download(sorted(src) + ["QQQ"], period="3mo", interval="1d", auto_adjust=True, progress=False, group_by="column")
        C, V = d["Close"], d["Volume"]
        q5 = C["QQQ"].dropna().iloc[-1] / C["QQQ"].dropna().iloc[-6] - 1
        pool, price_ok = [], []
        for t in src:
            if t not in C.columns:
                continue
            c, v = C[t].dropna(), V[t].dropna()
            if len(c) < 30:
                continue
            px = float(c.iloc[-1])
            dv = float((c.iloc[-20:] * v.iloc[-20:]).mean())
            r1, r5, r21 = px / c.iloc[-2] - 1, px / c.iloc[-6] - 1, px / c.iloc[-22] - 1
            vr = float(v.iloc[-3:].mean() / max(v.iloc[-23:-3].mean(), 1))
            jump = float(c.pct_change().iloc[-5:].max())
            ok = (px >= 5 and dv >= 20e6 and r5 > 0 and r5 > q5 and vr >= 1.5 and px > c.iloc[-20:].mean()
                  and r21 < 0.5 and jump < 0.4)
            if not ok:
                continue
            price_ok.append(t)
            w = wiki_spike(t, uni[t]["name"], cache)
            if w:
                src[t]["wiki"] = w
            if len(src[t]) < 2:
                continue
            pool.append({"ticker": t, "px": px, "r1": r1 * 100, "r5": r5 * 100, "vr": vr, "why": src[t]})
    picks, fail = [], []
    for p in sorted(pool, key=lambda p: (-len(p["why"]), -p["vr"])):
        if p["ticker"] in shown and (pd.Timestamp.now() - pd.Timestamp(shown[p["ticker"]])).days <= 56:
            continue
        f = fundamentals(p["ticker"])
        if not f or not f["ok"]:
            fail.append((p["ticker"], f["tag"] if f else "데이터 없음"))
            continue
        p["f"] = f
        p["bottleneck"] = "edgar" in p["why"] and bool(f["gm_up"])
        p["score"] = len(p["why"]) + (2 if p["bottleneck"] else 0) + min(p["vr"], 4) / 2
        picks.append(p)
    picks = sorted(picks, key=lambda p: -p["score"])
    extra = len(picks) - MAX_PICKS
    picks = picks[:MAX_PICKS]

    ny = pd.Timestamp.now(tz="America/New_York")
    day = (ny - pd.Timedelta(days=1) if ny.hour < 16 else ny).normalize()
    while day.weekday() >= 5:
        day -= pd.Timedelta(days=1)
    ds = day.strftime("%Y-%m-%d")
    md = f"# 📡 소셜 아비트리지 — {ds} 뉴욕 종가\n\n"
    md += "> 관심 급증(레딧·StockTwits·위키피디아·공시 병목 표현 중 2개↑) + 가격이 막 움직이기 시작 + 실적 개선 · 시총 $2B↑ · 하루 최대 2개 · 🔧 = 공시 병목 표현 증가 + 매출총이익률 상승\n\n"
    if picks:
        md += "| 티커 | 회사 | 섹터 | 오늘 | 왜 |\n| :--- | :--- | :--- | ---: | :--- |\n"
        for p in picks:
            t = p["ticker"]
            why = " · ".join(p["why"].values()) + " · 거래량 %.1f배 · %s" % (p["vr"], p["f"]["tag"])
            if p["f"]["rev_g"] is not None:
                why += f" · 매출 {p['f']['rev_g']:+.0f}%"
            md += f"| {fv(t)}{' 🔧' if p['bottleneck'] else ''} | {uni[t]['name'][:32]} | {uni[t]['sector']} | {p['r1']:+.1f}% | {why} |\n"
            shown[t] = ds
        if extra > 0:
            md += f"\n> 기준을 넘은 종목이 {extra}개 더 있어요. 내일도 기준을 넘으면 나와요.\n"
    else:
        md += "**오늘 없음** — 기준을 모두 넘는 종목이 없어요.\n"
    md += "\n> 알림 = '조사해볼 자리'. 진입은 7개 룰과 실적을 직접 확인 · 뽑힌 종목은 8주 동안 풀백 추적 (🔔 칸)\n"
    open(f"{OUT}/daily/{ds}.md", "w", encoding="utf-8").write(md)
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    json.dump(shown, open(f"{OUT}/shown.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(cache, open(f"{OUT}/wiki_map.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(md)
    log = [f"{ds} 거름망 기록",
           "출처별: " + str({k: sum(1 for v in src.values() if k in v) for k in ("reddit", "stocktwits", "edgar", "wiki")}),
           f"관심 출처 1개↑ {len(src)}개: " + ", ".join(f"{t}({'+'.join(src[t])})" for t in sorted(src)),
           f"가격 조건 통과 {len(price_ok)}개: " + ", ".join(f"{t}({'+'.join(src[t])})" for t in price_ok),
           f"출처 2개↑ 후보 풀 {len(pool)}개: " + ", ".join(f"{p['ticker']}({'+'.join(p['why'])})" for p in pool),
           "실적 탈락: " + ", ".join(f"{t}({why})" for t, why in fail)]
    open(f"{OUT}/funnel.txt", "w", encoding="utf-8").write("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
