from dotenv import load_dotenv
load_dotenv()

import imaplib, email, requests, re, time, os
import email.header
import email.utils
from datetime import datetime, timezone, timedelta
import logging

# --- ログ設定 ---
LOG_FILE = "notify.log"  # ログファイルのパス
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# --- Configuration ---
IMAP_SERVER = "imap.gmail.com"
EMAIL_ACCOUNT = os.environ.get("GMAIL_USER")
PASSWORD = os.environ.get("GMAIL_PASS")
LINE_CHANNEL_TOKEN = os.environ.get("LINE_CHANNEL_TOKEN")
GROUP_ID = os.environ.get("GROUP_ID")
RAKUMA_PROCESSED_UIDS_FILE = "rakuma_processed_uids.txt"
MERCARI_PROCESSED_UIDS_FILE = "mercari_processed_uids.txt"

# --- Helper Functions for Processed UIDs ---

def load_processed_uids(filename: str) -> set[str]:
    """Loads processed email UIDs from a file into a set."""
    if not os.path.exists(filename):
        return set()
    with open(filename, 'r') as f:
        return {line.strip() for line in f}

def save_processed_uid(uid, filename):
    """Appends a processed email UID to the file."""    
    with open(filename, 'a') as f:
        f.write(str(uid) + '\n')

# --- LINE Notification ---
def log(msg: str):
    """タイムスタンプ付きでログを出力する"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")
    logging.info(msg)
    
def send_line_message(text):
    """Messaging APIを使用してLINEにプッシュメッセージを送信する"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}"
    }
    data = {"to": GROUP_ID, "messages": [{"type": "text", "text": text}]}
    try:
        # Messaging APIは 'json' パラメータで送信
        resp = requests.post(url, headers=headers, json=data, timeout=10)        
        log(f"LINE API Response: Status {resp.status_code}, Body: {resp.text}")
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        log(f"LINE API Request failed: {e}")
        return False
    return resp.status_code == 200

# --- Email Processing ---

def extract_order_info(body, order_no_pattern):
    """メール本文から注文情報を抽出する"""
    order_no, product, price = None, None, None
    m = re.search(order_no_pattern, body)
    if m: order_no = m.group(1)
    m = re.search(r"商品名\s*[:：]\s*(.+)", body)
    if m: product = m.group(1).strip()
    m = re.search(r"(?:商品価格|合計金額|金額|価格)\s*[:：]?\s*[¥￥]?\s*([\d,]+)", body)
    if m:
        price = m.group(1).replace(',', '') + "円"
    return order_no, product, price

