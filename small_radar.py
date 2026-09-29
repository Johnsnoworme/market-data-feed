"""
🌱 소형 병목 레이더 (BE 초기형) — 매주
BE(블룸에너지)가 크게 오르기 전 같은 모양: 작지만 시대의 병목을 쥔 회사
조건 3개 모두: ① 병목 테마 산업(⚡전력 · 🧠AI 칩·장비 · 🔌AI 인프라: 메모리·광·부품)
              ② 매출 성장 30%↑ (최근 분기, 전년 대비)  ③ 지수보다 강함 (3개월 QQQ 대비 +)
대상: 미국 상장 시가총액 $2B~$10B, 하루 거래대금 2천만$↑ → 3개월 QQQ 대비 강한 순 최대 3개
결과: hanbang/small/latest.md · latest.json · YYYY-MM-DD.md
"""
import json, os, time
from datetime import datetime, timezone
import requests
import yfinance as yf
from jb_scanner import download_daily
from hanbang_radar import THEME_RULES, theme_of, fundamentals, ftxt, fvl, accumulation

OUT = "hanbang/small"
MIN_CAP, MAX_CAP = 2e9, 10e9
BOTTLENECK = ("⚡ 전력·에너지 병목", "🧠 AI 칩·장비", "🔌 AI 인프라 (메모리·광·부품)")
PRE_SECTORS = ("Technology", "Industrials", "Utilities", "Energy", "Basic Materials", "Telecommunications")
SHOW = 3


def universe():
    r = requests.get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true", timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"})
    r.raise_for_status()
    out = {}
    for x in r.json()["data"]["rows"]:
        s = (x.get("symbol") or "").strip()
        try:
            cap = float(x.get("marketCap") or 0)
        except ValueError:
            continue
        if not s or "^" in s or "/" in s or not (MIN_CAP <= cap < MAX_CAP):
            continue
        if (x.get("sector") or "") not in PRE_SECTORS:
            continue
        out[s.replace(".", "-")] = dict(name=(x.get("name") or "")[:40], cap=cap, sector=x.get("sector"), industry=x.get("industry"))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    u = universe()
    print(f"$2~10B 후보 섹터 종목: {len(u)}개")
    d = download_daily(set(u) | {"QQQ"}, period="1y")
    C, H, L, V = d["Close"], d["High"], d["Low"], d["Volume"]
    q = C["QQQ"].dropna()
    ny = q.index[-1].strftime("%Y-%m-%d")
    q63 = (q.iloc[-1] / q.iloc[-64] - 1) * 100
    pre = []
    for t in u:
        if t not in C.columns:
            continue
        c = C[t].dropna()
        if len(c) < 70 or c.index[-1] != q.index[-1]:
            continue
        dv = float((c.iloc[-20:] * V[t].reindex(c.index).iloc[-20:]).mean())
        vs63 = (c.iloc[-1] / c.iloc[-64] - 1) * 100 - q63
        if dv < 20e6 or vs63 <= 0:
            continue
        pre.append((t, round(float(vs63), 1), round(float((c.iloc[-1] / c.iloc[-252:].max() - 1) * 100), 1), c))
    print(f"지수보다 강함 + 거래대금 통과: {len(pre)}개")
    hits, near = [], []
    for t, vs63, dd, c in sorted(pre, key=lambda x: -x[1]):
        f = fundamentals(t)
        time.sleep(0.2)
        th = theme_of(f)
        if th not in BOTTLENECK:
            continue
        rev = f.get("rev")
        acc = accumulation(c, H[t], L[t], V[t], q)
        row = dict(ticker=t, name=u[t]["name"], cap_b=round(u[t]["cap"] / 1e9, 1), theme=th, industry=f.get("industry", ""),
                   rev=rev, vs63=vs63, dd=dd, acc=(acc or {}).get("score"), fund=ftxt(f))
        if rev is not None and rev >= 0.30:
            hits.append(row)
        else:
            near.append(row)
    hits = hits[:SHOW]
    md = f"# 🌱 소형 병목 레이더 (BE 초기형) — {ny}\n\n"
    md += ("> 작지만 시대의 병목을 쥔 회사 · 조건 3개 모두: ① 병목 테마(⚡전력 · 🧠AI 칩·장비 · 🔌메모리·광·부품) "
           "② 매출 성장 30%↑ ③ 3개월 QQQ 대비 + · 시가총액 $2~10B · 거래대금 2천만$↑ · 매수 추천 아님\n\n")
    if hits:
        md += "| # | 티커 | 회사 | 테마 | 시총 | 매출 성장 | 3개월 QQQ 대비 | 고점 대비 | 🧲 |\n| ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |\n"
        for i, r in enumerate(hits, 1):
            md += (f"| {i} | {fvl(r['ticker'])} | {r['name']} | {r['theme']} | ${r['cap_b']}B | {r['rev'] * 100:+.0f}% | "
                   f"{r['vs63']:+.0f}%p | {r['dd']:+.0f}% | {r['acc'] if r['acc'] is not None else '—'} |\n")
    else:
        md += "- 이번 주 3조건을 다 맞춘 종목 없음\n"
    if near:
        md += "\n> 아깝게 빠짐 (병목 테마 + 지수보다 강함, 매출 성장 30% 미만): " + ", ".join(
            f"{r['ticker']}({'' if r['rev'] is None else format(r['rev'] * 100, '+.0f') + '%'})" for r in near[:8]) + "\n"
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)
    open(f"{OUT}/{ny}.md", "w", encoding="utf-8").write(md)
    json.dump(dict(ny_date=ny, hits=hits, near=near[:8], generated_utc=datetime.now(timezone.utc).isoformat()),
              open(f"{OUT}/latest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(md)


if __name__ == "__main__":
    main()
