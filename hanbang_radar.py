"""
🎯 한 방 레이더 (매일, 뉴욕 장 마감 후) — 이동평균 없이 가격·거래량만 본다
1) 🟢 공포 속 기회: 시총 $10B+ 중 52주 고점 대비 -35% 이하로 빠졌는데, 매도가 마르고(하락일 거래량 감소)
   저점이 덜 내려가고, 최근 지수만큼은 버티는 종목 → 좋은 회사가 과한 공포에 빠졌을 수 있는 자리
2) 🧲 매집 흔적 점수(0~10): 오른 날 거래량 > 내린 날 거래량 · 하락일 거래량 감소 · 지수 하락일에 선방 · 종가가 하루 범위 위쪽
3) ⭐ 워치리스트 상태: 1군·2군 전부의 고점 대비·지수 대비·🧲
결과: hanbang/radar/latest.md · latest.json · YYYY-MM-DD.md (Claude 매일 심사가 읽음)
"""
import json, os
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from jb_scanner import get_large_caps, get_watchlist, download_daily, yf_symbol

OUT = "hanbang/radar"
FEAR_DD = -35.0          # 52주 고점 대비 이 %보다 더 빠지면 공포 후보
MIN_DOLLAR_VOL = 50_000_000
FEAR_SHOW = 12


def read_watchlist():
    t1, t2, tier = [], [], 1
    if os.path.exists("watchlist.txt"):
        for line in open("watchlist.txt", encoding="utf-8"):
            if line.strip().startswith("# ⭐ 2군"):
                tier = 2
            s = line.split("#")[0].strip().upper()
            if s:
                (t1 if tier == 1 else t2).append(yf_symbol(s))
    return t1, t2


def tracked():
    out = {}
    try:
        for r in json.load(open("top3/follow/latest.json", encoding="utf-8"))["rows"]:
            out[yf_symbol(r["ticker"])] = "🧭김종봉" if r.get("src") == "J" else "🏆Top3"
    except Exception as e:
        print(f"Top3 추적 읽기 실패: {e}")
    return out


def accumulation(c, h, l, v, q):
    """🧲 매집 흔적 0~10 + 세부. 최근 50거래일."""
    c, h, l, v, q = [x.dropna().iloc[-60:] for x in (c, h, l, v, q)]
    idx = c.index.intersection(v.index).intersection(q.index).intersection(h.index).intersection(l.index)
    if len(idx) < 40:
        return None
    c, h, l, v, q = c[idx], h[idx], l[idx], v[idx], q[idx]
    r, qr = c.pct_change(), q.pct_change()
    w = slice(-50, None)
    upv, dnv = v[w][r[w] > 0].sum(), v[w][r[w] < 0].sum()
    udr = upv / dnv if dnv else 2.0
    dn = v[r < 0]
    dry = (dn.iloc[-5:].mean() / dn.iloc[-15:-5].mean()) if len(dn) >= 15 and dn.iloc[-15:-5].mean() else 1.0
    qd = qr[-20:] < -0.005
    beat = float((r[-20:][qd] > qr[-20:][qd]).mean()) if qd.sum() else 0.5
    rng = (h - l).replace(0, np.nan)
    clv = float(((c - l) / rng).iloc[-10:].mean())
    s = 0
    s += 3 if udr >= 1.3 else 2 if udr >= 1.1 else 1 if udr >= 0.95 else 0
    s += 2 if dry <= 0.75 else 1 if dry <= 0.95 else 0
    s += 3 if beat >= 0.7 else 2 if beat >= 0.55 else 1 if beat >= 0.4 else 0
    s += 2 if clv >= 0.6 else 1 if clv >= 0.5 else 0
    return dict(score=int(s), udr=round(float(udr), 2), dry=round(float(dry), 2), beat=round(beat, 2),
                clv=round(clv if clv == clv else 0.5, 2), qd_days=int(qd.sum()))


def fundamentals(t):
    try:
        i = yf.Ticker(t).info
    except Exception:
        return {}
    g = lambda k: i.get(k)
    return dict(pm=g("profitMargins"), rev=g("revenueGrowth"), eq=g("earningsQuarterlyGrowth"),
                fpe=g("forwardPE"), cap=g("marketCap"), name=g("shortName") or "")


def ftxt(f):
    if not f:
        return "—"
    parts = []
    pm = f.get("pm")
    if pm is not None:
        parts.append("흑자" if pm > 0 else "적자")
    if f.get("rev") is not None:
        parts.append(f"매출 {f['rev'] * 100:+.0f}%")
    if f.get("eq") is not None:
        parts.append(f"순이익(분기) {f['eq'] * 100:+.0f}%")
    return " · ".join(parts) or "—"


def fvl(t):
    return f"[{t}](https://finviz.com/quote.ashx?t={t.replace('-', '.')}&p=w)"


