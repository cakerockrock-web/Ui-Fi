import os
import json
import time
import re
from datetime import datetime
import requests

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STORAGE_FILE = "last_tweet_ids.json"
TARGET_USERNAME = "trickcal_en"

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

def parse_twitter_date(date_str):
    """แปลงเวลา 'Wed Oct 10 20:19:24 +0000 2026' เป็น timestamp เพื่อเปรียบเทียบ"""
    try:
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return dt.timestamp()
    except Exception:
        return 0

def fetch_tweets(username):
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://twitter.com/{username}",
    }
    
    # ดึงข้อมูลพร้อมระบบรอหากติด Rate Limit
    res = None
    for attempt in range(2):
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                break
            elif res.status_code == 429:
                print(f"[Rate Limit 429] Twitter CDN จำกัดความถี่ รอ 15 วินาที (ครั้งที่ {attempt+1}/2)...")
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
        
        raw_list = []
        for entry in timeline:
            if entry.get("type") != "tweet":
                continue
            
            t = entry.get("content", {}).get("tweet", {})
            if not t or t.get("retweeted_status_id_str"):
                continue

            t_id = str(t.get("id_str"))
            created_at = t.get("created_at", "")
            timestamp = parse_twitter_date(created_at)
            raw_text = t.get("text", "")

            # เช็ก Article
            urls = t.get("entities", {}).get("urls", [])
            is_article = any("/article/" in u.get("expanded_url", "") for u in urls)

            # เช็ก Media
            media = t.get("entities", {}).get("media", [])
            has_video = False
            img_url = None
            if media:
                m_type = media[0].get("type", "")
                if m_type in ["video", "animated_gif"]:
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

            raw_list.append({
                "id": t_id,
                "timestamp": timestamp,
                "title": title,
                "description": description,
                "tweet_url": tweet_url,
                "is_article": is_article,
                "has_video": has_video,
                "image_url": img_url
            })

        if not raw_list:
            return []

        # --- ตรวจจับและตัดทวีต Pin อัตโนมัติ ---
        # ถ้าโพสต์แรก (index 0) มีเวลาเก่ากว่าโพสต์ถัดไป (index 1) แปลว่ามันคือทวีตปักหมุดแน่นอน
        if len(raw_list) > 1 and raw_list[0]["timestamp"] > 0 and raw_list[1]["timestamp"] > 0:
            if raw_list[0]["timestamp"] < raw_list[1]["timestamp"]:
                print(f"[Filtered Pin] ตัดทวีตปักหมุด ID: {raw_list[0]['id']} ออกเรียบร้อย")
                raw_list = raw_list[1:]

        return raw_list
    except Exception as e:
        print(f"[Parse Error] {e}")
        return []

def send_to_discord(tweet):
    if not WEBHOOK_URL:
        return
    
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

    for _ in range(3):
        try:
            resp = requests.post(WEBHOOK_URL, json=payload, timeout=15)
            if resp.status_code in (200, 204):
                print(f"[Sent] Post ID: {t_id}")
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

    tweets = fetch_tweets(TARGET_USERNAME)
    if not tweets:
        print("ไม่พบทวีตหรือติดข้อจำกัดเครือข่าย")
        return

    # คัดเลือก 5 ทวีตปกติล่าสุด (เรียงตามลำดับธรรมชาติจากบนลงล่าง = ใหม่ไปเก่า)
    top_5_tweets = tweets[:5]

    print(f"=== รายการ 5 ทวีตล่าสุดที่ตรวจพบ ===")
    for idx, t in enumerate(top_5_tweets):
        print(f"[{idx+1}] ID: {t['id']} | {t['title'][:35]}")

    # หาว่าโพสต์ไหนที่ยังไม่เคยส่ง
    if is_test_mode:
        to_post = list(top_5_tweets)
    else:
        to_post = [t for t in top_5_tweets if t["id"] not in seen_ids]

    # ส่งเข้า Discord: เรียงจากเก่าในกลุ่ม -> ไปหาใหม่ล่าสุด
    # เพื่อให้โพสต์ล่าสุดอยู่ล่างสุดใน Discord ตามที่ต้องการ
    if to_post:
        print(f"\nกำลังเริ่มส่ง {len(to_post)} โพสต์เข้า Discord...")
        for t in reversed(to_post):
            send_to_discord(t)
            seen_ids.append(t["id"])
            time.sleep(1.8)
    else:
        print("\nไม่มีโพสต์ใหม่ที่ต้องส่ง")

    # บันทึก ID ของทั้ง 5 โพสต์นี้ลงไฟล์ประวัติ
    current_ids = [t["id"] for t in top_5_tweets]
    all_seen = list(dict.fromkeys(seen_ids + current_ids))
    save_history(all_seen[-200:])
    print(f"เสร็จสิ้น บันทึกประวัติเรียบร้อย ({len(all_seen[-200:])} รายการ)")

if __name__ == "__main__":
    run()
