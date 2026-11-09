import os
import json
import time
import requests

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STORAGE_FILE = "last_tweet_ids.json"

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

def send_to_webhook(payload):
    if not WEBHOOK_URL:
        return
    for _ in range(3):
        try:
            res = requests.post(WEBHOOK_URL, json=payload, timeout=15)
            if res.status_code in (200, 204):
                return
            elif res.status_code == 429:
                retry_after = res.json().get("retry_after", 2)
                time.sleep(float(retry_after) + 0.5)
            else:
                break
        except Exception:
            time.sleep(2)

def post_tweet_to_discord(tweet):
    tweet_id = str(tweet.get("id")).strip()
    tweet_text = tweet.get("text", "")
    author_name = tweet.get("author_name", "Twitter")
    author_icon = tweet.get("author_icon", "")
    tweet_url = f"https://x.com/{tweet.get('username')}/status/{tweet_id}"
    image_url = tweet.get("image_url")  # ดึงรูปแรกถ้ามี

    embed = {
        "author": {
            "name": f"{author_name} (@{tweet.get('username')})",
            "url": tweet_url,
            "icon_url": author_icon
        },
        "description": tweet_text,
        "url": tweet_url,
        "color": 0x1DA1F2,  # สีฟ้า Twitter
        "footer": {
            "text": f"X (Twitter) | ID: {tweet_id}"
        }
    }

    if image_url:
        embed["image"] = {"url": image_url}

    payload = {
        "username": author_name,
        "avatar_url": author_icon,
        "embeds": [embed]
    }

    send_to_webhook(payload)
    print(f"Posted Tweet {tweet_id} successfully.")

def run():
    seen_ids = load_last_ids()
    
    # ดึงข้อมูลจากฟังก์ชันดึงทวีต (เช่น Syndication API หรือ RSS feed)
    tweets = fetch_latest_tweets() 
    if not tweets:
        return

    # กรณีรันครั้งแรก บันทึกทวีตปัจจุบันเป็นฐานไว้ก่อน
    if not seen_ids:
        save_last_ids([str(t["id"]) for t in tweets])
        print("Initial run: Saved current tweets.")
        return

    new_tweets = [t for t in tweets if str(t["id"]).strip() not in seen_ids]

    if new_tweets:
        for tweet in reversed(new_tweets[:5]):
            post_tweet_to_discord(tweet)
            seen_ids.append(str(tweet["id"]).strip())
            save_last_ids(seen_ids[-100:])
            time.sleep(1.5)
    else:
        print("No new tweets.")

if __name__ == "__main__":
    run()
