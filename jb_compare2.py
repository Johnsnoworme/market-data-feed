"""지금 방식 vs 김종봉 원본 방식 + 관심 종목 타임라인 (수동 실행)"""
import os
import pandas as pd

from jb_scanner import (get_sp500, get_ndx, get_watchlist, download_daily, pct, norm_sector, EXCLUDE_WORDS,
                        MIN_DOLLAR_VOL_DAY)
from jb_compare import caps, patterns, sig_points
from jb_original import legs, kim

OUT = "scanner/jb/compare"
TIMELINE = ["PLTR", "INTC", "MSFT", "HOOD", "MSTR", "NVDA", "TSLA", "ORCL", "CRCL", "TEM", "MU", "AMD", "BE", "SNDK", "META", "AVGO"]
LEADERS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "TSLA"]


def fv(t, w=True):
    return f'<a href="https://finviz.com/quote.ashx?p={"w" if w else "d"}&t={t}" target="_blank">{t}</a>'


def main():
    os.makedirs(OUT, exist_ok=True)
    cp = caps()
    names = {**{k: (v[1], v[2]) for k, v in cp.items()}, **get_ndx(), **get_sp500()}
    universe = sorted(set(cp) | get_watchlist() | set(TIMELINE) | set(LEADERS))
    d = download_daily(set(universe) | {"QQQ", "SPY"}, period="3y")
    wc = d["Close"].resample("W-FRI").last()
    wl = d["Low"].resample("W-FRI").min()
    dollar = (d["Close"] * d["Volume"]).resample("W-FRI").sum()
    days = d["Close"].resample("W-FRI").count()
    mc = d["Close"].resample("ME").last()
    q, spy = wc["QQQ"].dropna(), wc["SPY"].dropna()
    last = q.index[-1]
    L = legs(q)
    q13, s13 = pct(q.iloc[-1], q.iloc[-14]), pct(spy.iloc[-1], spy.iloc[-14])
    q1, s1 = pct(q.iloc[-1], q.iloc[-2]), pct(spy.iloc[-1], spy.iloc[-2])

    rows = []
    for t in universe:
        if t not in wc.columns:
            continue
        c = wc[t].dropna()
        if len(c) < 60 or c.index[-1] != last:
            continue
        name = names.get(t, ("", ""))[0]
        if any(w in name for w in EXCLUDE_WORDS):
            continue
        dv = dollar[t].reindex(c.index).iloc[-4:].sum() / max(days[t].reindex(c.index).iloc[-4:].sum(), 1)
        if dv < MIN_DOLLAR_VOL_DAY or t not in cp and t not in TIMELINE + LEADERS:
            continue
        k = kim(c, q, L)
        if not k:
            continue
        r13 = pct(c.iloc[-1], c.iloc[-14])
        old = r13 > q13 and r13 > s13
        lo = wl[t].reindex(c.index)
        sig = patterns(c, lo, lambda r1: r1 > q1 and r1 > s1, mc[t])
        rows.append(dict(k, ticker=t, name=name[:26], sector=norm_sector(names.get(t, ("", ""))[1]),
                         cap_b=round(cp.get(t, (0,))[0] / 1e9), old=old, raw13=round(r13 - q13, 1), sig=sig,
                         in_uni=t in cp))
    R = {r["ticker"]: r for r in rows}
    uni = [r for r in rows if r["in_uni"]]
    focus = lambda r: any(s in ("🚗", "⭐월", "⭐주") for s in r["sig"])
    s_old = lambda r: sig_points(r["sig"]) + min(max(r["raw13"], 0) / 10, 3)
    s_new = lambda r: sig_points(r["sig"]) + min(max(r["score"], 0) / 5, 3) + (1 if r["fire"] else 0) + (1 if r["first"] else 0)
    top_old = sorted([r for r in uni if r["old"] and focus(r)], key=lambda r: -s_old(r))[:5]
    top_new = sorted([r for r in uni if r["pass"] and focus(r)], key=lambda r: -s_new(r))[:5]
    P_old = {r["ticker"] for r in uni if r["old"]}
    P_new = {r["ticker"] for r in uni if r["pass"]}

    H = "| 티커 | 회사 | 시총 | 지수 하락 구간 (종목 / 나스닥) | 반등 구간 (종목 / 나스닥) | 표시 | 신호 |\n| :--- | :--- | ---: | :--- | :--- | :--- | :--- |\n"
    def line(r):
        tag = ("🔥" if r["fire"] else "") + (f"🥇{r['first_date'][5:]}" if r["first"] else "")
        return (f"| {fv(r['ticker'])} | {r['name']} | ${r['cap_b']}B | {r['down']:+.1f}% / {r['q_down']:+.1f}% | "
                f"{r['up']:+.1f}% / {r['q_up']:+.1f}% | {tag} | {' '.join(r['sig'])} |\n")

    md = f"# 김종봉 원본 기준 비교 — {last.strftime('%Y-%m-%d')} 주간\n\n"
    md += (f"> 나스닥(QQQ) 최근 조정: **{L['peak_d'].strftime('%Y-%m-%d')} 고점 {L['peak']:.2f} → {L['trough_d'].strftime('%Y-%m-%d')} 저점 {L['trough']:.2f}** "
           f"({(L['trough']/L['peak']-1)*100:+.1f}%) → 지금 {q.iloc[-1]:.2f} (저점 대비 {(q.iloc[-1]/L['trough']-1)*100:+.1f}%)\n")
    md += "> 원본 통과 = 하락 구간에 나스닥보다 **덜 빠지고** + 반등 구간에 나스닥보다 **더 오름** · 🔥 하락 구간에 오히려 오름 · 🥇 나스닥보다 먼저 직전 고점 돌파(날짜) · 티커 = Finviz 주봉 차트\n"
    md += f"> 검사 {len(uni)}개 (시총 $10B+) · **지금 방식 통과 {len(P_old)}개 · 원본 통과 {len(P_new)}개 · 둘 다 {len(P_old & P_new)}개**\n\n"
    md += "## 👑 대장주 신호 (나스닥 시총 상위가 지수를 이기나)\n" + H + "".join(line(R[t]) for t in LEADERS if t in R)
    md += "\n## 🏆 핵심 5 비교\n### 지금 방식\n" + H + "".join(line(r) for r in top_old)
    md += "\n### 김종봉 원본\n" + H + "".join(line(r) for r in top_new)
    surv = sorted([r for r in uni if r["old"] and r["pass"] and focus(r)], key=lambda r: -s_new(r))
    gone = sorted([r for r in uni if r["old"] and not r["pass"] and focus(r)], key=lambda r: -s_old(r))
    new = sorted([r for r in uni if r["pass"] and not r["old"] and focus(r)], key=lambda r: -s_new(r))
    md += f"\n## ✅ 둘 다 통과 = 살아남은 종목 (신호 있는 것 {len(surv)}개)\n" + H + "".join(line(r) for r in surv[:25])
    md += f"\n## ❌ 지금 방식만 → 원본에서 탈락 (신호 있는 것 {len(gone)}개)\n" + H + "".join(line(r) for r in gone[:25])
    md += f"\n## 🆕 원본에서만 통과 (신호 있는 것 {len(new)}개)\n" + H + "".join(line(r) for r in new[:25])
    fire = sorted([r for r in uni if r["pass"] and r["fire"]], key=lambda r: -r["down"])
    md += f"\n## 🔥 나스닥 하락 구간에 오히려 오른 종목 (원본 통과, 신호 무관, {len(fire)}개 중 20개)\n" + H + "".join(line(r) for r in fire[:20])

    # 타임라인: 매주 돌렸다면 언제 걸렸나 (2024-06 ~ 지금)
    md += "\n## 📅 관심 종목 타임라인 — 매주 원본 기준으로 돌렸다면 언제 걸렸나\n"
    md += "> 연속으로 통과한 기간을 묶어서 표시 (시작일 = 그 주 금요일). 🔥/🥇/🚗⭐ 가 붙은 주는 괄호로. 티커 = Finviz 주봉 차트\n\n"
    weeks = q[q.index >= pd.Timestamp("2024-06-01")].index
    for t in TIMELINE:
        if t not in wc.columns:
            continue
        runs, cur, marks = [], None, {}
        for w in weeks:
            qq = q[:w]
            cc = wc[t][:w].dropna()
            if len(cc) < 20 or cc.index[-1] != w:
                cur = None
                continue
            Lw = legs(qq)
            k = kim(cc, qq, Lw) if Lw else None
            if k and k["pass"]:
                if cur is None:
                    cur = [w, w]
                    runs.append(cur)
                else:
                    cur[1] = w
                m = ("🔥" if k["fire"] else "") + ("🥇" if k["first"] else "")
                if m:
                    marks.setdefault(runs.index(cur), set()).update(m)
            else:
                cur = None
        runs = [r for r in runs if (r[1] - r[0]).days >= 7]  # 2주 이상 연속만
        close = lambda w: wc[t][:w].dropna().iloc[-1]
        items = [f"{a.strftime('%Y-%m-%d')} (${close(a):.2f}) → {b.strftime('%Y-%m-%d')} (${close(b):.2f}) {''.join(sorted(marks.get(i, [])))}"
                 for i, (a, b) in enumerate(runs)]
        md += f"- **{fv(t)}**: " + ("; ".join(items[-6:]) if items else "2주 이상 연속 통과한 적 없음") + "\n"
    open(f"{OUT}/original.md", "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    main()
