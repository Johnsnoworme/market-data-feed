"""
🗽 뉴욕 종가 확인 (2026-10-05 추가)

왜 필요한가:
- Yahoo(yfinance) 일봉은 뉴욕 장 마감 후 약 5~6시간이 지나야 그날 줄이 생긴다
  (실측: 마감 16:00 → 그날 종가는 뉴욕 밤 21:15~21:45 사이에야 들어옴).
- 그 전에 돌면 '어제 데이터'를 오늘 것처럼 저장하는 일이 생겼다
  (한 방 레이더가 매일 하루 늦게 기록 · 2026-10-02 김종봉 주간 기록 누락).

규칙:
- expected_session(): 지금 시점에서 '마지막으로 끝난' 뉴욕 거래일 (주말·휴장일 제외, 마감 + 30분 기준)
- require_fresh(last_day, name): 다운로드한 마지막 거래일이 그 날짜보다 이르면
  아무것도 저장하지 않고 종료 → 다음 예약 실행에서 다시 시도
- 강제 실행: 환경변수 DATA_FORCE=1
"""
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
READY_AFTER = dt.time(16, 30)  # 장 마감 16:00 + 30분

# NYSE 휴장일 (매년 초에 다음 해를 추가)
NYSE_HOLIDAYS = {
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
    "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    # 2027
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
    "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}


def is_trading_day(d):
    return d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS


def expected_session(now=None):
    """지금 시점에서 종가가 확정된 마지막 뉴욕 거래일 (date)."""
    n = (now or dt.datetime.now(dt.timezone.utc)).astimezone(NY)
    d = n.date()
    if not (is_trading_day(d) and n.time() >= READY_AFTER):
        d -= dt.timedelta(days=1)
    while not is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def require_fresh(last_day, name=""):
    """last_day(다운로드 데이터의 마지막 날짜)가 최신 거래일이 아니면 저장하지 않고 종료."""
    last = last_day.date() if hasattr(last_day, "date") else last_day
    exp = expected_session()
    if last >= exp:
        print(f"✅ {name} 데이터 최신: {last} (기대 거래일 {exp})")
        return True
    if os.environ.get("DATA_FORCE") == "1":
        print(f"⚠️ {name} 데이터가 {last}까지만 있음 (기대 {exp}) — DATA_FORCE=1이라 그대로 진행")
        return True
    print(f"⏳ {name} {exp} 종가가 아직 Yahoo에 없음 (마지막 {last}) → 저장하지 않고 다음 실행에서 다시 시도")
    sys.exit(0)
