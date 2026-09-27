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

from jb_rules import check as rule_check

OUT = "scanner/jb/pullback"
TRACK_PATH = "scanner/jb/tracking.json"
FIB = [23.6, 38.2, 50.0, 61.8]
TOL = 1.5  # 레벨 '도달' 판정 여유 (%p)


ZONE_LO, ZONE_HI = 38.2, 70.0   # 2파 풀백 알림 구간 (정확한 숫자 대신 범위)


def zone(r):
    """되돌림 %를 구간으로 (알림 여부, 표시 이름, 순서). 38.2~70% 전체가 알림 구간."""
    if r < 0:
        return (False, "🚀 신고가", 0)
    if r < 23.6:
        return (False, "🟢 고점 근처 (0~23.6%)", 1)
    if r < ZONE_LO:
        return (False, "🟡 얕은 조정 (23.6~38.2%)", 2)
    if r < 50:
        return (True, "🔔 38.2~50%", 3)
    if r < 61.8:
        return (True, "🔔 50~61.8% (이상적)", 4)
    if r <= ZONE_HI:
        return (True, "🔔 61.8~70% (마지막 방어선)", 5)
    return (True, "⚠️ 70% 이탈 → 추적 종료", 8)


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
    # 👀 조기 경보 대상: $10B+ 전체 + 워치리스트 (월말 전에 월봉 전환 조짐 잡기)
    from jb_scanner import get_large_caps, get_watchlist, download_daily
    from jb_signals import early_monthly
    large = get_large_caps()
    wl = get_watchlist()
    active = [t for t, e in track.items() if e["status"] == "active"]
    universe = sorted(set(large) | wl | set(active) | {"QQQ"})
    d = download_daily(universe, period="2y")
    last_day = d["Close"]["QQQ"].dropna().index[-1]
    ny_date = last_day.strftime("%Y-%m-%d")
    if now_ny.weekday() < 5 and now_ny.hour >= 16 and last_day.date() != now_ny.date() and os.environ.get("JB_FORCE") != "1":
        print(f"오늘({today}) 종가가 아직 없음 → 건너뜀")
        return
    fname = f"{OUT}/{ny_date}.md"
    if os.path.exists(fname) and os.environ.get("JB_OVERWRITE") != "1":
        print(f"{fname} 이미 있음 → 건너뜀")
        return

    early = []
    expires = (last_day + timedelta(days=56)).strftime("%Y-%m-%d")
    for t in universe:
        if t == "QQQ" or t not in d["Close"].columns:
            continue
        if not (t in large or t in wl):
            continue
        try:
            e = early_monthly(d["Close"][t], d["High"][t], d["Close"]["QQQ"])
        except Exception:
            e = None
        if not e:
            continue
        name = large.get(t, ("", ""))[0]
        if any(w in name for w in ("Preferred", "Warrant", " Unit", "Depositary Shares")):
            continue
        tr = track.get(t)
        is_new = not (tr and tr.get("status") == "active" and "👀" in tr.get("kind", ""))
        early.append(dict(e, ticker=t, name=name, new=is_new))
        if tr and tr.get("status") == "active":
            if "👀" not in tr["kind"]:
                tr["kind"] += "👀"
            tr["expires"] = max(tr["expires"], expires)
        else:
            track[t] = {"name": name, "first_seen": ny_date, "last_seen": ny_date, "expires": expires,
                        "kind": "👀", "status": "active", "last_zone": ""}
    early.sort(key=lambda r: (not r["new"], -r["mtd_pct"]))
    active = [t for t, e in track.items() if e["status"] == "active"]

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
        l_date = l_win.idxmin()
        # 1파 확정: 고점이 '이번 주 이전'에 나왔고, 그 뒤 완성된 주봉이 고점 아래에서 마감 (윗꼬리/되돌림 시작)
        week_start = (last_day - timedelta(days=last_day.weekday())).normalize()
        wave1_done = h_date < week_start
        alert, name, order = zone(retr)
        if not wave1_done and order < 8:
            alert, name, order = (False, "⏳ 1파 진행 중 (고점이 이번 주)", 1)
        new_zone = name != e.get("last_zone", "")
        e["last_zone"] = name
        if order == 8:
            e["status"] = "broken"
        rc = None
        if alert and order < 8:
            try:
                rc = rule_check(d["Open"][t], hi, lo, c, d["Volume"][t], l, h, l_date, h_date, retr)
            except Exception as ex:
                print(t, "룰 체크 실패", ex)
        rows.append({
            "ticker": t, "name": e.get("name", ""), "kind": e.get("kind", ""), "first_seen": e["first_seen"],
            "expires": e["expires"], "close": round(close, 2), "swing_low": round(l, 2), "swing_high": round(h, 2),
            "wave1": f"{l_date.strftime('%m/%d')}→{h_date.strftime('%m/%d')}",
            "retrace_pct": round(retr, 1), "zone": name, "alert": alert, "new": new_zone, "order": order,
            "lv382": round(h - (h - l) * 0.382, 2), "lv50": round(h - (h - l) * 0.5, 2),
            "lv618": round(h - (h - l) * 0.618, 2), "lv70": round(h - (h - l) * 0.70, 2), "rules": rc,
        })

    kind_rank = lambda k: 0 if k.startswith("🚗") else (1 if "⭐" in k else 2)
    rows.sort(key=lambda r: (kind_rank(r["kind"]), -r["order"], r["ticker"]))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    alerts = [r for r in rows if r["alert"]]
    news = [r for r in alerts if r["new"]]
    md = f"# 🔔 풀백 알림 — {ny_date} 뉴욕 종가\n\n"
    md += "### 👀 월봉 전환 조짐 (이번 달 진행 중 · 월말 전 조기 경보)\n"
    md += "> 긴 바닥(12개월 중 6개월↑ 12개월선 아래) → 이번 달 +8%↑ 큰 양봉이 지난달 고점을 뚫고 12개월선에 닿거나 돌파 + 나스닥보다 강함\n\n"
    if early:
        md += "| 티커 | 회사 | 이번 달 | 나스닥 이번 달 | 12개월선 대비 | 지난달 고점 | 바닥 개월 |\n| :--- | :--- | ---: | ---: | ---: | ---: | ---: |\n"
        for r in early[:10]:
            md += (f"| {r['ticker']}{' 🆕' if r['new'] else ''} | {r['name']} | {r['mtd_pct']:+.1f}% | {r['qqq_mtd_pct']:+.1f}% | "
                   f"{r['vs_ma12m_pct']:+.1f}% | {r['prev_high']} | {r['base']}/12 |\n")
        if len(early) > 10:
            md += f"\n> [!note]- 나머지 {len(early) - 10}개\n> " + ", ".join(f"{r['ticker']} {r['mtd_pct']:+.0f}%" for r in early[10:]) + "\n"
    else:
        md += "오늘은 없음\n"
    md += "\n### 🔔 2파 풀백 구간 (추적 종목 = 지수보다 강했던 종목)\n"
    md += f"> 👀 조기 경보 {len(early)}개 (새로 {sum(r['new'] for r in early)}개) · 추적 {len(rows)}개 · 풀백 구간 {len(alerts)}개 · 오늘 새로 진입 {len(news)}개 · 생성 {now}\n"
    md += "> 1파 = 스윙 저점→고점 상승, 되돌림 % = 지금 2파로 1파의 몇 %를 내려왔나. 🚗 막 출발 / ⭐월·⭐주 인텔형 / 👀 조기 경보 / 🏁 학습용\n\n"
    ICON = ["👤", "🧱", "🔪", "🧠", "🌊", "🥊"]
    def rules_txt(r):
        rc = r.get("rules")
        if not rc:
            return "—", "—"
        marks = " ".join(k + ("✅" if v else "·") for k, v in rc["checks"].items())
        p = rc["plan"]
        plan = f"진입 {p['entry']} · 손절 {p['stop']} · 목표 {p['target1']} / {p['target2']}" + (f" · 손익비 {p['rr_t1']}" if p["rr_t1"] else "")
        return f"{rc['score']}/6 {marks} · 🧠{rc['room_left']}캔들", plan
    live = [r for r in alerts if r["order"] < 8]
    broken = [r for r in alerts if r["order"] == 8]
    live.sort(key=lambda r: (-(r["rules"]["score"] if r.get("rules") else 0), kind_rank(r["kind"]), r["ticker"]))
    top = [r for r in live if r.get("rules") and r["rules"]["score"] == 6]
    if top:
        md += "#### ✅ 자동 룰 6/6 통과 → 차트 직접 확인 + 👓 계획 확정\n"
        for r in top:
            md += f"- **{r['ticker']}** {r['kind']} {r['zone']} · {rules_txt(r)[1]}\n"
        md += "\n"
    if live:
        md += "| 티커 | 구분 | 구간 | 되돌림 | 1파 | 종가 | 38.2% · 50% · 61.8% · 70% | 룰 자동 체크 | 👓 계획 제안 |\n"
        md += "| :--- | :--- | :--- | ---: | :--- | ---: | :--- | :--- | :--- |\n"
        for r in live:
            rt, plan = rules_txt(r)
            md += (f"| {r['ticker']}{' 🆕' if r['new'] else ''} | {r['kind']} | {r['zone']} | {r['retrace_pct']:.1f}% | {r['wave1']} | {r['close']} | "
                   f"{r['lv382']} · {r['lv50']} · {r['lv618']} · {r['lv70']} | {rt} | {plan} |\n")
    else:
        md += "오늘 2파 풀백 구간(38.2~70%)에 있는 종목이 없어요.\n"
    if broken:
        md += "\n⚠️ 70% 이탈 → 추적 종료: " + ", ".join(r["ticker"] for r in broken) + "\n"
    waiting = [r for r in rows if not r["alert"]]
    if waiting:
        md += f"\n> [!note]- 대기 중 {len(waiting)}개 (38.2% 전 또는 1파 진행 중)\n> " + ", ".join(f"{r['ticker']} {r['retrace_pct']:.0f}%" for r in waiting) + "\n"
    md += "\n> 🆕 = 오늘 새 구간 · ⏳ = 1파 고점이 이번 주라 아직 확정 전(알림 안 함) · 룰 체크: 👤Big shadows 🧱Kwon 🔪Sharp 🧠Room for the left 🌊Liquidity 🥊Enter at the counter (기계 근사치, 차트 직접 확인 필수) · 👓 No plan no trade는 제안값을 보고 직접 확정\n"

    open(fname, "w", encoding="utf-8").write(md)
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    json.dump({"ny_date": ny_date, "early": early, "rows": rows, "generated_utc": now},
              open(f"{OUT}/latest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(track, open(TRACK_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(md)


if __name__ == "__main__":
    main()
