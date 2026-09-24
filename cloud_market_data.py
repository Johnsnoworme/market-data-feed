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

# 2. Finviz 크롤링 (Large Cap $10B+ & Overview View v=111)
def get_finviz_top3(order_param, change_col_idx):
    # v=111: Overview 뷰, f=cap_largeover10: 시총 $10B 이상
    url = f"https://finviz.com/screener.ashx?v=111&f=cap_largeover10&o={order_param}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        rows = soup.select('tr.styled-row')
        top3 = []
        
        for row in rows[:3]:
            cols = row.find_all('td')
            if len(cols) > change_col_idx:
                ticker = cols[1].text.strip()
                change = cols[change_col_idx].text.strip()
                top3.append((ticker, change))
        return top3
    except Exception as e:
        return []

# 데이터 수집
fg_result = get_fear_and_greed()

# Overview(v=111) 기준:
# Daily: o=-change (Change 컬럼은 9번 인덱스)
# Weekly: Performance(v=141) 기준 o=-perf1w (Perf Week 컬럼은 2번 인덱스)
# Monthly: Performance(v=141) 기준 o=-perf4w (Perf Month 컬럼은 3번 인덱스)
daily_top3 = get_finviz_top3("-change", 9)

# Performance 뷰(v=141) 크롤러 별도 함수 (주간/월간 전용)
def get_finviz_perf_top3(order_param, col_idx):
    url = f"https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o={order_param}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select('tr.styled-row')
        top3 = []
        for row in rows[:3]:
            cols = row.find_all('td')
            if len(cols) > col_idx:
                ticker = cols[1].text.strip()
                change = cols[col_idx].text.strip()
                top3.append((ticker, change))
        return top3
    except Exception as e:
        return []

weekly_top3 = get_finviz_perf_top3("-perf1w", 2)
monthly_top3 = get_finviz_perf_top3("-perf4w", 3)

# Markdown 작성
md_content = f"""# Market Data

## Fear & Greed Index
{fg_result}

## Daily Top 3
| 티커 | 변동률 |
| :--- | :--- |
"""
for ticker, change in daily_top3:
    md_content += f"| [{ticker}](https://finviz.com/quote.ashx?t={ticker}) | {change} |\n"

md_content += """
👉 [Finviz Daily Large-Cap Screener 전체보기](https://finviz.com/screener.ashx?v=111&f=cap_largeover10&o=-change)

## Weekly Top 3
| 티커 | 주간 변동률 |
| :--- | :--- |
"""
for ticker, change in weekly_top3:
    md_content += f"| [{ticker}](https://finviz.com/quote.ashx?t={ticker}) | {change} |\n"

md_content += """
👉 [Finviz Weekly Large-Cap Screener 전체보기](https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf1w)

## Monthly Top 3
| 티커 | 월간 변동률 |
| :--- | :--- |
"""
for ticker, change in monthly_top3:
    md_content += f"| [{ticker}](https://finviz.com/quote.ashx?t={ticker}) | {change} |\n"

md_content += """
👉 [Finviz Monthly Large-Cap Screener 전체보기](https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf4w)
"""

with open("Market_Data.md", "w", encoding="utf-8") as f:
    f.write(md_content.strip())

print("Market_Data.md 업데이트 완료!")
