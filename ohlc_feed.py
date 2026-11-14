"""
🕯️ OHLC 피드 (2026-11-14 추가 — Sean 승인, 캔들스틱 분석가용)

목적: 팀의 🕯️ 캔들스틱 분석가가 차트 스크린샷 대신 "정확한 캔들 숫자"를 읽게 한다.
- 대상: 시총 대형주 + 나스닥 100 + 워치리스트 + 한 방 레이더 풀/추적 + 18개월 v2 직접 수혜 + 장기 후보 + extra.txt
- 산출: out/ohlc/<TICKER>.json  (일봉 60 · 주봉 78 · 월봉 48, 수정주가) + out/ohlc/_summary.json (전 종목 한 줄 요약)
- 게시: 워크플로가 out/ 을 'ohlc-data' 브랜치(단일 커밋 강제 푸시)에 올린다 → 기록이 쌓이지 않아 저장소가 안 커진다.
  읽는 주소: https://raw.githubusercontent.com/Johnsnoworme/market-data-feed/ohlc-data/ohlc/<TICKER>.json
- 안전: ny_session(최신 거래일 아니면 저장 안 함) + data_guard(90% 미만이면 저장 안 함). Claude 토큰 0.

⚠️ aids(풀백·큰 그림자·왼쪽 공간)는 '보조 계산'이다. 최종 판단은 분석가가 봉(bars)을 직접 보고 한다.
풀백 구간: 1파의 28% ~ 80% (Sean 결정 2026-11-14).
"""
import io
import json
import os
import re
import sys
import datetime as dt

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from ny_session import expected_session
from data_guard import require_coverage

OUT = "out/ohlc"
ZONE_LO, ZONE_HI = 28.0, 80.0
LEVELS = [28.0, 38.2, 50.0, 61.8, 70.0, 80.0]
N_D, N_W, N_M = 60, 78, 48
ZIGZAG_PCT = 10.0      # 주봉 종가 기준 스윙 판정 (10% 이상 되돌림이면 새 스윙)
MIN_WAVE1_PCT = 8.0    # 1파가 8% 미만이면 알림 가치 약함 (기존 한 방 규칙과 동일)
UA = {"User-Agent": "Mozilla/5.0 (market-data-feed ohlc)"}

# 시총 대형주(고정 목록: 나스닥 100에 없는 NYSE 대형주 위주) — 목록은 hanbang/ohlc/extra.txt 로 늘릴 수 있다
MEGA = """AAPL MSFT NVDA AMZN GOOGL GOOG META AVGO TSLA BRK-B LLY WMT JPM V UNH XOM ORCL MA COST HD PG JNJ NFLX BAC ABBV CVX KO
CRM AMD TMUS MRK WFC CSCO PEP ADBE LIN MCD ABT TMO IBM GE NOW CAT QCOM INTU DIS ISRG TXN AXP GS RTX BKNG SPGI AMGN PLTR
TSM ASML ARM MU SNDK WDC STX LRCX AMAT KLAC ANET COHR LITE AAOI GEV ETN HUBB POWL HWM ATI CRS BKR VST CEG TLN NRG
LMT NOC LHX CCJ LEU UEC FCX SCCO TECK FRO VLO MPC PSX BE HOOD MSTR SPCX CRWD PANW TEM MRNA""".split()


def ysym(t):
    return str(t).strip().upper().replace(".", "-").replace("/", "-")


def get_ndx100():
    try:
        r = requests.get("https://en.wikipedia.org/wiki/Nasdaq-100", headers=UA, timeout=30)
        r.raise_for_status()
        for t in pd.read_html(io.StringIO(r.text)):
            for col in ("Ticker", "Symbol"):
                if col in t.columns and len(t) >= 90:
                    return {ysym(x) for x in t[col].astype(str)}
    except Exception as e:
        print(f"나스닥 100 위키 실패: {e}")
    return set()


def read_list(path):
    s = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.split("#")[0].strip()
            if line:
                s.add(ysym(line))
    return s


def radar_tickers():
    s = set()
    p = "hanbang/radar/latest.json"
    if os.path.exists(p):
        try:
            j = json.load(open(p, encoding="utf-8"))
            for r in j.get("pool", []):
                if r.get("ticker"):
                    s.add(ysym(r["ticker"]))
            for k in ("watchlist", "tracked"):
                v = j.get(k)
                if isinstance(v, dict):
                    for x in v.values():
                        if isinstance(x, list):
                            s |= {ysym(i if isinstance(i, str) else i.get("ticker", "")) for i in x if i}
                elif isinstance(v, list):
                    s |= {ysym(i if isinstance(i, str) else i.get("ticker", "")) for i in v if i}
        except Exception as e:
            print(f"레이더 읽기 실패: {e}")
    return {x for x in s if x}


