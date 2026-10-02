"""
🤖 유튜브 백업 요약 (2026-10-02 추가) — Mac이 꺼져 있어도 요약이 빠지지 않게
- 대상: 🐒 소수몽키(@sosumonkey) · 📊 성상현(@SSH_MacroBeyond)  ※ 🎖️ 장군님은 여러 채널 출연(검색 필요)이라 Mac 작업만 담당
- 방법: 채널 "동영상" 탭에서 새 영상 찾기 (RSS는 2026-10 기준 404) → Gemini API에 유튜브 주소를 주고 요약 (GitHub에서는 자막이 막혀 있지만 Gemini는 구글이 직접 영상을 봄)
- GEMINI_API_KEY(깃허브 Secret)가 없으면: 영상 링크만 있는 "대기" 노트를 저장 (놓친 영상이 있다는 건 알 수 있게)
- 결과: youtube/backup/<채널>/<video_id>.md + youtube/backup/index.json
- Obsidian 자동 생성기가 가져가서 📺 소수몽키 / 🎙️ 전문가 렌즈 폴더와 Daily 노트에 넣음
  (Claude 예약 작업이 이미 요약한 영상은 가져가지 않음. Claude가 나중에 같은 파일을 자세한 버전으로 바꿈)
"""
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

SYD = ZoneInfo("Australia/Sydney")
OUT = "youtube/backup"
SINCE = datetime(2026, 9, 30, tzinfo=timezone.utc)   # 이 날 이후 영상만
MAX_AGE = timedelta(days=7)
MAX_TRIES = 4
CHANNELS = {
    "sosumonkey": {"name": "소수몽키", "handle": "@sosumonkey"},
    "ssh": {"name": "성상현 (매크로비욘드)", "handle": "@SSH_MacroBeyond"},
}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}
MODELS = [m for m in [os.environ.get("GEMINI_MODEL"), "gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash"] if m]
KEY = os.environ.get("GEMINI_API_KEY", "").strip()
RAW = "https://raw.githubusercontent.com/Johnsnoworme/market-data-feed/main"

PROMPT_SOSU = """너는 한국 주식 유튜브 '소수몽키' 영상을 요약하는 비서다. 독자는 시드니에 사는 개인 트레이더 John이다.
영상을 처음부터 끝까지 보고, 한국어로 아주 쉽게, 중요한 내용을 빠짐없이 아래 형식의 마크다운만 출력하라 (앞뒤 설명 금지, 코드블럭 금지).
매수 추천은 하지 않는다. 사실과 의견을 구분한다. 영상에 없는 티커·숫자를 지어내지 않는다.

## ⚡ 핵심 3줄
1. 이모지 **굵은 한 문장** — 설명 1~2줄

2. 이모지 **굵은 한 문장** — 설명 1~2줄

3. 이모지 **굵은 한 문장** — 설명 1~2줄

> 🧭 **시장 판단**: 소수몽키 본인의 표현 그대로 한 줄

## 📖 자세히 (영상 흐름대로)
### 1️⃣ 이모지 소제목
- 이모지 불릿 3~6개 (주장·사례·숫자·출처·소수몽키 생각을 구분)
> 💡 **왜 중요?** 한 줄 (필요할 때만)

(영상 순서대로 소주제 5~9개, 소제목 사이 빈 줄 2개, 표·슬라이드 내용은 표로)

## 🎯 종목
| 티커 | 회사 | 소수몽키 입장 | 이유 한 줄 | 내 시스템 |
| :--- | :--- | :--- | :--- | :--- |
(미국 티커는 <a href="https://finviz.com/quote.ashx?t=T&p=w">T</a> 형식. 입장 = 👍 선호·👀 관심·⚠️ 주의·💬 언급만. '내 시스템' 칸: 아래 [내 추적 목록]에 있으면 ✅ Top 3 추적 중, [워치리스트]에 있으면 ✅ ⭐ 워치리스트, 없으면 -. 겹치는 종목을 맨 위에. 목록으로 스쳐간 종목은 마지막 한 줄 "💬 리스트만: ...")

## 📅 일정
- 영상에 나온 날짜·이벤트 (없으면 "언급 없음")

## ⚠️ 리스크·반대 의견
-

## 📝 사실 vs 의견
- ✅ 사실(영상 속 설명):
- 💭 의견·전망 (누구의 의견인지):

> 👉 **내가 할 일**: 새 진입 이유인지 아닌지 한 줄 (진입은 7개 룰로 직접 확인)
"""

