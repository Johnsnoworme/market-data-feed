"""
소셜 아비트리지 레이더 백테스트 — '몇 개월 들고 가는 옵션 트레이더' 관점 (수동 실행)
신호(2018-01 ~ 12개월 전): 지금 레이더의 가격 조건 + 거래량 1.5배↑, 같은 종목 21거래일 중복 제거
그룹: 실적(당시 SEC 공시 EPS·매출, 분기 끝 50일 후부터 사용) / 위키피디아 관심 급증 / 거래량 2.5배↑
측정: 1·3·6·9·12개월 수익·QQQ 대비, 12개월 안 최고점, 풀백(30~70%) 빈도, 20% 조정 횟수,
      콜옵션(3·6·9·12개월 만기, ATM·10% OTM, 블랙숄즈 + 변동성 = 60일 실제 변동성 × 1.2) 4가지 매도 방식
※ 지금 시총 $2B↑ 종목만(생존 편향) · 옵션은 모델 가격(실제 호가·스프레드 없음) → 그룹·기간끼리 비교로 해석
결과: research/social_bt/latest.md, research/social_bt/events.csv.gz
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy.special import ndtr

OUT = "research/social_bt"
UA = {"User-Agent": "market-data-feed/1.0 (johnsnoworme research)"}
SEC_UA = {"User-Agent": "market-data-feed research Johnsnoworme@users.noreply.github.com"}
START_SIG = "2018-01-01"
HZ = {"1개월": 21, "3개월": 63, "6개월": 126, "9개월": 189, "12개월": 252}
EXP = {"3개월": 63, "6개월": 126, "9개월": 189, "12개월": 252}
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    LOG.append(s)


# ---------------- 데이터 ----------------
def universe():
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
         "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
    rows = requests.get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true", headers=h, timeout=30).json()["data"]["rows"]
    out = {}
    for r in rows:
        try:
            cap = float(r.get("marketCap") or 0)
        except ValueError:
            continue
        s = (r.get("symbol") or "").strip()
        if s and "^" not in s and "/" not in s and cap >= 2e9:
            out[s.replace(".", "-")] = r.get("name") or s
    return out


def prices(tickers):
    parts = {k: [] for k in ("Close", "High", "Low", "Volume")}
    for i in range(0, len(tickers), 100):
        d = yf.download(tickers[i:i + 100], start="2017-01-01", interval="1d", auto_adjust=True, progress=False, group_by="column", threads=True)
        if d.empty:
            continue
        for k in parts:
            parts[k].append(d[k])
    out = {}
    for k, v in parts.items():
        x = pd.concat(v, axis=1)
        out[k] = x.loc[:, ~x.columns.duplicated()]
    return out


SCODE = {}


def sec_get(url):
    for i in range(2):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            SCODE[r.status_code] = SCODE.get(r.status_code, 0) + 1
            if r.status_code == 200:
                return r.json()
            if r.status_code in (403, 404):
                return None
        except Exception:
            SCODE["err"] = SCODE.get("err", 0) + 1
        time.sleep(2)
    return None


def norm(n):
    n = re.sub(r"\b(COMMON STOCK|CLASS [A-C]|ORDINARY SHARES?|AMERICAN DEPOSITARY SHARES?|ADS|INC|INCORPORATED|CORP|CORPORATION|HOLDINGS?|LTD|LIMITED|PLC|N ?V|S ?A|CO|COMPANY|GROUP|THE|COMMON|SHARES?|/DE|/MD|/NEW)\b", " ",
               re.sub(r"[^A-Z0-9/ ]", " ", n.upper()))
    return re.sub(r"\s+", " ", n).strip()


def fundamentals(names):
    if os.path.exists(f"{OUT}/fund_cache.json"):
        d = json.load(open(f"{OUT}/fund_cache.json"))
        log(f"SEC 실적 캐시 사용: {len(d)}개 종목")
        return {t: {int(k): v for k, v in x.items()} for t, x in d.items()}
    """{ticker: {qidx: {end, eps, rev}}} — SEC XBRL frames. 티커는 회사 이름으로 연결 (www.sec.gov 막힘)"""
    t0 = time.time()
    by_name = {}
    for t, nm in names.items():
        by_name.setdefault(norm(nm), t)
    out, cik2t, miss = {}, {}, set()
    tags = [("eps", "EarningsPerShareDiluted", "USD-per-shares"), ("eps", "EarningsPerShareBasic", "USD-per-shares"),
            ("rev", "Revenues", "USD"), ("rev", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
            ("rev", "SalesRevenueNet", "USD"), ("rev", "RevenueFromContractWithCustomerIncludingAssessedTax", "USD")]
    for y in range(2016, 2027):
        for q in range(1, 5):
            qi = y * 4 + q - 1
            for kind, tag, unit in tags:
                j = sec_get(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/{unit}/CY{y}Q{q}.json")
                time.sleep(0.12)
                if not j:
                    continue
                for d in j.get("data", []):
                    cik = int(d["cik"])
                    if cik not in cik2t:
                        cik2t[cik] = by_name.get(norm(d.get("entityName", "")))
                    t = cik2t[cik]
                    if not t:
                        continue
                    e = out.setdefault(t, {}).setdefault(qi, {"end": d.get("end")})
                    e.setdefault(kind, float(d["val"]))
    log(f"SEC 실적 (회사 이름으로 연결): {len(out)}/{len(names)}개 종목 · 응답 코드 {SCODE} · {time.time() - t0:.0f}초")
    json.dump({t: {str(k): v for k, v in d.items()} for t, d in out.items()}, open(f"{OUT}/fund_cache.json", "w"))
    return out


def fund_flags(f, date):
    """신호일에 알 수 있었던 최신 분기 vs 1년 전 같은 분기"""
    if not f:
        return None
    cut = (date - pd.Timedelta(days=50)).strftime("%Y-%m-%d")
    avail = [qi for qi, e in f.items() if e.get("end") and e["end"] <= cut and "eps" in e]
    if not avail:
        return None
    qi = max(avail)
    if qi - 4 not in f or "eps" not in f[qi - 4]:
        return None
    e0, e4 = f[qi]["eps"], f[qi - 4]["eps"]
    r0, r4 = f[qi].get("rev"), f[qi - 4].get("rev")
    return {"eps_pos": e0 > 0, "eps_up": e0 > e4, "rev_up": (r0 is not None and r4 is not None and r0 > r4)}


def clean_name(n):
    n = re.sub(r"\b(Common Stock|Class [A-C]|Ordinary Shares?|American Depositary Shares?|ADS|Inc\.?|Corp\.?|Corporation|Holdings?|Ltd\.?|plc|N\.V\.|S\.A\.|Co\.?|Group|Company|Common|Shares?)\b", "", n, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"[,().]", " ", n)).strip()


WIKI_DEADLINE = [0.0]


def wget(url, **kw):
    if time.time() > WIKI_DEADLINE[0]:
        return None
    for i in range(2):
        try:
            r = requests.get(url, headers=UA, timeout=15, **kw)
            if r.status_code == 200:
                return r.json()
            WCODE[r.status_code] = WCODE.get(r.status_code, 0) + 1
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(1)
    WERR.append(url)
    return None


WERR, WCODE = [], {}


def wiki_one(item):
    t, name = item
    cn = clean_name(name)
    if not cn:
        return t, None
    r = wget("https://en.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "format": "json", "srsearch": cn + " company", "srlimit": 1})
    res = (r or {}).get("query", {}).get("search", [])
    if not res or cn.split()[0].lower() not in res[0]["title"].lower():
        return t, None
    title = res[0]["title"]
    j = wget("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
             f"{requests.utils.quote(title.replace(' ', '_'), safe='')}/daily/20160101/20260927")
    if not j:
        return t, None
    s = pd.Series({pd.Timestamp(i["timestamp"][:8]): i["views"] for i in j.get("items", [])})
    if len(s) < 200:
        return t, None
    s = s.asfreq("D").fillna(0)
    rec, base = s.rolling(3).mean(), s.shift(3).rolling(30).mean()
    spike = ((rec >= 2 * base.clip(lower=1)) & (rec >= 300)).astype(int).rolling(7, min_periods=1).max() > 0
    return t, spike


def wiki_all(names):
    WIKI_DEADLINE[0] = time.time() + 25 * 60   # 위키는 최대 25분
    with ThreadPoolExecutor(4) as ex:
        res = dict(ex.map(wiki_one, names.items()))
    ok = {t: s for t, s in res.items() if s is not None}
    log(f"위키피디아 연결: {len(ok)}/{len(names)}개 종목 (요청 실패 {len(WERR)}건, 응답 코드 {WCODE})")
    return ok


# ---------------- 옵션 ----------------
def bs(S, K, T, sig, r=0.04):
    T = np.maximum(T, 1e-6)
    d1 = (np.log(S / K) + (r + 0.5 * sig ** 2) * T) / (sig * np.sqrt(T))
    return S * ndtr(d1) - K * np.exp(-r * T) * ndtr(d1 - sig * np.sqrt(T))


def option_stats(paths, sig, days, mny):
    """paths: (n, 253) 종가 경로(0=신호일). 4가지 매도 방식 ROI"""
    S0 = paths[:, 0]
    K = S0 * mny
    prem = bs(S0, K, days / 252, sig)
    j = np.arange(days + 1)
    S = paths[:, :days + 1]
    Tleft = (days - j) / 252
    val = bs(S, K[:, None], Tleft[None, :], sig[:, None])
    val[:, -1] = np.maximum(S[:, -1] - K, 0)
    roi = val / prem[:, None] - 1
    half = days // 2
    hit = roi >= 1.0
    first = np.where(hit.any(1), hit.argmax(1), 10 ** 6)
    out = {
        "만기까지": roi[:, -1],
        "절반 시점 매도": roi[:, half],
        "+100% 익절, 아니면 만기": np.where(first <= days, roi[np.arange(len(S)), np.minimum(first, days)], roi[:, -1]),
        "+100% 익절, 아니면 절반 시점": np.where(first <= half, roi[np.arange(len(S)), np.minimum(first, half)], roi[:, half]),
    }
    return out


# ---------------- 백테스트 ----------------
def compute(names):
    log(f"대상(지금 시총 $2B↑): {len(names)}개")
    P = prices(sorted(names))
    C, Hh, Lw, V = P["Close"], P["High"], P["Low"], P["Volume"]
    q = yf.download("QQQ", start="2017-01-01", interval="1d", auto_adjust=True, progress=False)["Close"].squeeze().reindex(C.index).ffill()
    C = C.where(C > 0)
    r5 = C / C.shift(5) - 1
    base = ((r5 > 0) & r5.gt(q / q.shift(5) - 1, axis=0) & (C > C.rolling(20).mean()) & (C / C.shift(21) - 1 < 0.5)
            & (C.pct_change(fill_method=None).rolling(5).max() < 0.4) & (C >= 5) & ((C * V).rolling(20).mean() >= 20e6))
    vr = V.rolling(3).mean() / V.shift(3).rolling(20).mean()
    sig = base & (vr >= 1.5)
    sig = sig & (sig.astype(int).rolling(21, min_periods=1).sum() == 1)
    vol60 = (np.log(C / C.shift(1))).rolling(60).std() * np.sqrt(252)
    idx = C.index
    last_ok = len(idx) - 253
    s0 = idx.searchsorted(pd.Timestamp(START_SIG))
    S = sig.values.copy()
    S[:s0] = False
    S[last_ok:] = False
    ti, ci = np.nonzero(S)
    log(f"신호(가격 조건 + 거래량 1.5배↑): {len(ti):,}개 ({idx[s0]:%Y-%m} ~ {idx[last_ok - 1]:%Y-%m})")

    Cn = C.ffill().values
    Ln = Lw.reindex(columns=C.columns).ffill().values
    rows = ti[:, None] + np.arange(253)[None, :]
    path = Cn[rows, ci[:, None]]
    qn = q.values
    qpath = qn[rows]
    ok = ~np.isnan(path).any(1) & ~np.isnan(qpath).any(1)
    ti, ci, path, qpath = ti[ok], ci[ok], path[ok], qpath[ok]
    n = len(ti)
    ev = pd.DataFrame({"date": idx[ti], "ticker": C.columns[ci], "vr": vr.values[ti, ci], "vol60": vol60.values[ti, ci]})
    for k, h in HZ.items():
        ev[f"ret_{k}"] = path[:, h] / path[:, 0] - 1
        ev[f"ex_{k}"] = ev[f"ret_{k}"] - (qpath[:, h] / qpath[:, 0] - 1)
    for k, h in (("3개월", 63), ("6개월", 126), ("12개월", 252)):
        ev[f"maxup_{k}"] = path[:, 1:h + 1].max(1) / path[:, 0] - 1
    ev["peak_day"] = path[:, 1:].argmax(1) + 1
    ev["mdd_12개월"] = path[:, 1:].min(1) / path[:, 0] - 1

    # 풀백: 1파 저점 = 신호 전 63일 최저 종가, 고점 = 신호 후 누적 최고
    low63 = np.array([np.nanmin(Cn[max(t - 63, 0):t + 1, c]) for t, c in zip(ti, ci)])
    runmax = np.maximum.accumulate(path, axis=1)
    leg = runmax - low63[:, None]
    retr = np.where(leg > 0, (runmax - path) / np.where(leg > 0, leg, 1), 0)
    valid_leg = (runmax / low63[:, None] - 1) >= 0.08
    zone = (retr >= 0.30) & valid_leg
    zone[:, 0] = False
    zhit = zone.any(1)
    zday = np.where(zhit, zone.argmax(1), -1)
    rec, brk, zret3, zmax6 = [], [], [], []
    for i in range(n):
        d = zday[i]
        if d < 0:
            rec.append(np.nan), brk.append(np.nan), zret3.append(np.nan), zmax6.append(np.nan)
            continue
        pk = runmax[i, d]
        after = path[i, d + 1:]
        newhi = np.nonzero(after > pk)[0]
        over70 = np.nonzero(retr[i, d + 1:] > 0.70)[0]
        rec.append(float(len(newhi) > 0))
        brk.append(float(len(over70) > 0 and (len(newhi) == 0 or over70[0] < newhi[0])))
        full = Cn[ti[i] + d: ti[i] + d + 127, ci[i]]
        zret3.append(full[min(63, len(full) - 1)] / full[0] - 1)
        zmax6.append(np.nanmax(full[1:]) / full[0] - 1 if len(full) > 1 else np.nan)
    ev["zone_hit"], ev["zone_day"] = zhit, zday
    ev["zone_recover"], ev["zone_break70"], ev["zone_ret3"], ev["zone_max6"] = rec, brk, zret3, zmax6
    cnt20 = []
    for i in range(n):
        c, inside = 0, False
        for j in range(1, 253):
            dr = path[i, j] / runmax[i, j] - 1
            if not inside and dr <= -0.20:
                c, inside = c + 1, True
            elif inside and path[i, j] >= runmax[i, j]:
                inside = False
        cnt20.append(c)
    ev["dd20_count"] = cnt20

    # 옵션
    sg = np.clip(np.nan_to_num(ev["vol60"].values, nan=0.6), 0.15, 3.0) * 1.2
    for m, lab in ((1.0, "ATM"), (1.1, "OTM10")):
        for k, days in EXP.items():
            for strat, roi in option_stats(path, sg, days, m).items():
                ev[f"opt_{lab}_{k}_{strat}"] = roi

    return ev, C, idx[s0], idx[last_ok - 1]


def main():
    os.makedirs(OUT, exist_ok=True)
    names = universe()
    if os.environ.get("ENRICH") == "1" and os.path.exists(f"{OUT}/events.csv.gz"):
        ev = pd.read_csv(f"{OUT}/events.csv.gz", parse_dates=["date"])
        ev = ev[[c for c in ev.columns if c not in ("has_f", "eps_pos", "eps_up", "rev_up", "has_w", "wiki")]]
        log(f"저장된 신호 {len(ev):,}개 불러옴 (주가 계산 재사용)")
        C = pd.DataFrame(columns=range(len(names)))
        s0_date, end_date = ev.date.min(), ev.date.max()
    else:
        ev, C, s0_date, end_date = compute(names)
    # 실적·위키
    fund = fundamentals(names)
    ff = [fund_flags(fund.get(t), d) for t, d in zip(ev["ticker"], ev["date"])]
    ev["has_f"] = [f is not None for f in ff]
    ev["eps_pos"] = [bool(f and f["eps_pos"]) for f in ff]
    ev["eps_up"] = [bool(f and f["eps_up"]) for f in ff]
    ev["rev_up"] = [bool(f and f["rev_up"]) for f in ff]
    wk = wiki_all({t: names.get(t, t) for t in ev["ticker"].unique()})
    ev["has_w"] = ev["ticker"].isin(list(wk))
    ev["wiki"] = [bool(wk[t].asof(d)) if t in wk and d >= wk[t].index[0] else False for t, d in zip(ev["ticker"], ev["date"])]
    ev.to_csv(f"{OUT}/events.csv.gz", index=False, compression="gzip")

    # ---------------- 그룹 ----------------
    G = {
        "① 전체 (가격+거래량 1.5배)": ev.index == ev.index,
        "② 실적 개선 (EPS↑·매출↑, 적자 축소 포함) = 지금 레이더": ev.eps_up & ev.rev_up,
        "③ 흑자 + EPS↑ + 매출↑": ev.eps_pos & ev.eps_up & ev.rev_up,
        "④ 적자 회사 (EPS < 0)": ev.has_f & ~ev.eps_pos,
        "⑤ ③ + 거래량 2.5배↑": ev.eps_pos & ev.eps_up & ev.rev_up & (ev.vr >= 2.5),
        "⑥ ② + 위키 관심 급증": ev.eps_up & ev.rev_up & ev.wiki,
        "⑦ 위키 관심 급증 (실적 무관)": ev.wiki,
    }
    days_n = len(pd.bdate_range(START_SIG, end_date))
    md = "# 🧪 소셜 아비트리지 레이더 백테스트 — 몇 개월 트레이더 관점\n\n"
    md += (f"> 신호 {s0_date:%Y-%m} ~ {end_date:%Y-%m} · 지금 시총 $2B↑ {len(names)}개 종목 · 신호 = 레이더 가격 조건 + 거래량 1.5배↑ (같은 종목 21일 중복 제거)\n"
           "> 실적 = 당시 SEC 공시(분기 끝 50일 후부터 사용) · 위키 = 최근 7일 안 조회수 3일 평균 ≥ 이전 30일 × 2 (하루 300↑)\n"
           "> ⚠️ 생존 편향(지금 살아 있는 종목만) · 레딧·StockTwits 과거 기록 없음 · 옵션 = 블랙숄즈 모델값(변동성 = 60일 실제 × 1.2, 스프레드 없음) → **그룹·기간끼리 비교용**\n\n")
    md += "## 1. 주가: 신호 후 N개월 (QQQ 대비 초과수익)\n| 그룹 | 신호 수 | 하루 평균 | 1개월 | 3개월 | 6개월 | 9개월 | 12개월 | 6개월 QQQ 이긴 % | 12개월 QQQ 이긴 % |\n| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n"
    for g, m in G.items():
        e = ev[m]
        if len(e) < 30:
            md += f"| {g} | {len(e)} | 표본 부족 |||||||||\n"
            continue
        md += (f"| {g} | {len(e):,} | {len(e) / days_n:.2f} | " + " | ".join(f"{e[f'ex_{k}'].mean() * 100:+.1f}%" for k in HZ)
               + f" | {(e['ex_6개월'] > 0).mean() * 100:.0f}% | {(e['ex_12개월'] > 0).mean() * 100:.0f}% |\n")
    md += "\n> 평균은 크게 오른 몇 종목에 끌려감 → 중앙값도 확인\n\n| 그룹 | 3개월 중앙값 | 6개월 중앙값 | 12개월 중앙값 (수익률) |\n| :--- | ---: | ---: | ---: |\n"
    for g, m in G.items():
        e = ev[m]
        if len(e) >= 30:
            md += f"| {g} | {e['ret_3개월'].median() * 100:+.1f}% | {e['ret_6개월'].median() * 100:+.1f}% | {e['ret_12개월'].median() * 100:+.1f}% |\n"
    md += "\n## 2. 들고 있는 동안 최고점 (팔 수 있었던 최대)\n| 그룹 | 3개월 안 최고 (중앙) | 6개월 안 최고 (중앙) | 12개월 안 최고 (중앙) | 6개월 안 +30%↑ 찍음 | 6개월 안 +50%↑ | 12개월 안 +100%↑ | 12개월 최고점 날 (중앙) | 12개월 중 최저 (중앙) |\n| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n"
    for g, m in G.items():
        e = ev[m]
        if len(e) >= 30:
            md += (f"| {g} | {e['maxup_3개월'].median() * 100:+.0f}% | {e['maxup_6개월'].median() * 100:+.0f}% | {e['maxup_12개월'].median() * 100:+.0f}% | "
                   f"{(e['maxup_6개월'] >= 0.3).mean() * 100:.0f}% | {(e['maxup_6개월'] >= 0.5).mean() * 100:.0f}% | {(e['maxup_12개월'] >= 1.0).mean() * 100:.0f}% | "
                   f"{e['peak_day'].median() / 21:.1f}개월 | {e['mdd_12개월'].median() * 100:+.0f}% |\n")
    md += "\n## 3. 풀백 (12개월 안)\n> 풀백 = 1파(신호 전 3개월 저점 → 신호 후 최고) 대비 30% 이상 되돌림, 1파 8%↑만 · 20% 조정 = 최고점 대비 -20%가 몇 번 왔나\n\n"
    md += "| 그룹 | 풀백 옴 | 오기까지 (중앙) | 풀백 후 신고가 회복 | 풀백 후 70% 이탈 | 풀백 자리 매수 → 3개월 (중앙) | 풀백 자리 → 6개월 안 최고 (중앙) | 20% 조정 평균 횟수 | 20% 조정 1번↑ |\n| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n"
    for g, m in G.items():
        e = ev[m]
        if len(e) >= 30:
            z = e[e.zone_hit]
            md += (f"| {g} | {e.zone_hit.mean() * 100:.0f}% | {z['zone_day'].median() / 21:.1f}개월 | {z['zone_recover'].mean() * 100:.0f}% | {z['zone_break70'].mean() * 100:.0f}% | "
                   f"{z['zone_ret3'].median() * 100:+.1f}% | {z['zone_max6'].median() * 100:+.0f}% | {e['dd20_count'].mean():.1f}번 | {(e['dd20_count'] >= 1).mean() * 100:.0f}% |\n")
    md += "\n## 4. 콜옵션 — 만기·매도 방식별 (옵션 수익률, 프리미엄 대비)\n> ROI 평균 · 중앙값 · 이익 본 비율 · +100%↑ 비율 · -80%↓(거의 전액 손실) 비율\n"
    for g in list(G)[:5]:
        e = ev[G[g]]
        if len(e) < 30:
            continue
        for lab, lname in (("ATM", "ATM (행사가 = 현재가)"), ("OTM10", "10% OTM (행사가 = 현재가 +10%)")):
            if lab == "OTM10" and not g.startswith(("②", "③")):
                continue
            md += f"\n### {g} — {lname}\n| 만기 | 매도 방식 | 평균 | 중앙값 | 이익 % | +100%↑ | -80%↓ |\n| :--- | :--- | ---: | ---: | ---: | ---: | ---: |\n"
            for k in EXP:
                for strat in ("만기까지", "절반 시점 매도", "+100% 익절, 아니면 만기", "+100% 익절, 아니면 절반 시점"):
                    x = e[f"opt_{lab}_{k}_{strat}"]
                    md += (f"| {k} | {strat} | {x.mean() * 100:+.0f}% | {x.median() * 100:+.0f}% | {(x > 0).mean() * 100:.0f}% | "
                           f"{(x >= 1).mean() * 100:.0f}% | {(x <= -0.8).mean() * 100:.0f}% |\n")
    md += "\n## 5. 연도별 6개월 초과수익 (그룹 ②·③·④)\n| 연도 | ② | ③ | ④ |\n| :--- | ---: | ---: | ---: |\n"
    ks = list(G)
    for y in sorted(ev.date.dt.year.unique()):
        cells = []
        for g in (ks[1], ks[2], ks[3]):
            e = ev[G[g] & (ev.date.dt.year == y)]
            cells.append(f"{e['ex_6개월'].mean() * 100:+.1f}% ({len(e)})" if len(e) >= 10 else "—")
        md += f"| {y} | " + " | ".join(cells) + " |\n"
    md += "\n## 기록\n" + "\n".join("- " + s for s in LOG) + f"\n- 실적 데이터 있는 신호 {ev.has_f.mean() * 100:.0f}% · 위키 연결 신호 {ev.has_w.mean() * 100:.0f}%\n"
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    main()
