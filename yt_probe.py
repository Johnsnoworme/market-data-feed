# 2026-10-02 시험 3: 채널 페이지(한국어 제목·상대시간) + 영상 페이지 업로드 시각
import re, requests
out = []
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}
CK = {"CONSENT": "YES+1", "SOCS": "CAI"}
for h in ["@sosumonkey", "@SSH_MacroBeyond"]:
    r = requests.get(f"https://www.youtube.com/{h}/videos?hl=ko&gl=KR", headers=UA, cookies=CK, timeout=30)
    t = r.text
    blocks = re.findall(r'"lockupViewModel":\{"contentImage".*?"contentId":"([\w-]{11})".*?"title":\{"content":"(.*?)"\}.*?"content":"([^"]*(?:ago|전))"', t)[:4]
    out.append(f"{h}: {r.status_code} lockups {len(blocks)}")
    for b in blocks: out.append("   " + " | ".join(b))
    if not blocks:
        out.append("   ids " + str(list(dict.fromkeys(re.findall(r'"contentId":"([\w-]{11})"', t)))[:5]) + " rel " + str(re.findall(r'"content":"([^"]*(?:ago|전))"', t)[:5]))
for vid in ["2cduC5_rK9I", "kiQ_USot1go"]:
    r = requests.get(f"https://www.youtube.com/watch?v={vid}&hl=ko", headers=UA, cookies=CK, timeout=30)
    pd = re.search(r'"publishDate":"([^"]+)"', r.text); ud = re.search(r'"uploadDate":"([^"]+)"', r.text)
    ti = re.search(r'<meta name="title" content="([^"]+)"', r.text); ln = re.search(r'"lengthSeconds":"(\d+)"', r.text)
    out.append(f"watch {vid}: {r.status_code} publishDate {pd and pd.group(1)} uploadDate {ud and ud.group(1)} len {ln and ln.group(1)} title {ti and ti.group(1)}")
open("research/yt_probe.txt", "w").write("\n".join(out))
print("\n".join(out))
