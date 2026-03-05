import requests
import time
import os
from flask import Flask, request
from datetime import datetime
from supabase import create_client

app = Flask(__name__)

# =========================
# 環境変数
# =========================
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

JMA_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"
last_event_id = None


# =========================
# グループ管理（Supabase）
# =========================
def save_group(group_id):
    existing = supabase.table("groups").select("*").eq("group_id", group_id).execute()

    if not existing.data:
        supabase.table("groups").insert({"group_id": group_id}).execute()
        print("グループ登録:", group_id, flush=True)


def load_groups():
    response = supabase.table("groups").select("*").execute()
    return [g["group_id"] for g in response.data]


# =========================
# LINE送信
# =========================
def send_line_message(text):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    groups = load_groups()

    for group_id in groups:
        data = {
            "to": group_id,
            "messages": [
                {
                    "type": "text",
                    "text": text
                }
            ]
        }

        requests.post(url, headers=headers, json=data)


def send_line_message_to_group(group_id, text):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    data = {
        "to": group_id,
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }

    requests.post(url, headers=headers, json=data)


# =========================
# 時間制御
# =========================
def is_quiet_time():
    hour = datetime.now().hour
    return hour >= 21 or hour < 7


# =========================
# 地震チェック
# =========================
def check_earthquake():
    global last_event_id

    try:
        res = requests.get(JMA_URL, timeout=10)
        data = res.json()

        if not isinstance(data, list):
            return

        for item in data:
            if item.get("ttl") != "震度速報":
                continue

            event_id = item.get("eid")
            if not event_id or event_id == last_event_id:
                return

            detail_url = f"https://www.jma.go.jp/bosai/quake/data/{item.get('json')}"
            detail_res = requests.get(detail_url, timeout=10)
            detail = detail_res.json()

            # 🔒 安全チェック
            body = detail.get("body")
            if not body:
                return

            intensity = body.get("intensity", {})
            observation = intensity.get("observation", {})
            prefs = observation.get("pref", [])

            for pref in prefs:
                if pref.get("name") != "鹿児島県":
                    continue

                max_int_raw = pref.get("maxInt")
                if not max_int_raw:
                    continue

                max_int = int(
                    max_int_raw.replace("震度", "").replace("+", "").replace("-", "")
                )

                if max_int >= 3 and not is_quiet_time():
                    earthquake_time = body.get("earthquake", {}).get("time", "不明")

                    text = (
                        f"【地震情報】\n"
                        f"鹿児島県で震度{max_int}を観測しました。\n"
                        f"発生時刻：{earthquake_time}\n"
                        f"大丈夫ですか？"
                    )

                    send_line_message(text)

            last_event_id = event_id
            return

    except Exception as e:
        print("地震チェックエラー:", e, flush=True)

# =========================
# Webhook受信
# =========================
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        data = request.json
        print("Webhook受信:", data, flush=True)

        events = data.get("events", [])

        for event in events:
            if event["type"] == "join":
                group_id = event["source"]["groupId"]
                save_group(group_id)

                send_line_message_to_group(
                    group_id,
                    "このグループを地震通知の配信先に登録しました。"
                )

        return "OK", 200

    return "Bot is running"


# =========================
# 起動処理
# =========================
if __name__ == "__main__":
    import threading

    def run_loop():
        while True:
            check_earthquake()
            time.sleep(60)

    thread = threading.Thread(target=run_loop)
    thread.start()

    app.run(host="0.0.0.0", port=10000)