def get_email_body(msg):
    """Extracts the text body from an email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", 'ignore')
    else:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", 'ignore')
    return body

def decode_subject(msg):
    """Correctly decodes an email subject."""
    subject = ""
    subject_header = email.header.decode_header(msg["subject"])
    for s, charset in subject_header:
        if isinstance(s, bytes):
            subject += s.decode(charset or "utf-8")
        else:
            subject += s
    return subject

# --- Main Logic ---

SITE_CONFIGS = [
    {
        "name": "ラクマ",
        "subject_keywords": ["ラクマ", ("注文", "決済完了")],
        "extractor": lambda body: extract_order_info(body, r"オーダーID\s*[:：]\s*(\d+)"),
        "processed_uids_file": RAKUMA_PROCESSED_UIDS_FILE,
    },
    {
        "name": "メルカリShops",
        "subject_keywords": ["メルカリShops", "発送をお願いします"],
        "extractor": lambda body: extract_order_info(body, r"注文番号\s*[:：]\s*([a-zA-Z0-9_]+)"),
        "processed_uids_file": MERCARI_PROCESSED_UIDS_FILE,
    },
]

def check_and_notify():
    # 各サイトの処理済みUIDを読み込む
    for config in SITE_CONFIGS:
        config["processed_uids_set"] = load_processed_uids(config["processed_uids_file"])

    notifications_to_send = []
    uids_to_mark_seen = []

    try:
        with imaplib.IMAP4_SSL(IMAP_SERVER) as M:
            M.login(EMAIL_ACCOUNT, PASSWORD)
            M.select("INBOX")
            
            search_criteria = '(UNSEEN)'
            typ, data = M.uid('search', None, search_criteria)            
            
            if typ != 'OK':
                log(f"Error searching emails: {data}")
                return

            uids = data[0].split()
            if not uids:
                return

            for uid_bytes in uids:
                uid = uid_bytes.decode()
                
                typ, msg_data = M.uid('fetch', uid_bytes, '(RFC822)')
                if typ != 'OK':
                    continue

                msg = email.message_from_bytes(msg_data[0][1])
                subject = decode_subject(msg)

                date_dt = email.utils.parsedate_to_datetime(msg['Date'])
                jst = timezone(timedelta(hours=9))
                date_dt_jst = date_dt.astimezone(jst)
                received_time_str = date_dt_jst.strftime('%Y-%m-%d %H:%M')

                for config in SITE_CONFIGS:
                    # 件名のキーワードをチェック
                    keywords = config["subject_keywords"]
                    # 最初の要素は必須、2番目以降はOR条件などを考慮
                    if not all(k in subject for k in keywords if isinstance(k, str)):
                        continue
                    # タプルはOR条件として扱う
                    if any(isinstance(k, tuple) and not any(sub_k in subject for sub_k in k) for k in keywords):
                        continue

                    # 処理済みかチェック
                    if uid in config["processed_uids_set"]:
                        log(f"Skipping UID {uid} for {config['name']} as it has already been processed.")
                        continue

                    # --- 通知処理 ---
                    log(f"Found new order from {config['name']} (UID: {uid})")

                    body = get_email_body(msg)
                    order_no, product, price = config["extractor"](body)                    

                    # 通知メッセージを作成
                    individual_message = f"{config['name']}注文通知"
                    individual_message += f"\n受信時刻: {received_time_str}"
                    if product: individual_message += f"\n商品名: {product}"                    
                    if price: individual_message += f"\n価格: {price}"
                    
                    notifications_to_send.append(individual_message)
                    uids_to_mark_seen.append(uid_bytes)
                    
                    # 処理済みとしてUIDをファイルに保存
                    save_processed_uid(uid, config["processed_uids_file"])

                    break # このメールは処理したので次のメールへ

            # --- ループ終了後、通知が1件以上あればまとめて送信 ---
            if notifications_to_send:
                count = len(notifications_to_send)
                header = f"新規注文{count}件\n"
                full_message = header + "\n" + "\n----------\n".join(notifications_to_send)
                
                if send_line_message(full_message):
                    log(f"LINEに{count}件の注文を通知しました。メールを既読にします。")
                    for uid_bytes in uids_to_mark_seen:
                        M.uid('store', uid_bytes, '+FLAGS', '(\Seen)')

    except imaplib.IMAP4.error as e:
        log(f"An IMAP error occurred: {e}")
    except requests.exceptions.RequestException as e:
        log(f"A network error occurred while sending to LINE: {e}")
    except Exception as e:
        log(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    # --- 環境変数のチェック ---
    required_env_vars = ["GMAIL_USER", "GMAIL_PASS", "LINE_CHANNEL_TOKEN", "GROUP_ID"]
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    if missing_vars:
        print(f"エラー: 必要な環境変数が設定されていません: {', '.join(missing_vars)}")
        print("スクリプトを実行する前に、.envファイルにこれらの変数を設定してください。")
        exit(1)

    print("========================================")
    print(f"メールチェックを開始します... ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print("========================================")

    check_and_notify()

    print("========================================")
    print("メールチェックが完了しました。")
    print("========================================")
    # このスクリプトをOSのタスクスケジューラ等で
    # 9時, 12時, 15時, 18時, 21時, 0時に実行してください。