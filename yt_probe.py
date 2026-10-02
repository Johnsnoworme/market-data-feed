# 2026-10-02 시험: GitHub에서 유튜브 영상 목록을 읽을 수 있는 방법 찾기
import json, re, subprocess, requests
out = []
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
for name, u in [("RSS+UA", "https://www.youtube.com/feeds/videos.xml?channel_id=UCC3yfxS5qC6PCwDzetUuEWg"),
                ("RSS playlist", "https://www.youtube.com/feeds/videos.xml?playlist_id=UUC3yfxS5qC6PCwDzetUuEWg")]:
    try:
        r = requests.get(u, headers=UA, timeout=30); out.append(f"{name}: {r.status_code} {len(r.text)}")
    except Exception as e: out.append(f"{name}: ERR {e}")
try:
    r = requests.get("https://www.youtube.com/@sosumonkey/videos", headers=UA, cookies={"CONSENT": "YES+1", "SOCS": "CAI"}, timeout=30)
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", r.text)
    ids = re.findall(r'"videoId":"([\w-]{11})"', r.text)
    rel = re.findall(r'"publishedTimeText":\{"simpleText":"([^"]+)"', r.text)
    out.append(f"HTML videos: {r.status_code} len {len(r.text)} ytInitialData {'O' if m else 'X'} ids {list(dict.fromkeys(ids))[:6]} rel {rel[:4]}")
except Exception as e: out.append(f"HTML: ERR {e}")
def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return (p.stdout.strip() or p.stderr.strip())[:700]
out.append("YTDLP flat: " + run(["yt-dlp", "--flat-playlist", "--playlist-end", "4", "--print", "%(id)s|%(title)s|%(timestamp)s|%(upload_date)s", "https://www.youtube.com/@sosumonkey/videos"]))
ids = re.findall(r"^([\w-]{11})\|", out[-1].replace("YTDLP flat: ", ""), re.M)
if ids:
    out.append("YTDLP video: " + run(["yt-dlp", "--skip-download", "--print", "%(id)s|%(timestamp)s|%(upload_date)s|%(duration)s", f"https://www.youtube.com/watch?v={ids[0]}"]))
open("research/yt_probe.txt", "w").write("\n".join(out))
print("\n".join(out))
