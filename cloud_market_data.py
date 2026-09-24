import os
import re
import requests
from bs4 import BeautifulSoup

# 실제 브라우저와 동일한 최신 헤더 설정
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Sec-Ch-Ua': '"Not-A.Brand";v="99", "Chromium";v="124", "Google Chrome";v="124"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1'
}

# 1. CNN Fear & Greed Index 수집
def get_fear_and_greed():
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json()
        score = round(data['fear_and_greed']['score'], 1)
        rating = data['fear_and_greed']['rating'].title()
        return f"{score} / 100 ({rating})"
    except Exception:
        return "데이터 가져오기 실패"

# 2. Finviz 전용 수집 ($10B+ Large-Cap 전수 탐색)
def get_finviz_top3(view_type, order_param):
    # 단 하나의 필터: Market Cap Over $10 Bln (cap_largeover10)
    url = f"https://finviz.com/screener.ashx?v={view_type}&f=cap_largeover10&o={order_param}"
    results = []
    
    session = requests.Session()
    try:
        # 쿠키 생성을 위한 메인 접속
        session.get("https://finviz.com/", headers=HEADERS, timeout=5)
        res = session.get(url, headers=HEADERS, timeout=10)
        
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.find_all('tr')
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 5:
                    continue
                    
                # quote.ashx?t= 패턴 검색으로 티커 탐색
                ticker_a = row.find('a', href=re.compile(r'quote\.ashx\?t='))
                if not ticker_a:
                    continue
                    
                ticker = ticker_a.text.strip().upper()
                if not ticker or len(ticker) > 5 or not ticker.isalpha():
                    continue

                # Overview (v=111) vs Performance (v=141) 열 분기
                if view_type == 111:
                    company = cols[2].text.strip() if len(cols) > 2 else ticker
                    sector = cols[3].text.strip() if len(cols) > 3 else "N/A"
                    change = cols[-2].text.strip() if len(cols) >= 10 else cols[-1].text.strip()
                else:  # Performance (v=141)
                    company = cols[2].text.strip() if len(cols) > 2 else ticker
                    sector = cols[3].text.strip() if len(cols) > 3 else "N/A"
                    # Performance 뷰에서 변동률 컬럼 추출 (Weekly는 보통 5~6번째 열)
                    change = cols[5].text.strip() if len(cols) > 5 else "N/A"

                results.append({
                    'ticker': ticker,
                    'company': company,
                    'sector': sector,
                    'change': change
                })
                
                if len(results) == 3:
                    break
    except Exception as e:
        print(f"Finviz 수집 중 에러: {e}")
        
    return results

# 데이터 수집 실행
fg_result = get_fear_and_greed()
daily_top3 = get_finviz_top3(111, "-change")
weekly_top3 = get_finviz_top3(141, "-perf1w")
monthly_top3 = get_finviz_top3(141, "-perf4w")

# 마크다운 표 생성 (티커 OR 회사 이름 클릭 시 Finviz 연결 + 새 탭 적용)
def render_table(title, items, screener_url):
    md = f"## {title}\n"
    md += "| 티커 | 회사 이름 | 섹터 | 변동률 |\n"
    md += "| :--- | :--- | :--- | :--- |\n"
    if not items:
        md += "| - | 데이터 수집 실패 | - | - |\n"
    else:
        for item in items:
            finviz_quote_url = f'https://finviz.com/quote.ashx?t={item["ticker"]}'
            
            # 티커와 회사 이름 클릭 시 새 탭으로 연결
            ticker_link = f'<a href="{finviz_quote_url}" target="_blank">{item["ticker"]}</a>'
            company_link = f'<a href="{finviz_quote_url}" target="_blank">{item["company"]}</a>'
            
            md += f'| {ticker_link} | {company_link} | {item["sector"]} | {item["change"]} |\n'
    
    # 하단 전체보기 링크 클릭 시 Finviz 스크리너 연결 (새 탭)
    md += f'\n👉 <a href="{screener_url}" target="_blank">Finviz {title} Large-Cap Screener 전체보기</a>\n\n'
    return md

# 마크다운 내용 작성
md_content = f"# Market Data\n\n## Fear & Greed Index\n{fg_result}\n\n"
md_content += render_table("Daily Top 3", daily_top3, "https://finviz.com/screener.ashx?v=111&f=cap_largeover10&o=-change")
md_content += render_table("Weekly Top 3", weekly_top3, "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf1w")
md_content += render_table("Monthly Top 3", monthly_top3, "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf4w")

with open("Market_Data.md", "w", encoding="utf-8") as f:
    f.write(md_content.strip())

print("Market_Data.md 업데이트 완료!")
