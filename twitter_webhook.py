import os
import json
import time
import requests
from datetime import datetime

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STORAGE_FILE = "last_tweet_ids.json"
TARGET_USERNAME = "trickcal_en"

# ลิสต์ ID ที่เป็น Pin หรือต้องการแบนไม่ให้ส่งเด็ดขาด
IGNORED_IDS = ["2117542439829528790"]

def load_history():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            return []
    return []

def save_history(history_ids):
    clean_ids = list(dict.fromkeys([str(x).strip() for x in history_ids if str(x).strip()]))
    with open(STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_ids, f, ensure_ascii=False, indent=2)

def parse_date(date_str):
    try:
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return dt.timestamp()
    except Exception:
        return 0

def fetch_5_latest_tweets(username):
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://twitter.com/{username}",
    }

    res = None
    for attempt in range(2):
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                break
            elif res.status_code == 429:
                print(f"[Rate Limit 429] รอ 15 วินาที (ครั้งที่ {attempt+1}/2)...")
                time.sleep(15)
            else:
                print(f"[HTTP Error] {res.status_code}")
                return []
        except Exception as e:
            print(f"[Connection Error] {e}")
            time.sleep(3)

    if not res or res.status_code != 200:
        return []

    try:
        start_token = '<script id="__NEXT_DATA__" type="application/json">'
        if start_token not in res.text:
            return []

        json_str = res.text.split(start_token)[1].split('</script>')[0]
        data = json.loads(json_str)
        timeline = data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])

        normal_tweets = []
        for entry in timeline:
            if entry.get("type") != "tweet":
                continue

            content = entry.get("content", {})
            t = content.get("tweet", {})
            if not t or t.get("retweeted_status_id_str"):
                continue

            t_id = str(t.get("id_str"))

            # 1. ข้ามถ้าอยู่ในลิสต์ Pin / Ignore
            if t_id in IGNORED_IDS:
                continue

            # 2. เช็กว่าเป็น Article หรือ Status ธรรมดา
            urls = t.get("entities", {}).get("urls", [])
            is_article = any("/article/" in u.get("expanded_url", "") for u in urls)
            
            # ใช้ Fixupx URL สำหรับส่งเข้า Discord
            if is_article:
                fixupx_url = f"https://fixupx.com/{username}/article/{t_id}"
            else:
                fixupx_url = f"https://fixupx.com/{username}/status/{t_id}"

            created_time = parse_date(t.get("created_at", ""))

            normal_tweets.append({
                "id": t_id,
                "url": fixupx_url,
                "timestamp": created_time,
                "text": t.get("text", "")[:35].replace("\n", " ")
            })

        if not normal_tweets:
            return []

        # 3. ตรวจสอบ Pin แบบอัตโนมัติ: ถ้าโพสต์แรกเก่ากว่าโพสต์ถัดไป ให้ตัดโพสต์แรกทิ้งทันที
        if len(normal_tweets) > 1 and normal_tweets[0]["timestamp"] > 0 and normal_tweets[1]["timestamp"] > 0:
            if normal_tweets[0]["timestamp"] < normal_tweets[1]["timestamp"]:
                print(f"[Auto-Filter] ตรวจพบ Pin อัตโนมัติ ตัด ID {normal_tweets[0]['id']} ออก")
                normal_tweets = normal_tweets[1:]

        # หยิบเฉพาะ 5 โพสต์ล่าสุดบนสุด
        return normal_tweets[:5]
    except Exception as e:
        print(f"[Parse Error] {e}")
        return []

def send_fixupx_to_discord(url):
    if not WEBHOOK_URL:
        return
    payload = {"content": url}
    for _ in range(3):
        try:
            resp = requests.post(WEBHOOK_URL, json=payload, timeout=15)
            if resp.status_code in (200, 204):
                print(f"[Sent] {url}")
                return
            elif resp.status_code == 429:
                retry_after = resp.json().get("retry_after", 2)
                time.sleep(float(retry_after) + 0.5)
            else:
                break
        except Exception:
            time.sleep(2)

def run():
    saved_history = load_history()
    is_test_mode = "0" in saved_history
    seen_ids = [x for x in saved_history if x != "0"]

    tweets = fetch_5_latest_tweets(TARGET_USERNAME)
    if not tweets:
        print("ไม่สามารถดึงข้อมูลทวีตได้ในรอบนี้")
        return

    print("=== รายการ 5 ทวีตล่าสุดที่ดึงได้ ===")
    for idx, t in enumerate(tweets):
        print(f"[{idx+1}] ID: {t['id']} | {t['text']}")

    # โหมดทดสอบ (มี '0') ให้ส่งครบทั้ง 5 อัน / โหมดปกติส่งเฉพาะอันที่ยังไม่เคยส่ง
    if is_test_mode:
        to_post = list(tweets)
    else:
        to_post = [t for t in tweets if t["id"] not in seen_ids]

    # ส่งจากล่างขึ้นบน (เก่าในกลุ่ม 5 อัน -> ใหม่ล่าสุด)
    if to_post:
        print(f"\nเริ่มส่ง {len(to_post)} โพสต์เข้า Discord...")
        for t in reversed(to_post):
            send_fixupx_to_discord(t["url"])
            seen_ids.append(t["id"])
            time.sleep(2)  # เว้น 2 วินาทีให้ Discord คลี่การ์ด Fixupx ได้ครบ
    else:
        print("\nไม่มีโพสต์ใหม่ที่ต้องส่ง")

    # บันทึกประวัติ
    current_ids = [t["id"] for t in tweets]
    all_seen = list(dict.fromkeys(seen_ids + current_ids + IGNORED_IDS))
    save_history(all_seen[-200:])
    print(f"บันทึกประวัติสำเร็จ ({len(all_seen[-200:])} รายการ)")

if __name__ == "__main__":
    run()
