"""
드러켄밀러(Duquesne Family Office, CIK 1536411) 13F 트래커
- SEC EDGAR에서 13F-HR 전체 이력을 모아 분기별 보유 종목을 저장하고, 직전 분기와 비교한다.
- 13F: 분기 말 기준 미국 상장 주식·옵션 보유 내역, 분기 끝나고 45일 안에 공시 (연 4회: 대략 2/14, 5/15, 8/14, 11/14)
- 결과: druck/latest.md (최신 분기 + 변화), druck/history.md (전 분기 요약, 학습용),
        druck/quarters/YYYY-QN.json, druck/cusip_map.json (CUSIP→티커 캐시)
"""
import json, os, re, time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import requests

CIK = "1536411"
OUT = "druck"
UA = os.environ.get("SEC_UA") or "Johnsnoworme-market-data-feed github-actions@users.noreply.github.com"
H = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
S = requests.Session()
S.headers.update(H)


def get(url, **kw):
    for i in range(4):
        r = S.get(url, timeout=30, **kw)
        if r.status_code == 200:
            time.sleep(0.15)
            return r
        if r.status_code in (403, 429, 503):
            time.sleep(2 + i * 3)
            continue
        r.raise_for_status()
    r.raise_for_status()


def list_filings():
    j = get(f"https://data.sec.gov/submissions/CIK{CIK.zfill(10)}.json").json()
    blocks = [j["filings"]["recent"]]
    for f in j["filings"].get("files", []):
        blocks.append(get(f"https://data.sec.gov/submissions/{f['name']}").json())
    out = []
    for b in blocks:
        for form, acc, fdate, rdate in zip(b["form"], b["accessionNumber"], b["filingDate"], b["reportDate"]):
            if form in ("13F-HR", "13F-HR/A"):
                out.append(dict(form=form, acc=acc, filed=fdate, period=rdate))
    return sorted(out, key=lambda x: (x["period"], x["filed"]))


def quarter(period):
    d = datetime.strptime(period, "%Y-%m-%d")
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def info_table(acc):
    base = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{acc.replace('-', '')}"
    idx = get(f"{base}/index.json").json()
    xmls = [it["name"] for it in idx["directory"]["item"] if it["name"].lower().endswith(".xml")]
    cand = [n for n in xmls if "primary_doc" not in n.lower()]
    for n in cand + xmls:
        txt = get(f"{base}/{n}").text
        if "infoTable" in txt:
            return txt
    return None


def parse(xml_text, dollars):
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    rows = []
    for it in root.iter():
        if not it.tag.endswith("infoTable"):
            continue
        v = {}
        for ch in it.iter():
            tag = ch.tag.split("}")[-1]
            if ch.text and ch.text.strip():
                v[tag] = ch.text.strip()
        try:
            val = float(v.get("value", "0").replace(",", ""))
        except ValueError:
            val = 0.0
        if not dollars:
            val *= 1000
        rows.append(dict(name=v.get("nameOfIssuer", ""), cls=v.get("titleOfClass", ""), cusip=v.get("cusip", "").upper(),
                         value=val, shares=float(v.get("sshPrnamt", "0").replace(",", "") or 0),
                         kind=v.get("sshPrnamtType", ""), putcall=(v.get("putCall") or "").upper()))
    agg = {}
    for r in rows:
        k = (r["cusip"], r["putcall"])
        a = agg.setdefault(k, dict(r, value=0.0, shares=0.0))
        a["value"] += r["value"]
        a["shares"] += r["shares"]
    return list(agg.values())


def map_cusips(cusips, cache):
    todo = [c for c in cusips if c and c not in cache]
    for i in range(0, len(todo), 10):
        chunk = todo[i:i + 10]
        body = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in chunk]
        try:
            r = requests.post("https://api.openfigi.com/v3/mapping", json=body, timeout=30,
                              headers={"Content-Type": "application/json"})
            if r.status_code == 429:
                time.sleep(15)
                r = requests.post("https://api.openfigi.com/v3/mapping", json=body, timeout=30,
                                  headers={"Content-Type": "application/json"})
            res = r.json() if r.status_code == 200 else [{}] * len(chunk)
        except Exception as e:
            print(f"OpenFIGI 실패: {e}")
            res = [{}] * len(chunk)
        for c, x in zip(chunk, res):
            d = (x or {}).get("data") or []
            cache[c] = d[0].get("ticker", "") if d else ""
        time.sleep(2.6)  # 키 없이 분당 25회 제한
    return cache


