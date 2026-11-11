import os
import json
import time
import requests
from datetime import datetime, timezone

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STORAGE_FILE = "last_tweet_ids.json"
USERNAME = "trickcal_en"

# กรองโพสต์ที่เก่ากว่า 1 กันยายน 2026 ออกอัตโนมัติ
CUTOFF_TIMESTAMP = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()

def load_seen():
    """โหลดรายการ Tweet ID ที่เคยส่งแล้วจากไฟล์"""
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [str(x) for x in data if str(x).strip() and str(x) != "0"]
        except Exception as e:
            print(f"Warning: Failed to load storage file ({e}). Starting fresh.")
            return []
    return []

def save_seen(ids):
    """บันทึก Tweet ID ทั้งหมดโดยตัดค่าซ้ำออก"""
    clean = list(dict.fromkeys([str(x) for x in ids if str(x).strip()]))
    try:
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving storage file: {e}")

def parse_twitter_date(date_str):
    """แปลงรูปแบบวันที่ของ Twitter เป็น timestamp"""
    try:
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return dt.timestamp()
    except Exception:
        return 0

def fetch_all_tweets():
    """ดึงข้อมูลโพสต์ล่าสุดจาก timeline syndication"""
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{USERNAME}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"Fetch failed: HTTP {resp.status_code}")
            return []
    except requests.RequestException as e:
        print(f"Network error while fetching: {e}")
        return []

    token = '<script id="__NEXT_DATA__" type="application/json">'
    if token not in resp.text:
        print("Error: '__NEXT_DATA__' token not found in response HTML.")
        return []

    try:
        json_str = resp.text.split(token)[1].split('</script>')[0]
        data = json.loads(json_str)
        entries = data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        print(f"Error parsing timeline JSON: {e}")
        return []

    tweets = []
    for entry in entries:
        if entry.get("type") != "tweet":
            continue

        t = entry.get("content", {}).get("tweet", {})
        # ข้ามถ้าไม่มีข้อมูลทวีต หรือเป็น Retweet
        if not t or t.get("retweeted_status_id_str"):
            continue

        # ตรวจสอบวันเวลา: ข้ามโพสต์ที่เก่ากว่า cutoff
        created_at = t.get("created_at", "")
        t_time = parse_twitter_date(created_at)
        if t_time and t_time < CUTOFF_TIMESTAMP:
            continue

        t_id = str(t.get("id_str", "")).strip()
        if not t_id:
            continue

        # ตรวจสอบประเภทลิงก์ (Article หรือ Status ปกติ)
        urls = t.get("entities", {}).get("urls", [])
        is_article = any("/article/" in u.get("expanded_url", "") for u in urls)

        if is_article:
            url_to_send = f"https://x.com/{USERNAME}/article/{t_id}"
        else:
            url_to_send = f"https://fixupx.com/{USERNAME}/status/{t_id}"

        tweets.append({"id": t_id, "url": url_to_send})

    return tweets

def send_discord(url):
    """ยิง Webhook ส่งลิงก์เข้า Discord พร้อมระบบ Retry กรณีติด Rate limit"""
    if not WEBHOOK_URL:
        print("Warning: DISCORD_WEBHOOK_URL is not set.")
        return False

    for attempt in range(1, 4):
        try:
            r = requests.post(WEBHOOK_URL, json={"content": url}, timeout=15)
            if r.status_code in (200, 204):
                print(f"Sent: {url}")
                return True
            elif r.status_code == 429:
                retry_after = r.json().get("retry_after", 2)
                wait_time = float(retry_after) + 0.5
                print(f"Rate limited by Discord. Waiting {wait_time:.1f}s (Attempt {attempt}/3)...")
                time.sleep(wait_time)
            else:
                print(f"Discord responded with status {r.status_code}: {r.text}")
                time.sleep(2)
        except requests.RequestException as e:
            print(f"Webhook request failed: {e} (Attempt {attempt}/3)")
            time.sleep(2)
    return False

def main():
    seen_ids = load_seen()
    # ตรวจสอบว่าเป็นการรันครั้งแรกสุดหรือไม่ (ไฟล์ยังไม่มี หรือยังไม่มีประวัติ ID)
    is_first_run = not os.path.exists(STORAGE_FILE) or len(seen_ids) == 0

    tweets = fetch_all_tweets()
    if not tweets:
        print("No valid tweets found in this cycle.")
        return

    # กรณีรันครั้งแรกสุด: ให้บันทึกสถานะปัจจุบันไว้เป็นฐาน ไม่ส่งสแปมย้อนหลังเข้า Discord
    if is_first_run:
        current_ids = [t["id"] for t in tweets]
        save_seen(current_ids)
        print(f"Initial run completed: Saved {len(current_ids)} existing tweets to baseline. Nothing sent.")
        return

    # คัดเฉพาะทวีตใหม่ที่ยังไม่เคยส่ง
    to_post = [t for t in tweets if t["id"] not in seen_ids]

    if not to_post:
        print("No new tweets to post.")
        return

    # กลับลำดับข้อมูล: syndication ส่งจากใหม่ -> เก่า
    # ต้องกลับเป็น เก่า -> ใหม่ เพื่อให้โพสต์ล่าสุดอยู่ล่างสุดใน Discord ตามลำดับเวลาอ่าน
    to_post.reverse()

    posted_ids = []
    for t in to_post:
        success = send_discord(t["url"])
        if success:
            posted_ids.append(t["id"])
        # เว้นช่วงระหว่างข้อความเพื่อความปลอดภัยต่อ Discord Rate Limit
        time.sleep(2)

    # อัปเดตรายการที่เคยส่งแล้วและบันทึกลงไฟล์
    all_seen = list(dict.fromkeys(seen_ids + posted_ids))
    save_seen(all_seen)
    print(f"Completed. Successfully posted {len(posted_ids)}/{len(to_post)} items.")

if __name__ == "__main__":
    main()
