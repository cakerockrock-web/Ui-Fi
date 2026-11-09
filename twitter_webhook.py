import os
import json
import time
import requests

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STORAGE_FILE = "last_tweet_ids.json"
TARGET_USERNAME = "Trickcal_Re"  # เปลี่ยนเป็น username บัญชีเป้าหมาย (ไม่ต้องใส่ @)

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
    """ดึงทวีตสาธารณะล่าสุดโดยไม่ต้องพึ่ง Twitter Developer API Key"""
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            return []
        
        # สกัด JSON จากแท็ก __NEXT_DATA__
        html_text = res.text
        start_token = '<script id="__NEXT_DATA__" type="application/json">'
        if start_token not in html_text:
            return []
        
        json_str = html_text.split(start_token)[1].split('</script>')[0]
        data = json.loads(json_str)
        timeline = data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])
        
        tweets = []
        for entry in timeline:
            if entry.get("type") == "tweet":
                t = entry.get("content", {}).get("tweet", {})
                if not t: continue
                
                # ข้ามกรณีเป็น Retweet (ถ้าต้องการเฉพาะโพสต์ของช่อง)
                if t.get("retweeted_status_id_str"):
                    continue
                
                t_id = str(t.get("id_str"))
                text = t.get("text", "")
                user_info = t.get("user", {})
                
                # ดึงรูปแรกถ้ามีแนบมากับทวีต
                media = t.get("entities", {}).get("media", [])
                img_url = media[0].get("media_url_https") if media else None
                
                tweets.append({
                    "id": t_id,
                    "text": text,
                    "author_name": user_info.get("name", username),
                    "username": user_info.get("screen_name", username),
                    "author_icon": user_info.get("profile_image_url_https", ""),
                    "image_url": img_url
                })
        return tweets
    except Exception as e:
        print(f"Fetch error: {e}")
        return []

def send_to_webhook(payload):
    if not WEBHOOK_URL: return
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
    tweet_url = f"https://x.com/{tweet['username']}/status/{t_id}"
    
    embed = {
        "author": {
            "name": f"{tweet['author_name']} (@{tweet['username']})",
            "url": tweet_url,
            "icon_url": tweet["author_icon"]
        },
        "description": tweet["text"],
        "url": tweet_url,
        "color": 0x1DA1F2,
        "footer": {
            "text": f"X (Twitter) | ID: {t_id}"
        }
    }
    if tweet["image_url"]:
        embed["image"] = {"url": tweet["image_url"]}

    payload = {
        "username": tweet["author_name"],
        "avatar_url": tweet["author_icon"],
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

    # รันรอบแรกสุดให้จำทวีตปัจจุบันไว้ก่อน
    if not seen_ids:
        save_last_ids([t["id"] for t in tweets])
        print("Initial run: Synced current tweet IDs.")
        return

    is_test_mode = "0" in seen_ids
    seen_ids = [x for x in seen_ids if x != "0"]
    new_tweets = [t for t in tweets if t["id"] not in seen_ids]

    if is_test_mode and new_tweets:
        new_tweets = new_tweets[:2]

    if new_tweets:
        for t in reversed(new_tweets[:5]):
            post_tweet(t)
            if t["id"] not in seen_ids:
                seen_ids.append(t["id"])
            save_last_ids(seen_ids[-100:])
            time.sleep(1.5)
    else:
        print("No new tweets found.")

if __name__ == "__main__":
    run()
