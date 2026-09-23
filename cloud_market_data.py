"""
cloud_market_data.py
GitHub Actions에서 매일 자동 실행되는 스크립트.

수집 데이터:
  1. CNN Fear & Greed 지수
  2. S&P500 + 나스닥100 중 시가총액 $10B 이상 종목의
     Daily / Weekly / Monthly Top 3 상승 종목

결과: Market_Data.md 파일로 저장 (이 리포지토리에 커밋됨)
      -> raw.githubusercontent.com URL로 공개 접근 가능
"""

import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

MARKET_CAP_MIN = 10_000_000_000  # $10B
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def get_fear_greed_index():
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {
        **BROWSER_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://edition.cnn.com/markets/fear-and-greed",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        score = data["fear_and_greed"]["score"]
        rating = data["fear_and_greed"]["rating"]
        # CNN이 주는 타임스탬프 (예: "2026-09-23T20:59:03+00:00", UTC 기준)
        raw_ts = data["fear_and_greed"].get("timestamp")
        ny_ts_text = None
        if raw_ts:
            try:
                dt_utc = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                dt_ny = dt_utc - timedelta(hours=4)  # 대략 미국 동부시간(EDT, UTC-4) 환산
                ny_ts_text = dt_ny.strftime("%Y-%m-%d %H:%M ET (뉴욕 기준)")
            except Exception:
                ny_ts_text = None
        return {"score": round(score, 1), "rating": rating, "ny_time": ny_ts_text}
    except Exception as e:
        print(f"Fear & Greed 실패: {e}")
        return None


def get_universe():
    """S&P500 + 나스닥100 종목과 회사명을 가져옴 (ticker -> name 딕셔너리)"""
    universe = {}

    try:
        resp = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=BROWSER_HEADERS, timeout=10,
        )
        table = pd.read_html(resp.text)[0]
        for _, row in table.iterrows():
            t = str(row["Symbol"]).replace(".", "-")
            universe[t] = row.get("Security", t)
    except Exception as e:
        print(f"S&P500 실패: {e}")

    try:
        resp = requests.get(
            "https://en.wikipedia.org/wiki/Nasdaq-100",
            headers=BROWSER_HEADERS, timeout=10,
        )
        tables = pd.read_html(resp.text)
        for tb in tables:
            if "Ticker" in tb.columns:
                name_col = "Company" if "Company" in tb.columns else tb.columns[0]
                for _, row in tb.iterrows():
                    t = str(row["Ticker"]).replace(".", "-")
                    universe[t] = row.get(name_col, t)
                break
    except Exception as e:
        print(f"나스닥100 실패: {e}")

    return universe


def filter_by_market_cap(universe, min_cap=MARKET_CAP_MIN, max_workers=20):
    """시가총액 $10B 이상 종목만 남김"""
    qualified = {}

    def check(ticker):
        try:
            info = yf.Ticker(ticker).fast_info
            cap = info.get("market_cap") or 0
            if cap >= min_cap:
                return ticker, cap
        except Exception:
            return None
        return None

    print(f"   시가총액 확인 중... ({len(universe)}개 종목)")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(check, t): t for t in universe}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                qualified[result[0]] = result[1]

    print(f"   -> $10B 이상 대형주 {len(qualified)}개 확인됨")
    return qualified


def get_top3_performance(qualified_tickers, universe_names, period_days):
    tickers = list(qualified_tickers.keys())
    if not tickers:
        return []

    data = yf.download(
        tickers,
        period=f"{period_days + 5}d",
        group_by="ticker",
        progress=False,
        threads=True,
    )

    results = []
    for t in tickers:
        try:
            closes = data[t]["Close"].dropna()
            if len(closes) < period_days + 1:
                continue
            pct = (closes.iloc[-1] / closes.iloc[-(period_days + 1)] - 1) * 100
            name = universe_names.get(t, t)
            results.append((t, name, pct))
        except Exception:
            continue

    results.sort(key=lambda x: x[2], reverse=True)
    return results[:3]


def format_table(results):
    if not results:
        return "| 티커 | 회사명 | 등락률 |\n|---|---|---|\n| - | 데이터 없음 | - |"
    lines = ["| 티커 | 회사명 | 등락률 |", "|---|---|---|"]
    for t, name, pct in results:
        lines.append(f"| {t} | {name} | +{pct:.2f}% |")
    return "\n".join(lines)


def main():
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    print("1) Fear & Greed")
    fg = get_fear_greed_index()
    if fg:
        ts_line = f" _(측정 시각: {fg['ny_time']})_" if fg.get("ny_time") else ""
        fg_text = f"**{fg['score']} / 100 ({fg['rating']})**{ts_line}"
    else:
        fg_text = "가져오기 실패"

    print("2) 대형주 유니버스 수집")
    universe = get_universe()

    print("3) 시가총액 $10B 이상 필터링")
    qualified = filter_by_market_cap(universe)

    print("4) Daily Top 3")
    daily = get_top3_performance(qualified, universe, 1)

    print("5) Weekly Top 3 (5거래일)")
    weekly = get_top3_performance(qualified, universe, 5)

    print("6) Monthly Top 3 (21거래일)")
    monthly = get_top3_performance(qualified, universe, 21)

    content = f"""# Market Data
_최종 갱신: {now_str}_

## Fear & Greed
{fg_text}

## Daily Top 3 (시총 $10B+)
{format_table(daily)}

## Weekly Top 3 (시총 $10B+)
{format_table(weekly)}

## Monthly Top 3 (시총 $10B+)
{format_table(monthly)}
"""

    with open("Market_Data.md", "w", encoding="utf-8") as f:
        f.write(content)

    print("완료: Market_Data.md 작성됨")


if __name__ == "__main__":
    main()
