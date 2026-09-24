import os
import requests
import cloudscraper
from bs4 import BeautifulSoup

# Cloudscraper 인스턴스 생성 (Finviz 차단 우회)
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

# 1. CNN Fear & Greed Index 수집
def get_fear_and_greed():
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        score = round(data['fear_and_greed']['score'], 1)
        rating = data['fear_and_greed']['rating'].title()
        return f"{score} / 100 ({rating})"
    except Exception:
        return "데이터 가져오기 실패"

# 2. Finviz 스크리너 파싱 (열 꼬임 문제 완벽 해결 + 순수 티커만 추출)
def get_finviz_top3(screener_url):
    results = []
    try:
        response = scraper.get(screener_url)
        if response.status_code != 200:
            return results

        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 8:
                continue
            
            # 티커 링크 tag (quote.ashx?t=) 직접 조회하여 중복 문자열 제거
            ticker_a = row.find('a', href=lambda h: h and 'quote.ashx?t=' in h)
            if not ticker_a:
                continue
            
            # Pure Ticker 추출
            raw_href = ticker_a['href']
            ticker = raw_href.split('t=')[-1].split('&')[0].upper().strip()
            
            if not ticker or len(ticker) > 5 or not ticker.isalpha():
                continue

            # 클래스가 tablink인 a 태그들만 필터링 (회사명, 섹터 추출)
            tablinks = [a.text.strip() for a in row.find_all('a', class_='tablink')]
            
            if len(tablinks) >= 3:
                # tablinks 구조: [0]: Ticker, [1]: Company, [2]: Sector
                company = tablinks[1]
                sector = tablinks[2]
            else:
                company = cols[2].text.strip()
                sector = cols[3].text.strip()

            # 변동률 컬럼: %가 포함되고 숫자/부호가 포함된 최우측 값 자동 매핑
            change = "N/A"
            for col in reversed(cols):
                text = col.text.strip()
                if '%' in text and any(char.isdigit() for char in text):
                    change = text
                    break

            # 티커 중복 수집 방지
            if any(r['ticker'] == ticker for r in results):
                continue

            results.append({
                'ticker': ticker,
                'company': company,
                'sector': sector,
                'change': change
            })

            if len(results) == 3:
                break

    except Exception as e:
        print(f"Parsing Error: {e}")
        
    return results

fg_result = get_fear_and_greed()

# $10B 이상 Large Cap 스크리너 URL
url_daily = "https://finviz.com/screener.ashx?v=111&f=cap_largeover10&o=-change"
url_weekly = "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf1w"
url_monthly = "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf4w"

daily_top3 = get_finviz_top3(url_daily)
weekly_top3 = get_finviz_top3(url_weekly)
monthly_top3 = get_finviz_top3(url_monthly)

# 마크다운 표 생성 (회사명 링크 전면 삭제, 오직 티커만 링크 적용)
def render_table(title, items, screener_url):
    md = f"## {title}\n"
    md += "| 티커 | 회사 이름 | 섹터 | 변동률 |\n"
    md += "| :--- | :--- | :--- | :--- |\n"
    if not items:
        md += "| - | 데이터 수집 실패 | - | - |\n"
    else:
        for item in items:
            finviz_quote_url = f'https://finviz.com/quote.ashx?t={item["ticker"]}'
            
            # 티커에만 링크 적용
            ticker_link = f'<a href="{finviz_quote_url}" target="_blank">{item["ticker"]}</a>'
            # 회사명은 링크 없는 일반 텍스트
            company_name = item["company"]
            
            md += f'| {ticker_link} | {company_name} | {item["sector"]} | {item["change"]} |\n'
    
    md += f'\n👉 <a href="{screener_url}" target="_blank">Finviz {title} Large-Cap Screener 전체보기</a>\n\n'
    return md

# 마크다운 최종 작성
md_content = f"# Market Data\n\n## Fear & Greed Index\n{fg_result}\n\n"
md_content += render_table("Daily Top 3", daily_top3, url_daily)
md_content += render_table("Weekly Top 3", weekly_top3, url_weekly)
md_content += render_table("Monthly Top 3", monthly_top3, url_monthly)

with open("Market_Data.md", "w", encoding="utf-8") as f:
    f.write(md_content.strip())

print("Market_Data.md 정상 생성 완료!")
