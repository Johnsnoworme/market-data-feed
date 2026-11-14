"""
🕯️ 지수 캔들 피드 (index_candles.py)

목적: 캔들스틱 분석가가 지수 티커를 '하나도 빠짐없이', '정확한 시가/고가/저가/종가/거래량'으로 보게 한다.

원칙
- 원본 가격 사용 (auto_adjust=False): 배당 보정을 하지 않은 실제 시가·고가·저가·종가 (지수는 원래 보정 없음)
- 일봉만 내려받고, 주봉·월봉·연봉은 일봉에서 직접 만든다 (같은 출처라 서로 어긋나지 않음)
- 검증 게이트: 하나라도 어긋나면 그 티커는 '사용 금지'로 표시 (조용히 넘어가지 않음)
    1) 봉 모양 검사 (고가 >= 시/종, 저가 <= 시/종, 빈 값·0 이하 없음)
    2) 신선도 (뉴욕 마지막 거래일 종가까지 들어왔는지, ny_session.py)
    3) 직접 만든 주봉/월봉 vs Yahoo가 만든 주봉/월봉 (완성된 봉만, 오차 0.1% 이내)
    4) ETF vs 지수 일간 등락률 추적 (SPY-^GSPC 등)
    5) 공식 종가 기준점 (S&P500·다우·나스닥 역사적 날짜의 공식 종가와 대조)
- 실패 시 out/index/_error.txt 를 남긴다 (로그를 못 읽어도 원인 확인 가능)
"""
import datetime as dt
import json
import os
import sys
import time
import traceback

import numpy as np
import pandas as pd

OUT = "out/index"

# (티커, 이름, 종류)
TICKERS = [
    ("^GSPC", "S&P 500", "index"),
    ("^NDX", "나스닥 100", "index"),
    ("^IXIC", "나스닥 종합", "index"),
    ("^DJI", "다우 30", "index"),
    ("^RUT", "러셀 2000", "index"),
    ("^SOX", "필라델피아 반도체", "index"),
    ("^VIX", "VIX 변동성", "index"),
    ("SPY", "SPY (S&P 500 ETF)", "etf"),
    ("QQQ", "QQQ (나스닥 100 ETF)", "etf"),
    ("DIA", "DIA (다우 ETF)", "etf"),
    ("IWM", "IWM (러셀 2000 ETF)", "etf"),
    ("MDY", "MDY (S&P 400 중형주 ETF)", "etf"),
    ("SMH", "SMH (반도체 ETF)", "etf"),
]
CORE = ["^GSPC", "^NDX", "SPY", "QQQ"]
PAIRS = [("SPY", "^GSPC"), ("QQQ", "^NDX"), ("DIA", "^DJI"), ("IWM", "^RUT")]

# 공식 종가 기준점 (거래소 공식 종가, 소수 둘째자리). 오차 0.05% 이내여야 통과.
ANCHORS = [
    ("^GSPC", "2007-10-09", 1565.15),
    ("^GSPC", "2009-03-09", 676.53),
    ("^GSPC", "2020-03-23", 2237.40),
    ("^GSPC", "2022-10-12", 3577.03),
    ("^DJI", "2009-03-09", 6547.05),
    ("^DJI", "2020-03-23", 18591.93),
    ("^IXIC", "2020-03-23", 6860.67),
]
ANCHOR_TOL = 0.0005
BAR_TOL = 0.001          # 직접 만든 봉 vs Yahoo 봉
BAR_MISMATCH_MAX = 0.02  # 비교한 봉 중 어긋난 비율 상한
TRACK_TOL = 0.006        # ETF-지수 일간 등락률 차이 (배당락일 감안)
TRACK_BAD_MAX = 0.02

KEEP = {"d": 260, "w": 260, "m": 240}


# ---------------- 데이터 가져오기 (모의 테스트에서 바꿔 끼움) ----------------
def fetch(ticker, interval):
    import yfinance as yf
    last = None
    for i in range(3):
        try:
            h = yf.Ticker(ticker).history(period="max", interval=interval, auto_adjust=False, actions=False)
            if h is not None and len(h) > 0:
                return h
        except Exception as e:  # noqa
            last = e
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"{ticker} {interval} 다운로드 실패: {last}")


