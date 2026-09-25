# 시스템 설명서 — Obsidian 자동 다이어리 (Trinity)

> 마지막 정리: 2026-09-25 · 이 노트는 Claude가 새 대화에서도 시스템 구조를 바로 파악하도록 만든 설명서입니다.

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
- `Market_Data.md` : 결과 파일 (Fear & Greed, Daily/Weekly/Monthly Top 3)
  - 원본 주소: `https://raw.githubusercontent.com/Johnsnoworme/market-data-feed/main/Market_Data.md`
- `fix_obsidian.sh` : 2026-09-25 Obsidian 설정 복구용으로 한 번 쓴 스크립트 (백업: `~/Documents/obsidian_backup_날짜`)

## 3. 노트 만드는 곳 — Obsidian (보관소 Trinity)

- 위치: `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Trinity` (iCloud로 Mac/iPad/iPhone 동기화)
- 필수 플러그인: **Templater**(켜져 있어야 함!), Dataview, Periodic Notes, Calendar
  - Templater 설정: Template folder = `Templates`, **Trigger Templater on new file creation = 켜짐**
- 템플릿 (`Templates/`)
  - `Daily_Note_Template` : Fear & Greed + Daily Top 3 자동 입력 + Upcoming Events(2주)
  - `Weekly_Note_Template` : Weekly Top 3 자동 입력 + 이벤트(4주)
  - `Monthly_Note_Template` : Monthly Top 3 자동 입력 + 이벤트(2개월)
  - 자동 입력 부분은 `<%* ... %>` 코드 블럭 — 요청 없이 건드리지 말 것
- 노트 저장 위치: `Stock note/Daily`, `Stock note/Weekly`, `Stock note/Monthly`
  - Daily 파일 이름 형식: `2026-09-25(Friday)`
- `Events Log` (보관소 맨 위, Templates 폴더 **밖**): 이벤트 장부
  - 형식: `- [date:: 2026-10-15] [event:: 로보택시 데이] [importance:: high]`
  - 여기에 한 줄 적으면 Daily/Weekly/Monthly의 Upcoming Events 표에 자동으로 나타남

## 4. 언제 노트를 만들면 좋은가

- 뉴욕 장 마감 = 시드니 06:00 (4~10월 초) / 07:00 (10월 서머타임 시작 후) / 08:00 (11~3월)
- GitHub 데이터 준비 = 시드니 07:15 또는 08:15
- **규칙: Daily·Weekly 노트는 시드니 오전 8시 반 이후에 만들기** (노트 안 "📡 데이터 기준" 시간으로 확인 가능)
- Weekly = 토요일 오전, Monthly = 매달 1일 오전에 사용자가 직접 생성 (폰 자동 생성은 쓰지 않기로 함)

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
