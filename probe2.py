import requests, json
from bt_social import SEC_UA, UA
for u in ["https://www.sec.gov/files/company_tickers.json","https://www.sec.gov/include/ticker.txt",
          "https://data.sec.gov/api/xbrl/frames/us-gaap/EarningsPerShareDiluted/USD-per-shares/CY2020Q1.json",
          "https://data.sec.gov/submissions/CIK0001045810.json"]:
    for h in (SEC_UA, UA, {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}):
        try:
            r=requests.get(u,headers=h,timeout=30); print(u[-45:], h["User-Agent"][:25], r.status_code, len(r.content), r.text[:80].replace("\n"," "))
        except Exception as e: print(u, e)
r=requests.get("https://en.wikipedia.org/w/api.php",headers=UA,timeout=30,params={"action":"query","list":"search","format":"json","srsearch":"Nvidia company","srlimit":1})
print("wiki search", r.status_code, r.text[:200])
for end in ("20260930","20260927"):
    r=requests.get(f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/Nvidia/daily/20160101/{end}",headers=UA,timeout=30)
    print("pv", end, r.status_code, r.text[:150])
