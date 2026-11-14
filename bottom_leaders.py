"""
🌄 반등 리더 분석가 — 백테스트 + 라이브 스캐너 (기록 전용 · 매수 추천 아님)

질문: "시장 저점이 확인된 날, 그 뒤 60거래일 동안 더 오른 종목은 그날 어떤 특징이 있었나?"
      → 그 특징으로 줄 세우면(⭐종합) 무작위로 고르는 것보다 정말 나은가?

──────────── 규칙 (결과를 보기 전에 고정. 결과 보고 바꾸지 않는다) ────────────
① 저점 신호 = SPY가 52주 고점 대비 -10% 이하로 내려간 뒤, 저점(종가) 4~25거래일 사이에
   '하루 +1.5% 이상 + 거래량이 전날보다 큼'(팔로우스루)이 처음 나온 날. 신호 사이 40거래일 이상.
   저점 날짜는 그날까지의 데이터로만 정한다(미래 정보 금지).
② 신호일 T에 종목별 특징 6개 + 종합을 T까지의 데이터로만 계산 (features()는 T까지 잘라 둔 데이터만 받는다).
     resil 버티는 힘 · rebound 반등 속도 · beta · volsurge 거래량 급증 · mom 12-1 모멘텀 · above50 50일선 위 거리
     ⭐composite = rebound · mom · above50 퍼센타일 평균   ← 합류 판정은 이 하나만 본다(나머지는 탐색용)
③ 진입 = T 다음 거래일 종가, 20·60거래일 뒤 수익(수정주가). 평가 = 상위 20% 평균 − 유니버스 평균(lift).
④ 자동 합격 판정(⭐종합) — 모두 만족해야 '통과':
     · 20일·60일 모두 평균 lift > 0, 중앙값 > 0, 이긴 비율 ≥ 65%
     · 60일 최악 에피소드 ≥ -15%p, 에피소드 ≥ 10개
     · 전반부(2016-01-01 이전)·후반부 각각 60일 평균 lift > 0 (각 4개 이상)
     · 무작위 선택 대비 p값(60일) ≤ 0.05  (7개 특징을 동시에 시험하므로 ≤ 0.007이면 '강', 그 사이는 '약')
⑤ 데이터 신뢰 게이트 — 하나라도 실패하면 **결과를 저장하지 않고 중단**:
     · 유니버스 80% 이상 확보, SPY 5,400거래일 이상
     · 알려진 시장 낙폭과 대조(2007-09 금융위기·2020 코로나·2022 약세장): 범위를 벗어나면 중단
     · 2차 출처(Stooq) 교차검증: 접속되면 종가가 0.7% 넘게 다르면 중단, 접속 안 되면 '단일 출처'라고 보고서에 표시
     · 하루 ±70% 넘는 움직임이 있는 종목은 데이터 오류 의심으로 제외하고 목록을 보고서에 적는다
⑥ 정직 공개: 유니버스는 '지금 살아 있는' 대형주(생존 편향) → 절대수익이 아니라 같은 유니버스 평균 대비 lift만 본다.
   에피소드가 적다(10~15개) → 통계는 '무작위 대비 p값'과 전반/후반 일관성으로 우연을 가려낸다.

실행
  python bottom_leaders.py backtest  → research/bottom_leaders/backtest_YYYY-MM-DD.md + .json
  python bottom_leaders.py live      → status.json + latest.md  (검증 통과 뒤 매일 실행용)
  BT_MOCK=1 python bottom_leaders.py backtest → 합성 데이터로 코드만 점검(mock_out/, 숫자 의미 없음)
"""
import datetime as dt
import io
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

MOCK = bool(os.environ.get("BT_MOCK"))
OUT = "mock_out" if MOCK else "research/bottom_leaders"

