# 시스템 설명서 — Obsidian 자동 다이어리 (Trinity)

> 마지막 정리: 2026-09-25 (주간/월간 확정 기록 + 자동 생성 추가) · 이 노트는 Claude가 새 대화에서도 시스템 구조를 바로 파악하도록 만든 설명서입니다.

## 1. 한눈에 보기

```
[Finviz + CNN]  →  [GitHub Actions: 매일 UTC 21:15]  →  Market_Data.md (GitHub)
                                                              ↓ (노트가 만들어지는 순간 가져옴)
                         [Obsidian: Templater 템플릿]  →  Daily / Weekly / Monthly 노트에 숫자 기록
```

- 데이터는 **GitHub 클라우드**에서 만들어짐 → Mac이 꺼져 있어도 됨
- 노트를 **만드는 순간**(Mac/폰/iPad 어디서든) 그날 숫자가 노트에 **직접 적힘** → 나중에 안 바뀌고 기록으로 남음

## 2. 데이터 만드는 곳 — GitHub

- 저장소: `Johnsnoworme/market-data-feed` (Public)
- `cloud_market_data.py` : 데이터 수집 스크립트
  - Fear & Greed: CNN (`production.dataviz.cnn.io`)
  - Top 3: **Finviz 스크리너, 시가총액 $10B 이상(+Large, `f=cap_largeover`)** 화면을 그대로 읽음
    - Daily = Change % 순 / Weekly = Perf Week 순 / Monthly = Perf Month 순, 각 상위 3개
  - Finviz 접속이 막히면 백업: Nasdaq 전체 상장 $10B+ 종목을 yfinance로 계산 (이때 파일에 "데이터 출처: 백업" 표시, 경계선 종목 1~2개 다를 수 있음)
  - 실패하면 Actions가 빨간색(실패)으로 표시됨
- `.github/workflows/market_data.yml` : 자동 실행 설정
  - 매일 **UTC 21:15** = 시드니 **07:15 (AEST) / 08:15 (AEDT 서머타임)**
  - 수동 실행: GitHub → Actions → Update Market Data → Run workflow
- `Market_Data.md` : 결과 파일 (Fear & Greed, Daily/Weekly/Monthly Top 3) — **Daily 노트용** (Weekly/Monthly는 Finviz의 최근 5거래일/약 21거래일 기준)
- `archive/` : **주간/월간 확정 기록** (Weekly/Monthly 노트는 이것을 사용)
  - `archive/weekly/2026-W39.md` : 지난주 마지막 거래일 종가 → 그 주(월~금) 마지막 거래일 종가
  - `archive/monthly/2026-09.md` : 지난달 마지막 거래일 종가 → 그 달 마지막 거래일 종가
  - 대상: Nasdaq 상장 $10B+ 전 종목(막히면 Finviz +Large 목록), 종가는 yfinance(수정주가)로 직접 계산
  - 기간이 끝난 뒤(뉴욕 16:30 이후) 첫 실행 때 한 번만 만들고, **이미 있으면 절대 다시 쓰지 않음**
  - `archive/index.json` : 최신 확정 주/달 이름 (Obsidian 자동 생성기가 읽음)
  - 실패하면 로그에 "확정 기록 실패"만 남기고 다음 날 다시 시도 (Market_Data.md는 정상 저장)
  - 원본 주소: `https://raw.githubusercontent.com/Johnsnoworme/market-data-feed/main/Market_Data.md`
- `fix_obsidian.sh` : 2026-09-25 Obsidian 설정 복구용으로 한 번 쓴 스크립트 (백업: `~/Documents/obsidian_backup_날짜`)

## 3. 노트 만드는 곳 — Obsidian (보관소 Trinity)

- 위치: `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Trinity` (iCloud로 Mac/iPad/iPhone 동기화)
- 필수 플러그인: **Templater**(켜져 있어야 함!), Dataview, Periodic Notes, Calendar
  - Templater 설정: Template folder = `Templates`, **Trigger Templater on new file creation = 켜짐**
- 템플릿 (`Templates/`)
  - `Daily_Note_Template` : Fear & Greed + Daily Top 3 자동 입력 + Upcoming Events(2주)
  - `Weekly_Note_Template` : Weekly Top 3(archive 확정 기록) + 이벤트(4주). 노트 이름 형식 `GGGG-[W]WW` (ISO 주, 예: 2026-W39)
  - `Monthly_Note_Template` : Monthly Top 3(archive 확정 기록) + 이벤트(2개월). 노트 이름 `YYYY-MM`
  - 확정 기록이 아직 없으면 `> ⏳ 아직 확정 기록이 없어요` 표시 → 나중에 자동으로 채워짐
  - `_Startup_AutoCreate` : **자동 생성기** (Templater Startup template로 등록). Obsidian이 켜질 때 + 30분마다 index.json을 보고 최신 Weekly/Monthly 노트가 없으면 만들고, ⏳ 노트를 채움. 폰/iPad는 2분 기다렸다 실행(중복 방지)
  - 자동 입력 부분은 `<%* ... %>` 코드 블럭 — 요청 없이 건드리지 말 것