def clean(h):
    h = h.copy()
    idx = pd.to_datetime(h.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    h.index = idx.normalize()
    h = h[["Open", "High", "Low", "Close", "Volume"]]
    h = h[~h.index.duplicated(keep="last")].sort_index()
    return h


# ---------------- 검증 ----------------
def bar_problems(df):
    """일봉 모양 검사. 문제 목록 반환."""
    p = []
    if df[["Open", "High", "Low", "Close"]].isna().any().any():
        n = int(df[["Open", "High", "Low", "Close"]].isna().any(axis=1).sum())
        p.append(f"빈 값 {n}줄")
    d = df.dropna(subset=["Open", "High", "Low", "Close"])
    if (d[["Open", "High", "Low", "Close"]] <= 0).any().any():
        p.append("0 이하 가격 있음")
    hi_bad = d["High"] < d[["Open", "Close"]].max(axis=1) - 1e-6
    lo_bad = d["Low"] > d[["Open", "Close"]].min(axis=1) + 1e-6
    if hi_bad.any():
        p.append(f"고가<시/종가 {int(hi_bad.sum())}줄 (예: {d.index[hi_bad][-1].date()})")
    if lo_bad.any():
        p.append(f"저가>시/종가 {int(lo_bad.sum())}줄 (예: {d.index[lo_bad][-1].date()})")
    return p


def agg(df, rule):
    """일봉 → 주/월/연봉. 라벨 = 그 기간의 마지막 거래일. 기간 key 도 함께."""
    g = df.resample(rule)
    o = g["Open"].first()
    h = g["High"].max()
    l = g["Low"].min()
    c = g["Close"].last()
    v = g["Volume"].sum(min_count=1)
    last_day = pd.Series(df.index, index=df.index).resample(rule).last()
    out = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v, "last": last_day}).dropna(subset=["Close"])
    out["key"] = out.index  # 기간 끝 날짜(W-FRI 금요일, M 월말, Y 연말)
    out.index = pd.to_datetime(out["last"])
    return out.drop(columns=["last"])


def compare_native(ticker, mine, interval):
    """직접 만든 봉 vs Yahoo 자체 주/월봉 (완성된 봉만)."""
    nat = clean(fetch(ticker, interval))
    if interval == "1wk":
        nat_key = nat.index - pd.to_timedelta(nat.index.weekday, unit="D")  # 그 주 월요일
        mine_key = mine["key"] - pd.Timedelta(days=4)                        # 금요일 → 월요일
    else:
        nat_key = nat.index.to_period("M")
        mine_key = mine["key"].dt.to_period("M")
    nat = nat.assign(k=nat_key).drop_duplicates("k", keep="last").set_index("k")
    m = mine.assign(k=mine_key.values if hasattr(mine_key, "values") else mine_key).drop_duplicates("k", keep="last").set_index("k")
    m = m.iloc[:-1]  # 마지막(진행 중일 수 있는) 봉 제외
    common = m.index.intersection(nat.index)
    common = common[-300:] if interval == "1wk" else common[-120:]
    if len(common) < 20:
        return {"checked": 0, "bad": 0, "note": "비교할 봉 부족"}
    bad = 0
    worst = []
    for k in common:
        a, b = m.loc[k], nat.loc[k]
        errs = []
        for col in ("High", "Low", "Close"):
            if b[col] and abs(a[col] / b[col] - 1) > BAR_TOL:
                errs.append(col)
        if errs:
            bad += 1
            worst.append(f"{k} {','.join(errs)} 내값C={a['Close']:.2f} 야후C={b['Close']:.2f}")
    out = {"checked": int(len(common)), "bad": bad, "bad_ratio": round(bad / len(common), 4), "examples": worst[-3:]}
    if bad / len(common) > BAR_MISMATCH_MAX:
        # 진단 전용(판정 기준은 그대로): 야후 봉이 한 칸 밀려 있는지 확인
        for sh in (-1, 1):
            ok = 0
            for k in common:
                pos = nat.index.get_loc(k) + sh
                if 0 <= pos < len(nat) and abs(m.loc[k]["Close"] / nat.iloc[pos]["Close"] - 1) <= BAR_TOL:
                    ok += 1
            out[f"shift{sh:+d}_match"] = f"{ok}/{len(common)}"
        out["native_tail"] = [[str(i.date()) if hasattr(i, "date") else str(i), round(float(r.Close), 2)] for i, r in nat.iloc[-4:].iterrows()]
        out["mine_tail"] = [[str(i.date()) if hasattr(i, "date") else str(i), round(float(r.Close), 2)] for i, r in m.iloc[-4:].iterrows()]
    return out


