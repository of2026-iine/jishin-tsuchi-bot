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

# 管理者（あなた）のLINEユーザーID
ADMIN_USER_ID = "U7655be872bdb66a953e83bff821e4be5"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
JMA_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"

# 重複チェック用に、過去に通知した詳細JSONファイル名のセットを保持（過去10件程度）
notified_files = set()

# =========================
# グループ保存
# =========================
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
        print("グループ登録:", group_id, flush=True)
        return True
    except Exception as e:
        print("グループ保存エラー:", e, flush=True)
        return False

# =========================
# グループ削除
# =========================
def remove_group(group_id):
    try:
        supabase.table("groups").delete().eq("group_id", group_id).execute()
        print("グループ削除:", group_id, flush=True)
    except Exception as e:
        print("グループ削除エラー:", e, flush=True)

# =========================
# グループ一覧取得
# =========================
def load_groups():
    try:
        response = (
            supabase
            .table("groups")
            .select("*")
            .execute()
        )
        groups = []
        for g in response.data:
            groups.append(g["group_id"])
        return groups
    except Exception as e:
        print("グループ取得失敗:", e, flush=True)
        return []

# =========================
# LINE送信
# =========================
def send_line(group_id, text):
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
    try:
        res = requests.post(url, headers=headers, json=data, timeout=10)
        if res.status_code != 200:
            print("LINE送信失敗:", res.status_code, res.text, flush=True)
    except Exception as e:
        print("LINE送信エラー:", e, flush=True)

# =========================
# 全グループ送信
# =========================
def send_all(text):
    groups = load_groups()
    for group_id in groups:
        try:
            # 管理者がいるか確認
            if not check_admin_in_group(group_id):
                print("管理者不在のため削除:", group_id, flush=True)
                remove_group(group_id)
                continue
            send_line(group_id, text)
        except Exception as e:
            print("送信処理エラー:", e, flush=True)

# =========================
# 管理者確認
# =========================
def check_admin_in_group(group_id):
    url = f"https://api.line.me/v2/bot/group/{group_id}/member/{ADMIN_USER_ID}"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print("管理者確認エラー:", e, flush=True)
        return False

# =========================
# 夜間通知停止
# =========================
def is_quiet_time():
    hour = datetime.now().hour
    return hour >= 21 or hour < 7

# =========================
# 地震チェック（改良版）
# =========================
def check_earthquake():
    global notified_files
    try:
        res = requests.get(JMA_URL, timeout=10)
        data = res.json()

        if not isinstance(data, list):
            return

        # 直近数件（最大5件）のイベントをスキャンする
        for item in data[:5]:
            ttl = item.get("ttl", "")
            # 「震度速報」または「震源・震度に関する情報」を対象にする
            if "震度" not in ttl:
                continue

            json_file = item.get("json")
            if not json_file:
                continue

            # すでに通知済みの詳細ファイルならスキップ（returnせずcontinueで次のアイテムへ）
            if json_file in notified_files:
                continue

            detail_url = f"https://www.jma.go.jp/bosai/quake/data/{json_file}"
            detail_res = requests.get(detail_url, timeout=10)
            detail = detail_res.json()

            body = detail.get("body", {})
            earthquake = body.get("earthquake", {})
            hypocenter = earthquake.get("hypocenter", {})
            
            earthquake_time = earthquake.get("time", "不明")
            place = hypocenter.get("name", "不明")
            magnitude = hypocenter.get("magnitude", "不明")

            intensity = body.get("intensity", {})
            observation = intensity.get("observation", {})
            prefs = observation.get("pref", [])

            for pref in prefs:
                if pref.get("name") != "鹿児島県":
                    continue

                max_int_raw = pref.get("maxInt")
                if not max_int_raw:
                    continue

                # 震度文字列から数値を抽出（例: "3", "5+", "5-" などに対応）
                level_str = max_int_raw.replace("震度", "").replace("+", "").replace("-", "")
                try:
                    level = int(level_str)
                except ValueError:
                    continue

                # 条件合致で通知
                if level >= 3 and not is_quiet_time():
                    text = (
                        "【地震情報】\n"
                        f"鹿児島県で震度{max_int_raw.replace('震度', '')}を観測\n"
                        f"発生時刻：{earthquake_time}\n\n"
                        f"震源地：{place}\n"
                        f"マグニチュード：M{magnitude}\n"
                        "大丈夫ですか？"
                    )
                    send_all(text)

            # 処理したファイルを通知済みセットに追加
            notified_files.add(json_file)
            # 保持する履歴が多すぎないよう過去20件に制限
            if len(notified_files) > 20:
                notified_files.pop()

    except Exception as e:
        print("地震チェックエラー:", e, flush=True)

# =========================
# Webhook
# =========================
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        data = request.json
        print("Webhook受信:", data, flush=True)
        events = data.get("events", [])

        for event in events:
            source = event.get("source", {})
            source_type = source.get("type")

            if source_type != "group":
                continue

            group_id = source.get("groupId")

            if event["type"] == "join":
                if not check_admin_in_group(group_id):
                    send_line(group_id, "⚠このBOTは管理者がいるグループでのみ使用できます。")
                    continue

                save_group(group_id)
                send_line(
                    group_id,
                    "✅管理者を確認しました。\n"
                    "このグループを地震通知対象に登録しました。\n\n"
                    "鹿児島県で震度3以上の地震を検知した場合に通知します。\n"
                    "※21時〜7時の間は通知を停止します。"
                )

            elif event["type"] == "leave":
                remove_group(group_id)

            elif event["type"] == "message":
                text = event["message"].get("text", "")
                user_id = source.get("userId")

                if text == "/BOT test":
                    if user_id != ADMIN_USER_ID:
                        continue

                    send_line(
                        group_id,
                        "【地震情報テスト通知】\n"
                        "鹿児島県で震度3を観測\n"
                        "発生時刻：2026-03-15 16:20\n\n"
                        "震源地：奄美大島近海\n"
                        "マグニチュード：M4.6"
                    )

        return "OK", 200
    return "Bot is running"

# =========================
# 地震監視ループ
# =========================
def earthquake_loop():
    while True:
        check_earthquake()
        time.sleep(60)

# =========================
# 起動
# =========================
if __name__ == "__main__":
    import threading
    thread = threading.Thread(target=earthquake_loop)
    thread.daemon = True
    thread.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
