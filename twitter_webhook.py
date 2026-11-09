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
            print(f"HTTP Error: {res.status_code}")
            return []
        
        start_token = '<script id="__NEXT_DATA__" type="application/json">'
        if start_token not in res.text:
            print("Token __NEXT_DATA__ not found")
            return []
        
        json_str = res.text.split(start_token)[1].split('</script>')[0]
        data = json.loads(json_str)
        timeline = data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])
        
        all_tweets = []
        for entry in timeline:
            if entry.get("type") == "tweet":
                t = entry.get("content", {}).get("tweet", {})
                if not t:
                    continue
                
                # ข้าม Retweet
                if t.get("retweeted_status_id_str"):
                    continue
                
                t_id = str(t.get("id_str"))
                raw_text = t.get("text", "")

                # เช็กว่าเป็น X Article หรือไม่
                urls = t.get("entities", {}).get("urls", [])
                is_article = False
                for u in urls:
                    expanded = u.get("expanded_url", "")
                    if "/article/" in expanded:
                        is_article = True
                        break

                # เช็กวิดีโอ หรือ Animated GIF
                media = t.get("entities", {}).get("media", [])
                has_video = False
                img_url = None
                
                if media:
                    media_type = media[0].get("type", "")
                    if media_type in ["video", "animated_gif"]:
                        has_video = True
                    else:
                        img_url = media[0].get("media_url_https")

                if is_article:
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

                all_tweets.append({
                    "id": t_id,
                    "title": title,
                    "description": description,
                    "tweet_url": tweet_url,
                    "is_article": is_article,
                    "has_video": has_video,
                    "image_url": img_url
                })

        # กำจัดทวีตซ้ำ (กรณี Pin ไปซ้ำกับไทม์ไลน์ปกติ)
        unique_tweets = {t["id"]: t for t in all_tweets}.values()
        
        # เรียงลำดับจาก "ใหม่สุด -> เก่าสุด" ตาม Snowflake ID (ยิ่งเลขมาก แปลว่ายิ่งโพสต์ใหม่)
        sorted_tweets = sorted(unique_tweets, key=lambda x: int(x["id"]) if x["id"].isdigit() else 0, reverse=True)
        
        return sorted_tweets
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
    
    if tweet["is_article"]:
        payload = {"content": tweet["tweet_url"]}
    elif tweet["has_video"]:
        payload = {"content": f"https://fixupx.com/{TARGET_USERNAME}/status/{t_id}"}
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

    # คัดเลือก 5 โพสต์ล่าสุดจริงๆ โดยไม่สนใจว่าจะมี Pin คั่นอยู่ตรงไหน
    top_5_tweets = tweets[:5]
    print(f"Fetched {len(tweets)} tweets. Checking top 5 newest:")
    for t in top_5_tweets:
        print(f" - ID: {t['id']} | Title: {t['title'][:30]}")

    # รันรอบแรกสุด ให้จำ 5 โพสต์ล่าสุดนี้ไว้ทั้งหมด
    if not seen_ids:
        save_last_ids([t["id"] for t in top_5_tweets])
        print("Initial run: Synced top 5 IDs. No posts sent.")
        return

    # ตรวจสอบใน 5 โพสต์ล่าสุด ว่ามีอันไหนที่ยังไม่เคยส่งเข้า Discord
    new_tweets = [t for t in top_5_tweets if t["id"] not in seen_ids]

    if new_tweets:
        # เรียงลำดับส่งจากเก่าไปใหม่ เพื่อให้ทวีตเรียงไทม์ไลน์สวยๆ ใน Discord
        for t in reversed(new_tweets):
            post_tweet(t)
            seen_ids.append(t["id"])
            time.sleep(1.5)

    # บันทึก ID ทั้งหมดที่ผ่านตาเก็บไว้ในประวัติ ป้องกันส่งซ้ำ
    all_seen = list(dict.fromkeys(seen_ids + [t["id"] for t in top_5_tweets]))
    save_last_ids(all_seen[-200:])
    print(f"Done. Posted {len(new_tweets)} new tweets.")

if __name__ == "__main__":
    run()