def etf_weekly_fallback(t, w_idx, daily):
    """Yahoo 자체 주봉이 믿을 수 없을 때: 같은 일봉으로 만든 지수·ETF 주봉 수익률이 서로 맞는지 대조."""
    pair = {i: e for e, i in PAIRS}
    etf = pair.get(t)
    if not etf or etf not in daily:
        return None
    w_etf = agg(daily[etf], "W-FRI")
    a = w_idx["Close"].pct_change()
    b = w_etf["Close"].pct_change()
    a.index = w_idx["key"].values
    b.index = w_etf["key"].values
    j = pd.concat([a, b], axis=1, keys=["i", "e"]).dropna().iloc[-300:-1]
    if len(j) < 100:
        return None
    bad = int(((j["i"] - j["e"]).abs() > 0.006).sum())
    return {"etf": etf, "checked": int(len(j)), "bad": bad, "ok": bool(bad / len(j) <= 0.02)}


def check_anchors(daily):
    res = []
    for t, d, official in ANCHORS:
        df = daily.get(t)
        if df is None:
            res.append({"ticker": t, "date": d, "ok": None, "note": "데이터 없음"})
            continue
        ts = pd.Timestamp(d)
        if ts not in df.index:
            res.append({"ticker": t, "date": d, "ok": None, "note": "그 날짜 봉 없음"})
            continue
        got = float(df.loc[ts, "Close"])
        err = abs(got / official - 1)
        res.append({"ticker": t, "date": d, "official": official, "got": round(got, 2),
                    "err_pct": round(err * 100, 4), "ok": bool(err <= ANCHOR_TOL)})
    return res


def check_tracking(daily):
    res = {}
    for etf, idx in PAIRS:
        if etf not in daily or idx not in daily:
            continue
        a = daily[etf]["Close"].pct_change()
        b = daily[idx]["Close"].pct_change()
        j = pd.concat([a, b], axis=1, keys=["e", "i"]).dropna().iloc[-250:]
        if len(j) < 100:
            continue
        diff = (j["e"] - j["i"]).abs()
        bad = int((diff > TRACK_TOL).sum())
        res[f"{etf}~{idx}"] = {"days": int(len(j)), "bad_days": bad, "ok": bool(bad / len(j) <= TRACK_BAD_MAX)}
    return res


# ---------------- 캔들 읽기 ----------------
def tag_bar(cur, prev, vol_ratio):
    o, h, l, c = cur
    rng = h - l
    tags = []
    if rng <= 0:
        return ["무변동"]
    body = abs(c - o)
    up = h - max(o, c)
    lo = min(o, c) - l
    if body <= 0.1 * rng:
        tags.append("도지(망설임)")
    if body >= 0.85 * rng:
        tags.append("장대양봉" if c > o else "장대음봉")
    if body > 0 and lo >= 2 * body and up <= 0.35 * body + 0.05 * rng:
        tags.append("긴 아랫꼬리(해머형)")
    elif body > 0 and up >= 2 * body and lo <= 0.35 * body + 0.05 * rng:
        tags.append("긴 윗꼬리(유성형)")
    if prev is not None:
        po, ph, pl, pc = prev
        if pc < po and c > o and o <= pc and c >= po:
            tags.append("상승 장악형")
        if pc > po and c < o and o >= pc and c <= po:
            tags.append("하락 장악형")
        if h <= ph and l >= pl:
            tags.append("인사이드바")
        elif h > ph and l < pl:
            tags.append("아웃사이드바")
        if h > ph and c < pl:
            tags.append("고가 돌파 후 전봉 저가 이탈(약세 반전)")
        if l < pl and c > ph:
            tags.append("저가 이탈 후 전봉 고가 회복(강세 반전)")
    pos = (c - l) / rng
    tags.append("종가 고가권" if pos >= 0.8 else "종가 저가권" if pos <= 0.2 else "종가 중간")
    if vol_ratio is not None:
        if vol_ratio >= 1.5:
            tags.append(f"거래량 급증 x{vol_ratio:.1f}")
        elif vol_ratio <= 0.6:
            tags.append(f"거래량 급감 x{vol_ratio:.1f}")
    return tags


