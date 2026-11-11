"""
🔭 조기 레이더 (2026-11-12 추가) — Weekly / Monthly 노트용, 기록 전용 (매수 추천 아님)

왜: Top 3는 시총 $10B+ 만 본다 → 샌디스크·블룸에너지 같은 종목은 $10B가 되기 전에는 안 보였다.
    그래서 Top 3 "앞 단계"를 한 칸 덧붙인다. 기존 Top 3 · 김종봉 · 풀백 추적은 전혀 건드리지 않는다.

3가지 (전부 Finviz 화면 그대로 + 이미 저장된 기록 세기 — Claude 토큰 0):
  ① 🎓 졸업 후보 Top 3 : Finviz Mid($2B~$10B) 스크리너의 Perf Week / Perf Month 상위 3개
  ② 🏭 업종 Top 3      : Finviz Groups(Industry)의 Perf Week / Perf Month 상위 3개
  ③ 🔁 반복 등장       : 최근 8주 동안 Daily Top 3 · Weekly Top 3 · 졸업 후보에 2번 이상 나온 종목

저장: early/weekly/2026-W46.md · early/monthly/2026-11.md (한 번 저장하면 다시 안 바뀜)
시점: Top 3 확정 기록과 같은 규칙 — 그 주/달 마지막 뉴욕 거래일 장 마감 뒤 ~ 다음 거래일 프리마켓 전.
원칙: 틀린 숫자를 저장하느니 저장하지 않는다 (하나라도 못 읽으면 저장 안 함 → 다음 예약 실행이 다시 시도).
테스트: EARLY_TEST=1 이면 지금 화면 그대로 early/_test.md 에만 저장 (확정 기록은 안 만듦).
"""
import datetime
import glob
import json
import os
import re
import sys
import time

import requests

from cloud_market_data import FINVIZ_HEADERS, KO_WD, _finviz_json_rows, _next_trading_day, finviz_window_session
from data_guard import is_common

OUT = "early"
TICK = re.compile(r"[A-Z][A-Z0-9.\-]{0,6}")
ORDER_NAME = {"perf1w": "Perf Week (최근 1주)", "perf4w": "Perf Month (최근 1개월)"}


def _get(url):
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=FINVIZ_HEADERS, timeout=20)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa
            last = e
            print(f"   Finviz 시도 {attempt + 1}/3 실패: {e}")
            time.sleep([5, 20, 0][attempt])
    raise last


def _debug(name, html):
    try:
        os.makedirs(OUT, exist_ok=True)
        open(f"{OUT}/_debug_{name}.html", "w", encoding="utf-8").write(html)
    except Exception:
        pass


def _check(vals, label):
    if len(vals) < 3:
        raise ValueError(f"{label}: 결과가 3개 미만")
    if vals != sorted(vals, reverse=True) or any(abs(v) > 500 for v in vals):
        raise ValueError(f"{label}: 숫자 순서/크기 이상 {vals}")


def mid_top3(order):
    """Finviz Mid($2B~$10B) 화면 상위 3개. 보통주만(유닛·워런트·임시 거래 제외)."""
    url = f"https://finviz.com/screener.ashx?v=152&f=cap_mid&o=-{order}&c=1,2,3,4,6,42,43"
    html = _get(url)
    rows = _finviz_json_rows(html)
    if not rows:
        _debug("mid", html)
        raise ValueError("졸업 후보: Finviz 데이터(JSON) 없음")
    out = []
    for r in rows:
        t, n = r.get("text", {}), r.get("numbers", {})
        tk, v = t.get("ticker"), n.get(order)
        if not tk or v is None or not TICK.fullmatch(tk) or not is_common(t.get("company", "")):
            continue
        out.append((tk, t.get("company", ""), t.get("sector", ""), t.get("industry", ""), float(v)))
        if len(out) == 3:
            break
    _check([x[4] for x in out], "졸업 후보")
    if any(not x[1] for x in out):
        raise ValueError("졸업 후보: 회사 이름 비어 있음")
    return out


def _walk_lists(j):
    """JSON 안의 '딕셔너리 목록'을 전부 찾아 줌."""
    if isinstance(j, list):
        if j and all(isinstance(x, dict) for x in j):
            yield j
        for x in j:
            yield from _walk_lists(x)
    elif isinstance(j, dict):
        for x in j.values():
            yield from _walk_lists(x)


def _num(x):
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        m = re.fullmatch(r"\s*([+\-]?\d+(?:\.\d+)?)\s*%?\s*", x)
        if m:
            return float(m.group(1))
    return None


def _flat(d):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out.setdefault(k2, v2)
        else:
            out.setdefault(k, v)
    return out


