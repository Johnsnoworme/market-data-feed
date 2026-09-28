import re, requests, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
CH = "UCC3yfxS5qC6PCwDzetUuEWg"
out = []
r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={CH}", timeout=30)
out.append(f"RSS {r.status_code}")
ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
vids = []
if r.ok:
    root = ET.fromstring(r.content)
    for e in root.findall("a:entry", ns):
        vid = e.find("yt:videoId", ns).text
        pub = datetime.fromisoformat(e.find("a:published", ns).text)
        syd = pub.astimezone(timezone(timedelta(hours=10)))
        kst = pub.astimezone(timezone(timedelta(hours=9)))
        title = e.find("a:title", ns).text
        vids.append(vid)
        out.append(f"{kst:%Y-%m-%d %a %H:%M} KST | 시드니 {syd:%H:%M} | {vid} | {title}")
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    for v in vids[:3]:
        try:
            t = api.fetch(v, languages=["ko"])
            txt = " ".join(s.text for s in t)
            out.append(f"TRANSCRIPT {v}: OK {len(txt)}자 | 앞부분: {txt[:120]}")
        except Exception as e:
            out.append(f"TRANSCRIPT {v}: FAIL {type(e).__name__}: {str(e)[:200]}")
except Exception as e:
    out.append(f"transcript lib error {e}")
open("research/yt_probe.txt", "w").write("\n".join(out))
print("\n".join(out))
