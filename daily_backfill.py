"""한 번만 쓰는 스크립트 (2026-10-02): git 기록 속 Market_Data.md로 과거 Daily 스냅샷 채우기.
시드니 날짜마다 '장 마감 후 첫 번째 기록'을 그날 스냅샷으로 저장 (이미 있으면 건너뜀)."""
import datetime, re, subprocess
import cloud_market_data as c

log = subprocess.run(["git", "log", "--reverse", "--format=%H %ct", "--", "Market_Data.md"],
                     capture_output=True, text=True).stdout.split("\n")
for line in filter(None, log):
    sha, ts = line.split()
    md = subprocess.run(["git", "show", f"{sha}:Market_Data.md"], capture_output=True, text=True).stdout
    m = re.search(r"마지막 업데이트: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC", md)
    if not m or "## Daily Top 3" not in md:
        continue
    when = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    c.save_daily_snapshot(md, now_utc=when, use_yf=False)
c.write_daily_index()
