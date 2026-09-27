"""
김종봉 스캐너 공통 신호 (인텔형)
- 월봉 인텔형 ⭐월 : 돌파 전 12개월 중 6개월 이상 월봉 12개월선 아래(긴 바닥) → 최근 2개월 안에 12개월선 위로 돌파(+3% 이상)
- 주봉 인텔형 ⭐주 : 돌파 전 26주 중 13주 이상 주봉 12주선 아래(긴 바닥) → 최근 2주 안에 12주선 위로 돌파(+2% 이상) + 이번 주 강한 양봉
- 조기 경보 👀   : 월말을 기다리지 않고, 이번 달 진행 중인 월봉이 '큰 그림자(장악형 양봉)'로 12개월선을 뚫으려 할 때
                   (긴 바닥 + 지난달까지 12개월선 아래 + 이번 달 +8% 이상 + 지난달 고점 돌파 + 12개월선 -2% 이내 이상 + 나스닥보다 강함)
"""
import pandas as pd

MA_MONTHS = 12
MA_WEEKS = 12
M_BASE_MIN = 6        # 월봉: 직전 12개월 중 12개월선 아래였던 달 수
M_MIN_ABOVE = 3.0     # 월봉: 돌파 후 12개월선 대비 최소 %
W_BASE_MIN = 13       # 주봉: 직전 26주 중 12주선 아래였던 주 수
W_MIN_ABOVE = 2.0     # 주봉: 돌파 후 12주선 대비 최소 %
W_MIN_WEEK_RET = 4.0  # 주봉: 돌파 주(또는 이번 주) 최소 상승률
E_MIN_MTD = 8.0       # 조기 경보: 이번 달 최소 상승률
E_NEAR_MA = 0.98      # 조기 경보: 12개월선의 98% 이상이면 '뚫으려 함'


def pct(a, b):
    try:
        return (a / b - 1) * 100 if b else float("nan")
    except Exception:
        return float("nan")


def monthly_star(m):
    """m: 월말 종가 시리즈 (마지막 값이 이번 달, 진행 중이어도 됨)"""
    m = m.dropna()
    if len(m) < MA_MONTHS + 3:
        return None
    mma = m.rolling(MA_MONTHS).mean()
    base = int((m.iloc[-14:-2] < mma.iloc[-14:-2]).sum())
    crossed = m.iloc[-2] < mma.iloc[-2] or m.iloc[-3] < mma.iloc[-3]
    above = pct(m.iloc[-1], mma.iloc[-1])
    if base >= M_BASE_MIN and crossed and above >= M_MIN_ABOVE:
        return {"tf": "월", "base": base, "above_ma_pct": round(above, 2)}
    return None


def weekly_star(c):
    """c: 주말(금) 종가 시리즈"""
    c = c.dropna()
    if len(c) < MA_WEEKS + 28:
        return None
    ma = c.rolling(MA_WEEKS).mean()
    base = int((c.iloc[-28:-2] < ma.iloc[-28:-2]).sum())
    crossed = c.iloc[-2] < ma.iloc[-2] or c.iloc[-3] < ma.iloc[-3]
    above = pct(c.iloc[-1], ma.iloc[-1])
    big_week = max(pct(c.iloc[-1], c.iloc[-2]), pct(c.iloc[-2], c.iloc[-3])) >= W_MIN_WEEK_RET
    if base >= W_BASE_MIN and crossed and above >= W_MIN_ABOVE and big_week:
        return {"tf": "주", "base": base, "above_ma_pct": round(above, 2)}
    return None


def early_monthly(close, high, qqq_close):
    """daily 종가/고가 시리즈로 이번 달(진행 중) 월봉 조기 경보"""
    close, high = close.dropna(), high.dropna()
    if len(close) < 300:
        return None
    mc = close.resample("ME").last()
    mh = high.resample("ME").max()
    if len(mc) < MA_MONTHS + 3:
        return None
    mma = mc.rolling(MA_MONTHS).mean()
    cur, prev_close, prev_high = mc.iloc[-1], mc.iloc[-2], mh.iloc[-2]
    base = int((mc.iloc[-14:-2] < mma.iloc[-14:-2]).sum())
    q = qqq_close.dropna().resample("ME").last()
    mtd, q_mtd = pct(cur, prev_close), pct(q.iloc[-1], q.iloc[-2])
    ok = (base >= M_BASE_MIN
          and prev_close < mma.iloc[-2]               # 지난달까지는 12개월선 아래
          and cur >= mma.iloc[-1] * E_NEAR_MA         # 이번 달 12개월선에 닿거나 뚫음
          and mtd >= E_MIN_MTD                        # 큰 양봉
          and cur > prev_high                         # 지난달 고점 돌파 = 큰 그림자(장악형)
          and mtd > q_mtd)                            # 나스닥보다 강함
    if not ok:
        return None
    return {"base": base, "mtd_pct": round(mtd, 2), "qqq_mtd_pct": round(q_mtd, 2),
            "vs_ma12m_pct": round(pct(cur, mma.iloc[-1]), 2), "prev_high": round(float(prev_high), 2),
            "close": round(float(cur), 2)}
