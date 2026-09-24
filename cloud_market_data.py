"""
cloud_market_data.py (Finnhub 전용 스마트 누적 버전)
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime

# ============================================================
# ⚠️ 본인의 Finnhub API 키를 따옴표 안에 넣으세요
# ============================================================
FINNHUB_API_KEY = "여기에_발급받은_키_붙여넣기"
# ============================================================

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

def get_fear_greed_index():
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {**BROWSER_HEADERS, "Referer": "https://edition.cnn.com/markets/fear-and-greed"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()["fear_and_greed"]
        return {"score": round(data["score"], 1), "rating": data["rating"]}
    except Exception:
        return None

def get_finnhub_quote(ticker):
    url = "https://finnhub.io/api/v1/quote"
    params = {"symbol": ticker, "token": FINNHUB_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("c"), data.get("dp")
    except Exception:
        pass
    return None, None

def main():
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    print("1) Fear & Greed 수집")
    fg = get_fear_greed_index()
    fg_text = f"**{fg['score']} / 100 ({fg['rating']})**" if fg else "가져오기 실패"

    target_tickers = [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK.B", "AVGO", "PG",
        "JNJ", "COST", "HD", "NFLX", "AMD", "PEP", "KO", "BAC", "WMT", "JPM"
    ]

    print("2) Finnhub 시세 수집 중...")
    today_prices = {}
    daily_changes = {}

    for ticker in target_tickers:
        price, dp = get_finnhub_quote(ticker)
        if price and dp is not None:
            today_prices[ticker] = price
            daily_changes[ticker] = dp
        time.sleep(0.2)

    history_file = "history.csv"
    if os.path.exists(history_file):
        df_hist = pd.read_csv(history_file)
    else:
        df_hist = pd.DataFrame(columns=["date", "ticker", "price"])

    new_rows = []
    for t, p in today_prices.items():
        new_rows.append({"date": today_str, "ticker": t, "price": p})
    
    if new_rows:
        df_hist = pd.concat([df_hist, pd.DataFrame(new_rows)], ignore_index=True)
        df_hist.drop_duplicates(subset=["date", "ticker"], keep="last", inplace=True)
        df_hist.to_csv(history_file, index=False)

    sorted_daily = sorted(daily_changes.items(), key=lambda x: x[1], reverse=True)[:3]
    dates = sorted(df_hist["date"].unique())
    
    weekly_top3_text = "데이터 누적 중 (약 5일 소요)"
    if len(dates) >= 5:
        target_date = dates[-5]
        past_df = df_hist[df_hist["date"] == target_date].set_index("ticker")["price"]
        weekly_diff = {}
        for t, p in today_prices.items():
            if t in past_df:
                old_p = past_df[t]
                pct = ((p - old_p) / old_p) * 100
                weekly_diff[t] = pct
        sorted_weekly = sorted(weekly_diff.items(), key=lambda x: x[1], reverse=True)[:3]
        weekly_top3_text = "\n".join([f"| {t} | +{pct:.2f}% |" for t, pct in sorted_weekly])

    monthly_top3_text = "데이터 누적 중 (약 20일 소요)"
    if len(dates) >= 20:
        target_date = dates[-20]
        past_df = df_hist[df_hist["date"] == target_date].set_index("ticker")["price"]
        monthly_diff = {}
        for t, p in today_prices.items():
            if t in past_df:
                old_p = past_df[t]
                pct = ((p - old_p) / old_p) * 100
                monthly_diff[t] = pct
        sorted_monthly = sorted(monthly_diff.items(), key=lambda x: x[1], reverse=True)[:3]
        monthly_top3_text = "\n".join([f"| {t} | +{pct:.2f}% |" for t, pct in sorted_monthly])

    daily_table = "| 티커 | 등락률 |\n|---|---|\n" + "\n".join([f"| {t} | +{pct:.2f}% |" for t, pct in sorted_daily])
    
    content = f"""# Market Data
_최종 갱신: {now_str}_

## Fear & Greed
{fg_text}

## Daily Top 3
{daily_table}

## Weekly Top 3
{weekly_top3_text}

## Monthly Top 3
{monthly_top3_text}
"""

    with open("Market_Data.md", "w", encoding="utf-8") as f:
        f.write(content)

    print("완료!")

if __name__ == "__main__":
    main()
