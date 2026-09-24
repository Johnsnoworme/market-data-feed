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

# 2. Finviz 스크리너 파싱 (실시간 1, 2, 3위 추출)
def get_finviz_top3(screener_url):
    results = []
    try:
        response = scraper.get(screener_url)
        if response.status_code != 200:
            return results

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Finviz 테이블 행 찾기
        rows = soup.find_all('tr', class_=['styled-row', 'is-hovered']) 
        if not rows:
            rows = [tr for tr in soup.find_all('tr') if tr.find('a', class_='tablink')]

        for row in rows[:3]:
            cols = row.find_all('td')
            if len(cols) < 10:
                continue
            
            ticker = cols[1].text.strip()
            company = cols[2].text.strip()
            sector = cols[3].text.strip()
            change = cols[-2].text.strip() if '%' in cols[-2].text else cols[-1].text.strip()

            results.append({
                'ticker': ticker,
                'company': company,
                'sector': sector,
                'change': change
            })
    except Exception as e:
        print(f"Parsing Error: {e}")
        
    return results

fg_result = get_fear_and_greed()

url_daily = "https://finviz.com/screener.ashx?v=111&f=cap_largeover10&o=-change"
url_weekly = "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf1w"
url_monthly = "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf4w"

daily_top3 = get_finviz_top3(url_daily)
weekly_top3 = get_finviz_top3(url_weekly)
monthly_top3 = get_finviz_top3(url_monthly)

def render_table(title, items, screener_url):
    md = f"## {title}\n"
    md += "| 티커 | 회사 이름 | 섹터 | 변동률 |\n"
    md += "| :--- | :--- | :--- | :--- |\n"
    if not items:
        md += "| - | 데이터 수집 실패 | - | - |\n"
    else:
        for item in items:
            finviz_quote_url = f'https://finviz.com/quote.ashx?t={item["ticker"]}'
            ticker_link = f'<a href="{finviz_quote_url}" target="_blank">{item["ticker"]}</a>'
            company_link = f'<a href="{finviz_quote_url}" target="_blank">{item["company"]}</a>'
            md += f'| {ticker_link} | {company_link} | {item["sector"]} | {item["change"]} |\n'
    
    md += f'\n👉 <a href="{screener_url}" target="_blank">Finviz {title} Large-Cap Screener 전체보기</a>\n\n'
    return md

md_content = f"# Market Data\n\n## Fear & Greed Index\n{fg_result}\n\n"
md_content += render_table("Daily Top 3", daily_top3, url_daily)
md_content += render_table("Weekly Top 3", weekly_top3, url_weekly)
md_content += render_table("Monthly Top 3", monthly_top3, url_monthly)

with open("Market_Data.md", "w", encoding="utf-8") as f:
    f.write(md_content.strip())

print("Market_Data.md 업데이트 성공!")
