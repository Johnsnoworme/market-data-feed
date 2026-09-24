import os
import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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

# 2. Large Cap ($10B+) 사전 메타데이터 수집 (속도 최적화 & 차단 방지)
def build_largecap_dict():
    meta_dict = {}
    # Overview(v=111) 상위 100개 대형주 정보 일괄 수집 (1, 21, 41, 61, 81페이지)
    for r in [1, 21, 41, 61, 81]:
        url = f"https://finviz.com/screener.ashx?v=111&f=cap_largeover10&r={r}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.find_all('tr', class_=lambda c: c and 'styled-row' in c)
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    link = cols[1].find('a')
                    if link and 'href' in link.attrs:
                        # 순수 quote.ashx 링크만 정밀 매칭
                        match = re.search(r'quote\.ashx\?t=([A-Za-z0-9\.-]+)', link['href'])
                        if match:
                            ticker = match.group(1).upper()
                            company = cols[2].text.strip()
                            sector = cols[3].text.strip()
                            meta_dict[ticker] = {'company': company, 'sector': sector}
        except Exception:
            pass
    return meta_dict

# 3. Finviz Top 3 수집 함수
def get_finviz_top3(view_type, order_param, change_col_idx, meta_dict):
    url = f"https://finviz.com/screener.ashx?v={view_type}&f=cap_largeover10&o={order_param}"
    results = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.find_all('tr', class_=lambda c: c and 'styled-row' in c)
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) > change_col_idx:
                ticker_a = cols[1].find('a')
                if not ticker_a or 'href' not in ticker_a.attrs:
                    continue
                
                # 티커 추출 정규식 검증
                match = re.search(r'quote\.ashx\?t=([A-Za-z0-9\.-]+)', ticker_a['href'])
                if not match:
                    continue
                
                ticker = match.group(1).upper()
                if len(ticker) < 2:
                    continue
                    
                change = cols[change_col_idx].text.strip()
                
                # 메타 정보 매핑 (Overview면 직접 가져오고, 없으면 사전에서 조회)
                if view_type == 111 and len(cols) >= 4:
                    company = cols[2].text.strip()
                    sector = cols[3].text.strip()
                else:
                    meta = meta_dict.get(ticker, {'company': ticker, 'sector': 'N/A'})
                    company = meta['company']
                    sector = meta['sector']

                results.append({
                    'ticker': ticker,
                    'company': company,
                    'sector': sector,
                    'change': change
                })
                
                if len(results) == 3:
                    break
        return results
    except Exception:
        return []

# --- 실행 부분 ---
fg_result = get_fear_and_greed()
meta_dict = build_largecap_dict()

daily_top3 = get_finviz_top3(111, "-change", 9, meta_dict)
weekly_top3 = get_finviz_top3(141, "-perf1w", 2, meta_dict)
monthly_top3 = get_finviz_top3(141, "-perf4w", 3, meta_dict)

# 마크다운 표 구성
def render_table(title, items, screener_url):
    md = f"## {title}\n"
    md += "| 티커 | 회사 이름 | 섹터 | 변동률 |\n"
    md += "| :--- | :--- | :--- | :--- |\n"
    if not items:
        md += "| - | 데이터 수집 실패 | - | - |\n"
    else:
        for item in items:
            md += f'| <a href="https://finviz.com/quote.ashx?t={item["ticker"]}" target="_blank">{item["ticker"]}</a> | {item["company"]} | {item["sector"]} | {item["change"]} |\n'
    md += f'\n👉 <a href="{screener_url}" target="_blank">Finviz {title} Large-Cap Screener 전체보기</a>\n\n'
    return md

# 마크다운 저장
md_content = f"# Market Data\n\n## Fear & Greed Index\n{fg_result}\n\n"
md_content += render_table("Daily Top 3", daily_top3, "https://finviz.com/screener.ashx?v=111&f=cap_largeover10&o=-change")
md_content += render_table("Weekly Top 3", weekly_top3, "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf1w")
md_content += render_table("Monthly Top 3", monthly_top3, "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf4w")

with open("Market_Data.md", "w", encoding="utf-8") as f:
    f.write(md_content.strip())

print("Market_Data.md 업데이트 완료!")