PROMPT_SSH = """너는 매크로 유튜브 채널 '매크로비욘드'(성상현) 영상을 요약하는 비서다. 독자는 시드니의 개인 트레이더 John이다.
영상을 끝까지 보고 한국어로 아주 쉽게, 아래 형식의 마크다운만 출력하라 (앞뒤 설명 금지, 코드블럭 금지). 블록 사이에는 빈 줄.
매수 추천 금지. 사실(수치·발표)과 의견을 구분. 말하지 않은 티커를 지어내지 않는다.

🎯 **결론** — 이 사람이 지금 시장을 어떻게 보나, 핵심 구절은 **굵게**, 끝에 _(의견)_

🔎 **근거 1 · 짧은 소제목** — 1~3문장 (✅❌🔄⚠️📈📉 이모지를 뜻에 맞게)

🔎 **근거 2 · 짧은 소제목** — 1~3문장

이모지 **세 번째 요점 소제목** — 1~2문장

⚠️ **조심할 점** — 1~2문장

📌 **언급 섹터·티커**:
- 🔥 긍정/지금 주도:
- 👀 지켜볼 곳: (말한 경우만)
- ⚠️ 부정/위험: (말한 경우만)
- 💬 언급만:
(미국 티커는 [T](https://finviz.com/quote.ashx?t=T&p=w) 형식, 한국 주식은 이름 + "(한국 주식)", 개별 티커가 없으면 "🏷️ 개별 티커: 언급 없음")
"""


def clean(t):
    return re.sub(r'[\\/:*?"<>|#^\[\]]', "", t).strip()[:40].strip()


def rel_to_dt(rel, now):
    """'3시간 전' / '1일 전' / '5 hours ago' → 대략의 업로드 시각 (2026-10-02: RSS·영상 페이지가 GitHub에서 막혀 채널 목록의 상대 시간 사용)"""
    m = re.search(r"(\d+)\s*(초|분|시간|일|주|개월|second|minute|hour|day|week|month)", rel)
    if not m:
        return None
    n, u = int(m.group(1)), m.group(2)
    mult = {"초": 1, "second": 1, "분": 60, "minute": 60, "시간": 3600, "hour": 3600, "일": 86400, "day": 86400,
            "주": 604800, "week": 604800, "개월": 2592000, "month": 2592000}[u]
    return now - timedelta(seconds=n * mult)


def list_videos(handle, now):
    """채널 '동영상' 탭의 ytInitialData를 읽음 (Mac 작업의 공통 규칙 1⃣과 같은 방법). 쇼츠는 이 탭에 없음."""
    r = requests.get(f"https://www.youtube.com/{handle}/videos?hl=ko&gl=KR", headers=UA,
                     cookies={"CONSENT": "YES+1", "SOCS": "CAI"}, timeout=30)
    r.raise_for_status()
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", r.text, re.S)
    if not m:
        raise ValueError("ytInitialData 없음")
    out = []

    def walk(o):
        if len(out) >= 10:
            return
        if isinstance(o, dict):
            if "lockupViewModel" in o:
                lv = o["lockupViewModel"]
                js = json.dumps(lv, ensure_ascii=False)
                vid = (re.search(r'"contentId": "([\w-]{11})"', js) or [None, None])[1]
                title = (((lv.get("metadata") or {}).get("lockupMetadataViewModel") or {}).get("title") or {}).get("content", "")
                rel = (re.search(r'"content": "([^"]*(?:ago|전))"', js) or [None, ""])[1]
                ln = (re.search(r'"text": "(\d{1,2}:\d{2}(?::\d{2})?)"', js) or [None, ""])[1]
                if vid:
                    out.append({"id": vid, "title": title, "rel": rel, "length": ln, "pub": rel_to_dt(rel, now)})
                return
            if "videoRenderer" in o and o["videoRenderer"].get("videoId"):
                v = o["videoRenderer"]
                rel = (v.get("publishedTimeText") or {}).get("simpleText", "")
                title = "".join(x.get("text", "") for x in (v.get("title") or {}).get("runs", []))
                out.append({"id": v["videoId"], "title": title, "rel": rel,
                            "length": (v.get("lengthText") or {}).get("simpleText", ""), "pub": rel_to_dt(rel, now)})
                return
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(json.loads(m.group(1)))
    if not out:
        raise ValueError("목록 0개 (페이지 형식 변경?)")
    return out


