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

MIN_MARKET_CAP = 10_000_000_000  # Finviz "+Large (over $10bln)" 기준

def _clean_name(name):
    # Nasdaq 종목명 뒤에 붙는 "Common Stock", "Class A ..." 등 꼬리 제거
    for cut in [" Common Stock", " Class A", " Class B", " Class C", " Ordinary Shares",
                " American Depositary", " Sponsored ADR", " ADS", " Common Shares"]:
        idx = name.find(cut)
        if idx > 0:
            name = name[:idx]
    return name.strip()

def get_large_cap_universe():
    """
    Nasdaq 스크리너(NYSE/NASDAQ/AMEX 전체 상장 종목)에서 시가총액 $10B 이상만 추출.
    S&P 500만 보면 OKTA, VICR, TWST, NBIS 같은 비(非)S&P 대형주가 빠져서
    Finviz 결과와 달라지므로, Finviz와 같은 전체 시장 기준을 사용.
    반환: {ticker: {'Security': 회사명, 'GICS Sector': 섹터}}
    """
    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://www.nasdaq.com',
        'Referer': 'https://www.nasdaq.com/',
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    rows = resp.json()['data']['rows']

    info = {}
    for r in rows:
        sym = (r.get('symbol') or '').strip()
        try:
            cap = float(r.get('marketCap') or 0)
        except ValueError:
            continue
        # 우선주/워런트 등 특수 심볼(^ 포함) 제외, 시총 기준 미달 제외
        if not sym or '^' in sym or cap < MIN_MARKET_CAP:
            continue
        # yfinance 호환: BRK/B -> BRK-B
        yf_sym = sym.replace('/', '-').replace('.', '-')
        info[yf_sym] = {
            'Security': _clean_name(r.get('name') or yf_sym),
            'GICS Sector': r.get('sector') or 'N/A',
        }
    return info

FINVIZ_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://finviz.com/',
}

# Finviz 커스텀 뷰(v=152) 컬럼: 1=Ticker, 2=Company, 3=Sector, 42=Perf Week, 43=Perf Month, 66=Change %
FINVIZ_COLS = {'change': 'Change %', 'perf1w': 'Perf Week', 'perf4w': 'Perf Month'}

def get_finviz_top3(order):
    """
    Finviz 스크리너(+Large, 시총 $10B 이상)를 그대로 읽어서 상위 3개를 가져옴.
    사용자가 브라우저에서 보는 Finviz 화면과 100% 같은 결과.
    order: 'change' (Daily) / 'perf1w' (Weekly) / 'perf4w' (Monthly)
    반환: [(ticker, company, sector, pct_float), ...]
    """
    import lxml.html
    url = f"https://finviz.com/screener.ashx?v=152&f=cap_largeover&o=-{order}&c=1,2,3,42,43,66"
    resp = requests.get(url, headers=FINVIZ_HEADERS, timeout=20)
    resp.raise_for_status()
    doc = lxml.html.fromstring(resp.text)
    tables = doc.xpath("//table[contains(concat(' ', normalize-space(@class), ' '), ' screener_table ')]")
    if not tables:
        raise ValueError("Finviz 스크리너 표를 찾을 수 없습니다.")
    rows = tables[0].xpath(".//tr")
    header = [c.text_content().strip() for c in rows[0].xpath("./th|./td")]
    i_t, i_c, i_s = header.index('Ticker'), header.index('Company'), header.index('Sector')
    i_v = header.index(FINVIZ_COLS[order])

    out = []
    for r in rows[1:]:
        cells = [c.text_content().strip() for c in r.xpath("./td")]
        if len(cells) <= i_v or not cells[i_t]:
            continue
        val = float(cells[i_v].replace('%', '').replace(',', ''))
        out.append((cells[i_t], cells[i_c], cells[i_s], val))
        if len(out) == 3:
            break
    if len(out) < 3:
        raise ValueError(f"Finviz 결과가 3개 미만입니다: {out}")
    return out

