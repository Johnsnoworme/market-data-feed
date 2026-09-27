"""
김종봉 스캐너 추적 리스트 — 매일 풀백 구간 계산 (뉴욕 월~금 장 마감 후 GitHub Actions)
- 대상: scanner/jb/tracking.json 의 활성 종목 (신호 후 8주)
- 계산: 직전 상승(스윙 저점 → 스윙 고점) 대비 현재 종가가 얼마나 되돌렸나 (%)
    스윙 고점 = 신호 20거래일 전부터 오늘까지의 최고가
    스윙 저점 = 그 고점 이전 90거래일 안의 최저가
- 구간: 🟢 0~23.6 고점 근처 / 🟡 23.6~38.2 얕은 조정 / 🔔 38.2 도달, 38.2~50 / 🔔 50 도달, 50~61.8 / 🔔 61.8 도달 / ⚠️ 61.8 이탈(종가 기준 추세 깨짐) → 추적 종료
- 결과: scanner/jb/pullback/YYYY-MM-DD.md (뉴욕 날짜), scanner/jb/pullback/latest.md, latest.json
"""
import json
import os
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf

OUT = "scanner/jb/pullback"
TRACK_PATH = "scanner/jb/tracking.json"
FIB = [23.6, 38.2, 50.0, 61.8]
TOL = 1.5  # 레벨 '도달' 판정 여유 (%p)


def zone(r):
    """되돌림 %를 구간 이름으로 (알림 여부, 표시 이름, 순서)"""
    if r < 0:
        return (False, "🚀 신고가", 0)
    if r < 23.6:
        return (False, "🟢 고점 근처 (0~23.6%)", 1)
    if r < 38.2 - TOL:
        return (False, "🟡 얕은 조정 (23.6~38.2%)", 2)
    if r <= 38.2 + TOL:
        return (True, "🔔 38.2% 도달", 3)
    if r < 50 - TOL:
        return (True, "🔔 38.2~50% 사이", 4)
    if r <= 50 + TOL:
        return (True, "🔔 50% 도달 (이상적)", 5)
    if r < 61.8 - TOL:
        return (True, "🔔 50~61.8% 사이", 6)
    if r <= 61.8 + TOL:
        return (True, "🔔 61.8% 도달 (마지막 방어선)", 7)
    return (True, "⚠️ 61.8% 이탈 → 추적 종료", 8)


def main():
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(TRACK_PATH):
        print("추적 리스트 없음 → 종료")
        return
    track = json.load(open(TRACK_PATH, encoding="utf-8"))
    now_ny = pd.Timestamp.now(tz="America/New_York")
    today = now_ny.strftime("%Y-%m-%d")

    # 만료 처리
    for t, e in track.items():
        if e["status"] == "active" and e["expires"] < today:
            e["status"] = "expired"
    active = [t for t, e in track.items() if e["status"] == "active"]
    if not active:
        print("활성 추적 종목 없음")
        json.dump(track, open(TRACK_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return

    d = yf.download(active + ["QQQ"], period="1y", interval="1d", auto_adjust=True,
                    progress=False, group_by="column", threads=True)
    last_day = d["Close"]["QQQ"].dropna().index[-1]
    ny_date = last_day.strftime("%Y-%m-%d")
    if now_ny.weekday() < 5 and now_ny.hour >= 16 and last_day.date() != now_ny.date() and os.environ.get("JB_FORCE") != "1":
        print(f"오늘({today}) 종가가 아직 없음 → 건너뜀")
        return
    fname = f"{OUT}/{ny_date}.md"
    if os.path.exists(fname) and os.environ.get("JB_OVERWRITE") != "1":
        print(f"{fname} 이미 있음 → 건너뜀")
        return

    rows = []
    for t in active:
        e = track[t]
        try:
            c = d["Close"][t].dropna()
            hi = d["High"][t].dropna()
            lo = d["Low"][t].dropna()
        except KeyError:
            continue
        if len(c) < 30:
            continue
        start = pd.Timestamp(e["first_seen"]) - timedelta(days=28)
        h_win = hi[hi.index >= start]
        if h_win.empty:
            continue
        h_date, h = h_win.idxmax(), float(h_win.max())
        l_win = lo[(lo.index < h_date)].iloc[-90:]
        if l_win.empty:
            continue
        l = float(l_win.min())
        if h <= l:
            continue
        close = float(c.iloc[-1])
        retr = (h - close) / (h - l) * 100
        alert, name, order = zone(retr)
        new_zone = name != e.get("last_zone", "")
        e["last_zone"] = name
        if order == 8:
            e["status"] = "broken"
        rows.append({
            "ticker": t, "name": e.get("name", ""), "kind": e.get("kind", ""), "first_seen": e["first_seen"],
            "expires": e["expires"], "close": round(close, 2), "swing_low": round(l, 2), "swing_high": round(h, 2),
            "retrace_pct": round(retr, 1), "zone": name, "alert": alert, "new": new_zone, "order": order,
            "lv382": round(h - (h - l) * 0.382, 2), "lv50": round(h - (h - l) * 0.5, 2), "lv618": round(h - (h - l) * 0.618, 2),
        })

    kind_rank = lambda k: 0 if k.startswith("🚗") else (1 if "⭐" in k else 2)
    rows.sort(key=lambda r: (kind_rank(r["kind"]), -r["order"], r["ticker"]))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    alerts = [r for r in rows if r["alert"]]
    news = [r for r in alerts if r["new"]]
    md = f"# 🔔 풀백 알림 — {ny_date} 뉴욕 종가\n\n"
    md += f"> 추적 {len(rows)}개 · 풀백 구간 {len(alerts)}개 · 오늘 새로 진입 {len(news)}개 · 생성 {now}\n"
    md += "> 되돌림 % = 직전 상승(스윙 저점→고점) 중 얼마나 내려왔나. 🚗 막 출발 / ⭐ 인텔형 / 🏁 학습용\n\n"
    if alerts:
        md += "| 티커 | 구분 | 구간 | 되돌림 | 종가 | 38.2% | 50% | 61.8% | 신호일 |\n"
        md += "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |\n"
        for r in alerts:
            new = " 🆕" if r["new"] else ""
            md += (f"| {r['ticker']}{new} | {r['kind']} | {r['zone']} | {r['retrace_pct']:.1f}% | {r['close']} | "
                   f"{r['lv382']} | {r['lv50']} | {r['lv618']} | {r['first_seen']} |\n")
    else:
        md += "오늘 풀백 구간(38.2% 이상)에 들어온 종목이 없어요.\n"
    waiting = [r for r in rows if not r["alert"]]
    if waiting:
        md += f"\n> [!note]- 대기 중 {len(waiting)}개 (아직 38.2% 전)\n> " + ", ".join(f"{r['ticker']} {r['retrace_pct']:.0f}%" for r in waiting) + "\n"
    md += "\n> 🆕 = 오늘 새 구간에 들어옴 · 알림은 '지켜볼 자리'라는 뜻이지 진입 신호가 아님 → 7개 룰 확인\n"

    open(fname, "w", encoding="utf-8").write(md)
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    json.dump({"ny_date": ny_date, "rows": rows, "generated_utc": now},
              open(f"{OUT}/latest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(track, open(TRACK_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(md)


if __name__ == "__main__":
    main()
