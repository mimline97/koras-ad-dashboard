# GitHub Actions에서 매일 실행: 오늘 구독자 수를 youtube_subs.csv에 한 줄 추가
import os, csv, datetime
import urllib.request, urllib.parse, json

API_KEY = os.environ["YOUTUBE_API_KEY"]   # Actions Secret에서 주입
CHANNEL_ID = "UCbofDz8L4pyoBEjOEmM24GA"   # 코라스로보틱스
CSV_FILE = "youtube_subs.csv"

# 오늘 구독자 수 가져오기
url = "https://www.googleapis.com/youtube/v3/channels?" + urllib.parse.urlencode({
    "part": "statistics", "id": CHANNEL_ID, "key": API_KEY,
})
with urllib.request.urlopen(url, timeout=30) as r:
    data = json.loads(r.read().decode())
subs = int(data["items"][0]["statistics"]["subscriberCount"])
today = datetime.date.today().isoformat()

# 기존 CSV 읽기
rows = []
header = ["date", "subscribers"]
if os.path.exists(CSV_FILE):
    with open(CSV_FILE, encoding="utf-8") as f:
        reader = csv.reader(f)
        all_rows = list(reader)
    if all_rows:
        header = all_rows[0]
        rows = all_rows[1:]

# 오늘 날짜가 이미 있으면 값 갱신, 없으면 추가
dates = {r[0]: i for i, r in enumerate(rows) if r}
if today in dates:
    rows[dates[today]] = [today, str(subs)]
    action = "갱신"
else:
    rows.append([today, str(subs)])
    action = "추가"

# 날짜순 정렬 후 저장
rows = [r for r in rows if r]
rows.sort(key=lambda r: r[0])
with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(header)
    w.writerows(rows)

print(f"{today} 구독자 {subs}명 {action} 완료. (총 {len(rows)}일)")
