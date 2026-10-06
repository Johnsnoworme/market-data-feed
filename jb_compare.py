"""지금 방식(절대 비교) vs 새 방식(베타 보정 + 지수 하락 주 + 체급별 순위) 비교 — 수동 실행 전용"""
import os
import requests
import pandas as pd

from jb_scanner import (get_sp500, get_ndx, get_watchlist, download_daily, pct, yf_symbol, norm_sector,
                        EXCLUDE_WORDS, MA_WEEKS, PULLBACK_BAND, LAUNCH_MAX_WEEKS_AGO, LAUNCH_MAX_ABOVE_MA,
                        MIN_DOLLAR_VOL_DAY, MIN_MARKET_CAP)
from jb_signals import monthly_star, weekly_star
from jb_strength import strength, passes_new, bucket, add_percentiles

OUT = "scanner/jb/compare"


def caps():
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
         "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
    rows = requests.get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true", headers=h, timeout=30).json()["data"]["rows"]
    out = {}
    for r in rows:
        try:
            cap = float(r.get("marketCap") or 0)
        except ValueError:
            continue
        sym = (r.get("symbol") or "").strip()
        if sym and "^" not in sym and cap >= MIN_MARKET_CAP:
            out[yf_symbol(sym)] = (cap, r.get("name") or "", norm_sector(r.get("sector")))
    return out


def patterns(c, lo, idx1_ok_fn, mclose):
    """신호(🚗/🏁/⭐월/⭐주) — 강함 판정은 빼고 차트 모양만"""
    sig = []
    ma = c.rolling(MA_WEEKS).mean()
    now, prev = c.iloc[-1], c.iloc[-2]
    ret1 = pct(now, prev)
    if now > ma.iloc[-1] and ret1 > 0 and idx1_ok_fn(ret1):
        touched = [w for w in range(2, 8) if lo.iloc[-w] <= ma.iloc[-w] * PULLBACK_BAND]
        if touched:
            launch = (min(touched) - 1) <= LAUNCH_MAX_WEEKS_AGO and pct(now, ma.iloc[-1]) <= LAUNCH_MAX_ABOVE_MA
            sig.append("🚗" if launch else "🏁")
    if monthly_star(mclose):
        sig.append("⭐월")
    if weekly_star(c):
        sig.append("⭐주")
    return sig


def sig_points(sig):
    return (3 if "🚗" in sig else 0) + 2 * sum(1 for s in sig if s.startswith("⭐"))


def fv(t):
    return f'[{t}](https://finviz.com/quote.ashx?p=d&t={t})'


