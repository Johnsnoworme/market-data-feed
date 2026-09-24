import os
import requests
from bs4 import BeautifulSoup

def get_finviz_top3(signal_type="daily"):
    """
    Finviz Screener (Market Cap > $10B Large Cap) 기준
    signal_type: 'daily' (Change), 'weekly' (Perf Week), 'monthly' (Perf Month)
    """
    # Order parameter: -change (Daily), -perf1w (Weekly), -perf4w (Monthly)
    order_map = {
        "daily": "-change",
        "weekly": "-perf1w",
        "monthly": "-perf4w"
    }
    
    order = order_map.get(signal_type, "-change")
    url = f"https://finviz.com/screener.ashx?v=141&f=cap_largeover10&ft=4&o={order}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Screener table parsing
        rows = soup.select('tr.styled-row')
        results = []
        
        for row in rows[:3]: # Top 3
            cols = row.find_all('td')
            if len(cols) > 1:
                ticker = cols[1].text.strip()
                # Finviz link for each ticker
                ticker_link = f"[{ticker}](https://finviz.com/quote.ashx?t={ticker})"
                
                # Fetch performance metrics from row if available
                change_pct = cols[-2].text.strip() if len(cols) >= 10 else "N/A"
                results.append((ticker_link, change_pct))
                
        return results
    except Exception as e:
        print(f"Error fetching Finviz {signal_type}: {e}")
        return []

def get_fear_and_greed():
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=5).json()
        score = round(r['fear_and_greed']['score'], 1)
        rating = r['fear_and_greed']['rating']
        return f"{score} / 100 ({rating})"
    except:
        return "N/A"

def generate_markdown():
    fg = get_fear_and_greed()
    daily_top3 = get_finviz_top3("daily")
    weekly_top3 = get_finviz_top3("weekly")
    monthly_top3 = get_finviz_top3("monthly")
    
    screener_link = "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&ft=4&o=-change"
    
    md_content = f"""# Market Data

## Fear & Greed Index
{fg}

## Daily Top 3
| 티커 | 변동률 |
| :--- | :--- |
"""
    for t, c in daily_top3:
        md_content += f"| {t} | {c} |\n"
        
    md_content += f"\n👉 [Finviz Large-Cap Screener 전체보기]({screener_link})\n\n"
    
    md_content += "## Weekly Top 3\n| 티커 | 주간 변동률 |\n| :--- | :--- |\n"
    for t, c in weekly_top3:
        md_content += f"| {t} | {c} |\n"
        
    md_content += "\n## Monthly Top 3\n| 티커 | 월간 변동률 |\n| :--- | :--- |\n"
    for t, c in monthly_top3:
        md_content += f"| {t} | {c} |\n"
        
    with open("Market_Data.md", "w", encoding="utf-8") as f:
        f.write(md_content)

if __name__ == "__main__":
    generate_markdown()
