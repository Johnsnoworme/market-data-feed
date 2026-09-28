"""
거래량 기준 백테스트 — 소셜 아비트리지 '가격 조건' 중 거래량 배수가 몇 배일 때 가장 좋은가
- 신호: 5일 수익률 > 0 이고 기준지수보다 높음, 종가 > 20일선, 1개월 +50% 미만, 최근 5일 하루 +40% 급등 없음
        (+ 10년 테스트만: 주가 $5↑, 하루 거래대금 2천만$↑)
        + 최근 3일 평균 거래량 ≥ 그 전 20일 평균 × 배수
- 같은 종목은 21거래일 안에 다시 신호가 나와도 첫 신호만 (중복 제거)
- 결과: 신호일 종가에 샀다고 보고 1·3·6개월 후 수익률, 기준지수 대비 초과수익
A) 10년: 지금 시총 $2B↑ 미국 종목, 기준 QQQ
B) 50년(1976~): 지금 S&P 500 종목, 기준 S&P 500 지수(^GSPC)
※ 지금 살아 있는 종목만 쓰므로(상장폐지 종목 없음) 절대 수익률은 부풀려짐 → '배수끼리 비교'로만 해석
결과: research/volume/latest.md
"""
import os
import numpy as np
import pandas as pd
import requests
import yfinance as yf

from jb_scanner import get_sp500

OUT = "research/volume"
TH = [0, 1.0, 1.2, 1.3, 1.5, 2.0, 2.5, 3.0]
H = {"1개월": 21, "3개월": 63, "6개월": 126}


def caps_2b():
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
         "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
    rows = requests.get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true", headers=h, timeout=30).json()["data"]["rows"]
    out = []
    for r in rows:
        try:
            cap = float(r.get("marketCap") or 0)
        except ValueError:
            continue
        s = (r.get("symbol") or "").strip()
        if s and "^" not in s and "/" not in s and cap >= 2e9:
            out.append(s.replace(".", "-"))
    return sorted(set(out))


def download(tickers, **kw):
    C, V = [], []
    for i in range(0, len(tickers), 100):
        d = yf.download(tickers[i:i + 100], interval="1d", auto_adjust=True, progress=False, group_by="column", threads=True, **kw)
        if d.empty:
            continue
        C.append(d["Close"]), V.append(d["Volume"])
        print(f"다운로드 {min(i + 100, len(tickers))}/{len(tickers)}")
    C, V = pd.concat(C, axis=1), pd.concat(V, axis=1)
    C = C.loc[:, ~C.columns.duplicated()]
    V = V.loc[:, ~V.columns.duplicated()]
    return C, V


def run(C, V, bench, liquid):
    C = C.where(C > 0)
    V = V.where(V > 0)
    b = bench.reindex(C.index).ffill()
    r5 = C / C.shift(5) - 1
    br5 = b / b.shift(5) - 1
    base = (r5 > 0) & (r5.gt(br5, axis=0)) & (C > C.rolling(20).mean()) & (C / C.shift(21) - 1 < 0.5) \
        & (C.pct_change(fill_method=None).rolling(5).max() < 0.4)
    if liquid:
        base &= (C >= 5) & ((C * V).rolling(20).mean() >= 20e6)
    vr = V.rolling(3).mean() / V.shift(3).rolling(20).mean()
    fwd = {k: C.shift(-h) / C - 1 for k, h in H.items()}
    bfwd = {k: b.shift(-h) / b - 1 for k, h in H.items()}
    # 앞으로 6개월 데이터가 있는 날까지만
    valid = C.index[: len(C.index) - max(H.values())]
    res = []
    for t in TH:
        cond = base & (vr >= t) if t > 0 else base.copy()
        cond = cond & (cond.astype(int).rolling(21, min_periods=1).sum() == 1)  # 21일 안 첫 신호만
        cond = cond.loc[valid]
        n = int(cond.values.sum())
        if n == 0:
            continue
        row = {"배수": "조건 없음" if t == 0 else f"{t:.1f}배↑", "신호 수": n,
               "하루 평균": n / len(valid), "신호 있는 날 %": cond.any(axis=1).mean() * 100}
        for k in H:
            f = fwd[k].loc[valid].values[cond.values]
            bb = np.broadcast_to(bfwd[k].loc[valid].values[:, None], cond.shape)[cond.values]
            ok = ~np.isnan(f) & ~np.isnan(bb)
            f, ex = f[ok], (f - bb)[ok]
            row[f"{k} 평균"] = f.mean() * 100
            row[f"{k} 초과 평균"] = ex.mean() * 100
            row[f"{k} 초과 중앙값"] = np.median(ex) * 100
            row[f"{k} 지수 이긴 %"] = (ex > 0).mean() * 100
            if k == "6개월":
                row["6개월 +50%↑ 비율"] = (f >= 0.5).mean() * 100
                row["6개월 -30%↓ 비율"] = (f <= -0.3).mean() * 100
        # 연도별 3개월 초과 평균 (안정성)
        yr = pd.Series(np.broadcast_to(np.array(valid.year)[:, None], cond.shape)[cond.values])
        ex3 = (fwd["3개월"].loc[valid].values - bfwd["3개월"].loc[valid].values[:, None])[cond.values]
        s = pd.Series(ex3).groupby(yr.values).mean() * 100
        row["_years"] = s.dropna()
        res.append(row)
    return res


