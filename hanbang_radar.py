"""
🎯 한 방 레이더 (매일, 뉴욕 장 마감 후) — 이동평균 없이 가격·거래량만 본다
1) 🟢 공포 속 기회: 시총 $10B+ 중 52주 고점 대비 -35% 이하로 빠졌는데, 매도가 마르고(하락일 거래량 감소)
   저점이 덜 내려가고, 최근 지수만큼은 버티는 종목 → 좋은 회사가 과한 공포에 빠졌을 수 있는 자리
2) 🧲 매집 흔적 점수(0~10): 오른 날 거래량 > 내린 날 거래량 · 하락일 거래량 감소 · 지수 하락일에 선방 · 종가가 하루 범위 위쪽
3) ⭐ 워치리스트 상태: 1군·2군 전부의 고점 대비·지수 대비·🧲·풀백 위치
4) 🏁 통합 풀: ⭐워치 · 🏆Top3(D/W/M) · 🧭김종봉 · 🦅드러켄밀러(신규·늘림) · 🟢공포 → 한 줄에 출처를 모아 가격 점수로 순위
   (📺소수몽키는 옵시디언 대시보드에서 합친다 — 볼트 파일이라서)
5) 🌤️ 시장 날씨: QQQ 고점 대비 · 20일 흐름 · 대장주 8개 중 지수보다 강한 수 · Fear & Greed
결과: hanbang/radar/latest.md · latest.json · YYYY-MM-DD.md (옵시디언 🎯 한 방 대시보드 + Claude 매일 심사가 읽음)
"""
import json, os, re
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from jb_scanner import get_large_caps, get_watchlist, download_daily, yf_symbol

OUT = "hanbang/radar"
FEAR_DD = -35.0          # 52주 고점 대비 이 %보다 더 빠지면 공포 후보
MIN_DOLLAR_VOL = 50_000_000
FEAR_SHOW = 12


def read_watchlist():
    t1, t2, tier = [], [], 1
    if os.path.exists("watchlist.txt"):
        for line in open("watchlist.txt", encoding="utf-8"):
            if line.strip().startswith("# ⭐ 2군"):
                tier = 2
            s = line.split("#")[0].strip().upper()
            if s:
                (t1 if tier == 1 else t2).append(yf_symbol(s))
    return t1, t2


def tracked():
    out = {}
    try:
        for r in json.load(open("top3/follow/latest.json", encoding="utf-8"))["rows"]:
            out[yf_symbol(r["ticker"])] = "🧭김종봉" if r.get("src") == "J" else "🏆Top3"
    except Exception as e:
        print(f"Top3 추적 읽기 실패: {e}")
    return out


LEADERS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "TSLA"]


def top3_rows():
    """top3/follow/latest.json → {ticker: row} (신호 기준 풀백 위치 포함, 종료된 것 제외)"""
    out = {}
    try:
        for r in json.load(open("top3/follow/latest.json", encoding="utf-8"))["rows"]:
            if r.get("order", 0) >= 8:
                continue
            out[yf_symbol(r["ticker"])] = r
    except Exception as e:
        print(f"Top3 추적 읽기 실패: {e}")
    return out


def druck_moves():
    """드러켄밀러 최신 13F에서 새로 산 것·주식 수 20%↑ 늘린 것 (비중 0.8%↑)"""
    try:
        qs = sorted(f[:-5] for f in os.listdir("druck/quarters") if f.endswith(".json"))
        cmap = json.load(open("druck/cusip_map.json"))
        cur = json.load(open(f"druck/quarters/{qs[-1]}.json"))["holdings"]
        prev = json.load(open(f"druck/quarters/{qs[-2]}.json"))["holdings"]
    except Exception as e:
        print(f"13F 읽기 실패: {e}")
        return {}, ""
    tot = sum(h["value"] for h in cur) or 1
    pk = {(h["cusip"], h["putcall"]): h for h in prev}
    out = {}
    for h in cur:
        t = cmap.get(h["cusip"])
        if not t or h["putcall"] == "PUT" or h["value"] / tot < 0.008:
            continue
        p = pk.get((h["cusip"], h["putcall"]))
        tag = "신규" if not p else ("늘림" if p["shares"] and h["shares"] / p["shares"] >= 1.2 else None)
        if tag:
            t = yf_symbol(t)
            out[t] = f"{tag}{'(콜)' if h['putcall'] == 'CALL' else ''}"
    return out, qs[-1]


