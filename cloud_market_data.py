import os
import requests
import yfinance as yf

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
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

# 2. $10B 이상 대형주 데이터 안정적 수집 (차단 방지 로직)
def get_top3_stocks(sort_type='daily'):
    # 주요 $10B+ 라지캡 종목 풀 (차단 없이 빠르게 계산)
    candidate_tickers = [
        'NVDA', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'AMD', 'AVGO', 
        'NFLX', 'PLTR', 'SMCI', 'LLY', 'BRK-B', 'JPM', 'UNH', 'V', 'PG', 'COST', 
        'HD', 'BAC', 'XOM', 'CVX', 'MA', 'ABBV', 'MRK', 'ORCL', 'CRM', 'ACN'
    ]
    
    results = []
    
    for t in candidate_tickers:
        try:
            tk = yf.Ticker(t)
            # 1개월치 일봉 데이터 수집
            hist = tk.history(period='1mo')
            if hist.empty or len(hist) < 2:
                continue
            
            # $10B (100억 달러) 이상 필터링
            mcap = tk.fast_info.get('marketCap', 0)
            if mcap < 10_000_000_000:
                continue

            curr = hist['Close'].iloc[-1]
            
            # 기간별 변동률 계산
            if sort_type == 'daily':
                prev = hist['Close'].iloc[-2]
            elif sort_type == 'weekly':
                prev = hist['Close'].iloc[-5] if len(hist) >= 5 else hist['Close'].iloc[0]
            elif sort_type == 'monthly':
                prev = hist['Close'].iloc[0]

            perf = ((curr - prev) / prev) * 100
            
            info = tk.info
            company = info.get('shortName') or info.get('longName') or t
            sector = info.get('sector', 'N/A')

            results.append({
                'ticker': t,
                'company': company,
                'sector': sector,
                'perf_num': perf,
                'change': f"{'+' if perf > 0 else ''}{perf:.2f}%"
            })
        except Exception:
            continue

    # 상승률 상위 3개 정렬
    results.sort(key=lambda x: x['perf_num'], reverse=True)
    return results[:3]

# 데이터 수집 실행
fg_result = get_fear_and_greed()
daily_top3 = get_top3_stocks('daily')
weekly_top3 = get_top3_stocks('weekly')
monthly_top3 = get_top3_stocks('monthly')

# 마크다운 표 생성 (티커/회사명 클릭 시 Finviz로 이동 + 새 탭 target="_blank")
def render_table(title, items, screener_url):
    md = f"## {title}\n"
    md += "| 티커 | 회사 이름 | 섹터 | 변동률 |\n"
    md += "| :--- | :--- | :--- | :--- |\n"
    if not items:
        md += "| - | 데이터 수집 실패 | - | - |\n"
    else:
        for item in items:
            finviz_quote_url = f'https://finviz.com/quote.ashx?t={item["ticker"]}'
            
            # 티커와 회사 이름 모두 Finviz 링크 연결
            ticker_link = f'<a href="{finviz_quote_url}" target="_blank">{item["ticker"]}</a>'
            company_link = f'<a href="{finviz_quote_url}" target="_blank">{item["company"]}</a>'
            
            md += f'| {ticker_link} | {company_link} | {item["sector"]} | {item["change"]} |\n'
    
    # 하단 전체보기 버튼 (Finviz 스크리너 새 탭 연결)
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