def table(res, title, bench_name, span):
    md = f"## {title}\n> 기간 {span} · 기준지수 {bench_name} · 신호일 종가 매수 가정 · 같은 종목 21거래일 안 중복 제거\n\n"
    md += "### 신호가 얼마나 자주 나오나\n| 거래량 배수 | 신호 수 | 하루 평균 신호 | 신호 있는 날 |\n| :--- | ---: | ---: | ---: |\n"
    for r in res:
        md += f"| {r['배수']} | {r['신호 수']:,} | {r['하루 평균']:.2f}개 | {r['신호 있는 날 %']:.0f}% |\n"
    md += "\n### 신호 후 성과 (지수 대비 초과수익)\n| 거래량 배수 | 1개월 초과 | 3개월 초과 | 6개월 초과 | 6개월 중앙값 | 6개월 지수 이긴 % | 6개월 +50%↑ | 6개월 -30%↓ |\n| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n"
    for r in res:
        md += (f"| {r['배수']} | {r['1개월 초과 평균']:+.2f}% | {r['3개월 초과 평균']:+.2f}% | {r['6개월 초과 평균']:+.2f}% | "
               f"{r['6개월 초과 중앙값']:+.2f}% | {r['6개월 지수 이긴 %']:.1f}% | {r['6개월 +50%↑ 비율']:.1f}% | {r['6개월 -30%↓ 비율']:.1f}% |\n")
    years = sorted(set().union(*[set(r["_years"].index) for r in res]))
    pick = [r for r in res if r["배수"] in ("조건 없음", "1.0배↑", "1.3배↑", "1.5배↑", "2.0배↑", "3.0배↑")]
    md += "\n### 연도별 3개월 초과수익 (매년 같은 방향인가)\n| 연도 | " + " | ".join(r["배수"] for r in pick) + " |\n| :--- |" + " ---: |" * len(pick) + "\n"
    step = 1 if len(years) <= 12 else 5
    ys = years[::step] if step == 1 else sorted(set((y // 5) * 5 for y in years))
    for y in ys:
        cells = []
        for r in pick:
            s = r["_years"]
            v = s.get(y) if step == 1 else s[(s.index >= y) & (s.index < y + 5)].mean()
            cells.append("—" if v is None or pd.isna(v) else f"{v:+.1f}%")
        md += f"| {y if step == 1 else f'{y}~{y + 4}'} | " + " | ".join(cells) + " |\n"
    return md + "\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    md = "# 📊 거래량 배수 백테스트 — 소셜 아비트리지 가격 조건\n\n"
    md += "> ⚠️ 소셜 데이터(레딧·StockTwits)는 과거 기록이 없어 **가격+거래량 조건만** 검증 · 지금 살아 있는 종목만 사용(생존 편향) → 절대 수익은 부풀려짐, **배수끼리 비교**로 해석\n\n"
    # A) 10년
    tick = caps_2b()
    print("10년 대상", len(tick))
    C, V = download(tick, period="11y")
    q = yf.download("QQQ", period="11y", interval="1d", auto_adjust=True, progress=False)["Close"].squeeze()
    C, V = C.loc[C.index >= C.index[-1] - pd.DateOffset(years=10)], V.loc[V.index >= V.index[-1] - pd.DateOffset(years=10)]
    resA = run(C, V, q, liquid=True)
    md += table(resA, f"A) 최근 10년 — 시총 $2B↑ {C.shape[1]}개 종목", "QQQ", f"{C.index[0]:%Y-%m} ~ {C.index[-1]:%Y-%m}")
    del C, V
    # B) 50년
    sp = sorted(get_sp500())
    print("50년 대상", len(sp))
    C, V = download(sp, start="1976-01-01")
    g = yf.download("^GSPC", start="1976-01-01", interval="1d", auto_adjust=True, progress=False)["Close"].squeeze()
    resB = run(C, V, g, liquid=False)
    md += table(resB, f"B) 약 50년 — 지금 S&P 500 {C.shape[1]}개 종목", "S&P 500(^GSPC)", f"{C.index[0]:%Y-%m} ~ {C.index[-1]:%Y-%m}")
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    main()
