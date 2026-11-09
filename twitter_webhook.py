import os
import json
import time
import re
import requests

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STORAGE_FILE = "last_tweet_ids.json"
TARGET_USERNAME = "trickcal_en"

def load_last_ids():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            return []
    return []

def save_last_ids(data):
    clean_data = list(dict.fromkeys([str(x).strip() for x in data if str(x).strip()]))
    with open(STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_data, f, ensure_ascii=False, indent=2)

def fetch_tweets_syndication(username):
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            return []
        
        start_token = '<script id="__NEXT_DATA__" type="application/json">'
        if start_token not in res.text:
            return []
        
        json_str = res.text.split(start_token)[1].split('</script>')[0]
        data = json.loads(json_str)
        timeline = data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])
        
        tweets = []
        for entry in timeline:
            if entry.get("type") == "tweet":
                t = entry.get("content", {}).get("tweet", {})
                if not t:
                    continue
                
                # ข้าม Retweet
                if t.get("retweeted_status_id_str"):
                    continue
                
                t_id = str(t.get("id_str"))
                user_info = t.get("user", {})
                raw_text = t.get("text", "")

                # 1. ตรวจสอบกรณีเป็น X Article (บทความยาว)
                article_data = t.get("article", {})
                is_article = bool(article_data)
                
                title = ""
                description = ""
                
                if is_article:
                    title = article_data.get("title", "")
                    description = article_data.get("preview_text", "")
                    img_url = article_data.get("cover_media", {}).get("media_url_https")
                    tweet_url = f"https://x.com/{username}/article/{t_id}"
                else:
                    tweet_url = f"https://x.com/{username}/status/{t_id}"
                    img_url = None

                # 2. กรณีเป็นทวีตปกติ
                if not is_article:
                    # ดึงรูปภาพจาก media entities
                    media = t.get("entities", {}).get("media", [])
                    if media:
                        img_url = media[0].get("media_url_https")
                    
                    # ลบลิงก์รูปภาพ t.co ออกจากข้อความท้ายทวีต
                    clean_text = re.sub(r'https://t\.co/\S+$', '', raw_text).strip()
                    if not clean_text:
                        clean_text = raw_text

                    lines = [line.strip() for line in clean_text.split("\n") if line.strip()]
                    if lines:
                        title = lines[0]
                        description = "\n".join(lines[1:]) if len(lines) > 1 else ""
                    else:
                        title = f"Post from @{username}"
                        description = clean_text

                # ตัดความยาวให้อยู่ในเกณฑ์ปลอดภัยของ Discord Embed
                if len(title) > 250:
                    title = title[:247] + "..."
                if len(description) > 3000:
                    description = description[:2997] + "..."

                tweets.append({
                    "id": t_id,
                    "title": title,
                    "description": description,
                    "tweet_url": tweet_url,
                    "image_url": img_url
                })
        return tweets
    except Exception as e:
        print(f"Fetch error: {e}")
        return []

def send_to_webhook(payload):
    if not WEBHOOK_URL:
        return
    for _ in range(3):
        try:
            resp = requests.post(WEBHOOK_URL, json=payload, timeout=15)
            if resp.status_code in (200, 204):
                return
            elif resp.status_code == 429:
                retry_after = resp.json().get("retry_after", 2)
                time.sleep(float(retry_after) + 0.5)
            else:
                break
        except Exception:
            time.sleep(2)

def post_tweet(tweet):
    t_id = tweet["id"]
    tweet_url = tweet["tweet_url"]
    
    # ประกอบ Embed หน้าตาตามตัวอย่าง
    embed = {
        "title": tweet["title"],
        "url": tweet_url,
        "description": tweet["description"] if tweet["description"] else None,
        "color": 0x1DA1F2,  # สีฟ้าทางการของ X
        "footer": {
            "text": "X",
            "icon_url": "https://abs.twimg.com/favicons/twitter.3.ico"
        }
    }
    
    if tweet["image_url"]:
        embed["image"] = {"url": tweet["image_url"]}

    # ไม่ใส่ username / avatar_url เพื่อคงรูปโปรไฟล์น้องกบของ Webhook ไว้
    payload = {
        "content": tweet_url,
        "embeds": [embed]
    }
    
    send_to_webhook(payload)
    print(f"Posted Tweet {t_id}")

def run():
    seen_ids = load_last_ids()
    tweets = fetch_tweets_syndication(TARGET_USERNAME)
    if not tweets:
        print("No tweets fetched.")
        return

    # รันครั้งแรกสุด ให้จดจำทวีตทั้งหมดเป็นฐานข้อมูล
    if not seen_ids:
        save_last_ids([t["id"] for t in tweets])
        print("Initial run: Synced current tweet IDs.")
        return

    is_test_mode = "0" in seen_ids
    seen_ids = [x for x in seen_ids if x != "0"]
    new_tweets = [t for t in tweets if t["id"] not in seen_ids]

    # โหมดทดสอบ: ดึงเฉพาะโพสต์บนสุด 1 โพสต์เท่านั้น
    if is_test_mode and new_tweets:
        new_tweets = new_tweets[:1]

    if new_tweets:
        for t in reversed(new_tweets):
            post_tweet(t)
            time.sleep(1.5)

        # บันทึก ID ปัจจุบันทั้งหมดลงไฟล์ ป้องกันการดึงโพสต์เก่าย้อนหลัง
        all_current_ids = [t["id"] for t in tweets]
        save_last_ids(all_current_ids[-100:])
    else:
        print("No new tweets found.")

if __name__ == "__main__":
    run()
