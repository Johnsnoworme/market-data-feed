import os
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# 1. Fear & Greed Index 크롤링
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

# 2. Finviz 크롤링 (Large Cap $10B+ 필터 적용: f=cap_largeover10)
def get_finviz_top3(order_param):
    # f=cap_largeover10 옵션이 시가총액 $10B 이상(Large-Cap) 조건입니다.
    url = f"https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o={order_param}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        rows = soup.select('tr.styled-row')
        top3 = []
        
        for row in rows[:3]:
            cols = row.find_all('td')
            if len(cols) >= 10:
                ticker = cols[1].text.strip()
                # 기간별 변동률 컬럼 위치 (Daily=9번, Weekly=9번, Monthly=9번 퍼포먼스 뷰 기준)
                change = cols[9].text.strip()
                top3.append((ticker, change))
        return top3
    except Exception as e:
        return []

# 데이터 수집
fg_result = get_fear_and_greed()

# Finviz Order 파라미터 (시총 10B+ 필터 적용된 순위)
# -change: Daily Top Gainers
# -perf1w: Weekly Top Gainers
# -perf4w: Monthly Top Gainers
daily_top3 = get_finviz_top3("-change")
weekly_top3 = get_finviz_top3("-perf1w")
monthly_top3 = get_finviz_top3("-perf4w")

# Markdown 파일 작성
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
👉 [Finviz Daily Large-Cap Screener 전체보기](https://finviz.com/screener.ashx?v=141&f=cap_largeover10&ft=4&o=-change)

## Weekly Top 3
| 티커 | 주간 변동률 |
| :--- | :--- |
"""
for ticker, change in weekly_top3:
    md_content += f"| [{ticker}](https://finviz.com/quote.ashx?t={ticker}) | {change} |\n"

md_content += """
👉 [Finviz Weekly Large-Cap Screener 전체보기](https://finviz.com/screener.ashx?v=141&f=cap_largeover10&ft=4&o=-perf1w)

## Monthly Top 3
| 티커 | 월간 변동률 |
| :--- | :--- |
"""
for ticker, change in monthly_top3:
    md_content += f"| [{ticker}](https://finviz.com/quote.ashx?t={ticker}) | {change} |\n"

md_content += """
👉 [Finviz Monthly Large-Cap Screener 전체보기](https://finviz.com/screener.ashx?v=141&f=cap_largeover10&ft=4&o=-perf4w)
"""

# 저장
with open("Market_Data.md", "w", encoding="utf-8") as f:
    f.write(md_content.strip())

print("Market_Data.md 생성 완료!")