def compute_top3_fallback():
    """
    Finviz 접속이 막혔을 때의 백업: Nasdaq 전체 상장 $10B+ 종목을 yfinance로 직접 계산.
    (시총 경계선 종목 1~2개는 Finviz와 다를 수 있음)
    """
    info_dict = get_large_cap_universe()
    tickers = list(info_dict.keys())
    if len(tickers) < 100:
        raise ValueError(f"종목 수가 비정상적으로 적습니다: {len(tickers)}")
    print(f"   yfinance로 {len(tickers)}개 대형주 주가 일괄 다운로드 중...")
    data = yf.download(tickers, period="1mo", interval="1d", progress=False, threads=True)
    close = data['Close'].dropna(how='all')
    if len(close) < 2:
        raise ValueError("수익률을 계산할 충분한 거래일 데이터가 없습니다.")
    week_idx = -6 if len(close) >= 6 else 0
    rets = {
        'change': (close.iloc[-1] / close.iloc[-2] - 1) * 100,
        'perf1w': (close.iloc[-1] / close.iloc[week_idx] - 1) * 100,
        'perf4w': (close.iloc[-1] / close.iloc[0] - 1) * 100,
    }
    result = {}
    for key, ser in rets.items():
        result[key] = [
            (t, info_dict[t]['Security'], info_dict[t]['GICS Sector'], float(v))
            for t, v in ser.dropna().nlargest(3).items()
        ]
    return result

def top3_md(rows, title, finviz_url):
    md = f"## {title}\n"
    md += "| 티커 | 회사 이름 | 섹터 | 변동률 |\n"
    md += "| :--- | :--- | :--- | :--- |\n"
    if not rows:
        md += "| - | 데이터 수집 실패 | - | - |\n"
    for ticker, name, sector, val in rows:
        sign = "+" if val > 0 else ""
        finviz_quote = f"https://finviz.com/quote.ashx?t={ticker}"
        ticker_link = f'<a href="{finviz_quote}" target="_blank">{ticker}</a>'
        md += f"| {ticker_link} | {name} | {sector} | {sign}{val:.2f}% |\n"
    md += f'\n👉 <a href="{finviz_url}" target="_blank">Finviz {title} Large-Cap Screener 전체보기</a>\n\n'
    return md

def generate_market_data_md():
    print("1. Finviz 스크리너(+Large, 시총 $10B 이상)에서 Daily/Weekly/Monthly Top 3 수집 중...")
    results = {}
    try:
        for order in ['change', 'perf1w', 'perf4w']:
            results[order] = get_finviz_top3(order)
            print(f"   {order}: {[r[0] for r in results[order]]}")
        source = "Finviz"
    except Exception as e:
        print(f"   Finviz 수집 실패 ({e}) → 백업 방식(Nasdaq + yfinance)으로 계산합니다.")
        try:
            results = compute_top3_fallback()
            source = "Nasdaq + yfinance (백업)"
        except Exception as e2:
            print(f"백업 방식도 실패: {e2}")
            sys.exit(1)

    print("2. Market_Data.md 작성 중...")
    url_daily = "https://finviz.com/screener.ashx?v=111&f=cap_largeover&o=-change"
    url_weekly = "https://finviz.com/screener.ashx?v=141&f=cap_largeover&o=-perf1w"
    url_monthly = "https://finviz.com/screener.ashx?v=141&f=cap_largeover&o=-perf4w"

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    md_content = "# Market Data\n\n"
    md_content += f"> 마지막 업데이트: {now} (데이터 출처: {source})\n\n"
    md_content += f"## Fear & Greed Index\n{get_fear_and_greed()}\n\n"
    md_content += top3_md(results['change'], "Daily Top 3", url_daily)
    md_content += top3_md(results['perf1w'], "Weekly Top 3", url_weekly)
    md_content += top3_md(results['perf4w'], "Monthly Top 3", url_monthly)

    with open("Market_Data.md", "w", encoding="utf-8") as f:
        f.write(md_content.strip())

    print("Market_Data.md 정상 생성 완료!")

if __name__ == "__main__":
    generate_market_data_md()
