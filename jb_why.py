"""왜 안 걸렸나 + 최근 급등주 분석 + '먼저 고점 돌파' 변형 검증 (수동 실행)"""
import os
import pandas as pd
from jb_scanner import get_large_caps, get_watchlist, download_daily, pct, MA_WEEKS, MIN_DOLLAR_VOL_DAY, EXCLUDE_WORDS
from jb_original import legs, kim

OUT = "scanner/jb/compare"
ASK = ["BE", "PLTR", "HOOD", "MSTR", "TEM", "NVDA", "TSLA", "CRCL", "ORCL", "MU", "INTC", "AMD", "SNDK", "COIN"]


def fv(t):
    return f'[{t}](https://finviz.com/quote.ashx?p=w&t={t})'


def main():
    os.makedirs(OUT, exist_ok=True)
    large = get_large_caps()
    uni = sorted(set(large) | get_watchlist() | set(ASK))
    d = download_daily(set(uni) | {"QQQ"}, period="2y")
    wc = d["Close"].resample("W-FRI").last()
    dollar = (d["Close"] * d["Volume"]).resample("W-FRI").sum()
    days = d["Close"].resample("W-FRI").count()
    q = wc["QQQ"].dropna()
    L = legs(q)
    last = q.index[-1]
    rows = {}
    for t in uni:
        if t not in wc.columns:
            continue
        c = wc[t].dropna()
        if len(c) < 30 or c.index[-1] != last:
            continue
        name = large.get(t, ("", ""))[0]
        if any(w in name for w in EXCLUDE_WORDS):
            continue
        k = kim(c, q, L)
        if not k:
            continue
        dv = dollar[t].reindex(c.index).iloc[-4:].sum() / max(days[t].reindex(c.index).iloc[-4:].sum(), 1)
        ma = c.rolling(MA_WEEKS).mean().iloc[-1]
        fd = k["first_date"]
        since_first = pct(c.iloc[-1], c.loc[pd.Timestamp(fd)]) if fd else None
        rows[t] = dict(k, ticker=t, name=name[:24], liquid=dv >= MIN_DOLLAR_VOL_DAY, above_ma12=pct(c.iloc[-1], ma),
                       r2=pct(c.iloc[-1], c.iloc[-3]), r3=pct(c.iloc[-1], c.iloc[-4]), close=float(c.iloc[-1]),
                       first_px=float(c.loc[pd.Timestamp(fd)]) if fd else None, since_first=since_first)

    qd = (L["trough"] / L["peak"] - 1) * 100
    qu = (q.iloc[-1] / L["trough"] - 1) * 100
    def why(r):
        if r["pass"]:
            return "✅ 후보" + (" (이미 많이 오름 → 접힌 칸)" if r["above_ma12"] > 15 else "")
        if r["ex_down"] <= 0 and r["ex_up"] <= 0:
            return "❌ 더 빠지고 덜 오름"
        if r["ex_down"] <= 0:
            return "❌ 하락 구간에 나스닥보다 더 빠짐"
        return "❌ 반등 구간에 나스닥보다 덜 오름"
    H = "| 티커 | 하락 구간 (나스닥 %+.1f%%) | 반등 구간 (나스닥 %+.1f%%) | 12주선 대비 | 판정 | 🥇 먼저 고점 돌파 |\n| :--- | ---: | ---: | ---: | :--- | :--- |\n" % (qd, qu)
    def line(r, extra=""):
        fb = f"{r['first_date']} (${r['first_px']:.2f} → 지금 {r['since_first']:+.0f}%)" if r["first_date"] else "—"
        return f"| {fv(r['ticker'])} | {r['down']:+.1f}% | {r['up']:+.1f}% | {r['above_ma12']:+.0f}% | {why(r)} | {fb} |{extra}\n"
    md = f"# 왜 안 걸렸나 — {last.strftime('%Y-%m-%d')}\n\n> 나스닥 조정: {L['peak_d'].strftime('%m/%d')} → {L['trough_d'].strftime('%m/%d')} {qd:+.1f}%, 이후 {qu:+.1f}%\n\n"
    md += "## 관심 종목\n" + H + "".join(line(rows[t]) for t in ASK if t in rows)

    liq = [r for r in rows.values() if r["liquid"] and r["ticker"] in large]
    for key, lab in (("r3", "최근 3주"), ("r2", "최근 2주")):
        top = sorted(liq, key=lambda r: -r[key])[:20]
        caught = sum(r["pass"] for r in top)
        first = sum(bool(r["first_date"]) for r in top)
        md += f"\n## 🚀 {lab} 상승률 상위 20 (원본 후보였던 것 {caught}개 · 🥇 먼저 고점 돌파 {first}개)\n"
        md += H.replace("| 티커 |", f"| 티커 | {lab} |").replace("| :--- |", "| :--- | ---: |", 1)
        for r in top:
            md += line(r).replace(f"| {fv(r['ticker'])} |", f"| {fv(r['ticker'])} | {r[key]:+.0f}% |", 1)
    open(f"{OUT}/why.md", "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    main()
