import requests
import time
import os
from flask import Flask, request
from datetime import datetime
from supabase import create_client

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

JMA_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"

last_event_id = None


# =================
# グループ保存
# =================

def save_group(group_id, admin_id):

    existing = (
        supabase
        .table("groups")
        .select("*")
        .eq("group_id", group_id)
        .execute()
    )

    if not existing.data:

        supabase.table("groups").insert({
            "group_id": group_id,
            "admin_id": admin_id
        }).execute()

        print("グループ登録:", group_id)


# =================
# グループ削除
# =================

def remove_group(group_id):

    supabase.table("groups").delete().eq("group_id", group_id).execute()

    print("グループ削除:", group_id)


# =================
# グループ取得
# =================

def load_groups():

    response = supabase.table("groups").select("*").execute()

    return [g["group_id"] for g in response.data]


# =================
# LINE送信
# =================

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


# =================
# 夜間停止
# =================

def is_quiet_time():

    hour = datetime.now().hour

    return hour >= 21 or hour < 7


# =================
# 地震チェック
# =================

def check_earthquake():

    global last_event_id

    try:

        res = requests.get(JMA_URL)
        data = res.json()

        for item in data:

            if item.get("ttl") != "震度速報":
                continue

            event_id = item.get("eid")

            if event_id == last_event_id:
                return

            detail_url = f"https://www.jma.go.jp/bosai/quake/data/{item.get('json')}"
            detail = requests.get(detail_url).json()

            body = detail.get("body")

            earthquake = body.get("earthquake", {})

            earthquake_time = earthquake.get("time", "不明")
            hypocenter = earthquake.get("hypocenter", {})

            place = hypocenter.get("name", "不明")
            magnitude = hypocenter.get("magnitude", "不明")

            intensity = body.get("intensity", {})
            observation = intensity.get("observation", {})
            prefs = observation.get("pref", [])

            for pref in prefs:

                if pref.get("name") != "鹿児島県":
                    continue

                max_int_raw = pref.get("maxInt")

                max_int = int(
                    max_int_raw
                    .replace("震度", "")
                    .replace("+", "")
                    .replace("-", "")
                )

                if max_int >= 3 and not is_quiet_time():

                    text = (
                        "【地震情報】\n"
                        f"鹿児島県で震度{max_int}を観測\n"
                        f"発生時刻：{earthquake_time}\n\n"
                        f"震源地：{place}\n"
                        f"マグニチュード：M{magnitude}"
                    )

                    send_line_message(text)

            last_event_id = event_id
            return

    except Exception as e:

        print("地震チェックエラー:", e)


# =================
# webhook
# =================

@app.route("/", methods=["POST","GET"])
def home():

    if request.method == "POST":

        data = request.json

        events = data.get("events", [])

        for event in events:

            source = event.get("source", {})
            source_type = source.get("type")

            if source_type != "group":
                continue

            group_id = source.get("groupId")
            user_id = source.get("userId")

            if event["type"] == "message":

                message = event["message"].get("text","")

                # 管理者登録
                if message == "/BOT admin":

                    save_group(group_id, user_id)

                    send_line_message_to_group(
                        group_id,
                        "✅このグループを管理者として登録しました"
                    )

                # テスト通知
                if message == "/BOT test":

                    text = (
                        "【地震通知テスト】\n"
                        "鹿児島県で震度4を観測\n"
                        "発生時刻：テスト\n\n"
                        "震源地：鹿児島湾\n"
                        "マグニチュード：M5.0"
                    )

                    send_line_message_to_group(group_id, text)

            if event["type"] == "leave":

                remove_group(group_id)

        return "OK"

    return "BOT RUNNING"


# =================
# 地震ループ
# =================

def earthquake_loop():

    while True:

        check_earthquake()

        time.sleep(60)


if __name__ == "__main__":

    import threading

    thread = threading.Thread(target=earthquake_loop)
    thread.daemon = True
    thread.start()

    port = int(os.environ.get("PORT",10000))

    app.run(host="0.0.0.0", port=port)