START = "2004-06-01"
BT_FROM = "2006-01-01"
SPLIT = pd.Timestamp("2016-01-01")
DD_TRIGGER = -0.10
FTD_MIN, FTD_MAX = 4, 25
FTD_RET = 0.015
SIGNAL_GAP = 40
HORIZONS = (20, 60)
TOPFRAC = 0.2
N_SIMS = 4000
FACTORS = ["resil", "rebound", "beta", "volsurge", "mom", "above50", "composite"]
WATCH = ["INTC", "AMD", "MU", "SNDK", "MSFT", "PLTR", "NVDA", "AVGO"]
KNOWN_LOWS = ["2009-03-09", "2011-10-03", "2016-02-11", "2018-12-24", "2020-03-23", "2022-10-12", "2023-10-27", "2025-04-08"]
# (고점일, 저점일, 허용 낙폭 범위 %) — 수정주가 SPY 기준 공개된 대략값. 틀리면 데이터가 이상한 것.
ANCHORS = [("2007-10-09", "2009-03-09", -60, -50), ("2020-02-19", "2020-03-23", -37, -31), ("2022-01-03", "2022-10-12", -29, -22)]
XCHECK = ["SPY", "AAPL", "MSFT", "JPM", "XOM"]

UNIVERSE = """
AAPL MSFT AMZN GOOGL META NVDA INTC AMD MU QCOM TXN AVGO ADBE ORCL CSCO IBM HPQ AMAT LRCX KLAC WDC STX SNDK
NFLX TSLA CRM INTU ADSK ON MCHP ADI NXPI MRVL SWKS AKAM EBAY PYPL PLTR ANET NOW PANW CRWD TSM ASML ARM
JPM BAC C WFC GS MS AXP USB PNC SCHW BK BLK COF V MA
JNJ PFE MRK LLY ABT AMGN GILD BMY UNH CVS MDT TMO DHR ISRG REGN VRTX BIIB ZTS SYK
PG KO PEP WMT COST MCD MO PM CL KMB MDLZ
XOM CVX COP SLB OXY HAL EOG PSX VLO MPC
GE CAT DE BA LMT RTX HON UPS FDX MMM NOC GD EMR ETN
FCX NEM DOW LIN APD NUE
HD LOW NKE SBUX TGT DIS F GM BKNG MAR
T VZ CMCSA TMUS
DUK SO NEE D AEP
""".split()


# ───────────────────────── 데이터 ─────────────────────────
def _mock(tickers):
    rng = np.random.default_rng(7)
    idx = pd.bdate_range(START, "2026-11-13")
    n = len(idx)
    m = rng.normal(0.0004, 0.009, n)
    for s in (900, 1500, 2300, 3100, 3900, 4700, 5300):
        m[s:s + 40] = rng.normal(-0.012, 0.012, 40)
        m[s + 40:s + 60] = rng.normal(0.014, 0.012, 20)
    spy = 100 * np.cumprod(1 + m)
    closes, vols = {"SPY": spy}, {}
    up = np.r_[0, np.diff(spy)] > 0
    vols["SPY"] = rng.integers(50, 100, n) * (1 + 0.5 * up)
    for t in tickers:
        beta = rng.uniform(0.5, 2.0)
        r = beta * m + rng.normal(rng.normal(0.0002, 0.0004), 0.012, n)
        closes[t] = 20 * np.cumprod(1 + r)
        vols[t] = rng.integers(10, 100, n) * (1 + 0.3 * up)
    return pd.DataFrame(closes, index=idx), pd.DataFrame(vols, index=idx)


def load_prices(tickers):
    if MOCK:
        return _mock(tickers)
    import yfinance as yf
    allt = ["SPY"] + [t for t in tickers if t != "SPY"]
    closes, vols = [], []
    for i in range(0, len(allt), 40):
        chunk = allt[i:i + 40]
        df = None
        for attempt in range(3):
            try:
                df = yf.download(chunk, start=START, auto_adjust=True, progress=False, threads=True, group_by="column")
                if df is not None and len(df) > 0:
                    break
            except Exception as e:  # noqa
                print(f"   다운로드 {attempt + 1}/3 실패: {e}")
            time.sleep(5 * (attempt + 1))
        if df is None or len(df) == 0:
            continue
        c, v = df["Close"], df["Volume"]
        if isinstance(c, pd.Series):
            c, v = c.to_frame(chunk[0]), v.to_frame(chunk[0])
        closes.append(c)
        vols.append(v)
    if not closes:
        sys.exit("❌ 가격 데이터를 하나도 못 받았다 — 저장하지 않는다")
    C = pd.concat(closes, axis=1)
    V = pd.concat(vols, axis=1)
    C = C.loc[:, ~C.columns.duplicated()].sort_index()
    V = V.loc[:, ~V.columns.duplicated()].sort_index()
    return C, V


