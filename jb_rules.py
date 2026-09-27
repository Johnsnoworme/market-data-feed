"""
7개 룰 자동 1차 체크 (John의 '📏 나만의 트레이딩 룰' 기반, 상승 추세 기준)
기계로 흉내 낸 근사치다. 최종 판단은 차트를 직접 보고 한다.

1 👤 Big shadows   : 1파 구간 주봉에 큰 인골핑(전주 고가 위 마감 + 몸통이 최근 10주 평균의 1.5배↑)
                     또는 2~3주 합친 큰 양봉(+15%↑) 또는 상승 주 거래량이 20주 평균의 2배↑
2 🧱 Kwon          : 1파 안에서 1차 급등(+15%↑) → 3주↑ 박스권(폭 12% 이내) → 박스 고점 +5%↑ 돌파(2차)
3 🔪 Sharp         : 최근 5거래일 안, 풀백 바닥 근처(최근 10일 저점 +3% 이내)에서 일봉 상승 인골핑 또는 거래량 2배↑ 양봉
4 🧠 Room for left : 풀백 바닥 가격에서 왼쪽으로, 저가가 그 가격보다 위에 있던 캔들이 연속 몇 개인가 (10개↑ ✓, 숫자 기록)
5 🌊 Liquidity     : 최근 20일 하루 평균 거래대금 5천만 달러↑
6 👓 No plan       : 자동 제안(진입=오늘 종가, 손절=1파의 70% 되돌림 아래, 목표=1파 고점·1.618 확장) → 직접 확정
7 🥊 Counter       : Big shadows로 방향 확인 + 1파 확정 + 2파 풀백 구간(38.2~70%) 안
"""
import pandas as pd


def weekly_ohlcv(o, h, l, c, v):
    return (o.resample("W-FRI").first(), h.resample("W-FRI").max(), l.resample("W-FRI").min(),
            c.resample("W-FRI").last(), v.resample("W-FRI").sum())


def big_shadows(wo, wh, wl, wc, wv, start, end):
    body = (wc - wo).abs()
    avg_body = body.rolling(10).mean()
    avg_vol = wv.rolling(20).mean()
    for i in range(1, len(wc)):
        dt = wc.index[i]
        if dt < start or dt > end:
            continue
        up = wc.iloc[i] > wo.iloc[i]
        engulf = up and wc.iloc[i] > wh.iloc[i - 1] and body.iloc[i] >= 1.5 * (avg_body.iloc[i - 1] or 0)
        vol = up and wv.iloc[i] >= 2 * (avg_vol.iloc[i - 1] or float("inf"))
        combo = any(i - k >= 0 and (wc.iloc[i] / wo.iloc[i - k] - 1) >= 0.15 for k in (1, 2))
        if engulf or vol or combo:
            return True, dt.strftime("%Y-%m-%d")
    return False, ""


def kwon(wc, wh, wl, start, end):
    s = wc[(wc.index >= start) & (wc.index <= end)]
    if len(s) < 6:
        return False
    hs, ls = wh.reindex(s.index), wl.reindex(s.index)
    low0 = ls.iloc[0]
    for i in range(1, len(s) - 3):
        if s.iloc[i] / low0 - 1 < 0.15:
            continue
        for j in range(i + 3, len(s)):
            box_hi, box_lo = hs.iloc[i:j].max(), ls.iloc[i:j].min()
            if box_hi / box_lo - 1 > 0.12:
                break
            if j < len(s) and s.iloc[j:].max() >= box_hi * 1.05:
                return True
    return False


def sharp(o, h, l, c, v):
    lo10 = l.iloc[-10:].min()
    avg_v = v.iloc[-25:-5].mean()
    for k in range(1, 6):
        i = -k
        up = c.iloc[i] > o.iloc[i]
        near_bottom = l.iloc[i] <= lo10 * 1.03
        engulf = up and c.iloc[i] > max(o.iloc[i - 1], c.iloc[i - 1]) and o.iloc[i] <= min(o.iloc[i - 1], c.iloc[i - 1])
        vol = up and v.iloc[i] >= 2 * avg_v
        if near_bottom and (engulf or vol):
            return True
    return False


def room_left(l):
    level = l.iloc[-10:].min()
    n = 0
    for x in reversed(l.iloc[:-10].tolist()):
        if x > level:
            n += 1
        else:
            break
    return n, round(float(level), 2)


def check(o, h, l, c, v, swing_low, swing_high, low_date, high_date, retr):
    o, h, l, c, v = (x.dropna() for x in (o, h, l, c, v))
    wo, wh, wl, wc, wv = weekly_ohlcv(o, h, l, c, v)
    bs, bs_date = big_shadows(wo, wh, wl, wc, wv, low_date, high_date + pd.Timedelta(days=6))
    kw = kwon(wc, wh, wl, low_date, high_date + pd.Timedelta(days=6))
    sh = sharp(o, h, l, c, v)
    room, level = room_left(l)
    dv = float((c.iloc[-20:] * v.iloc[-20:]).mean())
    liq = dv >= 50_000_000
    counter = bs and 38.2 <= retr <= 70
    close = float(c.iloc[-1])
    rng = swing_high - swing_low
    stop = round(swing_high - rng * 0.72, 2)             # 70% 되돌림 아래 (여유 2%p)
    t1 = round(swing_high, 2)                            # 1파 고점
    t2 = round(min(level, close) + rng * 1.618, 2)       # 2파 바닥 + 1파 × 1.618 (3파 목표)
    rr = round((t1 - close) / (close - stop), 2) if close > stop else None
    checks = {"👤": bs, "🧱": kw, "🔪": sh, "🧠": room >= 10, "🌊": liq, "🥊": counter}
    return {
        "checks": checks, "score": sum(checks.values()), "big_shadow_week": bs_date,
        "room_left": room, "bottom": level, "dollar_vol_m": round(dv / 1e6, 1),
        "plan": {"entry": round(close, 2), "stop": stop, "target1": t1, "target2": t2, "rr_t1": rr},
    }
