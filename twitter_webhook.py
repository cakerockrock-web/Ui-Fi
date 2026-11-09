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
                return [str(x).strip() for x in data if str(x).strip() and str(x).strip() != "0"]
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
                if not t or t.get("retweeted_status_id_str"):
                    continue
                
                t_id = str(t.get("id_str"))
                raw_text = t.get("text", "")

                # ตรวจสอบว่ามีคลิปวิดีโอ หรือ Animated GIF หรือไม่
                media = t.get("entities", {}).get("media", [])
                has_video = False
                img_url = None
                
                if media:
                    media_type = media[0].get("type", "")
                    if media_type in ["video", "animated_gif"]:
                        has_video = True
                    else:
                        img_url = media[0].get("media_url_https")

                # ตรวจสอบกรณีเป็น X Article (บทความยาว)
                article_data = t.get("article", {})
                is_article = bool(article_data)
                
                if is_article:
                    title = article_data.get("title", "")
                    description = article_data.get("preview_text", "")
                    img_url = article_data.get("cover_media", {}).get("media_url_https")
                    tweet_url = f"https://x.com/{username}/article/{t_id}"
                else:
                    tweet_url = f"https://x.com/{username}/status/{t_id}"
                    clean_text = re.sub(r'https://t\.co/\S+$', '', raw_text).strip()
                    lines = [line.strip() for line in (clean_text or raw_text).split("\n") if line.strip()]
                    title = lines[0] if lines else f"Post from @{username}"
                    description = "\n".join(lines[1:]) if len(lines) > 1 else ""

                if len(title) > 250:
                    title = title[:247] + "..."
                if len(description) > 3000:
                    description = description[:2997] + "..."

                tweets.append({
                    "id": t_id,
                    "title": title,
                    "description": description,
                    "tweet_url": tweet_url,
                    "has_video": has_video,
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
    
    if tweet["has_video"]:
        fixup_url = f"https://fixupx.com/{TARGET_USERNAME}/status/{t_id}"
        payload = {"content": fixup_url}
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
    seen_ids = load_last_ids()
    tweets = fetch_tweets_syndication(TARGET_USERNAME)
    if not tweets:
        print("No tweets fetched.")
        return

    # ถ้าเพิ่งเริ่มรันครั้งแรกและยังไม่มี ID ในระบบ ให้จดจำของปัจจุบันไว้ทั้งหมดแล้วจบการทำงานทันที
    if not seen_ids:
        all_ids = [t["id"] for t in tweets]
        save_last_ids(all_ids)
        print("Initial run: Synced current tweet IDs. No posts sent.")
        return

    # หาค่า ID สูงสุดที่เคยเห็น (ID ใหม่สุดในอดีต)
    max_seen_id = max([int(x) for x in seen_ids if x.isdigit()])

    # คัดเฉพาะทวีตที่มีรหัส ID มากกว่า max_seen_id เท่านั้น (ตัดโพสต์เก่าและทวีตปักหมุดทิ้ง 100%)
    truly_new_tweets = [t for t in tweets if t["id"].isdigit() and int(t["id"]) > max_seen_id]

    if truly_new_tweets:
        # เรียงลำดับจากเก่าไปใหม่ เพื่อให้โพสต์ตามลำดับเวลาถูกต้อง
        truly_new_tweets.sort(key=lambda x: int(x["id"]))
        
        # ป้องกันสแปม: ให้โพสต์ไม่เกิน 2 โพสต์ล่าสุดต่อการรัน 1 รอบ
        for t in truly_new_tweets[:2]:
            post_tweet(t)
            time.sleep(1.5)

    # อัปเดตรายการ ID ปัจจุบันทั้งหมดลงไฟล์ (เก็บ 100 รายการล่าสุด)
    current_ids = [t["id"] for t in tweets]
    updated_ids = list(dict.fromkeys(seen_ids + current_ids))
    save_last_ids(updated_ids[-100:])
    print(f"Sync complete. New tweets posted: {len(truly_new_tweets)}")

if __name__ == "__main__":
    run()