def fear_greed():
    try:
        m = re.search(r"Fear & Greed Index\s*\n\s*([\d.]+)\s*/\s*100\s*\(([^)]+)\)", open("Market_Data.md", encoding="utf-8").read())
        return (float(m.group(1)), m.group(2)) if m else (None, "")
    except Exception:
        return (None, "")


def zone_of(r):
    if r is None:
        return ("—", 9)
    if r < 0:
        return ("🚀 신고가", 0)
    if r < 30:
        return ("🟢 고점 근처", 1)
    if r < 38.2:
        return ("🔔 30~38%", 2)
    if r < 50:
        return ("🔔 38~50%", 3)
    if r < 61.8:
        return ("🔔 50~62%", 4)
    if r <= 70:
        return ("🔔 62~70% 방어선", 5)
    if r <= 100:
        return ("⚠️ 70% 이탈", 8)
    return ("⬇️ 1파 저점 아래", 8)


def weekly_pullback(c, h, l):
    """신호 없는 종목용 주봉 풀백: 최근 26주 최고가(1파 고점) ← 그 전 26주 최저가(1파 저점), 지금 몇 % 되돌렸나"""
    H, Lo = h.resample("W-FRI").max().dropna(), l.resample("W-FRI").min().dropna()
    if len(H) < 8:
        return None
    hw = H.iloc[-26:]
    hd, hi = hw.idxmax(), float(hw.max())
    lo = float(Lo[Lo.index <= hd].iloc[-26:].min())
    if hi <= lo or hi / lo - 1 < 0.08:
        return None
    return round((hi - float(c.iloc[-1])) / (hi - lo) * 100, 1)


def wk(d):
    """'2026-09-25' → '9월4주'"""
    try:
        y, m, dd = map(int, str(d)[:10].split("-"))
        return f"{m}월{(dd - 1) // 7 + 1}주"
    except Exception:
        return ""


def quality(f):
    """🔢 숫자 게이트 (기관이 좋아하는 모양): 흑자+매출 10%↑ 또는 흑자+순이익 20%↑ = ✅ / 적자지만 매출 25%↑ = 🟡 / 나머지 ❌"""
    if not f:
        return "❔", None
    pm, rev, eq = f.get("pm"), f.get("rev"), f.get("eq")
    if pm is not None and pm > 0 and ((rev or 0) >= 0.10 or (eq or 0) >= 0.20):
        return "✅ 숫자 좋음", True
    if (pm is None or pm <= 0) and (rev or 0) >= 0.25:
        return "🟡 적자·고성장", True
    return "❌ 숫자 약함", False


def price_score(s):
    """가격 점수 (0~6): 📈 지수보다 강함 · 🎯 자리 · 🧲 매집 흔적. 출처 겹침·1군 가산은 대시보드에서 (+3까지)"""
    sc = 0
    sc += 2 if s["vs63"] >= 15 else 1 if s["vs63"] >= 0 else 0
    o = s["zone_order"]
    if s.get("fear"):
        sc += 2
    elif 2 <= o <= 5:
        sc += 2
    elif o == 8:
        sc -= 1
    a = s.get("acc")
    if a:
        sc += 2 if a["score"] >= 7 else 1 if a["score"] >= 5 else 0
    return max(sc, 0)


