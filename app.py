import requests
import time
import os
from flask import Flask, request
from datetime import datetime

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_GROUP_ID = os.environ.get("LINE_GROUP_ID")

JMA_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"

last_event_id = None

def send_line_message(text):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    data = {
        "to": LINE_GROUP_ID,
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }
    requests.post(url, headers=headers, json=data)

def is_quiet_time():
    hour = datetime.now().hour
    return hour >= 21 or hour < 7

def check_earthquake():
    global last_event_id
    try:
        res = requests.get(JMA_URL)
        data = res.json()

        for item in data:
            if item["ttl"] == "震度速報":
                event_id = item["eid"]
                if event_id == last_event_id:
                    return

                detail_url = f"https://www.jma.go.jp/bosai/quake/data/{item['json']}"
                detail = requests.get(detail_url).json()

                areas = detail["body"]["intensity"]["observation"]["pref"]

                for pref in areas:
                    if pref["name"] == "鹿児島県":
                        max_int = int(pref["maxInt"].replace("震度", "").replace("+", "").replace("-", ""))
                        if max_int >= 3:
                            if not is_quiet_time():
                                text = (
                                    f"【地震情報】\n"
                                    f"鹿児島県で震度{max_int}を観測しました。\n"
                                    f"発生時刻：{detail['body']['earthquake']['time']}"
                                )
                                send_line_message(text)

                last_event_id = event_id
                return
    except:
        pass

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        data = request.json
        print("Webhook受信:", data, flush=True)

        send_line_message("✅ Bot接続テスト成功")

        return "OK", 200
    return "Bot is running"

if __name__ == "__main__":
    import threading

    def run_loop():
        while True:
            check_earthquake()
            time.sleep(60)

    thread = threading.Thread(target=run_loop)
    thread.start()

    app.run(host="0.0.0.0", port=10000)
