"""
🩺 GitHub 건강검진 + 자가 복구 (2026-10-02 추가)
- 3시간마다: "있어야 할 결과물"이 제때 생겼는지 직접 확인 (작업이 '성공'이라고 말하는 것을 믿지 않음)
- 빠졌으면 해당 작업을 다시 실행 (하루 최대 2번까지 — 같은 실패를 무한 반복하지 않음)
- 최근 24시간 안에 실패(빨간색)한 작업도 찾아서 한 번 다시 실행
- 결과: health/status.md (지금 상태, 한눈에) · health/log.md (문제·원인·조치 일지 — 배운 것이 쌓임) · health/state.json
"""
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

SYD, NY = ZoneInfo("Australia/Sydney"), ZoneInfo("America/New_York")
REPO = os.environ.get("GITHUB_REPOSITORY", "Johnsnoworme/market-data-feed")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
H = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}
API = f"https://api.github.com/repos/{REPO}"
MAX_RETRY = 2
now = datetime.now(timezone.utc)
syd = now.astimezone(SYD)
today = syd.strftime("%Y-%m-%d")
os.makedirs("health", exist_ok=True)
state = json.load(open("health/state.json")) if os.path.exists("health/state.json") else {}
retries = state.get("retries", {}) if state.get("day") == today else {}
checks, actions, incidents = [], [], []


def dispatch(wf, why):
    key = wf
    if retries.get(key, 0) >= MAX_RETRY:
        actions.append(f"⛔ {wf}: 오늘 이미 {MAX_RETRY}번 다시 실행함 → 사람/Claude 확인 필요")
        incidents.append((why, f"{wf} 재실행 한도 초과 — 원인 확인 필요"))
        return
    r = requests.post(f"{API}/actions/workflows/{wf}/dispatches", headers=H, json={"ref": "main"}, timeout=30)
    ok = r.status_code == 204
    retries[key] = retries.get(key, 0) + 1
    actions.append(f"{'🔁' if ok else '❌'} {wf} 다시 실행 ({'성공' if ok else r.status_code})")
    incidents.append((why, f"{wf} 자동 재실행 {'요청함' if ok else '실패 ' + str(r.status_code)}"))


def exists(p):
    return os.path.exists(p)


# 1) 📸 오늘 Daily 스냅샷 — 시드니 12:30 이후에는 반드시 있어야 함 (실행 3번 = 시드니 아침~점심)
snap = f"archive/daily/{today}.md"
if exists(snap):
    checks.append(f"✅ 📸 Daily 스냅샷 {today}")
elif syd.hour * 60 + syd.minute >= 12 * 60 + 30:
    checks.append(f"❌ 📸 Daily 스냅샷 {today} 없음")
    dispatch("market_data.yml", f"Daily 스냅샷 {today} 없음 (예약 실행 3번 모두 실패 또는 지연)")
else:
    checks.append(f"⏳ 📸 Daily 스냅샷 {today} — 아직 시간 전 (12:30까지)")

# 2) 🔔 풀백 추적 — 스냅샷의 뉴욕 거래일 결과가 있어야 함
try:
    days = json.load(open("archive/daily/index.json"))["days"]
    ny = days.get(today)
    if ny:
        if exists(f"top3/follow/{ny}.md"):
            checks.append(f"✅ 🔔 풀백 추적 {ny}")
        else:
            checks.append(f"❌ 🔔 풀백 추적 {ny} 없음")
            dispatch("top3_follow.yml", f"풀백 추적 {ny} 없음 (스냅샷은 있음)")
except Exception as e:
    checks.append(f"⚠️ 🔔 풀백 확인 실패: {e}")

# 3) 📦 지난주 Weekly 확정 — 토요일 시드니 12시 이후
last_fri = (now.astimezone(NY).date() - timedelta(days=(now.astimezone(NY).weekday() - 4) % 7))
if now.astimezone(NY).weekday() == 4 and now.astimezone(NY).hour < 17:
    last_fri -= timedelta(days=7)
iso = (last_fri - timedelta(days=4)).isocalendar()
wk = f"{iso[0]}-W{iso[1]:02d}"
if exists(f"archive/weekly/{wk}.md"):
    checks.append(f"✅ 📦 Weekly {wk}")
elif (now - datetime.combine(last_fri, datetime.min.time(), NY).astimezone(timezone.utc)) > timedelta(hours=40):
    checks.append(f"❌ 📦 Weekly {wk} 없음")
    dispatch("market_data.yml", f"Weekly {wk} 확정 기록 없음")
