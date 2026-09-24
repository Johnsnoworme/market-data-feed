"""
cloud_market_data.py (v4 - 최종 병합판)

데이터 소스: Finnhub API만 사용 (야후 파이낸스 완전 배제 -> 클라우드 IP 차단 문제 없음)
표시 방식: 회사명 + Fear&Greed 측정 시각까지 함께 표기

수집 데이터:
  1. CNN Fear & Greed 지수 (측정 시각 포함)
  2. S&P500 + 나스닥100 종목의 Daily / Weekly / Monthly Top 3 상승 종목
     (티커 + 회사명 + 등락률)

결과: Market_Data.md 로 저장 -> GitHub에 커밋 -> raw URL로 공개 접근
"""

import io
import time
from datetime import datetime, timedelta
import requests
import pandas as pd

# ============================================================
# ⚠️ Finnhub API 키를 넣으세요
# ============================================================
FINNHUB_API_KEY = "dapf0l1r01qqnrhr82s0dapf0l1r01qqnrhr82sg"
# ============================================================

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

FINNHUB_CALL_INTERVAL = 1.1  # 무료 플랜 분당 60회 제한 대응


def get_fear_greed_index():
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {**BROWSER_HEADERS, "Referer": "https://edition.cnn.com/markets/fear-and-greed"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()["fear_and_greed"]
        score = round(data["score"], 1)
        rating = data["rating"]

        ny_ts_text = None
        raw_ts = data.get("timestamp")
        if raw_ts:
            try:
                dt_utc = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                dt_ny = dt_utc - timedelta(hours=4)  # EDT 근사치(UTC-4)
                ny_ts_text = dt_ny.strftime("%Y-%m-%d %H:%M ET (뉴욕 기준)")
            except Exception:
                pass

        return {"score": score, "rating": rating, "ny_time": ny_ts_text}
    except Exception as e:
        print(f"❌ Fear & Greed 실패: {e}")
        return None


def _read_html_with_headers(url):
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text))


def get_universe():
    """S&P500 + 나스닥100 종목: ticker -> 회사명 딕셔너리"""
    universe = {}
    try:
        table = _read_html_with_headers("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        for _, row in table.iterrows():
            t = str(row["Symbol"]).replace(".", "-")
            universe[t] = row.get("Security", t)
    except Exception as e:
        print(f"⚠️ S&P500 목록 실패: {e}")

    try:
        tables = _read_html_with_headers("https://en.wikipedia.org/wiki/Nasdaq-100")
        for tb in tables:
            if "Ticker" in tb.columns:
                name_col = "Company" if "Company" in tb.columns else tb.columns[0]
                for _, row in tb.iterrows():
                    t = str(row["Ticker"]).replace(".", "-")
                    universe[t] = row.get(name_col, t)
                break
    except Exception as e:
        print(f"⚠️ 나스닥100 목록 실패: {e}")

    return universe


def get_candles_from_finnhub(ticker):
    end = int(time.time())
    start = end - 40 * 24 * 60 * 60
    url = "https://finnhub.io/api/v1/stock/candle"
    params = {"symbol": ticker, "resolution": "D", "from": start, "to": end, "token": FINNHUB_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("s") != "ok":
            return None, f"status={data.get('s')}"
        closes = data.get("c", [])
        if len(closes) < 23:
            return None, f"데이터 부족 ({len(closes)}일치)"
        return closes, None
    except Exception as e:
        return None, str(e)


def compute_top3_by_timeframe(universe):
    tickers = list(universe.keys())
    daily, weekly, monthly = [], [], []
    fail_count = 0
    fail_reasons = {}

    for i, t in enumerate(tickers):
        closes, err = get_candles_from_finnhub(t)
        if err:
            fail_count += 1
            fail_reasons[err] = fail_reasons.get(err, 0) + 1
        else:
            name = universe.get(t, t)
            d = (closes[-1] / closes[-2] - 1) * 100
            w = (closes[-1] / closes[-6] - 1) * 100
            m = (closes[-1] / closes[-22] - 1) * 100
            daily.append((t, name, d))
            weekly.append((t, name, w))
            monthly.append((t, name, m))

        if (i + 1) % 50 == 0:
            print(f"   진행: {i + 1}/{len(tickers)} (실패 {fail_count}건)")

        time.sleep(FINNHUB_CALL_INTERVAL)

    print(f"   완료: 성공 {len(daily)}건 / 실패 {fail_count}건")
    if fail_reasons:
        print("   실패 사유 집계:")
        for reason, cnt in sorted(fail_reasons.items(), key=lambda x: -x[1])[:5]:
            print(f"     - {reason}: {cnt}건")

    if not daily:
        raise RuntimeError(
            "모든 티커에서 시세를 가져오지 못했습니다. 위 '실패 사유 집계'를 확인하세요."
        )

    daily.sort(key=lambda x: x[2], reverse=True)
    weekly.sort(key=lambda x: x[2], reverse=True)
    monthly.sort(key=lambda x: x[2], reverse=True)
    return daily[:3], weekly[:3], monthly[:3]


def format_table(results):
    if not results:
        return "| 티커 | 회사명 | 등락률 |\n|---|---|---|\n| - | 데이터 없음 | - |"
    lines = ["| 티커 | 회사명 | 등락률 |", "|---|---|---|"]
    for t, name, pct in results:
        lines.append(f"| {t} | {name} | +{pct:.2f}% |")
    return "\n".join(lines)


def main():
    if "여기에_발급받은_키" in FINNHUB_API_KEY:
        raise RuntimeError("FINNHUB_API_KEY를 채워넣지 않았습니다. 스크립트 상단을 확인하세요.")

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
    print(f"   총 {len(universe)}개 종목")

    print("3) Finnhub으로 Daily/Weekly/Monthly Top3 계산 중... (약 10분 소요)")
    daily, weekly, monthly = compute_top3_by_timeframe(universe)

    content = f"""# Market Data
_최종 갱신: {now_str}_

## Fear & Greed
{fg_text}

## Daily Top 3 (S&P500 + 나스닥100)
{format_table(daily)}

## Weekly Top 3 (S&P500 + 나스닥100)
{format_table(weekly)}

## Monthly Top 3 (S&P500 + 나스닥100)
{format_table(monthly)}
"""

    with open("Market_Data.md", "w", encoding="utf-8") as f:
        f.write(content)

    print("완료: Market_Data.md 작성됨")
    print(content)


if __name__ == "__main__":
    main()