def main():
    os.makedirs(OUT, exist_ok=True)
    cp = caps()
    names = {**{k: (v[1], v[2]) for k, v in cp.items()}, **get_ndx(), **get_sp500()}
    universe = sorted(set(cp) | get_watchlist())
    d = download_daily(set(universe) | {"QQQ", "SPY", "INTC"}, period="3y")
    wc = d["Close"].resample("W-FRI").last()
    wl = d["Low"].resample("W-FRI").min()
    dollar = (d["Close"] * d["Volume"]).resample("W-FRI").sum()
    days = d["Close"].resample("W-FRI").count()
    mc = d["Close"].resample("ME").last()
    q, spy = wc["QQQ"].dropna(), wc["SPY"].dropna()
    last = q.index[-1]
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
        if dv < MIN_DOLLAR_VOL_DAY:
            continue
        st = strength(c, q)
        if not st:
            continue
        r13 = pct(c.iloc[-1], c.iloc[-14])
        old = r13 > q13 and r13 > s13
        new = passes_new(st)
        lo = wl[t].reindex(c.index)
        sig_old = patterns(c, lo, lambda r1: r1 > q1 and r1 > s1, mc[t]) if old else []
        beta = st["beta"]
        sig_new = patterns(c, lo, lambda r1: r1 - beta * q1 > 0, mc[t]) if new else []
        cap = cp.get(t, (0,))[0]
        rows.append(dict(st, ticker=t, name=name, sector=norm_sector(names.get(t, ("", ""))[1]),
                         cap_b=round(cap / 1e9, 1), bucket=bucket(cap), old=old, new=new,
                         sig_old=sig_old, sig_new=sig_new, week_pct=round(pct(c.iloc[-1], c.iloc[-2]), 2)))

    rows = add_percentiles([r for r in rows if r["new"]]) + [r for r in rows if not r["new"]]
    for r in rows:
        r["score_old"] = round(sig_points(r["sig_old"]) + min(max(r["raw13"], 0) / 10, 3), 1) if r["old"] and r["sig_old"] else None
        r["score_new"] = (round(sig_points(r["sig_new"]) + (r.get("strength_score") or 0) / 33 + (1 if r["down_up"] >= 1 else 0)
                                + (1 if r["rs_high"] else 0), 1) if r["new"] and r["sig_new"] else None)

    def top(key, only_focus=True):
        c = [r for r in rows if r[key] is not None and (not only_focus or any(s in ("🚗", "⭐월", "⭐주") for s in r["sig_old" if key == "score_old" else "sig_new"]))]
        return sorted(c, key=lambda r: -r[key])

    old_list, new_list = top("score_old"), top("score_new")
    old_pass = [r for r in rows if r["old"]]
    new_pass = [r for r in rows if r["new"]]
    both = {r["ticker"] for r in old_pass} & {r["ticker"] for r in new_pass}
    head = "| 티커 | 회사 | 시총 | 베타 | 지수보다 (단순) | 진짜 초과 (베타 보정) | 지수 하락 주 | 신호 |\n| :--- | :--- | ---: | ---: | ---: | ---: | :--- | :--- |\n"
    def line(r, sigkey):
        da = f"{r['down_alpha']:+.1f}%/주 · {r['down_up']}/{r['down_weeks']}주 상승" if r["down_alpha"] is not None else "—"
        return (f"| {fv(r['ticker'])}{' 📈' if r['rs_high'] else ''} | {r['name'][:28]} | ${r['cap_b']:.0f}B | {r['beta']:.2f} | "
                f"{r['raw13']:+.1f}%p | {r['alpha13']:+.1f}%p | {da} | {' '.join(r[sigkey])} |\n")

    md = f"# 김종봉 '지수보다 강함' 비교 — {last.strftime('%Y-%m-%d')} 주간\n\n"
    md += f"> QQQ 13주 {q13:+.2f}% · 검사 {len(rows)}개 (시총 $10B+, 거래대금 2천만$+)\n"
    md += f"> **지금 방식** 통과 {len(old_pass)}개 · **새 방식** 통과 {len(new_pass)}개 · 둘 다 {len(both)}개\n"
    md += "> 새 방식 = 베타 보정 13주 초과 상승 > 0 **그리고** 지수 하락 주 평균 초과 > 0 → 체급(대형 $10~50B / 초대형 $50B+) 안에서 순위 · 📈 = 상대강도선 26주 신고가\n\n"
    md += "## 🏆 핵심 5 비교\n\n### 지금 방식 (단순 비교)\n" + head + "".join(line(r, "sig_old") for r in old_list[:5])
    md += "\n### 새 방식 (공정 비교)\n" + head + "".join(line(r, "sig_new") for r in new_list[:5])
    dropped = sorted([r for r in old_pass if not r["new"]], key=lambda r: -r["beta"])
    added = sorted([r for r in new_pass if not r["old"]], key=lambda r: -(r.get("strength_score") or 0))
    md += f"\n## ❌ 지금 방식만 통과 → 새 방식에서 탈락 ({len(dropped)}개, 베타 높은 순 10개)\n> 많이 오른 건 맞지만, 원래 크게 움직이는 만큼이었거나 지수 하락 주에 더 크게 빠진 종목\n\n" + head + "".join(line(r, "sig_old") for r in dropped[:10])
    md += f"\n## ✅ 새 방식에서만 통과 ({len(added)}개, 강함 점수 순 10개)\n> 숫자는 덜 올랐지만, 베타를 빼면 진짜 초과 상승 + 지수 약할 때 버틴 종목\n\n" + head + "".join(line(r, "sig_new") for r in added[:10])

    # 인텔 2025 검증
    md += "\n## 🔍 인텔 2025년 검증 (그 시점 데이터만 사용)\n| 날짜 | 종가 | 베타 | 단순 | 베타 보정 | 지수 하락 주 | 지금 방식 | 새 방식 |\n| :--- | ---: | ---: | ---: | ---: | :--- | :---: | :---: |\n"
    for dt in ["2025-05-16", "2025-06-20", "2025-07-11", "2025-08-15", "2025-08-29", "2025-09-12"]:
        cut = pd.Timestamp(dt)
        ci, qi, si = wc["INTC"][:cut].dropna(), q[:cut], spy[:cut]
        st = strength(ci, qi)
        if not st:
            continue
        r13 = pct(ci.iloc[-1], ci.iloc[-14])
        old = r13 > pct(qi.iloc[-1], qi.iloc[-14]) and r13 > pct(si.iloc[-1], si.iloc[-14])
        md += (f"| {dt} | {ci.iloc[-1]:.2f} | {st['beta']:.2f} | {st['raw13']:+.1f}%p | {st['alpha13']:+.1f}%p | "
               f"{st['down_alpha']:+.1f}%/주 · {st['down_up']}/{st['down_weeks']} | {'✅' if old else '·'} | {'✅' if passes_new(st) else '·'} |\n")
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    main()