def data_gate(C, V, tickers):
    """데이터 신뢰 게이트. (통과한 C, V, 보고서에 쓸 줄 목록) 반환. 실패하면 중단."""
    notes = []
    if "SPY" not in C.columns or C["SPY"].notna().sum() < 5400:
        sys.exit("❌ SPY 데이터가 5,400거래일 미만 — 저장하지 않는다")
    got = [t for t in tickers if t in C.columns and C[t].notna().sum() > 300]
    notes.append(f"유니버스 {len(got)}/{len(tickers)}종목 확보")
    if len(got) < 0.8 * len(tickers):
        sys.exit("❌ 데이터 커버리지 80% 미만 — 저장하지 않는다")
    if not MOCK:
        spy = C["SPY"].dropna()
        for a, b, lo, hi in ANCHORS:
            if a not in spy.index or b not in spy.index:
                sys.exit(f"❌ 알려진 날짜 {a} 또는 {b} 가 데이터에 없음 — 저장하지 않는다")
            dd = (spy.loc[b] / spy.loc[a] - 1) * 100
            if not (lo <= dd <= hi):
                sys.exit(f"❌ 데이터 이상: SPY {a}→{b} 낙폭 {dd:.1f}% (정상 범위 {lo}~{hi}%) — 저장하지 않는다")
            notes.append(f"✅ SPY {a}→{b} 낙폭 {dd:.1f}% (정상 범위 {lo}~{hi}%)")
    r = C[got].pct_change(fill_method=None).abs()
    bad = [t for t in got if (r[t] > 0.70).any()]
    if bad:
        notes.append("⚠️ 하루 ±70% 넘는 움직임이 있어 제외: " + ", ".join(bad))
    keep = [t for t in got if t not in bad]
    notes.append(cross_check())
    cols = ["SPY"] + keep
    return C[cols], V[cols], notes


def cross_check():
    if MOCK:
        return "교차검증: (합성 데이터 — 해당 없음)"
    try:
        import requests
        import yfinance as yf
        worst, n_ok = 0.0, 0
        dates = ["2008-09-15", "2009-03-09", "2013-05-15", "2018-12-24", "2020-03-23", "2022-10-12"]
        for t in XCHECK:
            raw = yf.download(t, start="2008-01-01", auto_adjust=False, progress=False)["Close"].squeeze()
            s = requests.get(f"https://stooq.com/q/d/l/?s={t.lower()}.us&i=d", timeout=20)
            st = pd.read_csv(io.StringIO(s.text), parse_dates=["Date"], index_col="Date")["Close"]
            for d in dates:
                d = pd.Timestamp(d)
                if d in raw.index and d in st.index:
                    worst = max(worst, float(abs(raw.loc[d] / st.loc[d] - 1) * 100))
                    n_ok += 1
        if n_ok < 10:
            return f"⚠️ 교차검증 못 함(Stooq 비교 {n_ok}건뿐) — 단일 출처(Yahoo)"
        if worst > 0.7:
            sys.exit(f"❌ Yahoo와 Stooq 종가가 {worst:.2f}% 다름(허용 0.7%) — 저장하지 않는다")
        return f"✅ 2차 출처(Stooq) 교차검증 {n_ok}건 · 최대 차이 {worst:.2f}%"
    except SystemExit:
        raise
    except Exception as e:  # noqa
        return f"⚠️ 교차검증 못 함({type(e).__name__}) — 단일 출처(Yahoo)"


# ───────────────────────── 저점 신호 ─────────────────────────
def find_signals(spy, vol):
    c, v = spy.values, vol.values
    n = len(c)
    roll_high = spy.rolling(252, min_periods=60).max().values
    ret = np.r_[np.nan, c[1:] / c[:-1] - 1]
    sigs = []
    in_corr, low_i = False, None
    last = -10**9
    for i in range(n):
        dd = c[i] / roll_high[i] - 1 if not np.isnan(roll_high[i]) else 0
        if dd <= DD_TRIGGER:
            if not in_corr:
                in_corr, low_i = True, i
            elif c[i] < c[low_i]:
                low_i = i
        if in_corr:
            if dd > -0.05:
                in_corr, low_i = False, None
                continue
            d = i - low_i
            if FTD_MIN <= d <= FTD_MAX and ret[i] >= FTD_RET and v[i] > v[i - 1]:
                if i - last >= SIGNAL_GAP and spy.index[i] >= pd.Timestamp(BT_FROM):
                    lo = max(0, low_i - 252)
                    peak_i = lo + int(np.argmax(c[lo:low_i + 1]))
                    sigs.append((i, low_i, peak_i))
                    last = i
                in_corr, low_i = False, None
    return sigs


