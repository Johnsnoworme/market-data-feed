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


ZONE_LO, ZONE_HI = 30.0, 70.0   # 2파 풀백 알림 구간: 30~70% 안이면 어떤 가격이든 알림


def zone(r):
    """되돌림 %를 구간으로 (알림 여부, 표시 이름, 순서). 30~70% 전체가 알림 구간."""
    if r < 0:
        return (False, "🚀 신고가", 0)
    if r < ZONE_LO:
        return (False, "🟢 고점 근처 (0~30%)", 1)
    if r < 38.2:
        return (True, "🔔 30~38.2%", 2)
    if r < 50:
        return (True, "🔔 38.2~50%", 3)
    if r < 61.8:
        return (True, "🔔 50~61.8%", 4)
    if r <= ZONE_HI:
        return (True, "🔔 61.8~70% (마지막 방어선)", 5)
    return (True, "⚠️ 70% 이탈 → 추적 종료", 8)


def swing(H, L, start, lookback, close, last_day, tf):
    """주봉/월봉 스윙: start 이후 최고가(1파 고점) ← 그 전 lookback개 캔들 최저가(1파 저점)"""
    H, L = H.dropna(), L.dropna()
    hw = H[H.index >= start]
    if hw.empty:
        return None
    hd, h = hw.idxmax(), float(hw.max())
    lw = L[L.index < hd].iloc[-lookback:]
    if lw.empty:
        return None
    ld, l = lw.idxmin(), float(lw.min())
    if h <= l:
        return None
    cur = H.index[-1]  # 진행 중인 이번 주/이번 달 캔들
    return {"tf": tf, "low": round(l, 2), "high": round(h, 2), "retr": round((h - close) / (h - l) * 100, 1),
            "done": hd < cur,  # 1파 고점이 이번 캔들 이전 = 캔들 마감으로 확정
            "wave1": f"{ld.strftime('%Y-%m' if tf == 'M' else '%m/%d')}→{hd.strftime('%Y-%m' if tf == 'M' else '%m/%d')}",
            "lv": {k: round(h - (h - l) * k / 100, 2) for k in (30, 38.2, 50, 61.8, 70)}}


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
    from jb_scanner import get_large_caps, get_watchlist, download_daily, fv
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
        close = float(c.iloc[-1])
        # 주봉 기준 1파: 신호 8주 전부터 지금까지 주봉 최고가 ← 그 전 26주 안 주봉 최저가
        # 월봉 기준 1파: 신호 6개월 전부터 월봉 최고가 ← 그 전 24개월 안 월봉 최저가 (지금 가격이 1파 저점 아래면 월봉 1파 없음)
        W = swing(hi.resample("W-FRI").max(), lo.resample("W-FRI").min(),
                  pd.Timestamp(e["first_seen"]) - timedelta(weeks=8), 26, close, last_day, "W")
        M = swing(hi.resample("ME").max(), lo.resample("ME").min(),
                  pd.Timestamp(e["first_seen"]) - pd.DateOffset(months=6), 24, close, last_day, "M")
        if M and M["retr"] > 100:
            M = None
        if not W and not M:
            continue
        zw = zone(W["retr"]) if W else (False, "—", -1)
        zm = zone(M["retr"]) if M else (False, "—", -1)
        aw, am = zw[0] and zw[2] < 8, zm[0] and zm[2] < 8
        alert = aw or am
        broken = bool(W) and zw[2] == 8 and not am   # 주봉 70% 이탈 + 월봉도 구간 밖 → 추적 종료
        if broken:
            alert, order = True, 8
        else:
            order = max(zw[2] if aw else -1, zm[2] if am else -1)
        label = lambda z, S: (z[1] + ("" if S["done"] else " ⏳미확정")) if S and z[0] else (z[1] if S else "—")
        name = f"주 {label(zw, W)} / 월 {label(zm, M)}"
        key = f"{zw[1]}|{zm[1]}"
        new_zone = alert and key != e.get("last_zone", "")
        e["last_zone"] = key
        if order == 8:
            e["status"] = "broken"
        rows.append({
            "ticker": t, "name": e.get("name", ""), "kind": e.get("kind", ""), "first_seen": e["first_seen"],
            "expires": e["expires"], "close": round(close, 2), "zone": name, "alert": alert, "new": new_zone,
            "order": order, "W": W, "M": M,
            "retrace_pct": round(min([x["retr"] for x in (W, M) if x and 30 <= x["retr"] <= 70] or [x["retr"] for x in (W, M) if x]), 1),
        })

    kind_rank = lambda k: 0 if k.startswith("🎯") and "↑" not in k else (1 if k.startswith("🎯") or k.startswith("🚗") else (2 if "⭐" in k or "👀" in k else 3))
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
            md += (f"| {fv(r['ticker'])}{' 🆕' if r['new'] else ''} | {r['name']} | {r['mtd_pct']:+.1f}% | {r['qqq_mtd_pct']:+.1f}% | "
                   f"{r['vs_ma12m_pct']:+.1f}% | {r['prev_high']} | {r['base']}/12 |\n")
        if len(early) > 10:
            md += f"\n> [!note]- 나머지 {len(early) - 10}개\n> " + ", ".join(f"{r['ticker']} {r['mtd_pct']:+.0f}%" for r in early[10:]) + "\n"
    else:
        md += "오늘은 없음\n"
    md += "\n### 🔔 2파 풀백 구간 (추적 종목 = 지수보다 강했던 종목)\n"
    md += f"> 👀 조기 경보 {len(early)}개 (새로 {sum(r['new'] for r in early)}개) · 추적 {len(rows)}개 · 풀백 구간 {len(alerts)}개 · 오늘 새로 진입 {len(news)}개 · 생성 {now}\n"
    md += "> 주봉·월봉 두 기준으로 따로 계산. 1파 = 스윙 저점→고점, 되돌림 % = 2파로 1파의 몇 %를 내려왔나. 둘 중 하나라도 30~70%면 알림. 🎯 오르려는 후보 / 🎯↑ 이미 많이 오른 후보 / 👀 월봉 조기 경보\n\n"
    live = [r for r in alerts if r["order"] < 8]
    broken = [r for r in alerts if r["order"] == 8]
    live.sort(key=lambda r: (not r["new"], kind_rank(r["kind"]), -r["order"], r["ticker"]))
    def lv(S):
        if not S:
            return "—"
        v = S["lv"]
        return f"{S['retr']:.0f}% · 1파 {S['wave1']} ({S['low']}→{S['high']}) · 30~70%: {v[30]} ~ {v[70]} (50%: {v[50]})"
    if live:
        md += "| 티커 | 구분 | 구간 (주봉 / 월봉) | 종가 | 주봉 풀백 | 월봉 풀백 | 신호일 |\n"
        md += "| :--- | :--- | :--- | ---: | :--- | :--- | :--- |\n"
        hdr = "| 티커 | 구분 | 구간 (주봉 / 월봉) | 종가 | 주봉 풀백 | 월봉 풀백 | 신호일 |\n| :--- | :--- | :--- | ---: | :--- | :--- | :--- |\n"
        rowf = lambda r: (f"| {fv(r['ticker'])}{' 🆕' if r['new'] else ''} | {r['kind']} | {r['zone']} | {r['close']} | "
                          f"{lv(r['W'])} | {lv(r['M'])} | {r['first_seen']} |\n")
        for r in live[:10]:
            md += rowf(r)
        if len(live) > 10:
            md += f"\n> [!note]- 나머지 풀백 {len(live) - 10}개\n" + "".join("> " + l + "\n" for l in (hdr + "".join(rowf(r) for r in live[10:])).strip().split("\n"))
    else:
        md += "오늘 2파 풀백 구간(주봉 또는 월봉 30~70%)에 있는 종목이 없어요.\n"
    if broken:
        md += "\n⚠️ 70% 이탈 → 추적 종료: " + ", ".join(r["ticker"] for r in broken) + "\n"
    waiting = [r for r in rows if not r["alert"]]
    if waiting:
        md += f"\n> [!note]- 대기 중 {len(waiting)}개 (아직 30% 전)\n> " + ", ".join(f"{r['ticker']} 주{r['W']['retr'] if r['W'] else '-'}/월{r['M']['retr'] if r['M'] else '-'}" for r in waiting) + "\n"
    md += "\n> 🆕 = 오늘 새 구간 · ⏳미확정 = 1파 고점이 이번 주(주봉) / 이번 달(월봉)이라 캔들 마감 전 · 알림은 '지켜볼 자리' → 7개 룰은 차트로 직접 확인\n"

    open(fname, "w", encoding="utf-8").write(md)
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    json.dump({"ny_date": ny_date, "early": early, "rows": rows, "generated_utc": now},
              open(f"{OUT}/latest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(track, open(TRACK_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(md)


if __name__ == "__main__":
    main()