def build_universe():
    u = set(MEGA) | read_list("watchlist.txt") | read_list("hanbang/ohlc/extra.txt")
    u |= {ysym(x) for x in os.environ.get("EXTRA", "").replace(",", " ").split() if x}
    u |= radar_tickers()
    u |= get_ndx100()
    u |= {"QQQ", "SPY"}
    return sorted(x for x in u if re.fullmatch(r"[A-Z0-9\-]{1,6}", x))


def download(tickers):
    frames = []
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        d = yf.download(chunk, period="5y", interval="1d", auto_adjust=True,
                        progress=False, group_by="ticker", threads=True)
        frames.append(d)
    return frames


def frame_for(frames, t):
    for d in frames:
        try:
            if isinstance(d.columns, pd.MultiIndex):
                if t in d.columns.get_level_values(0):
                    x = d[t][["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                    if len(x):
                        return x
            elif len(frames) == 1:
                return d[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        except Exception:
            continue
    return None


def resample(df, rule):
    o = df.resample(rule).agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return o.dropna(subset=["Close"])


def rows(df, n):
    out = []
    for idx, r in df.tail(n).iterrows():
        out.append([str(idx)[:10], round(float(r.Open), 2), round(float(r.High), 2),
                    round(float(r.Low), 2), round(float(r.Close), 2), int(r.Volume) if pd.notna(r.Volume) else 0])
    return out


def zigzag(c, pct):
    """종가 기준 스윙 목록 [(index, price, 'H'/'L')]. 마지막 항목은 아직 확정 안 된 현재 극값."""
    piv = []
    if len(c) < 2:
        return piv
    trend, ext_i, ext = 0, 0, c[0]
    for i in range(1, len(c)):
        x = c[i]
        if trend == 0:
            if x >= c[0] * (1 + pct / 100):
                piv.append((0, c[0], "L")); trend, ext_i, ext = 1, i, x
            elif x <= c[0] * (1 - pct / 100):
                piv.append((0, c[0], "H")); trend, ext_i, ext = -1, i, x
        elif trend == 1:
            if x > ext:
                ext_i, ext = i, x
            elif x <= ext * (1 - pct / 100):
                piv.append((ext_i, ext, "H")); trend, ext_i, ext = -1, i, x
        else:
            if x < ext:
                ext_i, ext = i, x
            elif x >= ext * (1 + pct / 100):
                piv.append((ext_i, ext, "L")); trend, ext_i, ext = 1, i, x
    if trend == 1:
        piv.append((ext_i, ext, "H"))
    elif trend == -1:
        piv.append((ext_i, ext, "L"))
    return piv


def left_room(w, level, upto):
    """upto 이전 주봉들 중, 가격대 level이 [저가,고가] 안에 한 번도 안 들어온 연속 캔들 수."""
    n = 0
    for k in range(upto - 1, -1, -1):
        if w.Low.iloc[k] <= level <= w.High.iloc[k]:
            break
        n += 1
    return n


def aids(w, m):
    """풀백·큰 그림자·왼쪽 공간 보조 계산 (주봉 기준)."""
    if len(w) < 20:
        return {"note": "주봉 20개 미만 — 계산 안 함"}
    cl = w.Close.values.astype(float)
    last = float(cl[-1])
    pv = zigzag(list(cl), ZIGZAG_PCT)
    res = {"last": round(last, 2), "tf": "weekly"}
    hi52 = float(w.High.tail(52).max())
    res["dd_52w_high_pct"] = round((last / hi52 - 1) * 100, 1)
    # 마지막 'H' 피벗과 그 앞의 'L' 피벗 = 1파
    h = next((p for p in reversed(pv) if p[2] == "H"), None)
    wave = None
    if h:
        l = next((p for p in reversed(pv) if p[2] == "L" and p[0] < h[0]), None)
        if l:
            wave = (l, h)
    if wave:
        (li, lp, _), (hi, hp, _) = wave
        size = (hp / lp - 1) * 100
        retr = (hp - last) / (hp - lp) * 100 if hp > lp else 0.0
        res["wave1"] = {"low": round(lp, 2), "low_date": str(w.index[li])[:10],
                        "high": round(hp, 2), "high_date": str(w.index[hi])[:10], "size_pct": round(size, 1)}
        res["retr_pct"] = round(retr, 1)
        if last < lp:
            res["state"] = "below_wave1_low"
        elif last >= hp * 0.9999:
            res["state"] = "new_high"
        elif size < MIN_WAVE1_PCT:
            res["state"] = "wave1_too_small"
        elif ZONE_LO <= retr <= ZONE_HI:
            res["state"] = "in_zone"
        elif retr < ZONE_LO:
            res["state"] = "shallow"
        else:
            res["state"] = "deeper_than_zone"
        res["levels"] = {str(x): round(hp - (hp - lp) * x / 100, 2) for x in LEVELS}
        res["left_room_weeks_at_last"] = left_room(w, last, len(w) - 1)
        res["left_room_weeks_at_wave_low"] = left_room(w, lp, li)
    else:
        res["state"] = "no_wave"
    # 큰 그림자: 최근 6주 중 바깥봉(직전 봉을 감싸는 봉) + 범위가 직전 10주 평균의 몇 배인지
    rng = (w.High - w.Low).values.astype(float)
    flags = []
    for k in range(len(w) - 6, len(w)):
        if k < 11:
            continue
        outside = bool(w.High.iloc[k] >= w.High.iloc[k - 1] and w.Low.iloc[k] <= w.Low.iloc[k - 1])
        base = float(rng[k - 10:k].mean())
        ratio = float(rng[k] / base) if base else float("nan")
        if not np.isfinite(ratio):
            ratio = None
        flags.append({"week": str(w.index[k])[:10], "outside_bar": outside,
                      "range_x_prior10": (round(ratio, 2) if ratio is not None else None),
                      "dir": "up" if w.Close.iloc[k] >= w.Open.iloc[k] else "down"})
    res["big_shadow_candidates"] = flags
    # 월봉 맥락
    if len(m) >= 14:
        mc = m.Close.values.astype(float)
        res["monthly"] = {"ret_12m_pct": round((mc[-1] / mc[-13] - 1) * 100, 1),
                          "dd_from_24m_high_pct": round((mc[-1] / float(m.High.tail(24).max()) - 1) * 100, 1)}
    return res


def main():
    uni = build_universe()
    print(f"대상 {len(uni)}개")
    frames = download(uni)
    # 신선도: QQQ 마지막 날짜 + 전체 커버리지
    q = frame_for(frames, "QQQ")
    if q is None:
        print("QQQ 없음 → 종료"); sys.exit(0)
    exp = expected_session()
    last_day = q.index[-1].date()
    if last_day < exp and os.environ.get("DATA_FORCE") != "1":
        print(f"⏳ {exp} 종가가 아직 없음 (마지막 {last_day}) → 저장하지 않음")
        sys.exit(0)
    ny_date = str(last_day)
    # 같은 거래일이 이미 게시돼 있으면 건너뜀
    if os.environ.get("FORCE") != "1":
        try:
            r = requests.get(f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY', 'Johnsnoworme/market-data-feed')}/ohlc-data/ohlc/_summary.json?t={dt.datetime.now().timestamp()}", timeout=20)
            if r.ok and r.json().get("ny_date") == ny_date:
                print(f"이미 {ny_date} 게시됨 → 건너뜀"); sys.exit(0)
        except Exception:
            pass
    cache = {t: frame_for(frames, t) for t in uni}
    close = pd.DataFrame({t: f.Close for t, f in cache.items() if f is not None})
    require_coverage(close, "OHLC", 0.85)

    os.makedirs(OUT, exist_ok=True)
    summary = {}
    for t in uni:
        d = cache.get(t)
        if d is None or len(d) < 60:
            continue
        d = d[d.index <= pd.Timestamp(ny_date)]
        w = resample(d, "W-FRI")
        try:
            m = resample(d, "ME")
        except Exception:
            m = resample(d, "M")
        a = aids(w, m)
        doc = {"ticker": t, "ny_date": ny_date, "adjusted": True,
               "note": "bars=[date,open,high,low,close,volume]. 주봉 W-FRI(마지막 주는 진행 중일 수 있음), 월봉 달 말. aids는 보조 계산.",
               "d": rows(d, N_D), "w": rows(w, N_W), "m": rows(m, N_M), "aids": a}
        json.dump(doc, open(f"{OUT}/{t}.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        summary[t] = {k: a.get(k) for k in ("last", "state", "retr_pct", "dd_52w_high_pct")}
        if a.get("wave1"):
            summary[t]["wave1_pct"] = a["wave1"]["size_pct"]
    json.dump({"ny_date": ny_date, "zone": [ZONE_LO, ZONE_HI], "count": len(summary),
               "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "tickers": summary}, open(f"{OUT}/_summary.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    inzone = [t for t, v in summary.items() if v.get("state") == "in_zone"]
    print(f"✅ {len(summary)}개 저장 · 풀백 {ZONE_LO:.0f}~{ZONE_HI:.0f}% 구간 {len(inzone)}개")


if __name__ == "__main__":
    main()
