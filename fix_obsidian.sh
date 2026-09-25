python3 - <<'PYEOF'
import json, os, shutil, datetime
V = os.path.expanduser("~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Trinity")
BK = os.path.expanduser("~/Documents/obsidian_backup_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
DAILY = r'''---
date: <% tp.file.title.substring(0, 10) %>
tags:
  - daily
---
# ☀️ Daily Note: <% tp.file.title.substring(0, 10) %>

<details>
<summary><b>🔮 [정기신] 육체, 기운, 정신의 조화</b> (클릭하여 열기/접기)</summary>

> 🌌 *우주의 리듬과 합일되는 최상의 바이오리듬 및 System 2 상태 유지*

### 🛌 수면 기록 (Sleep Tracker)
- **취침:** 00:00 | **기상:** 00:00 | **수면 시간:** 0시간 0분

### 🌿 정기신 체크리스트 (Jeong-Gi-Sin Routine)
- [ ] **精 (육체):** 수면 / 무과식 / 청결
- [ ] **氣 (기운):** 단전호흡 / 신체 운동
- [ ] **神 (정신):** 독서 / 서평 / System 1 통제
</details>

---

<%*
// 노트가 만들어지는 순간 GitHub에서 최신 Market_Data.md를 가져와서
// "그날의 숫자"를 노트 안에 직접 적어 넣습니다 (나중에 바뀌지 않고 그대로 기록으로 남음).
const RAW = "https://raw.githubusercontent.com/Johnsnoworme/market-data-feed/main/Market_Data.md";
let md = "";
try { md = await (await fetch(RAW + "?t=" + Date.now())).text(); } catch (e) { md = ""; }
function section(title) {
  const esc = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = md.match(new RegExp("## " + esc + "\\n([\\s\\S]*?)(?=\\n## |$)"));
  return m ? m[1].trim() : "⚠️ 데이터를 가져오지 못했습니다 (인터넷 연결 확인 후 노트를 다시 만들어 주세요)";
}
const updated = (md.match(/> 마지막 업데이트: (.*)/) || [, "알 수 없음"])[1];
tR += "## 😨😄 Fear & Greed Index\n";
tR += "> 📡 데이터 기준: " + updated + "\n\n";
tR += "**" + section("Fear & Greed Index") + "**\n\n";
tR += "## 🚀 Daily Top 3 (Large-Cap $10B+)\n";
tR += section("Daily Top 3") + "\n";
%>

---

<details open>
<summary><b>🚨 Upcoming Events (앞으로 2주)</b> (클릭하여 열기/접기)</summary>

> 🌏 *시드니 시차 반영: 미국 시장 대비 약 하루 빠름*

```dataview
TABLE WITHOUT ID L.event AS "이벤트", L.date AS "날짜", L.importance AS "중요도"
FROM "Events Log"
FLATTEN file.lists AS L
WHERE L.date AND L.date >= date(today) AND L.date <= date(today) + dur(14 days)
SORT L.date ASC
```
</details>
'''
WEEKLY = r'''<%*
const RAW = "https://raw.githubusercontent.com/Johnsnoworme/market-data-feed/main/Market_Data.md";
let md = "";
try { md = await (await fetch(RAW + "?t=" + Date.now())).text(); } catch (e) { md = ""; }
function section(title) {
  const esc = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = md.match(new RegExp("## " + esc + "\\n([\\s\\S]*?)(?=\\n## |$)"));
  return m ? m[1].trim() : "⚠️ 데이터를 가져오지 못했습니다 (인터넷 연결 확인 후 노트를 다시 만들어 주세요)";
}
const updated = (md.match(/> 마지막 업데이트: (.*)/) || [, "알 수 없음"])[1];
tR += "## 🚀 Weekly Top 3 (Large-Cap $10B+)\n";
tR += "> 📡 데이터 기준: " + updated + "\n\n";
tR += section("Weekly Top 3") + "\n";
%>'''
MONTHLY = r'''<%*
const RAW = "https://raw.githubusercontent.com/Johnsnoworme/market-data-feed/main/Market_Data.md";
let md = "";
try { md = await (await fetch(RAW + "?t=" + Date.now())).text(); } catch (e) { md = ""; }
function section(title) {
  const esc = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = md.match(new RegExp("## " + esc + "\\n([\\s\\S]*?)(?=\\n## |$)"));
  return m ? m[1].trim() : "⚠️ 데이터를 가져오지 못했습니다 (인터넷 연결 확인 후 노트를 다시 만들어 주세요)";
}
const updated = (md.match(/> 마지막 업데이트: (.*)/) || [, "알 수 없음"])[1];
tR += "## 🚀 Monthly Top 3 (Large-Cap $10B+)\n";
tR += "> 📡 데이터 기준: " + updated + "\n\n";
tR += section("Monthly Top 3") + "\n";
%>'''
def backup(p):
    os.makedirs(BK, exist_ok=True)
    shutil.copy2(p, os.path.join(BK, os.path.basename(p)))
print("=" * 50)
if not os.path.isdir(V):
    print("❌ Trinity 보관소를 찾을 수 없어요:", V); raise SystemExit
p = os.path.join(V, ".obsidian/plugins/templater-obsidian/data.json")
if os.path.exists(p):
    backup(p)
    d = json.load(open(p, encoding="utf-8"))
    d["trigger_on_file_creation"] = True
    json.dump(d, open(p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("✅ 1. Templater 자동 실행 설정 켬")
else:
    print("❌ 1. Templater 설정 파일이 없어요 (Templater 플러그인 확인 필요)")
src = os.path.join(V, "Templates/1.Events Log.md"); dst = os.path.join(V, "Events Log.md")
if os.path.exists(dst):
    print("✅ 2. Events Log 이미 제자리에 있음")
elif os.path.exists(src):
    shutil.move(src, dst); print("✅ 2. '1.Events Log' → 'Events Log' 로 옮김")
else:
    print("⚠️ 2. Events Log 파일을 못 찾았어요")
t = os.path.join(V, "Templates/Daily_Note_Template.md")
if os.path.exists(t): backup(t)
open(t, "w", encoding="utf-8").write(DAILY); print("✅ 3. Daily 템플릿 저장")
for name, block, key in [("Weekly_Note_Template.md", WEEKLY, "Weekly Top 3 (Large-Cap"), ("Monthly_Note_Template.md", MONTHLY, "Monthly Top 3 (Large-Cap")]:
    t = os.path.join(V, "Templates", name)
    if not os.path.exists(t):
        print("⚠️ 3.", name, "없음"); continue
    s = open(t, encoding="utf-8").read()
    if key in s:
        print("✅ 3.", name, "이미 들어가 있음"); continue
    backup(t)
    open(t, "w", encoding="utf-8").write(s.rstrip() + "\n\n---\n\n" + block + "\n")
    print("✅ 3.", name, "에 Top 3 블럭 추가")
dd = os.path.join(V, "Stock note/Daily"); today = datetime.date.today().isoformat()
if os.path.isdir(dd):
    for f in os.listdir(dd):
        fp = os.path.join(dd, f)
        # 템플릿 코드가 실행 안 된 채로 남은 노트만 정리 (정상 노트는 절대 안 건드림)
        if f.endswith(".md") and "<% tp." in open(fp, encoding="utf-8").read():
            backup(fp)
            os.remove(fp)
            print("✅ 4. 잘못 만들어진 오늘 노트(" + f + ") 정리 (백업 폴더에 보관됨)")
print("💾 백업 위치:", BK)
print("=" * 50)
PYEOF
