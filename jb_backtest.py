"""과거 날짜 기준으로 인텔형 신호가 떴을지 확인 (수동 실행 전용). 결과는 Actions 로그에 출력."""
import os
import pandas as pd
import yfinance as yf
from jb_signals import monthly_star, weekly_star, early_monthly

tickers = [t.strip().upper() for t in os.environ.get("BT_TICKERS", "INTC").split(",") if t.strip()]
start, end = os.environ.get("BT_START", "2025-06-01"), os.environ.get("BT_END", "2025-10-31")
d = yf.download(tickers + ["QQQ"], period="5y", interval="1d", auto_adjust=True, progress=False, group_by="column")
for t in tickers:
    print(f"\n===== {t} =====")
    for day in pd.bdate_range(start, end):
        c = d["Close"][t][:day]; h = d["High"][t][:day]; q = d["Close"]["QQQ"][:day]
        if c.empty or c.index[-1].date() != day.date():
            continue
        out = []
        e = early_monthly(c, h, q)
        if e: out.append(f"👀조기경보 {e}")
        if day.weekday() == 4:
            w = weekly_star(c.resample("W-FRI").last())
            if w: out.append(f"⭐주 {w}")
            m = monthly_star(c.resample("ME").last())
            if m: out.append(f"⭐월 {m}")
        if out:
            print(day.date(), f"종가 {c.iloc[-1]:.2f}", " | ".join(out))