def regime_now(spy, vol):
    sigs = find_signals(spy, vol)
    n = len(spy)
    c = spy.values
    roll_high = spy.rolling(252, min_periods=60).max().values
    dd_now = c[-1] / roll_high[-1] - 1
    if sigs and n - 1 - sigs[-1][0] <= 15:
        i, low_i, _ = sigs[-1]
        return "confirmed", {"signal_date": str(spy.index[i].date()), "low_date": str(spy.index[low_i].date()),
                             "days_since_signal": n - 1 - i, "dd_now_pct": round(dd_now * 100, 1)}
    recent_dd = (c[-120:] / roll_high[-120:] - 1).min()
    if dd_now <= DD_TRIGGER or (recent_dd <= DD_TRIGGER and dd_now < -0.05):
        return "forming", {"dd_now_pct": round(dd_now * 100, 1), "worst_dd_120d_pct": round(recent_dd * 100, 1)}
    return "none", {"dd_now_pct": round(dd_now * 100, 1)}


# ───────────────────────── 특징 (T까지의 데이터만) ─────────────────────────
def features(Cp, Vp, low_i, peak_i):
    cols = [t for t in Cp.columns if t != "SPY"]
    ok = Cp.iloc[-253:][cols].notna().all()
    cols = [t for t in cols if ok[t]]
    spy = Cp["SPY"]
    last = len(Cp) - 1
    f = pd.DataFrame(index=cols)
    f["resil"] = Cp[cols].iloc[low_i] / Cp[cols].iloc[peak_i] - 1 - (spy.iloc[low_i] / spy.iloc[peak_i] - 1)
    f["rebound"] = Cp[cols].iloc[last] / Cp[cols].iloc[low_i] - 1 - (spy.iloc[last] / spy.iloc[low_i] - 1)
    r = Cp.pct_change(fill_method=None).iloc[-252:]
    sr = r["SPY"] - r["SPY"].mean()
    f["beta"] = ((r[cols] - r[cols].mean()).mul(sr, axis=0)).sum() / (sr ** 2).sum()
    v5 = Vp[cols].iloc[-5:].mean()
    v50 = Vp[cols].iloc[-55:-5].mean().replace(0, np.nan)
    f["volsurge"] = v5 / v50
    f["mom"] = Cp[cols].iloc[-22] / Cp[cols].iloc[-253] - 1
    f["above50"] = Cp[cols].iloc[-1] / Cp[cols].iloc[-50:].mean() - 1
    f = f.replace([np.inf, -np.inf], np.nan).dropna()
    f["composite"] = f[["rebound", "mom", "above50"]].rank(pct=True).mean(axis=1)
    return f


# ───────────────────────── 백테스트 ─────────────────────────
def run_backtest(C, V):
    spy = C["SPY"]
    sigs = find_signals(spy, V["SPY"])
    n = len(C)
    episodes, frs = [], {}
    for (i, low_i, peak_i) in sigs:
        if i < 260:
            continue
        f = features(C.iloc[:i + 1], V.iloc[:i + 1], low_i, peak_i)   # ← 미래를 잘라낸 데이터
        if len(f) < 40:
            continue
        k = max(1, math.ceil(TOPFRAC * len(f)))
        ep = {"signal": str(spy.index[i].date()), "low": str(spy.index[low_i].date()), "peak": str(spy.index[peak_i].date()),
              "spy_dd_pct": round((spy.iloc[low_i] / spy.iloc[peak_i] - 1) * 100, 1), "n_stocks": len(f),
              "k": k, "fwd": {}, "lift": {}, "top5": [], "watch_rank": {}}
        for h in HORIZONS:
            if i + 1 + h >= n:
                continue
            fr = (C.iloc[i + 1 + h] / C.iloc[i + 1] - 1)[f.index].dropna()
            if len(fr) < 40:
                continue
            frs[(ep["signal"], h)] = fr
            ep["fwd"][h] = {"spy": round((spy.iloc[i + 1 + h] / spy.iloc[i + 1] - 1) * 100, 1), "universe": round(fr.mean() * 100, 1)}
            for fac in FACTORS:
                top = f.loc[fr.index, fac].nlargest(k).index
                ep["lift"].setdefault(fac, {})[h] = float((fr[top].mean() - fr.mean()) * 100)
            if h == 60:
                best = f["composite"].nlargest(5).index
                ep["top5"] = [{"t": t, "ret60": round(float(fr.get(t, np.nan)) * 100, 1)} for t in best]
        for w in WATCH:
            if w in f.index:
                ep["watch_rank"][w] = int(f["composite"].rank(ascending=False)[w])
        episodes.append(ep)
    return episodes, frs