- 노트 저장 위치: `Stock note/Daily`, `Stock note/Weekly`, `Stock note/Monthly`
  - Daily 파일 이름 형식: `2026-09-25(Friday)`
- `Events Log` (보관소 맨 위, Templates 폴더 **밖**): 이벤트 장부
  - 형식: `- [date:: 2026-10-15] [event:: 로보택시 데이] [importance:: high]`
  - 여기에 한 줄 적으면 Daily/Weekly/Monthly의 Upcoming Events 표에 자동으로 나타남

## 4. 언제 노트를 만들면 좋은가

- 뉴욕 장 마감 = 시드니 06:00 (4~10월 초) / 07:00 (10월 서머타임 시작 후) / 08:00 (11~3월)
- GitHub 데이터 준비 = 시드니 07:15 또는 08:15
- **규칙: Daily 노트는 시드니 오전 8시 반 이후에 만들기** (노트 안 "📡 데이터 기준" 시간으로 확인 가능)
- **Weekly / Monthly는 사용자가 만들지 않음** → 자동 생성기가 만듦
  - Weekly: 금요일 뉴욕 장 마감 → 토요일 시드니 아침 GitHub 확정 → Obsidian이 열려 있거나 열 때 자동 생성
  - Monthly: 마지막 거래일 장 마감 → 다음 달 1일 시드니 아침 확정 → 자동 생성
  - 확정 기록이 기간별로 고정 저장되므로, 노트가 늦게 만들어져도 숫자는 항상 같음

## 5. 문제가 생기면 (자주 있었던 것)

| 증상 | 원인 | 해결 |
|---|---|---|
| 노트에 `<% tp... %>` 코드가 글자로 보임 | Templater가 꺼져 있음 / 자동 실행 설정 꺼짐 | 설정 → Community plugins → Templater 켜기, "Trigger Templater on new file creation" 켜기. 기존 노트는 Cmd+P → "Templater: Replace templates in the active file" |
| "⚠️ 데이터를 가져오지 못했습니다" | 인터넷 문제 또는 GitHub 파일 문제 | 인터넷 확인 후 노트 다시 만들기. GitHub Actions 실행 기록 확인 |
| Upcoming Events 표가 비어 있음 | Events Log 위치/이름이 바뀜, 또는 기간 안에 이벤트 없음 | Events Log는 보관소 맨 위, 이름 정확히 `Events Log` |
| Top 3가 Finviz와 1~2개 다름 | 백업 방식으로 수집됨 | Market_Data.md의 "데이터 출처" 확인 |

## 6. Claude와 일하는 법

- Obsidian 작업은 Claude 앱의 **프로젝트 "Obsidian 자동 다이어리 (Trinity)"** 안에서 요청 (Trinity 폴더가 연결되어 있음)
- Mac이 켜져 있고 Claude 앱이 열려 있어야 폴더 작업 가능
- 사용자 선호: 아주 쉽게, 단계별로, 한국어로, 복사-붙여넣기만 하면 되게

## 7. 📸 Daily 확정 스냅샷 (2026-10-02 추가)

- 문제였던 것: Daily 노트는 "만드는 순간의 최신 Market_Data.md"를 가져왔음 → 어제 노트를 오늘 만들면 오늘 숫자가 들어감. 또 GitHub 예약 실행이 매일 2.5~3.5시간 늦게 시작됨.
- 해결:
  - `archive/daily/YYYY-MM-DD.md` (시드니 날짜) : 그날 아침 Fear & Greed + Daily Top 3를 **한 번만** 저장, 다시 안 바뀜
  - 뉴욕 장중(평일 04:00~16:20 뉴욕)에는 저장하지 않음 → 항상 "장 마감 숫자"
  - `archive/daily/index.json` : {시드니 날짜: 뉴욕 거래일} (토·일·월 시드니 = 금요일 뉴욕)
  - Market Data 실행 3번: UTC 21:41 / 23:13 / 01:27 (처음 성공한 것이 확정, 나머지는 백업)
  - Top3 Pullback Follow는 Market Data가 끝나면 자동으로 이어서 실행 (workflow_run)
  - 과거 날짜(2026-09-25~)는 `daily_backfill.py`로 git 기록에서 복원