def industry_top3(order):
    """Finviz Groups → Industry 화면에서 Perf Week / Perf Month 상위 3개 업종."""
    import lxml.html
    url = f"https://finviz.com/groups.ashx?g=industry&v=140&o=-{order}"
    html = _get(url)
    name_keys = ("name", "label", "group", "industry", "ticker")
    perf_keys = {"perf1w": ("perf1w", "perfWeek", "perfW", "performanceWeek", "perf_week", "Perf Week"),
                 "perf4w": ("perf4w", "perfMonth", "perfM", "performanceMonth", "perf_month", "Perf Month")}[order]
    best = []
    # 1) 새 화면: 페이지 안 JSON
    for sc in lxml.html.fromstring(html).xpath("//script"):
        txt = sc.text_content().strip()
        if not txt.startswith(("{", "[")):
            continue
        try:
            j = json.loads(txt)
        except Exception:
            continue
        for lst in _walk_lists(j):
            if not (60 <= len(lst) <= 250):  # 업종은 140여 개
                continue
            rows = []
            for d in lst:
                f = _flat(d)
                nm = next((f[k] for k in name_keys if isinstance(f.get(k), str) and f.get(k)), None)
                pv = next((_num(f[k]) for k in perf_keys if _num(f.get(k)) is not None), None)
                if nm and pv is not None:
                    rows.append((nm, pv))
            if len(rows) >= 60 and len(rows) > len(best):
                best = rows
    # 2) 옛 화면: HTML 표
    if not best:
        try:
            import pandas as pd
            from io import StringIO
            col = {"perf1w": "Perf Week", "perf4w": "Perf Month"}[order]
            for df in pd.read_html(StringIO(html)):
                if "Name" in df.columns and col in df.columns and len(df) >= 60:
                    best = [(str(a), _num(str(b))) for a, b in zip(df["Name"], df[col]) if _num(str(b)) is not None]
                    break
        except Exception as e:
            print(f"   업종 HTML 표 읽기 실패: {e}")
    if not best:
        _debug("industry", html)
        raise ValueError(f"업종: Finviz 데이터 없음 ({len(html)}자 — 화면 구조 변경/차단 가능성)")
    best = sorted(best, key=lambda x: -x[1])[:3]  # Finviz 정렬과 같지만, 순서가 달라도 안전하게 직접 정렬
    _check([v for _, v in best], "업종")
    return best


def _tickers(md, heading=None):
    if heading:
        m = re.search(heading + r"[^\n]*\n([\s\S]*?)(?:\n## |\n### |\Z)", md)
        md = m.group(1) if m else ""
    return re.findall(r"^\| \[([A-Z][A-Z0-9.\-]{0,6})\]", md, re.M)


def repeats(end, weeks=8, extra=()):
    """최근 8주: Daily Top 3(뉴욕 거래일 기준, 중복 날짜 1번) · Weekly Top 3 · 졸업 후보에 나온 횟수."""
    start = end - datetime.timedelta(days=weeks * 7 - 1)
    cnt = {}

    def add(t, k):
        cnt.setdefault(t, {"d": 0, "w": 0, "m": 0})[k] += 1

    try:
        days = json.load(open("archive/daily/index.json", encoding="utf-8")).get("days", {})
    except Exception:
        days = {}
    seen = set()
    for syd, ny in sorted(days.items()):
        if ny in seen:
            continue
        try:
            nd = datetime.date.fromisoformat(ny)
        except Exception:
            continue
        p = f"archive/daily/{syd}.md"
        if not (start <= nd <= end) or not os.path.exists(p):
            continue
        seen.add(ny)
        for t in _tickers(open(p, encoding="utf-8").read(), "## 🚀 Daily Top 3"):
            add(t, "d")

    def in_window(name):  # 2026-W45 → 그 주 금요일
        try:
            y, w = name.split("-W")
            fri = datetime.date.fromisocalendar(int(y), int(w), 5)
        except Exception:
            return False
        return start <= fri <= end + datetime.timedelta(days=4)

    for p in sorted(glob.glob("archive/weekly/*.md")):
        if in_window(os.path.basename(p)[:-3]):
            for t in _tickers(open(p, encoding="utf-8").read(), "## Weekly Top 3"):
                add(t, "w")
    for p in sorted(glob.glob(f"{OUT}/weekly/*.md")):
        if in_window(os.path.basename(p)[:-3]):
            for t in _tickers(open(p, encoding="utf-8").read(), "### 🎓 졸업 후보"):
                add(t, "m")
    for t in extra:  # 이번에 새로 뽑은 졸업 후보 (아직 파일로 저장되기 전)
        add(t, "m")
    rows = [(t, c) for t, c in cnt.items() if c["d"] + c["w"] + c["m"] >= 2]
    rows.sort(key=lambda x: (-(x[1]["d"] + x[1]["w"] + x[1]["m"]), -x[1]["w"], x[0]))
    return rows[:8]


