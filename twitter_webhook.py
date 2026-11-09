import os
import json
import time
import re
import requests

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STORAGE_FILE = "last_tweet_ids.json"
TARGET_USERNAME = "trickcal_en"

# ระบุ ID ของทวีต Pin ที่ไม่ต้องการให้ระบบดึงมาส่งเด็ดขาด
PINNED_ARTICLE_ID = "2117542439829528790"

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://twitter.com/{username}",
    }
    
    res = None
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                break
            elif res.status_code == 429:
                print(f"Rate limited (429). Waiting 15s before retry {attempt+1}/3...")
                time.sleep(15)
            else:
                print(f"HTTP Error: {res.status_code}")
                return []
        except Exception as e:
            print(f"Connection error: {e}")
            time.sleep(3)
            
    if not res or res.status_code != 200:
        return []

    try:
        start_token = '<script id="__NEXT_DATA__" type="application/json">'
        if start_token not in res.text:
            print("Token __NEXT_DATA__ not found")
            return []
        
        json_str = res.text.split(start_token)[1].split('</script>')[0]
        data = json.loads(json_str)
        timeline = data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])
        
        tweets = []
        for entry in timeline:
            if entry.get("type") != "tweet":
                continue

            content = entry.get("content", {})
            t = content.get("tweet", {})
            if not t or t.get("retweeted_status_id_str"):
                continue

            t_id = str(t.get("id_str"))
            
            # กรองทวีต Pin ออกอย่างเด็ดขาด
            if t_id == PINNED_ARTICLE_ID or t.get("isPinned") or entry.get("isPinned"):
                continue

            raw_text = t.get("text", "")

            urls = t.get("entities", {}).get("urls", [])
            is_article = any("/article/" in u.get("expanded_url", "") for u in urls)

            media = t.get("entities", {}).get("media", [])
            has_video = False
            img_url = None
            
            if media:
                media_type = media[0].get("type", "")
                if media_type in ["video", "animated_gif"]:
                    has_video = True
                else:
                    img_url = media[0].get("media_url_https")

            tweet_url = f"https://x.com/{username}/article/{t_id}" if is_article else f"https://x.com/{username}/status/{t_id}"

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
                "is_article": is_article,
                "has_video": has_video,
                "image_url": img_url
            })

        return tweets
    except Exception as e:
        print(f"Parse error: {e}")
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
    raw_saved = load_last_ids()
    is_test_mode = "0" in raw_saved
    seen_ids = [x for x in raw_saved if x != "0"]

    tweets = fetch_tweets_syndication(TARGET_USERNAME)
    if not tweets:
        print("No tweets fetched.")
        return

    # คัดเลือก 5 ทวีตปกติล่าสุดจริงๆ (ไม่มี Pin ปนแล้ว)
    target_5_tweets = tweets[:5]

    print(f"--- Top {len(target_5_tweets)} Normal Tweets ---")
    for idx, t in enumerate(target_5_tweets):
        print(f" [{idx+1}] ID: {t['id']} | Title: {t['title'][:35]}")

    if is_test_mode:
        new_tweets = list(target_5_tweets)
    else:
        new_tweets = [t for t in target_5_tweets if t["id"] not in seen_ids]

    # ส่งย้อนกลับ (จากเก่าในกลุ่ม 5 โพสต์ -> โพสต์ใหม่ล่าสุดปิดท้ายล่างสุด)
    if new_tweets:
        for t in reversed(new_tweets):
            post_tweet(t)
            seen_ids.append(t["id"])
            time.sleep(1.8)

    # อัปเดตประวัติ
    current_ids = [t["id"] for t in target_5_tweets]
    all_seen = list(dict.fromkeys(seen_ids + current_ids + [PINNED_ARTICLE_ID]))
    save_last_ids(all_seen[-200:])
    print(f"Sync complete. New tweets posted: {len(new_tweets)}")

if __name__ == "__main__":
    run()