def accumulation(c, h, l, v, q):
    """🧲 매집 흔적 0~10 + 세부. 최근 50거래일."""
    c, h, l, v, q = [x.dropna().iloc[-60:] for x in (c, h, l, v, q)]
    idx = c.index.intersection(v.index).intersection(q.index).intersection(h.index).intersection(l.index)
    if len(idx) < 40:
        return None
    c, h, l, v, q = c[idx], h[idx], l[idx], v[idx], q[idx]
    r, qr = c.pct_change(), q.pct_change()
    w = slice(-50, None)
    upv, dnv = v[w][r[w] > 0].sum(), v[w][r[w] < 0].sum()
    udr = upv / dnv if dnv else 2.0
    dn = v[r < 0]
    dry = (dn.iloc[-5:].mean() / dn.iloc[-15:-5].mean()) if len(dn) >= 15 and dn.iloc[-15:-5].mean() else 1.0
    qd = qr[-20:] < -0.005
    beat = float((r[-20:][qd] > qr[-20:][qd]).mean()) if qd.sum() else 0.5
    rng = (h - l).replace(0, np.nan)
    clv = float(((c - l) / rng).iloc[-10:].mean())
    s = 0
    s += 3 if udr >= 1.3 else 2 if udr >= 1.1 else 1 if udr >= 0.95 else 0
    s += 2 if dry <= 0.75 else 1 if dry <= 0.95 else 0
    s += 3 if beat >= 0.7 else 2 if beat >= 0.55 else 1 if beat >= 0.4 else 0
    s += 2 if clv >= 0.6 else 1 if clv >= 0.5 else 0
    return dict(score=int(s), udr=round(float(udr), 2), dry=round(float(dry), 2), beat=round(beat, 2),
                clv=round(clv if clv == clv else 0.5, 2), qd_days=int(qd.sum()))


def fundamentals(t):
    try:
        i = yf.Ticker(t).info
    except Exception:
        return {}
    g = lambda k: i.get(k)
    return dict(pm=g("profitMargins"), rev=g("revenueGrowth"), eq=g("earningsQuarterlyGrowth"),
                fpe=g("forwardPE"), cap=g("marketCap"), name=g("shortName") or "",
                industry=g("industry") or "", sector=g("sector") or "")


# 🧩 산업 → 18개월 지도 테마 (없으면 "테마 밖")
THEME_RULES = [
    ("⚡ 전력·에너지 병목", ("Electrical Equipment", "Independent Power", "Renewable", "Utilities - Regulated Electric", "Uranium", "Copper", "Oil & Gas Equipment")),
    ("🧠 AI 칩·장비", ("Semiconductor",)),
    ("🔌 AI 인프라 (메모리·광·부품)", ("Computer Hardware", "Electronic Components", "Communication Equipment", "Scientific & Technical Instruments")),
    ("🖥️ 소프트웨어", ("Software",)),
    ("🌐 AI 플랫폼·인터넷", ("Internet Content", "Internet Retail", "Telecom Services", "Entertainment")),
    ("🪙 크립토·토큰화·금융 인프라", ("Capital Markets", "Financial Data", "Credit Services")),
    ("🧬 AI 바이오·헬스", ("Biotechnology", "Diagnostics", "Drug Manufacturers", "Medical Devices", "Medical Instruments", "Health Information")),
    ("🚀 우주·방산", ("Aerospace",)),
    ("🤖 피지컬 AI·EV", ("Auto Manufacturers", "Specialty Industrial Machinery")),
    ("🛡️ 보안", ("Security",)),
]


def theme_of(f):
    ind = (f or {}).get("industry", "")
    for name, keys in THEME_RULES:
        if any(k in ind for k in keys):
            return name
    return "· 테마 밖" if ind else "❔"


def size_of(f):
    c = (f or {}).get("cap")
    if not c:
        return "❔"
    return "🐘 대형" if c >= 50e9 else ("🐕 중형" if c >= 10e9 else "🐁 소형")


