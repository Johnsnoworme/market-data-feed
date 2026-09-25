import datetime
import sys
from io import StringIO
import urllib3
import requests
import pandas as pd
import yfinance as yf

# SSL 경고 숨김
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_fear_and_greed():
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Referer': 'https://www.cnn.com/'
        }
        # verify=False 로 GitHub Actions 환경에서의 SSL 인증 오류 방지
        res = requests.get(url, headers=headers, timeout=10, verify=False)
        if res.status_code == 200:
            data = res.json()
            score = round(data['fear_and_greed']['score'], 1)
            rating = data['fear_and_greed']['rating'].title()
            return f"{score} / 100 ({rating})"
    except Exception as e:
        print(f"Fear & Greed Index 실패: {e}")
    return "데이터 수집 실패"

def generate_market_data_md():
    print("1. Wikipedia에서 대형주(S&P 500) 리스트 및 섹터 정보 수집 중...")
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        # User-Agent 없이 요청하면 Wikipedia가 403 Forbidden으로 차단함
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        sp500_df = tables[0]
        
        # yfinance 호환을 위해 티커의 '.'을 '-'로 변경 (예: BRK.B -> BRK-B)
        sp500_df['Symbol'] = sp500_df['Symbol'].str.replace('.', '-')
        
        # 티커를 키값으로 하여 회사명(Security)과 섹터(GICS Sector)를 매핑
        info_dict = sp500_df.set_index('Symbol')[['Security', 'GICS Sector']].to_dict('index')
        tickers = list(info_dict.keys())
    except Exception as e:
        print(f"S&P 500 리스트 수집 실패: {e}")
        sys.exit(1)

    print(f"2. yfinance로 {len(tickers)}개 대형주 주가 일괄 다운로드 중...")
    try:
        # progress=False로 콘솔 지저분함 방지, threads=True로 초고속 다운로드
        data = yf.download(tickers, period="1mo", interval="1d", progress=False, threads=True)
        close_prices = data['Close']
        
        # 주말/휴일 등 거래가 없어 전체가 NaN인 행 깔끔하게 제거
        close_prices = close_prices.dropna(how='all')
        
        if len(close_prices) < 2:
            raise ValueError("수익률을 계산할 충분한 거래일 데이터가 없습니다.")
            
    except Exception as e:
        print(f"주가 데이터 수집 실패: {e}")
        sys.exit(1)

    print("3. 기간별 수익률 계산 및 Top 3 동적 추출 중...")
    
    # 1. Daily: 가장 최근 거래일 vs 직전 거래일
    daily_ret = ((close_prices.iloc[-1] - close_prices.iloc[-2]) / close_prices.iloc[-2]) * 100
    
    # 2. Weekly: 가장 최근 거래일 vs 5거래일 전 (데이터가 5일 미만이면 가장 첫 데이터 사용)
    week_idx = -6 if len(close_prices) >= 6 else 0
    weekly_ret = ((close_prices.iloc[-1] - close_prices.iloc[week_idx]) / close_prices.iloc[week_idx]) * 100
    
    # 3. Monthly: 가장 최근 거래일 vs 1개월 전(가져온 데이터의 가장 첫 거래일)
    monthly_ret = ((close_prices.iloc[-1] - close_prices.iloc[0]) / close_prices.iloc[0]) * 100

    def get_top3_md(ret_series, title, finviz_url):
        # 수익률 기준 내림차순 정렬 후 상위 3개 진짜 종목 추출
        top3 = ret_series.dropna().nlargest(3)
        
        md = f"## {title}\n"
        md += "| 티커 | 회사 이름 | 섹터 | 변동률 |\n"
        md += "| :--- | :--- | :--- | :--- |\n"
        
        if top3.empty:
            md += "| - | 데이터 수집 실패 | - | - |\n"
        else:
            for ticker, val in top3.items():
                # Wikipedia 매핑 데이터에서 회사명과 섹터 가져오기
                name = info_dict.get(ticker, {}).get('Security', ticker)
                sector = info_dict.get(ticker, {}).get('GICS Sector', 'N/A')
                
                sign = "+" if val > 0 else ""
                change_str = f"{sign}{val:.2f}%"
                
                # 티커에만 Finviz 상세 페이지 링크 삽입
                finviz_quote = f"https://finviz.com/quote.ashx?t={ticker}"
                ticker_link = f'<a href="{finviz_quote}" target="_blank">{ticker}</a>'
                
                md += f"| {ticker_link} | {name} | {sector} | {change_str} |\n"
                
        md += f'\n👉 <a href="{finviz_url}" target="_blank">Finviz {title} Large-Cap Screener 전체보기</a>\n\n'
        return md

    # 테이블 하단에 들어갈 Finviz 전체보기 원본 링크
    url_daily = "https://finviz.com/screener.ashx?v=111&f=cap_largeover10&o=-change"
    url_weekly = "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf1w"
    url_monthly = "https://finviz.com/screener.ashx?v=141&f=cap_largeover10&o=-perf4w"

    md_content = "# Market Data\n\n"
    
    # 현재 UTC 기준 시간 기록
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    md_content += f"> 마지막 업데이트: {now}\n\n"
    
    md_content += f"## Fear & Greed Index\n{get_fear_and_greed()}\n\n"
    
    md_content += get_top3_md(daily_ret, "Daily Top 3", url_daily)
    md_content += get_top3_md(weekly_ret, "Weekly Top 3", url_weekly)
    md_content += get_top3_md(monthly_ret, "Monthly Top 3", url_monthly)

    # 마크다운 파일 덮어쓰기
    with open("Market_Data.md", "w", encoding="utf-8") as f:
        f.write(md_content.strip())
        
    print("Market_Data.md 정상 생성 완료!")

if __name__ == "__main__":
    generate_market_data_md()