def summarize(episodes, h, subset=None):
    rows = {}
    for fac in FACTORS:
        v = [e["lift"][fac][h] for e in episodes if (subset is None or subset(e)) and fac in e["lift"] and h in e["lift"][fac]]
        if v:
            rows[fac] = {"n": len(v), "mean": float(np.mean(v)), "median": float(np.median(v)),
                         "hit": 100 * float(np.mean([x > 0 for x in v])), "worst": float(min(v))}
    return rows


def random_pvalues(episodes, frs):
    """무작위로 같은 개수를 골랐을 때 '평균 lift'가 관찰값 이상 나올 확률."""
    rng = np.random.default_rng(2026)
    out = {}
    for h in HORIZONS:
        used = [e for e in episodes if (e["signal"], h) in frs]
        if not used:
            continue
        sims = np.zeros(N_SIMS)
        for e in used:
            fr = frs[(e["signal"], h)].values
            m, k = len(fr), min(e["k"], len(fr))
            R = rng.random((N_SIMS, m))
            idx = np.argpartition(-R, k - 1, axis=1)[:, :k]
            sims += (fr[idx].mean(axis=1) - fr.mean()) * 100
        sims /= len(used)
        for fac in FACTORS:
            obs = np.mean([e["lift"][fac][h] for e in used])
            out.setdefault(fac, {})[h] = float((sims >= obs).mean())
    return out


def known_low_check(spy, vol):
    sigs = [spy.index[i] for i, _, _ in find_signals(spy, vol)]
    idx = spy.index
    rows = []
    for d in KNOWN_LOWS:
        d0 = pd.Timestamp(d)
        if d0 < idx[0] or d0 > idx[-1]:
            continue
        pos = idx.searchsorted(d0)
        hit = [s for s in sigs if 0 <= idx.searchsorted(s) - pos <= 30]
        rows.append((d, str(hit[0].date()) if hit else None))
    return rows


def verdict(episodes, pvals):
    """⭐종합 하나에 대한 자동 합격 판정."""
    s20 = summarize(episodes, 20).get("composite")
    s60 = summarize(episodes, 60).get("composite")
    h1 = summarize(episodes, 60, lambda e: pd.Timestamp(e["signal"]) < SPLIT).get("composite")
    h2 = summarize(episodes, 60, lambda e: pd.Timestamp(e["signal"]) >= SPLIT).get("composite")
    p60 = pvals.get("composite", {}).get(60, 1.0)
    if not s20 or not s60:
        return "불통과", [("에피소드 부족", False, "20·60일 결과 없음")], "미달"
    checks = []

    def add(name, ok, detail):
        checks.append((name, bool(ok), detail))

    add("20일 평균·중앙값 > 0", s20["mean"] > 0 and s20["median"] > 0, f"평균 {s20['mean']:+.1f} · 중앙값 {s20['median']:+.1f}")
    add("60일 평균·중앙값 > 0", s60["mean"] > 0 and s60["median"] > 0, f"평균 {s60['mean']:+.1f} · 중앙값 {s60['median']:+.1f}")
    add("이긴 비율 ≥ 65% (20·60일 모두)", s20["hit"] >= 65 and s60["hit"] >= 65, f"20일 {s20['hit']:.0f}% · 60일 {s60['hit']:.0f}%")
    add("60일 최악 ≥ -15%p", s60["worst"] >= -15, f"{s60['worst']:+.1f}")
    add("에피소드 ≥ 10", s60["n"] >= 10, f"{s60['n']}개")
    add("전반부(2016 이전) 60일 평균 > 0 (≥4개)", bool(h1) and h1["n"] >= 4 and h1["mean"] > 0, f"{h1['mean']:+.1f} ({h1['n']}개)" if h1 else "표본 없음")
    add("후반부(2016~) 60일 평균 > 0 (≥4개)", bool(h2) and h2["n"] >= 4 and h2["mean"] > 0, f"{h2['mean']:+.1f} ({h2['n']}개)" if h2 else "표본 없음")
    strength = "강" if p60 <= 0.05 / 7 else "약" if p60 <= 0.05 else "미달"
    add("무작위 대비 p ≤ 0.05 (60일)", p60 <= 0.05, f"p = {p60:.4f} → {strength}")
    return ("통과" if all(c[1] for c in checks) else "불통과"), checks, strength


