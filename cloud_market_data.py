import os
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# 1. Fear & Greed Index
def get_fear_and_greed():
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        res = requests.get(url, headers=HEADERS, timeout=10)
        data = res.json()
        score = round(data['fear_and_greed']['score'], 1)
        rating = data['fear_and_greed']['rating'].title()
        return f"{score} / 100 ({rating})"
    except Exception as e:
        return "데이터 가져오기 실패"

# 2. Finviz 크롤러 (시총 $10B 이상 + 정확한 티커 파싱)
def get_finviz_top3(view_type, order_param, col_idx):
    # cap_largeover10: 시총 10B 달러 이상 필터
    url = f"https://finviz.com/screener.ashx?v={view_type}&f=cap_largeover10&o={order_param}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        rows = soup.select('tr.styled-row')
        top3 = []
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) > col_idx:
                # 티커 링크(a 태그)에서 정확한 티커명 추출 (앞글자 중복 방지)
                ticker_element = cols[1].find('a')
                if ticker_element:
                    ticker = ticker_element.text.strip()
                else:
                    ticker = cols[1].text.strip()
                
                change = cols[col_idx].text.strip()
                
                # 플러스(+) 상승률을 가진 종목만 필터링
                if change.startswith('+') or (not change.startswith('-') and change != '-'):
                    top3.append((ticker, change))
                
                if len(top3) == 3:
                    break
        return top3
    except Exception as e:
        return []

fg_result = get_fear_and_greed()

# Overview(v=111) 기준 Daily Top 3 (Change 컬럼 = 9)
daily_top3 = get_finviz_top3(111, "-change", 9)

# Performance(v=141) 기준 Weekly Top 3 (Perf Week 컬럼 = 2), Monthly Top 3 (Perf Month 컬럼 = 3)
weekly_top3 = get_finviz_top3(141, "-perf1w", 2)
monthly_top3 = get_finviz_top3(141, "-perf4w", 3)

# HTML 태그를 조합하여 새 탭(target="_blank") 생성 마크다운 작성
md_content = f"""# Market Data

## Fear & Greed Index
{fg_result}

## Daily Top 3
| 티커 | 변동률 |
| :--- | :--- |
"""
for ticker, change in daily_top3:
    md_content += f'| <a href="https://finviz.com/quote.ashx?t={ticker}" target="_blank">{ticker}</a> | {change} |\n'

md_content += """
👉 <a href="https://finviz.com/screener.ashx?v=111&f=cap_largeover10&o=-change" target="_blank">Finviz Daily Large-Cap Screener 전체보기</a>

## Weekly Top 3
| 티커 | 주간 변동률 |
| :--- | :--- |
"""
for ticker, change in weekly_top3:
    md_content += f'| <a href="https://finviz.com/quote.ashx?t={ticker}" target="_blank">{ticker}</a> | {change} |\n'

md_content += """
👉 <a href="https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf1w" target="_blank">Finviz Weekly Large-Cap Screener 전체보기</a>

## Monthly Top 3
| 티커 | 월간 변동률 |
| :--- | :--- |
"""
for ticker, change in monthly_top3:
    md_content += f'| <a href="https://finviz.com/quote.ashx?t={ticker}" target="_blank">{ticker}</a> | {change} |\n'

md_content += """
👉 <a href="https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf4w" target="_blank">Finviz Monthly Large-Cap Screener 전체보기</a>
"""

with open("Market_Data.md", "w", encoding="utf-8") as f:
    f.write(md_content.strip())

print("Market_Data.md 업데이트 완료!")
