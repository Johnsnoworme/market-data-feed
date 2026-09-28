import requests, json
UA={"User-Agent":"market-data-feed/1.0 (johnsnoworme research)"}
def t(name, fn):
    try:
        r=fn(); print(f"✅ {name}: {r}")
    except Exception as e:
        print(f"❌ {name}: {str(e)[:150]}")
t("Wikipedia pageviews (Bloom Energy)", lambda: sum(i["views"] for i in requests.get("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/Bloom_Energy/daily/20260901/20260925",headers=UA,timeout=20).json()["items"]))
t("ApeWisdom (Reddit/4chan 언급 순위)", lambda: [ (x["ticker"],x["mentions"],x.get("mentions_24h_ago")) for x in requests.get("https://apewisdom.io/api/v1.0/filter/all-stocks/page/1",timeout=20).json()["results"][:5]])
t("StockTwits trending", lambda: [x["symbol"] for x in requests.get("https://api.stocktwits.com/api/2/trending/symbols.json",headers=UA,timeout=20).json()["symbols"][:5]])
t("Reddit JSON", lambda: len(requests.get("https://www.reddit.com/r/stocks/hot.json?limit=5",headers=UA,timeout=20).json()["data"]["children"]))
def gt():
    from pytrends.request import TrendReq
    p=TrendReq(hl="en-US",tz=0); p.build_payload(["Sphere Las Vegas"],timeframe="today 3-m"); return int(p.interest_over_time().iloc[-1,0])
t("Google Trends (pytrends)", gt)
t("SEC EDGAR full-text", lambda: requests.get("https://efts.sec.gov/LATEST/search-index?q=%22fuel%20cell%22&forms=8-K",headers=UA,timeout=20).status_code)
