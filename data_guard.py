"""
🛡️ 데이터 안전장치 (2026-10-21 추가 — BTSGU·BIPJ·BRKRP 사고 후)

원칙: 틀린 숫자를 저장하느니 저장하지 않는다. (저장 안 하면 다음 예약 실행이 다시 시도하고,
      계속 안 되면 🩺 건강검진이 ❌로 알림)

1) is_common(name): 보통주·ADR만 True. 우선주·채권·유닛·워런트·권리·When Issued는 False
   (Finviz에 없는 증권 → 링크가 안 열리고, 숫자도 주식과 성격이 다름)
2) require_coverage(close, name): 마지막 거래일에 가격이 있는 종목이 90% 미만이면 저장하지 않고 종료
   (QQQ 하나만 최신이고 나머지는 반쪽인 경우를 막음 — ny_session.require_fresh는 QQQ만 봄)
"""
import os
import re
import sys

NON_COMMON = re.compile(
    r"preferred|\bnotes?\b|debentures?|subordinated|\bunits?\b|warrants?\b|\brights\b|"
    r"tangible equity|when[- ]issued|%|\bdue \d{4}", re.I)


def is_common(name):
    return not NON_COMMON.search(name or "")


def require_coverage(close, name="", min_ratio=0.9):
    """close: 날짜×종목 종가 표. 마지막 날짜에 값이 있는 종목 비율이 min_ratio 미만이면 종료."""
    cols = [c for c in close.columns if close[c].notna().any()]
    asked = len(close.columns)
    if asked == 0:
        print(f"⛔ {name}: 가격 데이터가 하나도 없음 → 저장하지 않고 종료")
        sys.exit(0)
    last = close.index[-1]
    have = int(close.loc[last].notna().sum())
    ratio = have / asked
    msg = f"{name} 데이터 채움: 마지막 거래일 {str(last)[:10]}에 {have}/{asked}개 ({ratio:.0%}) · 가격 있는 종목 {len(cols)}개"
    if ratio >= min_ratio or os.environ.get("DATA_FORCE") == "1":
        print(f"✅ {msg}")
        return ratio
    print(f"⛔ {msg} — {min_ratio:.0%} 미만이라 저장하지 않음 (Yahoo가 일부만 줌) → 다음 실행에서 다시 시도")
    sys.exit(0)
