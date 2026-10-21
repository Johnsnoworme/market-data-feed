"""🛡️ 안전장치 점검(수동): 각 스크립트의 실제 종목 목록을 Yahoo에서 받아, 마지막 거래일 채움 비율을 잼.
결과: health/guard_probe.md  (90% 기준이 평소에 오작동하지 않는지 확인용)"""
import datetime, pandas as pd
from jb_scanner import get_large_caps, get_sp500, get_ndx, get_watchlist, download_daily, LEADERS, INDEXES
from ny_session import expected_session
out = [f"# 🛡️ 데이터 채움 점검 — {datetime.datetime.utcnow():%Y-%m-%d %H:%M} UTC (기대 거래일 {expected_session()})\n"]
def measure(name, tickers):
    tickers = sorted(set(tickers) | {"QQQ"})
    d = download_daily(tickers, period="1mo")["Close"]
    last = d["QQQ"].dropna().index[-1]
    row = d.loc[last]
    miss = sorted(row[row.isna()].index)
    out.append(f"- **{name}**: {int(row.notna().sum())}/{len(tickers)} = {row.notna().mean():.1%} (마지막 {str(last)[:10]}) · 빠진 것 {len(miss)}개: {', '.join(miss[:40])}")
try:
    import cloud_market_data as c
    measure("Market Data 백업", c.get_large_cap_universe())
except Exception as e: out.append(f"- Market Data 백업: 실패 {e}")
try:
    large, sp, ndx = get_large_caps(), get_sp500(), get_ndx()
    measure("김종봉·한 방(대형주+S&P+NDX+워치)", set(large) | set(sp) | set(ndx) | get_watchlist() | set(LEADERS) | set(INDEXES))
except Exception as e: out.append(f"- 김종봉: 실패 {e}")
try:
    import top3_follow as tf
    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    sig = {**tf.daily_signals(), **tf.archive_signals("weekly", "W"), **tf.archive_signals("monthly", "M"), **tf.json_signals("scanner/jb/picks.json", "J")}
    sig = {k: v for k, v in sig.items() if (today - pd.Timestamp(k[2])).days <= tf.DAYS}
    measure("풀백 추적", {k[0].replace(".", "-") for k in sig})
except Exception as e: out.append(f"- 풀백 추적: 실패 {e}")
try:
    import small_radar as sr
    measure("소형 레이더", sr.universe())
except Exception as e: out.append(f"- 소형 레이더: 실패 {e}")
open("health/guard_probe.md", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("\n".join(out))
