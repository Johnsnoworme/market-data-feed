"""
'지수보다 강함' 공정한 측정 (베타 보정 · 지수 하락 주 · 체급별 순위 · 상대강도선)
- beta        : 최근 52주 주간 수익률로 계산한 나스닥(QQQ) 대비 베타
- alpha13     : 13주 수익률 - 베타 × QQQ 13주 수익률  (원래 움직일 만큼 빼고 남은 진짜 초과 상승)
- down_alpha  : 최근 26주 중 QQQ가 떨어진 주들만, (종목 - 베타 × QQQ) 평균  (지수 약할 때 버티는 힘)
- down_up     : 그 주들 중 종목이 오른 횟수
- rs_high     : 종목/QQQ 비율선이 최근 2주 안에 26주 신고가
"""
import numpy as np
import pandas as pd

RS_WEEKS = 13


def strength(c, q):
    """c, q: 같은 날짜 기준 주간 종가 시리즈 (종목, QQQ)"""
    df = pd.concat([c, q], axis=1, keys=["s", "q"]).dropna()
    if len(df) < 60:
        return None
    r = df.pct_change().dropna()
    r52 = r.iloc[-52:]
    var = r52["q"].var()
    if not var or var != var:
        return None
    beta = float(r52["s"].cov(r52["q"]) / var)
    s13 = df["s"].iloc[-1] / df["s"].iloc[-1 - RS_WEEKS] - 1
    q13 = df["q"].iloc[-1] / df["q"].iloc[-1 - RS_WEEKS] - 1
    r26 = r.iloc[-26:]
    down = r26[r26["q"] < 0]
    down_alpha = float((down["s"] - beta * down["q"]).mean()) if len(down) else float("nan")
    down_up = int((down["s"] > 0).sum())
    ratio = df["s"] / df["q"]
    rs_high = bool(ratio.iloc[-2:].max() >= ratio.iloc[-26:].max() * 0.999)
    return {
        "beta": round(beta, 2),
        "raw13": round(float(s13 - q13) * 100, 2),
        "alpha13": round(float(s13 - beta * q13) * 100, 2),
        "down_alpha": round(down_alpha * 100, 2) if down_alpha == down_alpha else None,
        "down_weeks": int(len(down)), "down_up": down_up,
        "rs_high": rs_high,
    }


def passes_new(st):
    return bool(st and st["alpha13"] > 0 and st["down_alpha"] is not None and st["down_alpha"] > 0)


def bucket(cap):
    return "초대형 $50B+" if cap >= 50e9 else "대형 $10~50B"


def add_percentiles(rows):
    """체급별로 alpha13, down_alpha를 0~99 점수로. strength_score = 둘 평균"""
    df = pd.DataFrame(rows)
    if df.empty:
        return rows
    for col in ("alpha13", "down_alpha"):
        df[col + "_pct"] = df.groupby("bucket")[col].rank(pct=True).fillna(0) * 99
    df["strength_score"] = ((df["alpha13_pct"] + df["down_alpha_pct"]) / 2).round(0)
    return df.to_dict("records")