def label(h, cmap):
    t = cmap.get(h["cusip"]) or ""
    base = t or h["name"][:22]
    return base + (f" {h['putcall']}" if h["putcall"] else "")


def fv(h, cmap):
    t = cmap.get(h["cusip"])
    lab = label(h, cmap)
    return f"[{lab}](https://finviz.com/quote.ashx?t={t}&p=w)" if t else lab


def money(v):
    return f"${v / 1e9:.2f}B" if v >= 1e9 else f"${v / 1e6:.0f}M"


def main():
    os.makedirs(f"{OUT}/quarters", exist_ok=True)
    cmap_p = f"{OUT}/cusip_map.json"
    cmap = json.load(open(cmap_p)) if os.path.exists(cmap_p) else {}
    filings = list_filings()
    print(f"13F 공시 {len(filings)}건")
    # 분기마다 원본(13F-HR) 기준, 같은 분기 여러 건이면 가장 늦은 원본 사용 (정정본 중 전체 재작성은 SEC상 표시가 애매해 제외)
    by_q = {}
    for f in filings:
        if f["form"] == "13F-HR":
            by_q[quarter(f["period"])] = f
    new_any = False
    for q, f in sorted(by_q.items()):
        p = f"{OUT}/quarters/{q}.json"
        if os.path.exists(p):
            continue
        xml = info_table(f["acc"])
        if not xml:
            print(f"{q}: XML 없음 → 건너뜀")
            continue
        dollars = f["filed"] >= "2023-01-03"
        hold = parse(xml, dollars)
        json.dump(dict(quarter=q, period=f["period"], filed=f["filed"], acc=f["acc"], holdings=hold),
                  open(p, "w"), ensure_ascii=False, indent=1)
        print(f"{q}: {len(hold)}종목 저장")
        new_any = True
    qs = sorted(fn[:-5] for fn in os.listdir(f"{OUT}/quarters") if fn.endswith(".json"))
    data = {q: json.load(open(f"{OUT}/quarters/{q}.json")) for q in qs}
    allc = {h["cusip"] for d in data.values() for h in d["holdings"]}
    cmap = map_cusips(sorted(allc), cmap)
    json.dump(cmap, open(cmap_p, "w"), indent=1, sort_keys=True)
    if not qs:
        print("저장된 분기 없음")
        return

    def book(d):
        tot = sum(h["value"] for h in d["holdings"]) or 1
        return {(h["cusip"], h["putcall"]): dict(h, w=h["value"] / tot * 100) for h in d["holdings"]}, tot

    # 최신 분기 + 변화
    cur_q = qs[-1]
    cur, tot = book(data[cur_q])
    prev, ptot = book(data[qs[-2]]) if len(qs) > 1 else ({}, 1)
    new = [h for k, h in cur.items() if k not in prev]
    gone = [h for k, h in prev.items() if k not in cur]
    chg = []
    for k, h in cur.items():
        if k in prev and prev[k]["shares"]:
            r = h["shares"] / prev[k]["shares"] - 1
            if abs(r) >= 0.2:
                chg.append((r, h))
    d = data[cur_q]
    md = f"# 🦅 드러켄밀러 13F — {cur_q} (분기 말 {d['period']}, 공시 {d['filed']})\n\n"
    md += (f"> Duquesne Family Office · {len(cur)}종목 · 총 {money(tot)} · 직전 {qs[-2] if len(qs) > 1 else '—'} 대비 · "
           f"13F는 45일 늦은 스냅샷(미국 주식·옵션만, 채권·통화·해외·숏은 안 보임) · 업데이트 {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n")
    md += "### 🏆 비중 상위 15\n| # | 종목 | 비중 | 금액 | 직전 대비 |\n| ---: | :--- | ---: | ---: | :--- |\n"
    for i, (k, h) in enumerate(sorted(cur.items(), key=lambda kv: -kv[1]["value"])[:15], 1):
        if k not in prev:
            tag = "🆕 신규"
        elif prev[k]["shares"]:
            r = h["shares"] / prev[k]["shares"] - 1
            tag = "➕ 늘림" if r >= 0.2 else ("➖ 줄임" if r <= -0.2 else "그대로")
            tag += f" ({r * 100:+.0f}%)" if abs(r) >= 0.2 else ""
        else:
            tag = "—"
        md += f"| {i} | {fv(h, cmap)} | {h['w']:.1f}% | {money(h['value'])} | {tag} |\n"
    md += "\n### 🆕 새로 산 것 (비중 순)\n" + ("".join(f"- {fv(h, cmap)} — {h['w']:.1f}% · {h['name']}\n" for h in sorted(new, key=lambda h: -h['w'])[:20]) or "- 없음\n")
    md += "\n### ❌ 다 판 것 (직전 비중 순)\n" + ("".join(f"- {fv(h, cmap)} — 직전 {h['w']:.1f}% · {h['name']}\n" for h in sorted(gone, key=lambda h: -h['w'])[:20]) or "- 없음\n")
    up = sorted([x for x in chg if x[0] > 0], key=lambda x: -x[1]["w"])[:12]
    dn = sorted([x for x in chg if x[0] < 0], key=lambda x: -x[1]["w"])[:12]
    md += "\n### ➕ 크게 늘린 것 (주식 수 +20%↑)\n" + ("".join(f"- {fv(h, cmap)} {r * 100:+.0f}% → 비중 {h['w']:.1f}%\n" for r, h in up) or "- 없음\n")
    md += "\n### ➖ 크게 줄인 것 (주식 수 -20%↓)\n" + ("".join(f"- {fv(h, cmap)} {r * 100:+.0f}% → 비중 {h['w']:.1f}%\n" for r, h in dn) or "- 없음\n")
    md += f"\n> 전체 이력(학습용): druck/history.md · 원본: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={CIK}&type=13F\n"
    open(f"{OUT}/latest.md", "w", encoding="utf-8").write(md)

    # 전 분기 이력 (학습용): 분기마다 상위 10 + 신규 상위 5 + 전량 매도 상위 5
    hm = "# 🦅 드러켄밀러 13F 전체 이력 (학습용)\n\n> 분기마다: 총액 · 종목 수 · 상위 10 · 새로 산 것 · 다 판 것. 최신 분기가 위.\n\n"
    for i in range(len(qs) - 1, -1, -1):
        q = qs[i]
        c, t = book(data[q])
        pv = book(data[qs[i - 1]])[0] if i > 0 else {}
        top = sorted(c.values(), key=lambda h: -h["value"])[:10]
        nw = sorted([h for k, h in c.items() if k not in pv], key=lambda h: -h["w"])[:5] if pv else []
        gn = sorted([h for k, h in pv.items() if k not in c], key=lambda h: -h["w"])[:5]
        hm += f"## {q} · {money(t)} · {len(c)}종목\n"
        hm += "- 상위: " + ", ".join(f"{label(h, cmap)} {h['w']:.0f}%" for h in top) + "\n"
        if nw:
            hm += "- 🆕 " + ", ".join(f"{label(h, cmap)} {h['w']:.1f}%" for h in nw) + "\n"
        if gn:
            hm += "- ❌ " + ", ".join(f"{label(h, cmap)} (직전 {h['w']:.1f}%)" for h in gn) + "\n"
        hm += "\n"
    open(f"{OUT}/history.md", "w", encoding="utf-8").write(hm)
    json.dump({"latest": cur_q, "quarters": qs, "new_filing": new_any,
               "updated_utc": datetime.now(timezone.utc).isoformat()}, open(f"{OUT}/status.json", "w"), indent=1)
    if os.path.exists(f"{OUT}/error.txt"):
        os.remove(f"{OUT}/error.txt")
    print(md)


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception:
        os.makedirs(OUT, exist_ok=True)
        open(f"{OUT}/error.txt", "w").write(datetime.now(timezone.utc).isoformat() + "\n" + traceback.format_exc())
        print(traceback.format_exc())