NAMES = {"resil": "버티는 힘(덜 빠짐)", "rebound": "반등 속도", "beta": "베타(큰 놈)", "volsurge": "거래량 급증",
         "mom": "12-1 모멘텀", "above50": "50일선 위 거리", "composite": "⭐ 종합(반등+모멘텀+50일선)"}


def write_report(episodes, frs, notes, spy, vol):
    os.makedirs(OUT, exist_ok=True)
    today = dt.date.today().isoformat()
    pvals = random_pvalues(episodes, frs)
    v, checks, strength = verdict(episodes, pvals)
    L = []
    if MOCK:
        L.append("> ⚠️ **합성(가짜) 데이터로 코드만 점검한 결과 — 숫자는 아무 의미 없음**\n")
    L += [f"# 🌄 반등 리더 백테스트 ({today})", "",
          f"## 🏁 자동 판정(⭐종합): **{v}**" + (f" ({strength})" if v == "통과" else ""), "",
          "> 합류 판정은 ⭐종합 하나만 본다(미리 정함). 아래 기준은 결과를 보기 전에 코드에 고정돼 있었다.", "",
          "| 기준 | 결과 | 값 |", "|---|:---:|---|"]
    for name, ok, det in checks:
        L.append(f"| {name} | {'✅' if ok else '❌'} | {det} |")
    L += ["", "## 🔒 데이터 신뢰 점검", ""] + [f"- {x}" for x in notes]
    kl = known_low_check(spy, vol)
    if kl:
        got = sum(1 for _, s in kl if s)
        L += [f"- 알려진 시장 저점 {len(kl)}개 중 {got}개에서 저점 후 30거래일 안에 신호가 잡힘 (신호 감지기 점검용)",
              "  - " + " · ".join(f"{d}→{s or '없음'}" for d, s in kl)]
    L += ["", "> 기록 전용 · 매수 추천 아님. 규칙은 실행 전에 고정했고 결과를 보고 바꾸지 않았다.",
          f"> 저점 신호 = SPY -10% 이상 하락 뒤 팔로우스루(저점 {FTD_MIN}~{FTD_MAX}일, +{FTD_RET*100:.1f}%·거래량↑) · 진입 = 신호 다음날 종가 · lift = 특징 상위 20% 평균 − 유니버스 평균 (%p)",
          f"> ⚠️ 에피소드 **{len(episodes)}개**" + (" (표본 30 미만 → 단정 금지, 참고만)" if len(episodes) < 30 else "")
          + " · 유니버스는 '지금 살아 있는' 대형주라 생존 편향 → 절대 수익이 아니라 lift만 본다 · 7개 특징을 동시에 시험했으니 p ≤ 0.007이면 '강'.", ""]
    for h in HORIZONS:
        L += [f"## 특징별 성적 — 신호 후 {h}거래일", "",
              "| 특징 | 에피소드 | 평균 lift | 중앙값 | 이긴 비율 | 최악 | 무작위 대비 p |", "|---|---:|---:|---:|---:|---:|---:|"]
        for fac, r in summarize(episodes, h).items():
            L.append(f"| {NAMES[fac]} | {r['n']} | {r['mean']:+.1f} | {r['median']:+.1f} | {r['hit']:.0f}% | {r['worst']:+.1f} | {pvals.get(fac, {}).get(h, float('nan')):.3f} |")
        L.append("")
    L += ["## 전반부 vs 후반부 (⭐종합, 60일)", "", "| 구간 | 에피소드 | 평균 lift | 이긴 비율 |", "|---|---:|---:|---:|"]
    for name, fn in (("2006~2015", lambda e: pd.Timestamp(e["signal"]) < SPLIT), ("2016~", lambda e: pd.Timestamp(e["signal"]) >= SPLIT)):
        r = summarize(episodes, 60, fn).get("composite")
        L.append(f"| {name} | {r['n']} | {r['mean']:+.1f} | {r['hit']:.0f}% |" if r else f"| {name} | 0 | - | - |")
    L += ["", "## 에피소드별 (60거래일)", "",
          "| 신호일 | SPY 낙폭 | 종목수 | SPY 60일 | 유니버스 60일 | ⭐종합 lift | 종합 상위 5 (60일 수익%) |", "|---|---:|---:|---:|---:|---:|---|"]
    for e in episodes:
        f60 = e["fwd"].get(60)
        lf = e["lift"].get("composite", {}).get(60)
        top5 = " · ".join(f"{x['t']} {x['ret60']:+.0f}" for x in e["top5"]) if e["top5"] else "(60일 미경과)"
        if f60 and lf is not None:
            L.append(f"| {e['signal']} | {e['spy_dd_pct']}% | {e['n_stocks']} | {f60['spy']:+.1f}% | {f60['universe']:+.1f}% | {lf:+.1f} | {top5} |")
        else:
            L.append(f"| {e['signal']} | {e['spy_dd_pct']}% | {e['n_stocks']} | - | - | - | {top5} |")
    L += ["", "## 팀장님이 보신 종목은 신호일에 몇 등이었나 (⭐종합 순위, 작을수록 상위)", "",
          "| 신호일 | " + " | ".join(WATCH) + " |", "|---|" + "---:|" * len(WATCH)]
    for e in episodes[-6:]:
        L.append(f"| {e['signal']} | " + " | ".join(str(e["watch_rank"].get(w, "-")) for w in WATCH) + " |")
    path = f"{OUT}/backtest_{today}.md"
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump({"asof": today, "verdict": v, "strength": strength, "checks": [[a, b, c] for a, b, c in checks], "notes": notes,
               "episodes": episodes, "pvalues": pvals}, open(f"{OUT}/backtest_{today}.json", "w"), ensure_ascii=False, indent=1, default=float)
    print(f"✅ 저장: {path} · 판정 {v} ({strength})")


