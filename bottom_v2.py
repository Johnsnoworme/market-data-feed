"""
🌄 반등 리더 v2 백테스트 — 저점 신호 개선 + '그룹(섹터 ETF)' 단위 시험 (기록 전용 · 매수 추천 아님)

1차(bottom_leaders.py) 결과: 개별 종목 ⭐종합 불통과, 2026-03 저점은 SPY -8.4%라 신호가 안 잡힘.
v2는 그 결과를 본 뒤 만든 후보이므로, **개발구간/시험구간을 나눠서** 과적합을 막는다.

──────────── 미리 정한 약속 (결과를 보기 전에 코드에 고정) ────────────
① 구간: 개발 2006~2015 · 시험 2016~현재. 규칙 선택은 개발구간만 본다. 시험구간은 선택 후 그대로 적용.
② 저점 신호 변형(둘뿐):
     A = SPY가 52주 고점 대비 -10% 이하 → 저점 4~25일 사이 팔로우스루(+1.5%·거래량↑)
     B = SPY 또는 QQQ가 -8% 이하 → 같은 팔로우스루 (그 지수 기준), 신호 사이 40거래일 이상
   선택 규칙: 개발구간의 '알려진 저점 6개' 중 30거래일 안에 신호가 더 많이 잡힌 쪽. 동률이면 A(더 단순).
③ 그룹 유니버스(고정 10개): XLK XLF XLE XLV XLY XLP XLI XLB XLU SMH  — 개별 종목은 쓰지 않는다
   (오늘의 승자로 목록을 만들면 생존 편향. 종목 단계는 앞으로의 그림자 기록으로만 검증).
④ 신호일 T에 그룹별 특징을 T까지의 데이터로만 계산: resil · rebound · beta · mom(12-1) · above50
   ⭐composite = rebound · mom · above50 퍼센타일 평균. **합류 판정 대상(사전 지정) = composite, beta 두 개**
⑤ 평가: 상위 3개 평균 수익 − 10개 평균 수익(lift), 진입 = T 다음날 종가, 20·60거래일.
⑥ 자동 판정(대상별, 모두 만족해야 '통과'):
     전체: 20·60일 평균·중앙값 > 0 · 이긴 비율 ≥ 65%(20·60일 모두) · 60일 최악 ≥ -15%p · 에피소드 ≥ 10
     개발구간 60일 평균 > 0
     시험구간 60일: 에피소드 ≥ 5 · 평균 > 0 · 중앙값 > 0 · 이긴 비율 ≥ 60% · 무작위 대비 p ≤ 0.10
     전체 60일 무작위 대비 p ≤ 0.025 (사전 지정 대상이 2개라 0.05/2)
⑦ 데이터 신뢰 게이트(하나라도 실패하면 저장하지 않고 중단): 12개 시세 모두 5,400거래일 이상,
   알려진 낙폭 대조 3개, 하루 ±70% 이상 움직임 점검, 2차 출처 교차검증(접속될 때만, 실패 사유를 적는다).

실행: python bottom_v2.py  → research/bottom_leaders/v2_backtest_YYYY-MM-DD.md/.json
      BT_MOCK=1 python bottom_v2.py → 합성 데이터로 코드만 점검(mock_out/, 숫자 의미 없음)
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
START, BT_FROM = "2004-06-01", "2006-01-01"
SPLIT = pd.Timestamp("2016-01-01")
FTD_MIN, FTD_MAX, FTD_RET, SIGNAL_GAP = 4, 25, 0.015, 40
HORIZONS = (20, 60)
K = 3
N_SIMS = 4000
ETFS = "XLK XLF XLE XLV XLY XLP XLI XLB XLU SMH".split()
INDEXES = ["SPY", "QQQ"]
FACTORS = ["resil", "rebound", "beta", "mom", "above50", "composite"]
PRIMARY = ["composite", "beta"]
DEV_LOWS = ["2008-11-20", "2009-03-09", "2010-07-02", "2011-10-03", "2012-06-01", "2015-08-25"]
HOLD_LOWS = ["2016-02-11", "2018-12-24", "2020-03-23", "2022-10-12", "2023-10-27", "2025-04-08"]
ANCHORS = [("2007-10-09", "2009-03-09", -60, -50), ("2020-02-19", "2020-03-23", -37, -31), ("2022-01-03", "2022-10-12", -29, -22)]
NAMES = {"resil": "버티는 힘", "rebound": "반등 속도", "beta": "베타", "mom": "12-1 모멘텀", "above50": "50일선 위", "composite": "⭐종합"}
GROUP = {"XLK": "기술", "XLF": "금융", "XLE": "에너지", "XLV": "헬스케어", "XLY": "경기소비", "XLP": "필수소비", "XLI": "산업재",
         "XLB": "소재", "XLU": "유틸리티", "SMH": "반도체"}


# ───────────────────────── 데이터 ─────────────────────────
def _mock():
    rng = np.random.default_rng(11)
    idx = pd.bdate_range(START, "2026-11-13")
    n = len(idx)
    m = rng.normal(0.0004, 0.009, n)
    for s in (900, 1500, 2300, 3100, 3900, 4700, 5300):
        m[s:s + 40] = rng.normal(-0.012, 0.012, 40)
        m[s + 40:s + 60] = rng.normal(0.014, 0.012, 20)
    spy = 100 * np.cumprod(1 + m)
    up = np.r_[0, np.diff(spy)] > 0
    C, V = {"SPY": spy}, {"SPY": rng.integers(50, 100, n) * (1 + 0.5 * up)}
    C["QQQ"] = 50 * np.cumprod(1 + 1.2 * m + rng.normal(0, 0.004, n))
    V["QQQ"] = rng.integers(50, 100, n) * (1 + 0.5 * up)
    for t in ETFS:
        C[t] = 30 * np.cumprod(1 + rng.uniform(0.6, 1.8) * m + rng.normal(0.0001, 0.006, n))
        V[t] = rng.integers(10, 100, n)
    return pd.DataFrame(C, index=idx), pd.DataFrame(V, index=idx)


def load():
    if MOCK:
        return _mock()
    import yfinance as yf
    allt = INDEXES + ETFS
    df = None
    for attempt in range(3):
        try:
            df = yf.download(allt, start=START, auto_adjust=True, progress=False, threads=True, group_by="column")
            if df is not None and len(df) > 0:
                break
        except Exception as e:  # noqa
            print(f"   다운로드 {attempt + 1}/3 실패: {e}")
        time.sleep(5 * (attempt + 1))
    if df is None or len(df) == 0:
        sys.exit("❌ 가격 데이터를 못 받았다 — 저장하지 않는다")
    return df["Close"].sort_index(), df["Volume"].sort_index()


def gate(C):
    notes = []
    for t in INDEXES + ETFS:
        if t not in C.columns or C[t].notna().sum() < 5400:
            sys.exit(f"❌ {t} 데이터가 5,400거래일 미만 — 저장하지 않는다")
    notes.append(f"시세 {len(INDEXES) + len(ETFS)}개 모두 5,400거래일 이상")
    if not MOCK:
        spy = C["SPY"].dropna()
        for a, b, lo, hi in ANCHORS:
            if a not in spy.index or b not in spy.index:
                sys.exit(f"❌ 알려진 날짜 {a} 또는 {b} 없음 — 저장하지 않는다")
            dd = (spy.loc[b] / spy.loc[a] - 1) * 100
            if not (lo <= dd <= hi):
                sys.exit(f"❌ 데이터 이상: SPY {a}→{b} 낙폭 {dd:.1f}% (정상 {lo}~{hi}%) — 저장하지 않는다")
            notes.append(f"✅ SPY {a}→{b} 낙폭 {dd:.1f}% (정상 {lo}~{hi}%)")
    r = C[INDEXES + ETFS].pct_change(fill_method=None).abs()
    bad = [t for t in INDEXES + ETFS if (r[t] > 0.70).any()]
    if bad:
        sys.exit("❌ 하루 ±70% 넘는 움직임(데이터 오류 의심): " + ", ".join(bad) + " — 저장하지 않는다")
    notes.append("✅ 하루 ±70% 넘는 움직임 없음")
    notes.append(cross_check())
    return notes


def cross_check():
    if MOCK:
        return "교차검증: (합성 데이터 — 해당 없음)"
    try:
        import requests
        import yfinance as yf
        worst, n_ok = 0.0, 0
        dates = ["2008-09-15", "2009-03-09", "2013-05-15", "2018-12-24", "2020-03-23", "2022-10-12"]
        for t in ("SPY", "QQQ", "XLE"):
            raw = yf.download(t, start="2008-01-01", auto_adjust=False, progress=False)["Close"]
            raw = raw.iloc[:, 0] if isinstance(raw, pd.DataFrame) else raw
            s = requests.get(f"https://stooq.com/q/d/l/?s={t.lower()}.us&i=d", timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            if "Date" not in s.text[:200]:
                return f"⚠️ 교차검증 못 함 — Stooq가 가격 대신 다른 응답을 줌({s.text[:60]!r}) · 단일 출처(Yahoo)"
            st = pd.read_csv(io.StringIO(s.text), parse_dates=["Date"], index_col="Date")["Close"]
            for d in dates:
                d = pd.Timestamp(d)
                if d in raw.index and d in st.index:
                    worst, n_ok = max(worst, float(abs(raw.loc[d] / st.loc[d] - 1) * 100)), n_ok + 1
        if n_ok < 10:
            return f"⚠️ 교차검증 못 함(비교 {n_ok}건뿐) — 단일 출처(Yahoo)"
        if worst > 0.7:
            sys.exit(f"❌ Yahoo와 Stooq 종가가 {worst:.2f}% 다름(허용 0.7%) — 저장하지 않는다")
        return f"✅ 2차 출처(Stooq) 교차검증 {n_ok}건 · 최대 차이 {worst:.2f}%"
    except SystemExit:
        raise
    except Exception as e:  # noqa
        return f"⚠️ 교차검증 못 함({type(e).__name__}: {str(e)[:60]}) — 단일 출처(Yahoo)"


# ───────────────────────── 저점 신호 ─────────────────────────
def find_signals(close, vol, thr):
    c, v = close.values, vol.values
    n = len(c)
    roll_high = close.rolling(252, min_periods=60).max().values
    ret = np.r_[np.nan, c[1:] / c[:-1] - 1]
    sigs, in_corr, low_i, last = [], False, None, -10**9
    for i in range(n):
        dd = c[i] / roll_high[i] - 1 if not np.isnan(roll_high[i]) else 0
        if dd <= thr:
            if not in_corr:
                in_corr, low_i = True, i
            elif c[i] < c[low_i]:
                low_i = i
        if in_corr:
            if dd > thr / 2:
                in_corr, low_i = False, None
                continue
            d = i - low_i
            if FTD_MIN <= d <= FTD_MAX and ret[i] >= FTD_RET and v[i] > v[i - 1]:
                if i - last >= SIGNAL_GAP and close.index[i] >= pd.Timestamp(BT_FROM):
                    lo = max(0, low_i - 252)
                    sigs.append((i, low_i, lo + int(np.argmax(c[lo:low_i + 1]))))
                    last = i
                in_corr, low_i = False, None
    return sigs


def variant_signals(variant, C, V):
    if variant == "A":
        return [(i, l, p, "SPY") for i, l, p in find_signals(C["SPY"], V["SPY"], -0.10)]
    allsig = []
    for X in INDEXES:
        allsig += [(i, l, p, X) for i, l, p in find_signals(C[X], V[X], -0.08)]
    allsig.sort(key=lambda s: s[0])
    out, last = [], -10**9
    for s in allsig:
        if s[0] - last >= SIGNAL_GAP:
            out.append(s)
            last = s[0]
    return out


def coverage(sigs, idx, lows):
    sd = [idx[s[0]] for s in sigs]
    res = []
    for d in lows:
        d0 = pd.Timestamp(d)
        if d0 < idx[0] or d0 > idx[-1]:
            continue
        pos = idx.searchsorted(d0)
        hit = [s for s in sd if 0 <= idx.searchsorted(s) - pos <= 30]
        res.append((d, str(hit[0].date()) if hit else None))
    return res


# ───────────────────────── 그룹 특징 (T까지만) ─────────────────────────
def feats(Cp, bench, low_i, peak_i):
    cols = [t for t in ETFS if Cp[t].iloc[-253:].notna().all()]
    last = len(Cp) - 1
    f = pd.DataFrame(index=cols)
    f["resil"] = Cp[cols].iloc[low_i] / Cp[cols].iloc[peak_i] - 1 - (bench.iloc[low_i] / bench.iloc[peak_i] - 1)
    f["rebound"] = Cp[cols].iloc[last] / Cp[cols].iloc[low_i] - 1 - (bench.iloc[last] / bench.iloc[low_i] - 1)
    r = Cp[cols].pct_change(fill_method=None).iloc[-252:]
    b = bench.pct_change(fill_method=None).iloc[-252:]
    bm = b - b.mean()
    f["beta"] = ((r - r.mean()).mul(bm, axis=0)).sum() / (bm ** 2).sum()
    f["mom"] = Cp[cols].iloc[-22] / Cp[cols].iloc[-253] - 1
    f["above50"] = Cp[cols].iloc[-1] / Cp[cols].iloc[-50:].mean() - 1
    f = f.replace([np.inf, -np.inf], np.nan).dropna()
    f["composite"] = f[["rebound", "mom", "above50"]].rank(pct=True).mean(axis=1)
    return f


def run(C, V, sigs):
    n = len(C)
    eps, frs = [], {}
    for (i, low_i, peak_i, X) in sigs:
        if i < 260:
            continue
        f = feats(C.iloc[:i + 1], C[X].iloc[:i + 1], low_i, peak_i)   # ← 미래 잘라냄
        if len(f) < 8:
            continue
        ep = {"signal": str(C.index[i].date()), "low": str(C.index[low_i].date()), "index": X,
              "dd_pct": round((C[X].iloc[low_i] / C[X].iloc[peak_i] - 1) * 100, 1), "lift": {}, "top3": [], "fwd": {}}
        for h in HORIZONS:
            if i + 1 + h >= n:
                continue
            fr = (C.iloc[i + 1 + h] / C.iloc[i + 1] - 1)[f.index].dropna()
            if len(fr) < 8:
                continue
            frs[(ep["signal"], h)] = fr
            ep["fwd"][h] = {"bench": round((C[X].iloc[i + 1 + h] / C[X].iloc[i + 1] - 1) * 100, 1), "groups": round(fr.mean() * 100, 1)}
            for fac in FACTORS:
                top = f.loc[fr.index, fac].nlargest(K).index
                ep["lift"].setdefault(fac, {})[h] = float((fr[top].mean() - fr.mean()) * 100)
            if h == 60:
                ep["top3"] = [{"g": GROUP[t], "ret60": round(float(fr[t]) * 100, 1)} for t in f["composite"].nlargest(3).index if t in fr.index]
        eps.append(ep)
    return eps, frs


def summ(eps, fac, h, fn=None):
    v = [e["lift"][fac][h] for e in eps if (fn is None or fn(e)) and fac in e["lift"] and h in e["lift"][fac]]
    if not v:
        return None
    return {"n": len(v), "mean": float(np.mean(v)), "median": float(np.median(v)), "hit": 100 * float(np.mean([x > 0 for x in v])), "worst": float(min(v))}


def sims_by_episode(eps, frs):
    rng = np.random.default_rng(2026)
    out = {}
    for e in eps:
        for h in HORIZONS:
            if (e["signal"], h) not in frs:
                continue
            fr = frs[(e["signal"], h)].values
            m, k = len(fr), min(K, len(fr))
            R = rng.random((N_SIMS, m))
            idx = np.argpartition(-R, k - 1, axis=1)[:, :k]
            out[(e["signal"], h)] = (fr[idx].mean(axis=1) - fr.mean()) * 100
    return out


def pval(eps, sims, fac, h, fn=None):
    used = [e for e in eps if (fn is None or fn(e)) and (e["signal"], h) in sims and h in e["lift"].get(fac, {})]
    if not used:
        return float("nan")
    avg = np.mean([sims[(e["signal"], h)] for e in used], axis=0)
    obs = np.mean([e["lift"][fac][h] for e in used])
    return float((avg >= obs).mean())


def in_hold(e):
    return pd.Timestamp(e["signal"]) >= SPLIT


def in_dev(e):
    return pd.Timestamp(e["signal"]) < SPLIT


def verdict(eps, sims, fac):
    s20, s60 = summ(eps, fac, 20), summ(eps, fac, 60)
    d, hd = summ(eps, fac, 60, in_dev), summ(eps, fac, 60, in_hold)
    p_all, p_hold = pval(eps, sims, fac, 60), pval(eps, sims, fac, 60, in_hold)
    if not s20 or not s60:
        return "불통과", [("에피소드 부족", False, "-")]
    ck = []
    def add(n, ok, det): ck.append((n, bool(ok), det))
    add("전체 20일 평균·중앙값 > 0", s20["mean"] > 0 and s20["median"] > 0, f"{s20['mean']:+.1f} · {s20['median']:+.1f}")
    add("전체 60일 평균·중앙값 > 0", s60["mean"] > 0 and s60["median"] > 0, f"{s60['mean']:+.1f} · {s60['median']:+.1f}")
    add("이긴 비율 ≥ 65% (20·60일)", s20["hit"] >= 65 and s60["hit"] >= 65, f"{s20['hit']:.0f}% · {s60['hit']:.0f}%")
    add("60일 최악 ≥ -15%p", s60["worst"] >= -15, f"{s60['worst']:+.1f}")
    add("에피소드 ≥ 10", s60["n"] >= 10, f"{s60['n']}개")
    add("개발구간 60일 평균 > 0", bool(d) and d["mean"] > 0, f"{d['mean']:+.1f} ({d['n']}개)" if d else "없음")
    add("시험구간 에피소드 ≥ 5", bool(hd) and hd["n"] >= 5, f"{hd['n']}개" if hd else "없음")
    add("시험구간 60일 평균·중앙값 > 0", bool(hd) and hd["mean"] > 0 and hd["median"] > 0, f"{hd['mean']:+.1f} · {hd['median']:+.1f}" if hd else "-")
    add("시험구간 이긴 비율 ≥ 60%", bool(hd) and hd["hit"] >= 60, f"{hd['hit']:.0f}%" if hd else "-")
    add("시험구간 무작위 대비 p ≤ 0.10", p_hold <= 0.10, f"p = {p_hold:.3f}")
    add("전체 60일 무작위 대비 p ≤ 0.025", p_all <= 0.025, f"p = {p_all:.4f}")
    return ("통과" if all(c[1] for c in ck) else "불통과"), ck


def main():
    C, V = load()
    notes = gate(C)
    idx = C.index
    vs = {v: variant_signals(v, C, V) for v in ("A", "B")}
    covd = {v: coverage(vs[v], idx, DEV_LOWS) for v in vs}
    covh = {v: coverage(vs[v], idx, HOLD_LOWS) for v in vs}
    nd = {v: sum(1 for _, s in covd[v] if s) for v in vs}
    chosen = "B" if nd["B"] > nd["A"] else "A"
    eps, frs = run(C, V, vs[chosen])
    if not eps:
        sys.exit("❌ 에피소드 0개 — 저장하지 않는다")
    sims = sims_by_episode(eps, frs)
    today = dt.date.today().isoformat()
    res = {f: verdict(eps, sims, f) for f in PRIMARY}
    os.makedirs(OUT, exist_ok=True)
    L = []
    if MOCK:
        L.append("> ⚠️ **합성(가짜) 데이터로 코드만 점검 — 숫자는 아무 의미 없음**\n")
    L += [f"# 🌄 v2 백테스트 — 그룹(섹터 ETF) 단위 ({today})", "",
          "## 🏁 자동 판정 (사전 지정 2개)", "", "| 대상 | 판정 |", "|---|---|"]
    for f in PRIMARY:
        L.append(f"| {NAMES[f]} | **{res[f][0]}** |")
    L += ["", "> 규칙·기준은 결과를 보기 전에 코드에 고정. 개발구간(2006~2015)에서 규칙을 고르고 시험구간(2016~)은 그대로 적용.", ""]
    for f in PRIMARY:
        L += [f"### {NAMES[f]} — {res[f][0]}", "", "| 기준 | 결과 | 값 |", "|---|:---:|---|"]
        L += [f"| {n} | {'✅' if ok else '❌'} | {d} |" for n, ok, d in res[f][1]]
        L.append("")
    L += ["## 🔒 데이터 신뢰 점검", ""] + [f"- {x}" for x in notes] + [""]
    L += ["## 🎯 저점 신호 변형 선택 (개발구간 알려진 저점 6개만 보고 선택)", "",
          f"- A(SPY -10%): 개발 {nd['A']}/{len(covd['A'])} · 시험 {sum(1 for _, s in covh['A'] if s)}/{len(covh['A'])}",
          f"- B(SPY·QQQ -8%): 개발 {nd['B']}/{len(covd['B'])} · 시험 {sum(1 for _, s in covh['B'] if s)}/{len(covh['B'])}",
          f"- **선택: {chosen}**", "",
          "| 변형 | 알려진 저점 → 신호일 |", "|---|---|"]
    for v in vs:
        L.append(f"| {v} | " + " · ".join(f"{d}→{s or '없음'}" for d, s in covd[v] + covh[v]) + " |")
    s26 = {v: [str(idx[s[0]].date()) for s in vs[v] if pd.Timestamp("2026-03-15") <= idx[s[0]] <= pd.Timestamp("2026-05-31")] for v in vs}
    L += ["", f"- 2026-03 말 저점 사례(팀장님 사례): A 신호 {s26['A'] or '없음'} · B 신호 {s26['B'] or '없음'} (결과를 본 뒤가 아니라 참고용 표시)", ""]
    L += ["## 특징별 성적 (60일, 전체 · 개발 · 시험)", "", "| 특징 | 전체 평균 | 이긴 비율 | 개발 평균 | 시험 평균 | 시험 이긴 비율 | 전체 p |", "|---|---:|---:|---:|---:|---:|---:|"]
    for f in FACTORS:
        a, d, h = summ(eps, f, 60), summ(eps, f, 60, in_dev), summ(eps, f, 60, in_hold)
        if a:
            L.append(f"| {NAMES[f]}{' ⭐대상' if f in PRIMARY else ' (탐색)'} | {a['mean']:+.1f} | {a['hit']:.0f}% | "
                     f"{(str(round(d['mean'], 1)) if d else '-')} | {(str(round(h['mean'], 1)) if h else '-')} | {(str(round(h['hit'])) + '%' if h else '-')} | {pval(eps, sims, f, 60):.3f} |")
    L += ["", "## 에피소드별 (⭐종합 상위 3그룹의 60일 수익)", "", "| 신호일 | 지수 낙폭 | 기준지수 60일 | 10그룹 평균 60일 | ⭐종합 lift | 상위 3그룹 (60일 %) |", "|---|---:|---:|---:|---:|---|"]
    for e in eps:
        f60 = e["fwd"].get(60)
        lf = e["lift"].get("composite", {}).get(60)
        t3 = " · ".join(f"{x['g']} {x['ret60']:+.0f}" for x in e["top3"]) if e["top3"] else "(60일 미경과)"
        L.append(f"| {e['signal']} ({e['index']}) | {e['dd_pct']}% | " + (f"{f60['bench']:+.1f}% | {f60['groups']:+.1f}% | {lf:+.1f}" if f60 and lf is not None else "- | - | -") + f" | {t3} |")
    L += ["", f"> 에피소드 {len(eps)}개 (표본이 작다) · 그룹 10개 중 상위 3개를 고른 평균 − 10개 평균 · 기록 전용 · 매수 추천 아님. 개별 종목은 생존 편향 때문에 백테스트하지 않았다."]
    path = f"{OUT}/v2_backtest_{today}.md"
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump({"asof": today, "chosen": chosen, "verdict": {f: res[f][0] for f in PRIMARY}, "notes": notes,
               "episodes": eps}, open(f"{OUT}/v2_backtest_{today}.json", "w"), ensure_ascii=False, indent=1, default=float)
    print(f"✅ 저장: {path} · 신호 {chosen} · 판정 " + " / ".join(f"{NAMES[f]} {res[f][0]}" for f in PRIMARY))


if __name__ == "__main__":
    main()