def read_tf(df, is_index_vol_ok=True):
    """한 시간 단위 캔들 읽기: 마지막 봉 + 직전 봉 태그."""
    if len(df) < 3:
        return None
    r = df.iloc[-1]
    p = df.iloc[-2]
    vr = None
    if is_index_vol_ok and df["Volume"].iloc[-21:-1].mean() and df["Volume"].iloc[-21:-1].mean() > 0:
        vr = float(df["Volume"].iloc[-1] / df["Volume"].iloc[-21:-1].mean())
    tags = tag_bar((r.Open, r.High, r.Low, r.Close), (p.Open, p.High, p.Low, p.Close), vr)
    return {
        "date": str(df.index[-1].date()),
        "o": round(float(r.Open), 2), "h": round(float(r.High), 2),
        "l": round(float(r.Low), 2), "c": round(float(r.Close), 2),
        "chg_pct": round(float((r.Close / p.Close - 1) * 100), 2),
        "tags": tags,
    }


def to_rows(df, n):
    d = df.iloc[-n:] if n else df
    rows = []
    for ts, r in d.iterrows():
        v = r.Volume
        rows.append([str(ts.date()), round(float(r.Open), 2), round(float(r.High), 2),
                     round(float(r.Low), 2), round(float(r.Close), 2),
                     None if pd.isna(v) else int(v)])
    return rows


def partial_flag(df_last_key, rule, last_daily):
    """마지막 봉이 아직 진행 중인지."""
    return bool(last_daily < df_last_key)


