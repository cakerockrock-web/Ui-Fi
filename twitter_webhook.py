import os
import json
import time
import requests
from datetime import datetime, timezone

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STORAGE_FILE = "last_tweet_ids.json"
USERNAME = "trickcal_en"

# กำหนดเส้นตาย: 1 กันยายน 2026 เวลา 00:00:00 UTC (โพสต์ที่เก่ากว่านี้จะถูกข้ามทันที)
CUTOFF_TIMESTAMP = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()

def load_seen():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [str(x) for x in data if str(x) != "0"]
        except Exception:
            return []
    return []

def save_seen(ids):
    clean = list(dict.fromkeys([str(x) for x in ids]))
    with open(STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)

def parse_twitter_date(date_str):
    """แปลงรูปแบบเวลาของ Twitter เช่น 'Wed Sep 02 12:00:00 +0000 2026' เป็น timestamp"""
    try:
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return dt.timestamp()
    except Exception:
        return 0

def fetch_all_tweets():
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{USERNAME}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }

    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"Fetch failed: HTTP {resp.status_code}")
        return []

    token = '<script id="__NEXT_DATA__" type="application/json">'
    if token not in resp.text:
        return []

    json_str = resp.text.split(token)[1].split('</script>')[0]
    data = json.loads(json_str)
    entries = data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])

    tweets = []
    for entry in entries:
        if entry.get("type") != "tweet":
            continue

        t = entry.get("content", {}).get("tweet", {})
        if not t or t.get("retweeted_status_id_str"):
            continue

        # ตรวจสอบวันเวลาโพสต์: ข้ามโพสต์ที่เก่ากว่าเดือนกันยายน 2026 ทันที
        created_at = t.get("created_at", "")
        t_time = parse_twitter_date(created_at)
        if t_time and t_time < CUTOFF_TIMESTAMP:
            continue

        t_id = str(t.get("id_str"))
        urls = t.get("entities", {}).get("urls", [])
        is_article = any("/article/" in u.get("expanded_url", "") for u in urls)

        if is_article:
            url_to_send = f"https://x.com/{USERNAME}/article/{t_id}"
        else:
            url_to_send = f"https://fixupx.com/{USERNAME}/status/{t_id}"

        tweets.append({"id": t_id, "url": url_to_send})

    return tweets

def send_discord(url):
    if not WEBHOOK_URL:
        return
    for _ in range(3):
        try:
            r = requests.post(WEBHOOK_URL, json={"content": url}, timeout=15)
            if r.status_code in (200, 204):
                print(f"Sent: {url}")
                return
            elif r.status_code == 429:
                retry_after = r.json().get("retry_after", 2)
                time.sleep(float(retry_after) + 0.5)
        except Exception:
            time.sleep(2)

def main():
    seen_ids = load_seen()
    is_test = False

    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if "0" in raw or not seen_ids:
                    is_test = True
        except Exception:
            is_test = True
    else:
        is_test = True

    tweets = fetch_all_tweets()
    if not tweets:
        print("No valid tweets found.")
        return

    if is_test:
        to_post = list(tweets)
    else:
        to_post = [t for t in tweets if t["id"] not in seen_ids]

    # ส่งเรียงตามลำดับหน้าเว็บ (บนลงล่าง)
    for t in to_post:
        send_discord(t["url"])
        seen_ids.append(t["id"])
        time.sleep(2)

    current_ids = [t["id"] for t in tweets]
    save_seen(list(dict.fromkeys(seen_ids + current_ids))[-200:])
    print(f"Completed. Posted {len(to_post)} items.")

if __name__ == "__main__":
    main()
