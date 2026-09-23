"""
cloud_market_data.py — GitHub Actions용 클라우드 자동 실행 스크립트

이 스크립트가 하는 일:
  1. 공포 & 탐욕 지수 (CNN)
  2. S&P500 + 나스닥100 중, 시가총액 $10B 이상인 대형주만 골라서
     일간 / 주간 / 월간 Top 3 상승 종목을 계산
  3. 결과를 market_data.md 파일로 저장 (아이폰 단축어가 이 파일을 읽어감)
"""

import io
import concurrent.futures
from datetime import date
import requests
import pandas as pd
import yfinance as yf

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

MARKET_CAP_MIN = 10_000_000_000  # $10B


def get_fear_greed_index():
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = dict(BROWSER_HEADERS)
    headers["Referer"] = "https://edition.cnn.com/markets/fear-and-greed"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        score = data["fear_and_greed"]["score"]
        rating = data["fear_and_greed"]["rating"]
        return {"score": round(score, 1), "rating": rating}
    except Exception as e:
        print(f"공포&탐욕 지수 실패: {e}")
        return None


def _read_html_with_headers(url):
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text))


def get_candidate_tickers():
    """S&P500 + 나스닥100 티커 목록 (시총 필터 전, 러셀2000은 제외)"""
    sp500_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    nasdaq100_url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    tickers = set()
    try:
        sp500_table = _read_html_with_headers(sp500_url)[0]
        tickers.update(sp500_table["Symbol"].tolist())
    except Exception as e:
        print(f"S&P500 목록 실패: {e}")
    try:
        nasdaq_tables = _read_html_with_headers(nasdaq100_url)
        for t in nasdaq_tables:
            if "Ticker" in t.columns:
                tickers.update(t["Ticker"].tolist())
                break
    except Exception as e:
        print(f"나스닥100 목록 실패: {e}")
    tickers = {t.replace(".", "-") for t in tickers if isinstance(t, str)}
    return sorted(tickers)


def _get_market_cap(ticker):
    try:
        info = yf.Ticker(ticker).fast_info
        mc = info.get("market_cap")
        return ticker, mc
    except Exception:
        return ticker, None


def filter_large_caps(tickers):
    """시가총액 $10B 이상만 남긴다 (병렬로 빠르게 조회)"""
    result = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        for ticker, mc in ex.map(_get_market_cap, tickers):
            if mc and mc >= MARKET_CAP_MIN:
                result.append(ticker)
    return result


def compute_top3_by_timeframe(tickers):
    """일간 / 주간 / 월간 Top3 상승 종목을 한 번의 다운로드로 계산"""
    data = yf.download(tickers, period="3mo", group_by="ticker", progress=False, threads=True)

    daily, weekly, monthly = [], [], []
    for t in tickers:
        try:
            closes = data[t]["Close"].dropna()
            if len(closes) < 23:
                continue
            d = (closes.iloc[-1] / closes.iloc[-2] - 1) * 100
            w = (closes.iloc[-1] / closes.iloc[-6] - 1) * 100
            m = (closes.iloc[-1] / closes.iloc[-22] - 1) * 100
            daily.append((t, d))
            weekly.append((t, w))
            monthly.append((t, m))
        except Exception:
            continue

    daily.sort(key=lambda x: x[1], reverse=True)
    weekly.sort(key=lambda x: x[1], reverse=True)
    monthly.sort(key=lambda x: x[1], reverse=True)
    return daily[:3], weekly[:3], monthly[:3]


def build_markdown(fg, daily, weekly, monthly, universe_size):
    lines = []
    lines.append(f"# 📊 Market Data — {date.today().isoformat()}")
    lines.append("")
    if fg:
        lines.append(f"**공포 & 탐욕 지수:** {fg['score']} ({fg['rating']})")
    else:
        lines.append("**공포 & 탐욕 지수:** 가져오기 실패")
    lines.append("")
    lines.append(f"**대형주($10B+) 조사 대상:** {universe_size}개 종목")
    lines.append("")
    lines.append("## Top 3 상승 종목")
    lines.append("")
    lines.append("**일간 (Daily):**")
    for t, pct in daily:
        lines.append(f"- {t}: +{pct:.2f}%")
    lines.append("")
    lines.append("**주간 (Weekly):**")
    for t, pct in weekly:
        lines.append(f"- {t}: +{pct:.2f}%")
    lines.append("")
    lines.append("**월간 (Monthly):**")
    for t, pct in monthly:
        lines.append(f"- {t}: +{pct:.2f}%")
    lines.append("")
    lines.append(f"_자동 생성: {date.today().isoformat()} (GitHub Actions)_")
    return "\n".join(lines)


if __name__ == "__main__":
    print("1) 공포&탐욕 지수 조회 중...")
    fg = get_fear_greed_index()

    print("2) 후보 종목 목록 가져오는 중...")
    candidates = get_candidate_tickers()
    print(f"   후보 {len(candidates)}개")

    print("3) 시가총액 $10B 이상만 필터링 중... (몇 분 걸릴 수 있음)")
    large_caps = filter_large_caps(candidates)
    print(f"   대형주 {len(large_caps)}개 확정")

    print("4) 일/주/월간 Top3 계산 중...")
    daily, weekly, monthly = compute_top3_by_timeframe(large_caps)

    md = build_markdown(fg, daily, weekly, monthly, len(large_caps))

    with open("market_data.md", "w", encoding="utf-8") as f:
        f.write(md)

    print("완료: market_data.md 저장됨")
    print(md)
