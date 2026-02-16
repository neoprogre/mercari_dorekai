import os
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv

# .envファイルを読み込む
load_dotenv()

def send_slack_notification(message, status="success"):
    """Slackに通知を送信"""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    
    if not webhook_url:
        print("⚠️ SLACK_WEBHOOK_URLが設定されていません")
        return False
    
    # ステータスに応じて色を変更
    color = "#36a64f" if status == "success" else "#ff0000"
    icon = "✅" if status == "success" else "❌"
    
    timestamp = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
    
    payload = {
        "attachments": [
            {
                "color": color,
                "title": f"{icon} 自動実行バッチ - {status.upper()}",
                "text": message,
                "footer": "自動実行システム | mercari_dorekai",
                "ts": int(datetime.now().timestamp()),
                "mrkdwn_in": ["text"]
            }
        ]
    }
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"✅ Slack通知を送信しました: {timestamp}")
            return True
        else:
            print(f"❌ Slack通知の送信に失敗しました: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Slack通知でエラーが発生しました: {e}")
        return False

if __name__ == "__main__":
    # コマンドライン引数からメッセージとステータスを取得
    if len(sys.argv) > 1:
        message = sys.argv[1]
        status = sys.argv[2] if len(sys.argv) > 2 else "success"
        send_slack_notification(message, status)
    else:
        send_slack_notification("テスト通知", "success")