def ftxt(f):
    if not f:
        return "—"
    parts = []
    pm = f.get("pm")
    if pm is not None:
        parts.append("흑자" if pm > 0 else "적자")
    if f.get("rev") is not None:
        parts.append(f"매출 {f['rev'] * 100:+.0f}%")
    if f.get("eq") is not None:
        parts.append(f"순이익(분기) {f['eq'] * 100:+.0f}%")
    return " · ".join(parts) or "—"


def fvl(t):
    return f"[{t}](https://finviz.com/quote.ashx?t={t.replace('-', '.')}&p=w)"


def main():
    os.makedirs(OUT, exist_ok=True)
    large = get_large_caps()
    t1, t2 = read_watchlist()
    t3 = top3_rows()
    dm, dq = druck_moves()
    universe = set(large) | set(t1) | set(t2) | set(t3) | set(dm) | set(LEADERS) | {"QQQ"}
    print(f"검사 대상 {len(universe)}개")
    d = download_daily(universe, period="1y")
    C, H, L, V = d["Close"], d["High"], d["Low"], d["Volume"]
    q = C["QQQ"].dropna()
    ny = q.index[-1].strftime("%Y-%m-%d")
    cache = {}

    def stats(t):
        if t in cache:
            return cache[t]
        cache[t] = None
        if t not in C.columns:
            return None
        c = C[t].dropna()
        if len(c) < 45 or c.index[-1] != q.index[-1]:
            return None
        n = min(63, len(c) - 1)
        hi = c.iloc[-252:].max()
        dd = (c.iloc[-1] / hi - 1) * 100
        r10 = (c.iloc[-1] / c.iloc[-11] - 1) * 100
        q10 = (q.iloc[-1] / q.iloc[-11] - 1) * 100
        rn = (c.iloc[-1] / c.iloc[-1 - n] - 1) * 100
        qn = (q.iloc[-1] / q.iloc[-1 - n] - 1) * 100
        lows_hold = c.iloc[-5:].min() >= c.iloc[-15:-5].min() * 0.97
        dv = float((c.iloc[-20:] * V[t].reindex(c.index).iloc[-20:]).mean())
        acc = accumulation(c, H[t], L[t], V[t], q)
        if t in t3:                       # Top 3·김종봉: 신호 기준 풀백 (top3_follow.py와 같은 값)
            retr, basis = t3[t]["retr"], "신호"
        else:
            retr, basis = weekly_pullback(c, H[t].dropna(), L[t].dropna()), "주봉"
        zn, zo = zone_of(retr)
        r = dict(ticker=t, close=round(float(c.iloc[-1]), 2), dd=round(float(dd), 1), vs10=round(float(r10 - q10), 1),
                 vs63=round(float(rn - qn), 1), lows_hold=bool(lows_hold), dollar_vol=dv, acc=acc,
                 retr=retr, zone=zn, zone_order=zo, basis=basis, fear=False)
        cache[t] = r
        return r

    # 🟢 공포 속 기회
    fear = []
    for t in large:
        s = stats(t)
        if not s or not s["acc"] or s["dd"] > FEAR_DD or s["dollar_vol"] < MIN_DOLLAR_VOL:
            continue
        a = s["acc"]
        ok = (a["dry"] <= 0.95) + s["lows_hold"] + (s["vs10"] >= -2)
        if ok >= 2:
            s["fear_ok"], s["fear"] = int(ok), True
            fear.append(s)
    fear.sort(key=lambda s: (-(s["acc"]["score"] + s["fear_ok"]), s["dd"]))
    fear = fear[:FEAR_SHOW]
    fear_set = {s["ticker"] for s in fear}
    for s in fear:
        s["f"] = fundamentals(s["ticker"])
    # 워치리스트 (공포 조건은 대형주 전체 기준으로 이미 표시됨; 워치리스트는 크게 빠짐만 따로)
    wl = {1: [], 2: []}
    for tier, lst in ((1, t1), (2, t2)):
        for t in lst:
            s = stats(t)
            if s:
                wl[tier].append(dict(s, tier=tier))
    # 🏁 통합 풀 (📺 소수몽키는 대시보드에서 합침) — 출처마다 날짜까지
    src = {}
    for t in t1:
        src.setdefault(t, []).append("⭐워치 1군")
    for t in t2:
        src.setdefault(t, []).append("⭐워치 2군")
    for t, r in t3.items():
        if r.get("src") == "J":
            src.setdefault(t, []).append(f"🧭김종봉 ({wk(r.get('date'))})")
        else:
            src.setdefault(t, []).append("🏆Top3 " + "·".join(k for k in ("D", "W", "M") if k in r.get("kinds", [])) + f" ({wk(r.get('date'))})")
    for t, tag in dm.items():
        src.setdefault(t, []).append(f"🦅드러켄밀러 {dq[2:4]}Q{dq[-1]} {tag}")
    for t in fear_set:
        src.setdefault(t, []).append("🟢공포 레이더")
    wl_set = set(t1) | set(t2)
    pool = []
    for t, tags in src.items():
        s = stats(t)
        if not s:
            continue
        f = next((x.get("f") for x in fear if x["ticker"] == t), None) or fundamentals(t)
        ql, qp = quality(f)
        ps = price_score(s)
        groups = {g[0] for g in tags}
        bonus = (2 if len(groups) >= 3 else 1 if len(groups) == 2 else 0) + (1 if "⭐워치 1군" in tags else 0)
        pool.append(dict(ticker=t, sources=tags, price_score=ps, score=ps + bonus, dd=s["dd"], vs63=s["vs63"],
                         acc=(s["acc"] or {}).get("score"), zone=s["zone"], zone_order=s["zone_order"], retr=s["retr"], basis=s["basis"],
                         fear=bool(s.get("fear")), quality=ql, q_pass=(True if t in wl_set else qp), watch=t in wl_set,
                         fund=ftxt(f), theme=theme_of(f), size=size_of(f), industry=(f or {}).get("industry", ""),
                cap_b=round((f or {}).get("cap") / 1e9, 1) if (f or {}).get("cap") else None))
    pool.sort(key=lambda r: -r["vs63"])
    # 🧩 오늘의 흐름: 최근 Top 3·김종봉 신호를 테마·산업으로 묶기
    flow = {}
    for r in pool:
        if any(x.startswith(("🏆", "🧭")) for x in r["sources"]):
            flow.setdefault(r["theme"], []).append(f"{r['ticker']}({r['industry'] or '?'})")
    flow = dict(sorted(flow.items(), key=lambda kv: -len(kv[1])))
    # 전체 가격 지표 (대시보드에서 📺 소수몽키 종목 찾을 때 씀)
    allstats = {}
    for t in universe - {"QQQ"}:
        s = stats(t)
        if s:
            allstats[t] = dict(dd=s["dd"], vs63=s["vs63"], acc=(s["acc"] or {}).get("score"), zone=s["zone"],
                               zone_order=s["zone_order"], retr=s["retr"], basis=s["basis"], ps=price_score(s))
    # 🌤️ 시장 날씨
    qdd = (q.iloc[-1] / q.iloc[-252:].max() - 1) * 100
    q20 = (q.iloc[-1] / q.iloc[-21] - 1) * 100
    lead_ok = [t for t in LEADERS if stats(t) and stats(t)["vs63"] > 0]
    fg, fgl = fear_greed()
    if qdd <= -10 or len(lead_ok) <= 2:
        wx, wtxt = "🔴 폭풍 → 🛍️ 빅 세일 모드", "좋은 종목(⭐워치·✅숫자)이 공포로 크게 빠진 것 우선. 단 바닥 신호(🧲 매집·저점 방어·지수보다 덜 빠짐)가 보일 때만, 나눠서"
    elif qdd > -5 and len(lead_ok) >= 5:
        wx, wtxt = "🟢 맑음 → 🔥 강세 눌림 모드", "지수보다 강한 종목의 30~70% 눌림 우선. 신고가 추격 금지"
    else:
        wx, wtxt = "🟡 흐림 → 두 모드 모두", "강세 눌림과 빅 세일 둘 다 본다. 가장 좋은 1개만"
    weather = dict(label=wx, advice=wtxt, qqq_dd=round(float(qdd), 1), qqq_20d=round(float(q20), 1),
                   leaders_strong=len(lead_ok), leaders=lead_ok, fear_greed=fg, fear_greed_label=fgl, fear_count=len(fear))

    def acc_txt(a):
        return f"{a['score']}/10" if a else "—"

    def pb(s):
        return f"{s['zone']}" + (f" ({s['retr']:.0f}%)" if s.get("retr") is not None and s['zone_order'] < 9 else "")

    md = f"# 🎯 한 방 레이더 — {ny} (뉴욕 종가)\n\n"
    md += (f"## 🌤️ 시장 날씨: {wx}\n> {wtxt}\n> QQQ 고점 대비 {qdd:+.1f}% · 최근 20일 {q20:+.1f}% · 대장주 8개 중 지수보다 강함 {len(lead_ok)}개"
           f"{' (' + ', '.join(lead_ok) + ')' if lead_ok else ''} · Fear & Greed {fg if fg is not None else '—'} {fgl} · 🟢공포 후보 {len(fear)}개\n\n")
    md += "> 가격·거래량만 본다 (이동평균 없음). 읽는 법 → 옵시디언 [[📖 한 방 대시보드 설명서]]. 매수 추천이 아니다.\n\n"
    md += "## 🧩 오늘의 흐름 — 최근 Top 3·김종봉 신호가 몰린 테마\n" + ("".join(f"- **{k}** {len(v)}개: {', '.join(v)}\n" for k, v in flow.items()) or "- 없음\n") + "\n"
    ready = [r for r in pool if r["q_pass"] is not False and (2 <= r["zone_order"] <= 5 or r["fear"])]
    wait = [r for r in pool if r["q_pass"] is not False and r not in ready]
    junk = [r for r in pool if r["q_pass"] is False]
    head = "| # | 티커 | 테마·크기 | 출처 (언제) | 풀백 위치 | 3개월 QQQ 대비 | 고점 대비 | 🧲 | 숫자 | 점수 |\n| ---: | :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- | ---: |\n"
    def prow(i, r):
        return (f"| {i} | {fvl(r['ticker'])} | {r['theme']} {r['size']} | {' · '.join(r['sources'])} | {r['zone']}{(' (' + format(r['retr'], '.0f') + '%)') if r['retr'] is not None else ''} | "
                f"{r['vs63']:+.0f}%p | {r['dd']:+.0f}% | {r['acc'] if r['acc'] is not None else '—'} | {r['quality']} | {r['score']} |\n")
    md += "## 🎯 지금 자리에 있는 후보 (🔔 30~70% 눌림 또는 🟢공포 · 3개월 QQQ 대비 강한 순)\n"
    md += (head + "".join(prow(i, r) for i, r in enumerate(ready, 1))) if ready else "- 없음\n"
    md += "\n## ⏳ 강하지만 아직 자리 아님 (기다림 · 3개월 QQQ 대비 강한 순)\n"
    md += (head + "".join(prow(i, r) for i, r in enumerate(wait[:15], 1))) if wait else "- 없음\n"
    if junk:
        md += "\n> 🗑️ 숫자 게이트에서 걸러짐 (흑자+성장 아님): " + ", ".join(f"{r['ticker']}({r['fund']})" for r in junk) + "\n"
    md += f"\n## 🟢 공포 속 기회 후보 (52주 고점 대비 {FEAR_DD:.0f}%↓ + 매도가 마르는 흔적)\n"
    if fear:
        md += "| 티커 | 고점 대비 | 🧲 | 최근 10일 QQQ 대비 | 저점 방어 | 하락일 거래량 | 숫자 |\n| :--- | ---: | ---: | ---: | :---: | ---: | :--- |\n"
        for s in fear:
            a = s["acc"]
            md += (f"| {fvl(s['ticker'])} | {s['dd']:+.0f}% | {acc_txt(a)} | {s['vs10']:+.1f}%p | {'✅' if s['lows_hold'] else '—'} | "
                   f"{(a['dry'] - 1) * 100:+.0f}% | {ftxt(s.get('f'))} |\n")
    else:
        md += "- 오늘은 없음\n"
    for tier, title in ((1, "🔴 ⭐ 1군 — 세상을 바꾸는 티커"), (2, "🟡 ⭐ 2군 — 메이저·핵심 테마")):
        md += f"\n## {title}\n| 티커 | 풀백 위치 (주봉) | 고점 대비 | 3개월 QQQ 대비 | 🧲 | 신호 |\n| :--- | :--- | ---: | ---: | ---: | :--- |\n"
        for s in sorted(wl[tier], key=lambda s: s["ticker"]):
            a = s["acc"]
            sig = []
            if s["dd"] <= FEAR_DD:
                sig.append("🟢 크게 빠짐")
            if a and a["score"] >= 7:
                sig.append("🧲 매집 강함")
            if s["vs63"] >= 15:
                sig.append("🔥 지수보다 강함")
            if 2 <= s["zone_order"] <= 5:
                sig.append("🔔 눌림 구간")
            md += f"| {fvl(s['ticker'])} | {pb(s)} | {s['dd']:+.0f}% | {s['vs63']:+.0f}%p | {acc_txt(a)} | {' '.join(sig)} |\n"
    md += "\n## 🧲 추적 중 (🏆 Top 3 · 🧭 김종봉) — 신호 이후 풀백 위치\n"
    trk = [dict(stats(t), src=("🧭김종봉" if r.get("src") == "J" else "🏆" + "·".join(k for k in ("D", "W", "M") if k in r.get("kinds", []))),
                sig_date=r.get("date")) for t, r in t3.items() if stats(t)]
    trk.sort(key=lambda s: (0 if 2 <= s["zone_order"] <= 5 else 1, -((s["acc"] or {}).get("score") or 0)))
    if trk:
        md += "| 티커 | 출처 | 신호일 | 풀백 위치 (신호 기준) | 🧲 | 3개월 QQQ 대비 |\n| :--- | :--- | :--- | :--- | ---: | ---: |\n"
        for s in trk:
            md += f"| {fvl(s['ticker'])} | {s['src']} | {s['sig_date']} | {pb(s)} | {acc_txt(s['acc'])} | {s['vs63']:+.0f}%p |\n"
    else:
        md += "- 없음\n"
    if dm:
        md += f"\n> 🦅 드러켄밀러 {dq} 신규·늘림 (비중 0.8%↑): " + ", ".join(f"{t} {v}" for t, v in dm.items()) + "\n"
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    open(f"{OUT}/{ny}.md", "w", encoding="utf-8").write(md)
    clean = lambda L: [{k: v for k, v in s.items() if k != "dollar_vol"} for s in L]
    json.dump(dict(ny_date=ny, weather=weather, pool=pool, flow=flow, fear=clean(fear), watchlist={"1": clean(wl[1]), "2": clean(wl[2])},
                   tracked=clean(trk), druck=dict(quarter=dq, moves=dm), stats=allstats,
                   generated_utc=datetime.now(timezone.utc).isoformat()),
              open(f"{OUT}/latest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=None, default=str)
    print(md)


if __name__ == "__main__":
    main()