def main():
    os.makedirs(OUT, exist_ok=True)
    large = get_large_caps()
    t1, t2 = read_watchlist()
    tr = tracked()
    universe = set(large) | set(t1) | set(t2) | set(tr) | {"QQQ"}
    print(f"검사 대상 {len(universe)}개")
    d = download_daily(universe, period="1y")
    C, H, L, V = d["Close"], d["High"], d["Low"], d["Volume"]
    q = C["QQQ"].dropna()
    ny = q.index[-1].strftime("%Y-%m-%d")

    def stats(t):
        if t not in C.columns:
            return None
        c = C[t].dropna()
        if len(c) < 120 or c.index[-1] != q.index[-1]:
            return None
        hi = c.iloc[-252:].max()
        dd = (c.iloc[-1] / hi - 1) * 100
        r10 = (c.iloc[-1] / c.iloc[-11] - 1) * 100
        q10 = (q.iloc[-1] / q.iloc[-11] - 1) * 100
        r63 = (c.iloc[-1] / c.iloc[-64] - 1) * 100
        q63 = (q.iloc[-1] / q.iloc[-64] - 1) * 100
        lows_hold = c.iloc[-5:].min() >= c.iloc[-15:-5].min() * 0.97
        dv = float((c.iloc[-20:] * V[t].reindex(c.index).iloc[-20:]).mean())
        acc = accumulation(c, H[t], L[t], V[t], q)
        return dict(ticker=t, close=round(float(c.iloc[-1]), 2), dd=round(float(dd), 1), vs10=round(float(r10 - q10), 1),
                    vs63=round(float(r63 - q63), 1), lows_hold=bool(lows_hold), dollar_vol=dv, acc=acc)

    # 🟢 공포 속 기회
    fear = []
    for t in large:
        s = stats(t)
        if not s or not s["acc"] or s["dd"] > FEAR_DD or s["dollar_vol"] < MIN_DOLLAR_VOL:
            continue
        a = s["acc"]
        ok = (a["dry"] <= 0.95) + s["lows_hold"] + (s["vs10"] >= -2)
        if ok >= 2:
            s["fear_ok"] = int(ok)
            fear.append(s)
    fear.sort(key=lambda s: (-(s["acc"]["score"] + s["fear_ok"]), s["dd"]))
    fear = fear[:FEAR_SHOW]
    for s in fear:
        s["f"] = fundamentals(s["ticker"])
    # ⭐ 워치리스트
    wl = []
    for tier, lst in ((1, t1), (2, t2)):
        for t in lst:
            s = stats(t)
            if s:
                s["tier"] = tier
                wl.append(s)
    # 🧲 추적 종목 매집 흔적
    trk = []
    for t, src in tr.items():
        s = stats(t)
        if s and s["acc"]:
            s["src"] = src
            trk.append(s)
    trk.sort(key=lambda s: -s["acc"]["score"])

    def acc_txt(a):
        return f"{a['score']}/10" if a else "—"

    md = f"# 🎯 한 방 레이더 — {ny} (뉴욕 종가)\n\n"
    md += "> 가격·거래량만 본다 (이동평균 없음). 🧲 매집 흔적 = 오른 날 거래량>내린 날 · 하락일 거래량 감소 · 지수 하락일에 선방 · 종가가 하루 범위 위쪽 (0~10)\n"
    md += "> 매수 추천이 아니다. Claude 매일 심사가 이 표를 보고 떡밥·숫자·촉매를 붙여 카드로 만든다.\n\n"
    md += f"## 🟢 공포 속 기회 후보 (52주 고점 대비 {FEAR_DD:.0f}%↓ + 매도가 마르는 흔적)\n"
    if fear:
        md += "| 티커 | 고점 대비 | 🧲 | 최근 10일 지수 대비 | 저점 방어 | 하락일 거래량 | 숫자 |\n| :--- | ---: | ---: | ---: | :---: | ---: | :--- |\n"
        for s in fear:
            a = s["acc"]
            md += (f"| {fvl(s['ticker'])} | {s['dd']:+.0f}% | {acc_txt(a)} | {s['vs10']:+.1f}%p | {'✅' if s['lows_hold'] else '—'} | "
                   f"{(a['dry'] - 1) * 100:+.0f}% | {ftxt(s.get('f'))} |\n")
    else:
        md += "- 오늘은 없음\n"
    md += "\n## ⭐ 워치리스트 상태\n| 군 | 티커 | 고점 대비 | 3개월 지수 대비 | 🧲 | 신호 |\n| :---: | :--- | ---: | ---: | ---: | :--- |\n"
    for s in sorted(wl, key=lambda s: (s["tier"], s["dd"])):
        a = s["acc"]
        sig = []
        if s["dd"] <= FEAR_DD:
            sig.append("🟢 크게 빠짐")
        if a and a["score"] >= 7:
            sig.append("🧲 매집 흔적 강함")
        if s["vs63"] >= 15:
            sig.append("🔥 지수보다 강함")
        md += f"| {s['tier']} | {fvl(s['ticker'])} | {s['dd']:+.0f}% | {s['vs63']:+.0f}%p | {acc_txt(a)} | {' '.join(sig)} |\n"
    md += "\n## 🧲 추적 중인 종목 (Top 3·김종봉) 매집 흔적 상위\n"
    if trk:
        md += "| 티커 | 출처 | 🧲 | 고점 대비 | 3개월 지수 대비 |\n| :--- | :--- | ---: | ---: | ---: |\n"
        for s in trk[:12]:
            md += f"| {fvl(s['ticker'])} | {s['src']} | {acc_txt(s['acc'])} | {s['dd']:+.0f}% | {s['vs63']:+.0f}%p |\n"
    else:
        md += "- 없음\n"
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    open(f"{OUT}/{ny}.md", "w", encoding="utf-8").write(md)
    clean = lambda L: [{k: v for k, v in s.items() if k != "dollar_vol"} for s in L]
    json.dump(dict(ny_date=ny, fear=clean(fear), watchlist=clean(wl), tracked=clean(trk),
                   generated_utc=datetime.now(timezone.utc).isoformat()),
              open(f"{OUT}/latest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(md)


if __name__ == "__main__":
    main()
