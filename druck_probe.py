import requests, os, json
out=[]
UAS=["Johnsnoworme-market-data-feed github-actions@users.noreply.github.com",
     "Trinity Research admin@trinityresearch.org",
     "Mozilla/5.0 (compatible; TrinityResearch/1.0; +admin@trinityresearch.org)"]
urls=["https://data.sec.gov/submissions/CIK0001536411.json",
      "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1536411&type=13F-HR&dateb=&owner=include&count=40&output=atom",
      "https://efts.sec.gov/LATEST/search-index?q=%221536411%22&forms=13F-HR"]
for ua in UAS:
    for u in urls:
        try:
            r=requests.get(u,headers={"User-Agent":ua,"Accept-Encoding":"gzip, deflate"},timeout=20)
            out.append(f"{r.status_code} | {ua[:30]} | {u[:70]} | {r.text[:150]!r}")
        except Exception as e:
            out.append(f"ERR {ua[:30]} {u[:70]} {e}")
for u in ["https://13f.info/manager/0001536411-duquesne-family-office-llc",
          "https://13f.info/data/13f/000153641126000006"]:
    try:
        r=requests.get(u,headers={"User-Agent":"Mozilla/5.0"},timeout=20)
        out.append(f"{r.status_code} | 13f.info | {u} | {r.text[:600]!r}")
    except Exception as e:
        out.append(f"ERR {u} {e}")
os.makedirs("druck",exist_ok=True)
open("druck/probe.txt","w").write("\n".join(out))
print("\n".join(out))