else:
    checks.append(f"⏳ 📦 Weekly {wk} — 아직 시간 전")

# 4) 🤖 유튜브 백업 — 마지막 실행이 12시간 안
try:
    first = open("youtube/backup/last_run.txt", encoding="utf-8").readline()
    t = datetime.strptime(first[:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    body = open("youtube/backup/last_run.txt", encoding="utf-8").read()
    if now - t > timedelta(hours=12):
        checks.append(f"❌ 🤖 유튜브 백업 마지막 실행 {t:%m-%d %H:%M} UTC (12시간 넘음)")
        dispatch("yt_backup.yml", "유튜브 백업이 12시간 넘게 안 돌았음")
    elif "❌" in body:
        checks.append("⚠️ 🤖 유튜브 백업: 목록 읽기 실패 있음 (유튜브 페이지 형식 변경 가능성) — last_run.txt 확인")
        incidents.append(("유튜브 목록 읽기 실패", "yt_backup.py의 list_videos 점검 필요 (페이지 형식 변경?)"))
    elif "Gemini 실패" in body:
        checks.append("⚠️ 🤖 유튜브 백업: Gemini 요약 실패 있음 (키·한도·모델 이름) — 다음 실행 때 자동 재시도")
    else:
        checks.append(f"✅ 🤖 유튜브 백업 ({t:%m-%d %H:%M} UTC)")
except Exception as e:
    checks.append(f"⚠️ 🤖 유튜브 백업 확인 실패: {e}")

# 5) 🚦 최근 24시간 실패한 작업 → 한 번 다시 실행
try:
    runs = requests.get(f"{API}/actions/runs?per_page=60", headers=H, timeout=30).json().get("workflow_runs", [])
    latest = {}
    for r in runs:  # 작업마다 가장 최근 실행만 본다 (이미 다시 성공했으면 괜찮음)
        latest.setdefault(r["path"].split("/")[-1], r)
    bad = [(wf, r) for wf, r in latest.items()
           if r.get("conclusion") == "failure" and now - datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) < timedelta(hours=24)
           and wf not in ("health_check.yml",)]
    if not bad:
        checks.append("✅ 🚦 최근 24시간 실패한 작업 없음")
    for wf, r in bad:
        checks.append(f"❌ 🚦 {r['name']} 마지막 실행 실패 ({r['created_at'][:16]})")
        dispatch(wf, f"{r['name']} 실패 (빨간색)")
except Exception as e:
    checks.append(f"⚠️ 🚦 실행 기록 확인 실패: {e}")

# 6) 🧭 김종봉 주간 기록 — 뉴욕 토요일 18시(금요일 마감 + 26시간) 이후에는 반드시 있어야 함 (2026-10-05 추가)
#    (2026-10-02 주간 기록이 '성공' 표시 뒤에서 조용히 빠졌던 일 때문에)
jb_file = f"scanner/jb/{last_fri.isoformat()}.md"
if exists(jb_file):
    checks.append(f"✅ 🧭 김종봉 주간 {last_fri}")
elif now > datetime.combine(last_fri, datetime.min.time(), NY).astimezone(timezone.utc) + timedelta(hours=16 + 26):
    checks.append(f"❌ 🧭 김종봉 주간 {last_fri} 없음")
    dispatch("jb_scanner.yml", f"김종봉 주간 기록 {last_fri} 없음 (Yahoo 종가 지연 가능성)")
else:
    checks.append(f"⏳ 🧭 김종봉 주간 {last_fri} — 아직 시간 전 (뉴욕 토요일 18시까지)")

# 7) 🎯 한 방 레이더 · 🔔 Top 3 추적 — 최신 뉴욕 거래일 날짜로 저장됐는지 (마감 + 16시간 이후 검사, 2026-10-05 추가)
#    (Yahoo 종가가 늦게 들어와 한 방 레이더가 매일 하루 늦은 데이터로 저장되던 일 때문에)
try:
    from ny_session import expected_session
    exp = expected_session(now)
    due = datetime.combine(exp, datetime.min.time(), NY).astimezone(timezone.utc) + timedelta(hours=16 + 16)
    for label, path, wf in (("🎯 한 방 레이더", "hanbang/radar", "hanbang_radar.yml"),
                            ("🔔 Top 3 추적", "top3/follow", "top3_follow.yml")):
        if exists(f"{path}/{exp.isoformat()}.md"):
            checks.append(f"✅ {label} {exp} (최신 거래일)")
        elif now > due:
            checks.append(f"❌ {label} {exp} 없음 (최신 거래일 기록이 안 생김)")
            dispatch(wf, f"{label} {exp} 기록 없음 (Yahoo 종가 지연 가능성)")
        else:
            checks.append(f"⏳ {label} {exp} — 아직 시간 전 (Yahoo 종가는 마감 후 약 6시간 뒤 들어옴)")
except Exception as e:
    checks.append(f"⚠️ 🎯 한 방·Top 3 날짜 확인 실패: {e}")

# 8) 🔎 데이터 품질 — 숫자·링크가 상식에 맞는지 (2026-10-07 추가: MMEDV When Issued +161%가 Top 3 1위로 들어간 사고)
#    · HTML 링크(<a href) = ❌ (표 안·아이폰에서 안 눌림)
#    · When Issued·권리·워런트 종목 = ❌ → market_data 다시 실행 (새 필터가 거름)
#    · 대형주 하루 +60%↑ / 주 +100%↑ / 달 +200%↑ = ⚠️ 확인 필요
#    · "데이터 수집 실패" = ❌ → 다시 실행
try:
    import re as _re
    probs = []
    for f in ["Market_Data.md", snap] + [f"archive/weekly/{wk}.md"]:
        if not exists(f):
            continue
        t = open(f, encoding="utf-8").read()
        if "<a href" in t:
            probs.append(("❌", f"{f}: HTML 링크 있음 (안 눌림)"))
        if "데이터 수집 실패" in t:
            probs.append(("❌", f"{f}: 데이터 수집 실패 표시"))
        for sec, lim in (("Daily", 60), ("Weekly", 100), ("Monthly", 200)):
            m = _re.search(r"## " + sec + r" Top 3\n([\s\S]*?)(?:\n## |$)", t)
            if not m:
                continue
            for row in m.group(1).splitlines():
                if not row.startswith("| [") and not row.startswith("| <"):
                    continue
                low = row.lower()
                tk = (_re.search(r"t=([A-Za-z0-9.\-]+)", row) or [None, "?"])[1]
                if "when issued" in low or " rights" in low or " warrant" in low:
                    probs.append(("❌", f"{f} {sec}: {tk} 상장 전 임시 거래/권리·워런트 종목"))
                v = _re.search(r"\|\s*([+\-][0-9.]+)%\s*\|\s*$", row)
                if v and abs(float(v.group(1))) > lim:
                    probs.append(("⚠️", f"{f} {sec}: {tk} {v.group(1)}% — 대형주치고 비정상, 확인 필요"))
    if not probs:
        checks.append("✅ 🔎 데이터 품질 (링크·숫자 상식 검사)")
    for lv, msg in probs:
        checks.append(f"{lv} 🔎 {msg}")
    if any(lv == "❌" and "Market_Data" in msg for lv, msg in probs):
        dispatch("market_data.yml", "Top 3 데이터 품질 문제 (HTML 링크/임시 거래 종목/수집 실패)")
except Exception as e:
    checks.append(f"⚠️ 🔎 데이터 품질 확인 실패: {e}")

# 결과 쓰기
bad_n = sum(c.startswith(("❌", "⚠️")) for c in checks)
md = f"# 🩺 GitHub 건강검진\n\n> 마지막 검사: {syd:%Y-%m-%d %H:%M} 시드니 · {'✅ 모두 정상' if not bad_n else f'⚠️ 문제 {bad_n}개'}\n\n"
md += "\n".join(f"- {c}" for c in checks) + "\n"
if actions:
    md += "\n## 🔧 자동 조치\n" + "\n".join(f"- {a}" for a in actions) + "\n"
md += "\n> 문제·원인·조치 일지: health/log.md (같은 문제가 반복되면 Claude가 근본 원인을 고침)\n"
open("health/status.md", "w", encoding="utf-8").write(md)
if incidents:
    new_log = not exists("health/log.md")
    with open("health/log.md", "a", encoding="utf-8") as f:
        if new_log:
            f.write("# 🧠 GitHub 자동화 일지 (문제 · 조치)\n\n")
        for why, what in incidents:
            f.write(f"- {syd:%Y-%m-%d %H:%M} · 문제: {why} · 조치: {what}\n")
json.dump({"day": today, "retries": retries, "checked_utc": now.isoformat(timespec="seconds")},
          open("health/state.json", "w"), indent=2)
print(md)
