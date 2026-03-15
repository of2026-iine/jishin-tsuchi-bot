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

ADMIN_USER_ID = "U7655be872bdb66a953e83bff821e4be5"

JMA_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"

last_event_id = None


# ------------------------
# グループ保存
# ------------------------

def save_group(group_id):

    try:

        existing = (
            supabase
            .table("groups")
            .select("*")
            .eq("group_id", group_id)
            .execute()
        )

        if existing.data:
            return False

        supabase.table("groups").insert({
            "group_id": group_id
        }).execute()

        return True

    except Exception as e:

        print("登録エラー", e)

        return False


# ------------------------
# グループ削除
# ------------------------

def remove_group(group_id):

    try:

        supabase.table("groups").delete().eq("group_id", group_id).execute()

    except:
        pass


# ------------------------
# グループ一覧
# ------------------------

def load_groups():

    try:

        res = supabase.table("groups").select("*").execute()

        return [g["group_id"] for g in res.data]

    except:

        return []


# ------------------------
# LINE送信
# ------------------------

def send_line(group_id, text):

    url = "https://api.line.me/v2/bot/message/push"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    data = {
        "to": group_id,
        "messages":[{"type":"text","text":text}]
    }

    requests.post(url, headers=headers, json=data)


def send_all(text):

    groups = load_groups()

    for g in groups:

        send_line(g, text)


# ------------------------
# 管理者がいるか確認
# ------------------------

def check_admin_in_group(group_id):

    url = f"https://api.line.me/v2/bot/group/{group_id}/member/{ADMIN_USER_ID}"

    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    r = requests.get(url, headers=headers)

    return r.status_code == 200


# ------------------------
# 夜間通知停止
# ------------------------

def is_quiet_time():

    hour = datetime.now().hour

    return hour >= 21 or hour < 7


# ------------------------
# 地震チェック
# ------------------------

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

            eq = body.get("earthquake",{})

            time_text = eq.get("time","不明")

            hypo = eq.get("hypocenter",{})

            place = hypo.get("name","不明")

            magnitude = hypo.get("magnitude","不明")

            intensity = body.get("intensity",{})

            obs = intensity.get("observation",{})

            prefs = obs.get("pref",[])

            for pref in prefs:

                if pref.get("name") != "鹿児島県":
                    continue

                raw = pref.get("maxInt")

                level = int(raw.replace("震度","").replace("+","").replace("-",""))

                if level >= 3 and not is_quiet_time():

                    text = (
                        "【地震情報】\n"
                        f"鹿児島県で震度{level}を観測\n"
                        f"発生時刻：{time_text}\n\n"
                        f"震源地：{place}\n"
                        f"マグニチュード：M{magnitude}"
                    )

                    send_all(text)

            last_event_id = event_id

            return

    except Exception as e:

        print("地震エラー", e)


# ------------------------
# webhook
# ------------------------

@app.route("/", methods=["POST","GET"])
def home():

    if request.method == "POST":

        data = request.json

        events = data.get("events",[])

        for event in events:

            source = event.get("source",{})

            if source.get("type") != "group":
                continue

            group_id = source.get("groupId")

            # BOT追加
            if event["type"] == "join":

                if check_admin_in_group(group_id):

                    save_group(group_id)

                    send_line(
                        group_id,
                        "✅管理者を確認しました。\n"
                        "このグループを地震通知対象に登録しました。"
                    )

                else:

                    send_line(
                        group_id,
                        "⚠このBOTは管理者がいるグループでのみ使用できます。"
                    )

            if event["type"] == "leave":

                remove_group(group_id)

            if event["type"] == "message":

                text = event["message"].get("text","")

                if text == "/BOT test":

                    send_line(
                        group_id,
                        "【地震通知テスト】\n"
                        "鹿児島県で震度4を観測\n"
                        "発生時刻：テスト\n\n"
                        "震源地：鹿児島湾\n"
                        "マグニチュード：M5.0"
                    )

        return "OK"

    return "RUNNING"


# ------------------------
# 地震監視
# ------------------------

def earthquake_loop():

    while True:

        check_earthquake()

        time.sleep(60)


if __name__ == "__main__":

    import threading

    t = threading.Thread(target=earthquake_loop)

    t.daemon = True

    t.start()

    port = int(os.environ.get("PORT",10000))

    app.run(host="0.0.0.0", port=port)