def fv(t):
    return f"[{t}](https://finviz.com/quote.ashx?t={t})"


def build(kind, name, order, d, stamp, weekly_extra=True):
    mid = mid_top3(order)
    time.sleep(2)
    ind = industry_top3(order)
    rep = repeats(d, extra=[x[0] for x in mid] if weekly_extra else ())
    md = f"# 🔭 조기 레이더 — {kind} {name}\n\n"
    md += (f"> 📅 Finviz {ORDER_NAME[order]} · 🗽 뉴욕 {d.isoformat()}({KO_WD[d.weekday()]}) 장 마감 기준 · 확정 {stamp}\n"
           "> Top 3($10B+)의 **앞 단계** 기록 · 매수 추천 아님 — 진입은 7개 룰이 모두 맞을 때만\n\n")
    md += "### 🎓 졸업 후보 Top 3 (시총 $2B~$10B)\n"
    md += "| 티커 | 회사 이름 | 섹터 · 업종 | 변동률 |\n| :--- | :--- | :--- | :--- |\n"
    for t, c, s, i, v in mid:
        md += f"| {fv(t)} | {c} | {s}{' · ' + i if i else ''} | {v:+.2f}% |\n"
    md += f"\n👉 [Finviz Mid-Cap 스크리너 전체보기](https://finviz.com/screener.ashx?v=141&f=cap_mid&o=-{order})\n\n"
    md += "### 🏭 업종 Top 3 (돈이 먼저 들어온 곳)\n"
    md += "| 업종 | 변동률 |\n| :--- | :--- |\n"
    for n, v in ind:
        md += f"| {n} | {v:+.2f}% |\n"
    md += f"\n👉 [Finviz 업종 전체보기](https://finviz.com/groups.ashx?g=industry&v=140&o=-{order})\n\n"
    md += "### 🔁 반복 등장 (최근 8주, 2번 이상)\n"
    if rep:
        md += "| 티커 | Daily Top 3 | Weekly Top 3 | 졸업 후보 | 합계 |\n| :--- | ---: | ---: | ---: | ---: |\n"
        for t, c in rep:
            md += f"| {fv(t)} | {c['d']} | {c['w']} | {c['m']} | {c['d'] + c['w'] + c['m']} |\n"
        md += "\n> 한 번은 뉴스, 반복은 돈의 흐름 — 여러 번 찍힌 종목은 풀백 구간을 따로 확인\n"
    else:
        md += "- 최근 8주 동안 2번 이상 등장한 종목 없음\n"
    return md


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    test = os.environ.get("EARLY_TEST") == "1"
    d = finviz_window_session(now)
    if d is None and not test:
        print("뉴욕 장중·프리마켓 → 저장 안 함")
        return
    jobs = []
    if d is not None:
        nxt = _next_trading_day(d)
        if nxt.isocalendar()[:2] != d.isocalendar()[:2]:
            iso = d.isocalendar()
            jobs.append(("Weekly", f"{iso[0]}-W{iso[1]:02d}", "perf1w"))
        if (nxt.year, nxt.month) != (d.year, d.month):
            jobs.append(("Monthly", f"{d.year}-{d.month:02d}", "perf4w"))
    failed = False
    for kind, name, order in jobs:
        path = f"{OUT}/{kind.lower()}/{name}.md"
        if os.path.exists(path):
            print(f"{kind} {name}: 이미 확정됨 (그대로 둠)")
            continue
        try:
            md = build(kind, name, order, d, stamp, weekly_extra=(kind == "Weekly"))
        except Exception as e:
            print(f"⛔ {kind} {name}: {e} → 저장하지 않음 (다음 실행에서 다시 시도)")
            failed = True
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(md)
        print(f"📌 조기 레이더 {kind} {name} 확정 저장")
    if not jobs:
        print("오늘은 주/달의 마지막 거래일이 아님 → 확정 기록 없음")
    if test:
        dd = d or (now.date() - datetime.timedelta(days=1))
        os.makedirs(OUT, exist_ok=True)
        parts = []
        for kind, order in (("Weekly", "perf1w"), ("Monthly", "perf4w")):
            try:
                parts.append(build(kind, "테스트(지금 화면)", order, dd, stamp, weekly_extra=False))
            except Exception as e:
                parts.append(f"# ⛔ {kind} 테스트 실패\n\n{e}\n")
                failed = True
        open(f"{OUT}/_test.md", "w", encoding="utf-8").write("\n\n---\n\n".join(parts))
        print(open(f"{OUT}/_test.md", encoding="utf-8").read())
    if failed:
        sys.exit(1)  # Actions에 빨간색으로 표시


if __name__ == "__main__":
    main()
