import os
import time
from pathlib import Path
from dotenv import load_dotenv
import json
import webbrowser
import requests
from urllib.parse import urlencode

# --- 設定 ---
# .envファイルのパス
ENV_PATH = r"C:\Users\progr\Desktop\Python\mercari_dorekai\.env"
# ダウンロードしたファイルを保存するフォルダ
DOWNLOAD_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\downloads"
# トークン保存先
TOKEN_FILE = "google_drive_token.json"
# Google Drive API スコープ
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def get_drive_service():
    """Google Drive API サービスを取得"""
    creds = None
    
    # トークンファイルがあればそれを読み込む
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    # 認証がない場合はブラウザで認証
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log("🔄 トークンを更新中...")
            creds.refresh(Request())
        else:
            log("📱 ブラウザでGoogle認証を行ってください...")
            flow = InstalledAppFlow.from_client_secrets_file(
                "client_secrets.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        # トークンを保存
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
    
    return googleapiclient.discovery.build("drive", "v3", credentials=creds)

def upload_to_google_drive(file_path, parent_folder_id=None):
    """Google Drive にファイルをアップロード（requests使用）"""
    try:
        log(f"📤 Google Drive にアップロード中...")
        
        if not os.path.exists(file_path):
            log(f"❌ ファイルが見つかりません: {file_path}")
            return False
        
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        log(f"📤 Google Drive にアップロード中: {filename} ({file_size} bytes)")
        
        # ⚠️ 注意: 初回実行時は.envにGOOGLE_DRIVE_ACCESS_TOKENが必要です
        access_token = os.environ.get("GOOGLE_DRIVE_ACCESS_TOKEN")
        
        if not access_token:
            log("❌ .envファイルにGOOGLE_DRIVE_ACCESS_TOKENを設定してください。")
            log("   以下の手順でトークンを取得してください:")
            log("   1. https://developers.google.com/oauthplayground にアクセス")
            log("   2. Google Drive API v3 スコープを選択")
            log("   3. 「Authorize APIs」をクリック")
            log("   4. 「Exchange authorization code for tokens」をクリック")
            log("   5. 表示されたaccess_tokenをコピーして.envに追加")
            return False
        
        # メタデータ
        metadata = {"name": filename}
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]
        
        # ファイルアップロード
        files = {
            "data": ("metadata", json.dumps(metadata), "application/json"),
            "file": open(file_path, "rb")
        }
        
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            headers=headers,
            files=files
        )
        
        if response.status_code == 200:
            file_id = response.json().get("id")
            log(f"✅ Google Drive にアップロード完了")
            log(f"   ファイルID: {file_id}")
            if parent_folder_id:
                log(f"   フォルダID: {parent_folder_id}")
            return True
        else:
            log(f"❌ アップロード失敗: HTTP {response.status_code}")
            log(f"   エラー: {response.text}")
            return False
            
    except Exception as e:
        log(f"❌ Google Drive アップロードエラー: {e}")
        return False

def main():
    load_dotenv(ENV_PATH)
    
    # アップロード対象のファイル
    files_to_upload = [
        "google_sheet.xlsx"
    ]
    
    # アップロード先フォルダID（.envから取得、なければルートにアップロード）
    parent_folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    
    if parent_folder_id:
        log(f"📁 アップロード先フォルダ: {parent_folder_id}")
    else:
        log(f"📁 アップロード先: Google Drive ルートフォルダ")
    
    log(f"\n☁️ Google Drive へのアップロードを開始します...\n")
    
    success_count = 0
    for filename in files_to_upload:
        file_path = os.path.join(DOWNLOAD_DIR, filename)
        if os.path.exists(file_path):
            if upload_to_google_drive(file_path, parent_folder_id):
                success_count += 1
            time.sleep(1)
        else:
            log(f"⚠️ スキップ: {filename} (ファイルが見つかりません)")
    
    log(f"\n✅ アップロード完了: {success_count}/{len(files_to_upload)} ファイル")

if __name__ == "__main__":
    main()
