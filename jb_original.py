"""
김종봉 원본 기준: "내려가면 덜 빠지고, 올라가면 더 오른다" (지수 차트와 종목 차트를 나란히 비교)
- 나스닥(QQQ) 주봉에서 최근 조정 구간을 자동으로 찾는다: 고점 → 저점 (5% 이상 하락, 없으면 3%)
- 하락 구간: 종목 수익률 > QQQ 수익률 (덜 빠짐)
- 반등 구간: 저점 → 지금, 종목 수익률 > QQQ 수익률 (더 오름)  ※ 아직 저점이 이번 주면 하락 구간만 봄
- 🔥 : 지수 하락 구간에 오히려 오름 (최강)
- 🥇 : 지수가 직전 고점을 넘기 전에 종목이 먼저 자기 직전 고점을 넘음 ("지수를 처음 이긴 자리")
"""
import pandas as pd


def legs(q, lookback=52):
    """q: QQQ 주봉 종가 (마지막 = 이번 주). 최근 조정 구간 {peak_d, peak, trough_d, trough}"""
    s = q.dropna().iloc[-lookback:]
    for thr in (0.05, 0.03, 0.02, 0.01):
        best = None
        rp, rpd = s.iloc[0], s.index[0]
        for d, v in s.items():
            if v > rp:
                rp, rpd = v, d
            if v / rp - 1 <= -thr and (best is None or best["peak_d"] != rpd or v < best["trough"]):
                best = {"peak_d": rpd, "peak": float(rp), "trough_d": d, "trough": float(v)}
        if best:
            return best
    return None


def kim(c, q, L):
    """c: 종목 주봉 종가, q: QQQ 주봉 종가, L: legs 결과"""
    c = c.dropna()
    try:
        cp, ct, cn = c.loc[L["peak_d"]], c.loc[L["trough_d"]], c.iloc[-1]
    except KeyError:
        return None
    qn = q.dropna().iloc[-1]
    sd, qd = float((ct / cp - 1) * 100), float((L["trough"] / L["peak"] - 1) * 100)
    has_up = L["trough_d"] < c.index[-1]
    su, qu = (float((cn / ct - 1) * 100), float((qn / L["trough"] - 1) * 100)) if has_up else (0.0, 0.0)
    down_ok = sd > qd
    up_ok = (su > qu) if has_up else True
    # 🥇 먼저 고점 돌파
    win = c[(c.index >= L["peak_d"] - pd.Timedelta(weeks=4)) & (c.index <= L["trough_d"])]
    prior_high = float(win.max()) if len(win) else float("nan")
    after = c[c.index > L["trough_d"]]
    sb = after[after > prior_high].index.min() if len(after) else None
    qa = q[q.index > L["trough_d"]]
    qb = qa[qa > L["peak"]].index.min() if len(qa) else None
    first = bool(pd.notna(sb) and (pd.isna(qb) or sb < qb))
    return {"down": round(sd, 1), "q_down": round(qd, 1), "up": round(su, 1), "q_up": round(qu, 1),
            "ex_down": round(sd - qd, 1), "ex_up": round(su - qu, 1),
            "pass": bool(down_ok and up_ok), "fire": bool(sd > 0), "first": first,
            "first_date": sb.strftime("%Y-%m-%d") if first else "",
            "score": round(min(sd - qd, su - qu if has_up else sd - qd), 1)}
