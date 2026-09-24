import os
import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://finviz.com/',
    'Connection': 'keep-alive'
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

# 2. Finviz 100% 단일 수집 ($10B+ Large-Cap 전수 탐색)
def get_finviz_top3(view_type, order_param, change_col_idx):
    # f=cap_largeover10 ($10B 이상 단일 필터만 사용)
    url = f"https://finviz.com/screener.ashx?v={view_type}&f=cap_largeover10&o={order_param}"
    results = []
    
    session = requests.Session()
    try:
        session.get("https://finviz.com/", headers=HEADERS, timeout=5)
        res = session.get(url, headers=HEADERS, timeout=10)
        
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.find_all('tr')
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) > change_col_idx:
                    link = cols[1].find('a')
                    if link and 'href' in link.attrs and 'quote.ashx?t=' in link['href']:
                        ticker = link.text.strip().upper()
                        if len(ticker) < 1 or len(ticker) > 5:
                            continue
                            
                        change = cols[change_col_idx].text.strip()
                        company = cols[2].text.strip() if len(cols) > 2 else ticker
                        sector = cols[3].text.strip() if len(cols) > 3 else "N/A"

                        results.append({
                            'ticker': ticker,
                            'company': company,
                            'sector': sector,
                            'change': change
                        })
                        
                        if len(results) == 3:
                            break
    except Exception as e:
        print(f"Finviz 수집 중 에러 발생: {e}")
        
    return results

# 데이터 수집 실행
fg_result = get_fear_and_greed()
daily_top3 = get_finviz_top3(111, "-change", 9)
weekly_top3 = get_finviz_top3(141, "-perf1w", 2)
monthly_top3 = get_finviz_top3(141, "-perf4w", 3)

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
            
            # 티커와 회사 이름 모두 각각 클릭 가능한 링크로 바인딩
            ticker_link = f'<a href="{finviz_quote_url}" target="_blank">{item["ticker"]}</a>'
            company_link = f'<a href="{finviz_quote_url}" target="_blank">{item["company"]}</a>'
            
            md += f'| {ticker_link} | {company_link} | {item["sector"]} | {item["change"]} |\n'
    
    # 하단 전체보기 버튼 클릭 시 Finviz 스크리너로 이동 (새 탭)
    md += f'\n👉 <a href="{screener_url}" target="_blank">Finviz {title} Large-Cap Screener 전체보기</a>\n\n'
    return md

# 마크다운 최종 작성
md_content = f"# Market Data\n\n## Fear & Greed Index\n{fg_result}\n\n"
md_content += render_table("Daily Top 3", daily_top3, "https://finviz.com/screener.ashx?v=111&f=cap_largeover10&o=-change")
md_content += render_table("Weekly Top 3", weekly_top3, "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf1w")
md_content += render_table("Monthly Top 3", monthly_top3, "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf4w")

with open("Market_Data.md", "w", encoding="utf-8") as f:
    f.write(md_content.strip())

print("Market_Data.md 업데이트 완료!")