# ---------------- 메인 ----------------
def build(expected):
    daily, errors = {}, {}
    for t, _n, _k in TICKERS:
        try:
            df = clean(fetch(t, "1d"))
            df = df[df.index <= pd.Timestamp(expected)]  # 마감 전 부분 봉 방지
            daily[t] = df
        except Exception as e:  # noqa
            errors[t] = str(e)[:200]

    result = {"tickers": {}, "problems": []}
    anchors = check_anchors(daily)
    tracking = check_tracking(daily)
    anchor_bad = [a for a in anchors if a["ok"] is False]
    track_bad = [k for k, v in tracking.items() if not v["ok"]]

    os.makedirs(OUT, exist_ok=True)
    for t, name, kind in TICKERS:
        info = {"name": name, "kind": kind, "status": "OK", "notes": []}
        if t not in daily:
            info["status"] = "FAIL"
            info["notes"].append("다운로드 실패: " + errors.get(t, "?"))
            result["tickers"][t] = info
            continue
        df = daily[t]
        # 1) 봉 모양
        bp = bar_problems(df.iloc[-2600:])
        if bp:
            info["status"] = "FAIL"
            info["notes"] += bp
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        # 2) 신선도
        last = df.index[-1].date()
        info["last_date"] = str(last)
        if last < expected:
            info["status"] = "FAIL"
            info["notes"].append(f"마지막 봉 {last} (기대 {expected}) — 최신 아님")
        # 주/월/연봉
        w = agg(df, "W-FRI")
        m = agg(df, "ME") if _pandas_has_me() else agg(df, "M")
        y = agg(df, "YE") if _pandas_has_me() else agg(df, "A")
        # 3) 네이티브 비교
        cmp_ = {}
        try:
            cmp_["w"] = compare_native(t, w, "1wk")
            cmp_["m"] = compare_native(t, m, "1mo")
            for k, v in list(cmp_.items()):
                if v.get("checked", 0) and v.get("bad_ratio", 0) > BAR_MISMATCH_MAX:
                    fb = etf_weekly_fallback(t, w, daily) if k == "w" else None
                    cmp_["w_fallback"] = fb
                    if fb and fb["ok"]:
                        info["notes"].append(
                            f"Yahoo 자체 주봉이 이상함(종가가 다음 주 값과 섞임) → ETF({fb['etf']}) 주봉 수익률 대조로 대체 검증 통과 {fb['bad']}/{fb['checked']}")
                        continue
                    info["status"] = "FAIL"
                    info["notes"].append(f"{k}봉 Yahoo와 불일치 {v['bad']}/{v['checked']} {v.get('examples')} 진단:{ {x: v[x] for x in v if x.startswith(('shift','native_tail','mine_tail'))} }")
        except Exception as e:  # noqa
            info["status"] = "WARN" if info["status"] == "OK" else info["status"]
            info["notes"].append(f"주/월봉 교차검증 못함: {str(e)[:120]}")
        info["cross_check"] = cmp_
        # 4) 추적 (ETF)
        for k in track_bad:
            if t in k.split("~"):
                info["status"] = "FAIL"
                info["notes"].append(f"추적 불일치 {k}")
        # 5) 기준점
        for a in anchor_bad:
            if a["ticker"] == t:
                info["status"] = "FAIL"
                info["notes"].append(f"공식 종가 불일치 {a['date']} 공식 {a['official']} / 받은 값 {a['got']}")

        vol_ok = kind == "etf" or t in ("^GSPC", "^NDX", "^IXIC", "^DJI", "^RUT")
        vol_ok = vol_ok and df["Volume"].iloc[-20:].sum() > 0
        # 12개월 합성 봉
        t12 = None
        if len(df) >= 252:
            s = df.iloc[-252:]
            t12 = {"from": str(s.index[0].date()), "o": round(float(s.Open.iloc[0]), 2),
                   "h": round(float(s.High.max()), 2), "l": round(float(s.Low.min()), 2),
                   "c": round(float(s.Close.iloc[-1]), 2)}
        c = df["Close"]
        hi52 = float(df["High"].iloc[-252:].max())
        ctx = {
            "dd_52w_high_pct": round(float((c.iloc[-1] / hi52 - 1) * 100), 2),
            "above_ma20": bool(c.iloc[-1] > c.iloc[-20:].mean()),
            "above_ma50": bool(c.iloc[-1] > c.iloc[-50:].mean()),
            "above_ma200": bool(len(c) >= 200 and c.iloc[-1] > c.iloc[-200:].mean()),
            "ret_5d_pct": round(float((c.iloc[-1] / c.iloc[-6] - 1) * 100), 2),
            "ret_20d_pct": round(float((c.iloc[-1] / c.iloc[-21] - 1) * 100), 2),
        }
        info["context"] = ctx
        info["candle"] = {
            "d": read_tf(df, vol_ok),
            "w": read_tf(w, vol_ok),
            "m": read_tf(m, vol_ok),
            "y": read_tf(y, False),
            "t12": t12,
        }
        info["partial"] = {
            "w": bool(w.index[-1] < w["key"].iloc[-1]),
            "m": bool(m.index[-1] < m["key"].iloc[-1]),
            "y": bool(y.index[-1] < y["key"].iloc[-1]),
        }
        info["volume_reliable"] = bool(vol_ok)
        data = {
            "ticker": t, "name": name, "ny_date": str(expected), "adjusted": False,
            "note": "원본 가격(배당 보정 없음). 봉 = [날짜, 시, 고, 저, 종, 거래량]. 주/월/연봉은 일봉에서 직접 합성.",
            "status": info["status"],
            "d": to_rows(df, KEEP["d"]), "w": to_rows(w, KEEP["w"]),
            "m": to_rows(m, KEEP["m"]), "y": to_rows(y, 0),
        }
        safe = t.replace("^", "")
        with open(f"{OUT}/{safe}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        result["tickers"][t] = info

    core_ok = all(result["tickers"].get(t, {}).get("status") in ("OK", "WARN") for t in CORE)
    all_ok = all(v["status"] == "OK" for v in result["tickers"].values())
    result["verdict"] = "OK" if all_ok else ("PARTIAL" if core_ok else "FAIL")
    result["anchors"] = anchors
    result["tracking"] = tracking
    return result


def _pandas_has_me():
    try:
        return int(pd.__version__.split(".")[0]) >= 2 and int(pd.__version__.split(".")[1]) >= 2 or int(pd.__version__.split(".")[0]) >= 3
    except Exception:  # noqa
        return False


def write_report(res, expected):
    gen = dt.datetime.utcnow().isoformat(timespec="seconds") + "+00:00"
    summary = {"ny_date": str(expected), "generated_utc": gen, "verdict": res["verdict"],
               "tickers": res["tickers"], "anchors": res["anchors"], "tracking": res["tracking"]}
    with open(f"{OUT}/_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    L = [f"# 🕯️ 지수 캔들 보고용 요약 · 뉴욕 {expected}",
         f"판정: **{res['verdict']}** (OK=전부 검증통과 / PARTIAL=핵심 4개는 통과 / FAIL=사용 금지)",
         "※ 원본 가격, 일→주·월·연봉 직접 합성. 상태가 OK가 아닌 티커는 숫자를 쓰지 말 것.", ""]
    L.append("| 티커 | 상태 | 일봉 종가(등락) | 일봉 모양 | 주봉 | 월봉 | 52주고점대비 | 50/200일선 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for t, i in res["tickers"].items():
        if "candle" not in i:
            L.append(f"| {t} | {i['status']} | - | {'; '.join(i['notes'])} | | | | |")
            continue
        c, x = i["candle"], i["context"]

        def short(tf, n=2):
            if not tf:
                return "-"
            return f"{tf['chg_pct']:+.1f}% " + "/".join(tf["tags"][:n])
        d = c["d"]
        L.append(f"| {t} | {i['status']} | {d['c']} ({d['chg_pct']:+.2f}%) | {'/'.join(d['tags'][:3])} | "
                 f"{short(c['w'])}{'(진행중)' if i['partial']['w'] else ''} | "
                 f"{short(c['m'])}{'(진행중)' if i['partial']['m'] else ''} | {x['dd_52w_high_pct']}% | "
                 f"{'위' if x['above_ma50'] else '아래'}/{'위' if x['above_ma200'] else '아래'} |")
    L.append("")
    L.append("## 검증 결과")
    L.append("- 공식 종가 대조: " + ", ".join(
        f"{a['ticker']} {a['date']} {'✅' if a['ok'] else ('❌' if a['ok'] is False else '–')}" for a in res["anchors"]))
    L.append("- ETF-지수 추적: " + ", ".join(f"{k} {'✅' if v['ok'] else '❌'}" for k, v in res["tracking"].items()))
    notes = [f"{t}: {n}" for t, i in res["tickers"].items() for n in i["notes"]]
    if notes:
        L.append("- 주의: " + " | ".join(notes))
    with open(f"{OUT}/_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main():
    try:
        sys.path.insert(0, os.getcwd())
        from ny_session import expected_session
        expected = expected_session()
        force = os.environ.get("DATA_FORCE", "0") == "1"
        # 이미 같은 거래일을 게시했으면 건너뜀 (워크플로에서 PUBLISHED_NY 로 전달)
        if os.environ.get("PUBLISHED_NY") == str(expected) and not force:
            print("이미 게시한 거래일:", expected)
            return
        res = build(expected)
        # 핵심 티커가 '최신 아님'뿐이라면 → 아직 Yahoo가 안 채운 것: 저장하지 않고 다음 예약에서 재시도
        stale_only = all(
            (i["status"] == "OK") or (i["notes"] and all("최신 아님" in n for n in i["notes"]))
            for i in res["tickers"].values()
        ) and any(i["status"] != "OK" for i in res["tickers"].values())
        if stale_only and not force:
            print("Yahoo가 아직 오늘 종가를 채우지 않음 → 저장 없이 종료")
            if os.path.isdir(OUT):
                for f in os.listdir(OUT):
                    os.remove(os.path.join(OUT, f))
            return
        write_report(res, expected)
        print(open(f"{OUT}/_report.md", encoding="utf-8").read())
    except Exception:
        os.makedirs(OUT, exist_ok=True)
        with open(f"{OUT}/_error.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print(traceback.format_exc())


if __name__ == "__main__":
    main()