def context():
    """Gemini가 '내 시스템' 칸을 채울 수 있게: 풀백 추적 중인 티커 + 워치리스트"""
    tr = ""
    try:
        j = json.load(open("top3/follow/latest.json", encoding="utf-8"))
        tr = ", ".join(sorted({r["ticker"] for r in j.get("rows", [])}))
    except Exception:
        pass
    wl = open("watchlist.txt", encoding="utf-8").read() if os.path.exists("watchlist.txt") else ""
    return f"\n\n[내 추적 목록 (Top 3·김종봉 8주 추적)]: {tr}\n[워치리스트]:\n{wl}\n"


def gemini(url, prompt):
    body = {"contents": [{"parts": [{"file_data": {"file_uri": url}}, {"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "mediaResolution": "MEDIA_RESOLUTION_LOW"}}
    last = ""
    for m in MODELS:
        u = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        for attempt in range(2):
            # 키는 주소 대신 헤더로 보냄 (새 형식 키 AQ.… 도 지원, 로그에 키가 안 남음)
            r = requests.post(u, json=body, timeout=600, headers={"x-goog-api-key": KEY})
            if r.status_code == 200:
                parts = r.json()["candidates"][0]["content"]["parts"]
                txt = "".join(p.get("text", "") for p in parts).strip()
                txt = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", txt)
                if len(txt) > 200:
                    return txt, m
                last = f"{m}: 답이 너무 짧음"
                break
            last = f"{m}: HTTP {r.status_code} {r.text[:200]}"
            if r.status_code in (404, 400) and "not found" in r.text.lower():
                break  # 모델 이름 없음 → 다음 모델
            if r.status_code in (429, 500, 503):
                time.sleep(30)
                continue
            break
    raise RuntimeError(last)


def note(ch, v, body, model):
    pub_syd = v["pub"].astimezone(SYD)
    daily = (pub_syd + timedelta(hours=5)).strftime("%Y-%m-%d")
    url = f"https://www.youtube.com/watch?v={v['id']}"
    src = "gemini-backup" if body else "gemini-stub"
    fm = (f"---\ndate: {pub_syd:%Y-%m-%d}\ndaily: {daily}\nvideo_id: {v['id']}\nvideo: {url}\n"
          f"uploaded: {pub_syd:%Y-%m-%d %H:%M} (시드니 · 추정)\nlength: {v.get('length', '')}\nsource: {src}\n"
          f"tags:\n  - {'소수몽키' if ch == 'sosumonkey' else '전문가렌즈'}\n  - 백업요약\n---\n")
    flag = (f"> 🤖 **Gemini 백업 요약** ({model}) — Mac이 꺼져 있어 GitHub가 대신 만든 요약이에요. Mac이 켜지면 Claude가 자세한 버전으로 바꿔요."
            if body else
            "> ⏳ **요약 대기** — Mac이 꺼져 있고 Gemini 키가 아직 없어서 링크만 저장했어요. Mac이 켜지면 Claude가 요약해요.")
    if ch == "sosumonkey":
        head = f"# 🐒 소수몽키 — {v['title']} ({pub_syd.month}/{pub_syd.day})\n> 🎬 [영상]({url}) · ⏱️ {v.get('length', '')}\n\n"
        if body:
            body = body.replace("## ⚡ 핵심 3줄\n", "## ⚡ 핵심 3줄\n" + flag + "\n\n", 1)
        else:
            body = f"## ⚡ 핵심 3줄\n{flag}\n\n🎬 [{v['title']}]({url})\n\n## 🎯 종목\n- (요약 대기)\n"
        return fm + head + body + "\n"
    # Daily 노트는 ![[이름#📊 요약]] 으로 이 칸을 불러옴
    head = (f"# 📊 성상현 — {v['title']}\n\n## 📊 요약\n"
            f"**📊 성상현 (의견)** — [매크로비욘드: {v['title']}]({url}) · {pub_syd:%Y-%m-%d} · ⏱️ {v.get('length', '')}\n\n{flag}\n\n")
    return fm + head + (body or "") + "\n"


LOG = []
_print = print
def print(*a):  # 실행 기록을 youtube/backup/last_run.txt에도 남김 (Actions 로그를 못 볼 때 확인용)
    LOG.append(" ".join(str(x) for x in a))
    _print(*a)


def main():
    os.makedirs(OUT, exist_ok=True)
    ip = os.path.join(OUT, "index.json")
    idx = json.load(open(ip, encoding="utf-8")) if os.path.exists(ip) else {}
    now = datetime.now(timezone.utc)
    ctx = context()
    for ch, info in CHANNELS.items():
        try:
            vids = list_videos(info["handle"], now)
            print(f"{info['name']}: 목록 {len(vids)}개 읽음 · 위 3개: " + " / ".join(f"{v['id']} {v['rel']}" for v in vids[:3]))
        except Exception as e:
            print(f"{info['name']}: ❌ 목록 실패 {e}")
            continue
        for v in vids:
            e = idx.get(v["id"], {})
            if e.get("published_utc"):  # 처음 본 시각의 추정값을 계속 사용 (상대 시간은 갈수록 부정확해짐)
                v["pub"] = datetime.fromisoformat(e["published_utc"])
            if not v["pub"] or not v["length"] or v["pub"] < SINCE or now - v["pub"] > MAX_AGE:
                continue
            if e.get("status") == "done" or e.get("tries", 0) >= MAX_TRIES:
                continue
            if e.get("status") == "stub" and not KEY:
                continue
            pub_syd = v["pub"].astimezone(SYD)
            fname = f"{pub_syd:%Y-%m-%d} {clean(v['title'])}"
            body, model, status, err = "", "", "stub", ""
            if KEY:
                try:
                    body, model = gemini(f"https://www.youtube.com/watch?v={v['id']}",
                                         (PROMPT_SOSU if ch == "sosumonkey" else PROMPT_SSH) + ctx)
                    status = "done"
                except Exception as ex:
                    err = str(ex)[:300]
                    print(f"   Gemini 실패 {v['id']}: {err}")
            if status != "done" and e.get("status") == "stub":
                idx[v["id"]] = {**e, "tries": e.get("tries", 0) + 1, "error": err}
                continue
            os.makedirs(os.path.join(OUT, ch), exist_ok=True)
            open(os.path.join(OUT, ch, f"{v['id']}.md"), "w", encoding="utf-8").write(note(ch, v, body, model))
            idx[v["id"]] = {"ch": ch, "title": v["title"], "name": fname,
                            "daily": (pub_syd + timedelta(hours=5)).strftime("%Y-%m-%d"),
                            "published_utc": v["pub"].isoformat(), "status": status, "model": model,
                            "tries": e.get("tries", 0) + (0 if status == "done" else 1), "error": err,
                            "updated_utc": now.isoformat(timespec="seconds")}
            print(f"   {'✅ 요약' if status == 'done' else '⏳ 대기'}: {info['name']} · {v['id']} · {v['title']}")
    json.dump(idx, open(ip, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(os.path.join(OUT, "last_run.txt"), "w", encoding="utf-8").write(
        f"{now:%Y-%m-%d %H:%M} UTC · Gemini 키 {'있음' if KEY else '없음'}\n" + "\n".join(LOG) + "\n")


if __name__ == "__main__":
    main()