- Obsidian: Daily 템플릿은 **노트 날짜의 스냅샷**을 읽음. 아직 없으면 `> ⏳ 아직 이 날짜의 Daily 데이터가 확정 전이에요` → `_Startup_AutoCreate`가 30분마다 채움. 스냅샷이 있는데 Daily 노트가 없으면 자동 생성기가 노트를 만들어 줌 (2026-10-02 이후 날짜만).

## 8. 🤖 유튜브 백업 요약 (2026-10-02 추가)

- 문제: 유튜브 자막은 Mac 내장 브라우저로만 읽힘 (GitHub·클라우드는 자막 차단, RSS는 404) → Mac이 꺼져 있으면 요약이 빠짐
- `yt_backup.py` + `.github/workflows/yt_backup.yml` : UTC 15:20 / 21:50 / 03:20 (하루 3번)
  - 채널 "동영상" 탭 HTML의 ytInitialData로 소수몽키(@sosumonkey)·성상현(@SSH_MacroBeyond) 새 영상 찾기 (업로드 시각 = 상대 시간 추정)
  - `GEMINI_API_KEY` Secret이 있으면 Gemini에 유튜브 주소를 줘서 요약(source: gemini-backup), 없으면 링크만(source: gemini-stub)
  - 결과: `youtube/backup/<sosumonkey|ssh>/<video_id>.md`, `youtube/backup/index.json`, `youtube/backup/last_run.txt`
  - 🎖️ 장군님(이선엽)은 여러 채널 출연이라 대상 아님 (Mac 작업만)
- Obsidian `_Startup_AutoCreate`의 runYouTube(): 업로드 11시간 뒤부터 볼트로 가져옴 (Claude 요약이 이미 있으면 건너뜀) → `📺 소수몽키/`, `🎙️ 전문가 렌즈/🤖 백업 요약/` + Daily 칸에 넣음
- Claude 예약 작업: 공통 규칙 5️⃣ — 백업 노트는 "미처리"로 보고 Mac이 켜지면 같은 파일을 자세한 Claude 요약으로 덮어씀
- Weekly/Monthly: 자동 생성기가 이제 index.json의 **빠진 주·달 전부**를 만듦 (예전: 최신 1개만)

## 🗽 Yahoo 종가 지연 규칙 (2026-10-05)
- 실측: Yahoo(yfinance) 일봉은 뉴욕 마감 후 약 5~6시간(뉴욕 밤 21:15~21:45)이 지나야 그날 줄이 생긴다.
- 그래서 yfinance를 쓰는 작업(🎯 한 방 레이더 · 🔔 Top 3 추적 · 🧭 김종봉 주간 · 소형 병목 레이더)은
  `ny_session.require_fresh()`로 "마지막으로 끝난 뉴욕 거래일(휴장일 반영)" 종가가 있는지 확인하고, 없으면 저장하지 않고 다음 실행에 다시 시도한다.
- 예약: 화~토 UTC 02:40 / 04:10 (+ 한 방 06:40) · 김종봉은 금 22:03/22:33 + 토 02:40/04:10/13:00 안전망.
- 🩺 건강검진이 김종봉 주간 파일, 한 방·Top 3 최신 거래일 파일을 직접 확인하고 없으면 다시 실행한다.
- Finviz에서 가져오는 Daily Top 3 · Fear & Greed(cloud_market_data.py)는 이 지연과 상관없다.
- NYSE 휴장일 목록은 ny_session.py에 있다 → 매년 초 다음 해를 추가할 것.

## 🛡️ 가짜 상승·링크 안전장치 (2026-10-07, MMEDV 사고 후)
- 사고: 10/5 Daily Top 3 1위 MMEDV +161.78% = Medtronic 분사 MiniMed의 When Issued(상장 전 임시 거래). 진짜 상승 아님.
- 1겹 이름 필터: When Issued·Rights·Warrant·Units → Finviz Top 3, 주간·월간 기록, 대형주 목록(Nasdaq), 소형주 레이더, 소셜 레이더에서 모두 제외.
- 2겹 상식 검사: 대형주가 일 40%·주 60%·월 100% 넘게 움직이면 yfinance 거래 이력 확인 → 20일 미만이면 제외, 충분하면 남기고 표 아래 "⚠️ 뉴스 확인 권장". 제외한 종목은 "🚫 자동 제외" 줄로 표시(숨기지 않음).
- 3겹 건강검진(health_check 8번): HTML 링크·임시 거래 종목·수집 실패·비정상 숫자 → ❌/⚠️, Market_Data 문제면 자동 재실행.
- 링크는 전부 마크다운 [T](url). HTML <a href> 금지 (옵시디언 표 안·아이폰·아이패드에서 안 눌림).
