import os
import json
import time
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

def fetch_tweets_fxtwitter(username):
    # ดึงข้อมูลผ่าน FxTwitter API ซึ่งดึงตรงจากไทม์ไลน์จริง
    url = f"https://api.fxtwitter.com/{username}"
    headers = {
        "User-Agent": "DiscordBot (compatible; Mozilla/5.0)"
    }
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            print(f"FxTwitter API Error: {res.status_code}")
            return []
        
        data = res.json()
        raw_tweets = data.get("tweets", [])
        
        # กรณี API ส่งมาเป็น object เดียว ให้ห่อเป็น list
        if not raw_tweets and "tweet" in data:
            raw_tweets = [data["tweet"]]

        parsed_tweets = []
        for t in raw_tweets:
            # ข้าม Retweet
            if t.get("retweet"):
                continue

            t_id = str(t.get("id"))
            text = t.get("text", "")
            
            # ตรวจสอบว่าเป็น X Article หรือไม่
            is_article = False
            if "/article/" in text or "x.com/i/article/" in text:
                is_article = True

            # ตรวจสอบว่ามีวิดีโอหรือ GIF หรือไม่
            has_video = False
            media_list = t.get("media", {})
            videos = media_list.get("videos", [])
            photos = media_list.get("photos", [])
            
            if videos:
                has_video = True
            
            img_url = photos[0].get("url") if photos else None

            # กำหนด URL ทวีต
            if is_article:
                tweet_url = f"https://x.com/{username}/article/{t_id}"
            else:
                tweet_url = f"https://x.com/{username}/status/{t_id}"

            # แยกบรรทัดชื่อเรื่องและเนื้อหา
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            title = lines[0] if lines else f"Post from @{username}"
            description = "\n".join(lines[1:]) if len(lines) > 1 else ""

            if len(title) > 250:
                title = title[:247] + "..."
            if len(description) > 3000:
                description = description[:2997] + "..."

            parsed_tweets.append({
                "id": t_id,
                "title": title,
                "description": description,
                "tweet_url": tweet_url,
                "is_article": is_article,
                "has_video": has_video,
                "image_url": img_url
            })

        return parsed_tweets
    except Exception as e:
        print(f"FxTwitter Fetch Error: {e}")
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
    
    # กรณี Article ส่งเป็นลิงก์เพียวเพื่อให้ Discord ดึงพรีวิวบทความอัตโนมัติ
    if tweet["is_article"]:
        payload = {"content": tweet["tweet_url"]}
    # กรณีวิดีโอ/GIF ส่งผ่าน fixupx เพื่อให้กดเล่นคลิปได้ในดิสคอร์ด
    elif tweet["has_video"]:
        payload = {"content": f"https://fixupx.com/{TARGET_USERNAME}/status/{t_id}"}
    # กรณีรูปภาพหรือข้อความทั่วไป ส่งเป็นการ์ด Embed
    else:
        embed = {
            "title": tweet["title"],
            "url": tweet["tweet_url"],
            "description": tweet["description"] if tweet["description"] else None,
            "color": 0x1DA1F2,
            "footer": {
                "text": "X",
                "icon_url": "https://abs.twimg.com/favicons/twitter.3.ico"
            }
        }
        if tweet["image_url"]:
            embed["image"] = {"url": tweet["image_url"]}

        payload = {
            "content": tweet["tweet_url"],
            "embeds": [embed]
        }
    
    send_to_webhook(payload)
    print(f"Posted Tweet {t_id}")

def run():
    raw_saved = load_last_ids()
    is_test_mode = "0" in raw_saved
    seen_ids = [x for x in raw_saved if x != "0"]

    tweets = fetch_tweets_fxtwitter(TARGET_USERNAME)
    if not tweets:
        print("No tweets fetched from FxTwitter.")
        return

    # คัดเลือก 5 ทวีตบนสุด
    target_5_tweets = tweets[:5]

    print(f"--- Fetched {len(tweets)} tweets. Top 5: ---")
    for idx, t in enumerate(target_5_tweets):
        print(f" [{idx+1}] ID: {t['id']} | Title: {t['title'][:35]}")

    if is_test_mode:
        new_tweets = list(target_5_tweets)
    else:
        new_tweets = [t for t in target_5_tweets if t["id"] not in seen_ids]

    # ส่งจากล่างขึ้นบน (เก่า -> ใหม่สุด) เพื่อให้โพสต์ล่าสุดอยู่ล่างสุดในแชท Discord
    if new_tweets:
        for t in reversed(new_tweets):
            post_tweet(t)
            seen_ids.append(t["id"])
            time.sleep(1.8)

    # บันทึก ID ลงประวัติ
    current_ids = [t["id"] for t in target_5_tweets]
    all_seen = list(dict.fromkeys(seen_ids + current_ids))
    save_last_ids(all_seen[-200:])
    print(f"Sync complete. New tweets posted: {len(new_tweets)}")

if __name__ == "__main__":
    run()