# ───────────────────────── 라이브 ─────────────────────────
def run_live(C, V):
    os.makedirs(OUT, exist_ok=True)
    spy = C["SPY"]
    state, info = regime_now(spy, V["SPY"])
    asof = str(spy.index[-1].date())
    json.dump({"asof": asof, "regime": state, **info}, open(f"{OUT}/status.json", "w"), ensure_ascii=False)
    L = [f"# 🌄 반등 리더 — 오늘 상태 ({asof})", "", f"- 시장: **{state}** · {json.dumps(info, ensure_ascii=False)}"]
    if state != "none":
        sigs = find_signals(spy, V["SPY"])
        if state == "confirmed" and sigs:
            i, low_i, peak_i = sigs[-1]
            f = features(C.iloc[:i + 1], V.iloc[:i + 1], low_i, peak_i)
        else:
            c = spy.values
            low_i = int(np.argmin(c[-130:])) + len(c) - 130
            lo = max(0, low_i - 252)
            peak_i = lo + int(np.argmax(c[lo:low_i + 1]))
            f = features(C, V, low_i, peak_i)
        L += ["", "## ⭐ 종합 상위 10", "", "| 순위 | 티커 | 반등 | 12-1 모멘텀 | 50일선 위 | 거래량 | 베타 |", "|---:|---|---:|---:|---:|---:|---:|"]
        for k, (t, r) in enumerate(f.sort_values("composite", ascending=False).head(10).iterrows(), 1):
            L.append(f"| {k} | [{t}](https://finviz.com/quote.ashx?t={t}&p=w) | {r.rebound*100:+.0f}% | {r.mom*100:+.0f}% | {r.above50*100:+.0f}% | {r.volsurge:.1f}x | {r.beta:.1f} |")
    L += ["", "> 기록 전용 · 매수 추천 아님."]
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"✅ 상태 {state} · {OUT}/latest.md")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "backtest"
    C, V = load_prices(UNIVERSE)
    C, V, notes = data_gate(C, V, UNIVERSE)
    if mode == "live":
        run_live(C, V)
    else:
        eps, frs = run_backtest(C, V)
        if not eps:
            sys.exit("❌ 에피소드 0개 — 저장하지 않는다")
        write_report(eps, frs, notes, C["SPY"], V["SPY"])
