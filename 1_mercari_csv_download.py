import os
import time
import datetime
import sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError
import requests

# --- 設定 ---
# .envファイルのパス
ENV_PATH = r"C:\Users\progr\Desktop\Python\mercari_dorekai\.env"
# ブラウザのユーザーデータを保存するフォルダ（ログイン状態を維持するため）
USER_DATA_DIR = r"C:\Users\progr\Desktop\Python\mercari_dorekai\mercari_user_data"
# ダウンロードしたCSVを保存するフォルダ
DOWNLOAD_DIR = r"C:\Users\progr\Desktop\Python\mercari_dorekai\downloads"
# メルカリShops 商品ダウンロードページURL
TARGET_URL = "https://mercari-shops.com/seller/shops/qWxSdPm7yRZ56vy6jEx9mK/products/download"
# Google Sheets URL
GOOGLE_SHEETS_ID = "1r9Mm3sGTpAvaYqbVJyi2hkjfVbRpnWchswzS8fIeFKk"
# 2つ目のGoogle Sheets URL（ブランド抽出など）
GOOGLE_SHEETS_ID_2 = "1rJ7qyc9HkKPGy0OclilliD5z0GSB-oU0HWGsOgQMdVY"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def send_slack_notification(message, status="info"):
    """Slack通知を送信する"""
    try:
        # 優先: .env に設定された webhook を使う
        webhook = os.environ.get("SLACK_WEBHOOK_URL")
        if webhook:
            try:
                resp = requests.post(webhook, json={"text": message}, headers={"Content-Type": "application/json"}, timeout=10)
                if 200 <= resp.status_code < 300:
                    return
                else:
                    log(f"⚠️ Slack webhook 送信失敗: HTTP {resp.status_code}")
            except Exception as e:
                log(f"⚠️ Slack webhook送信エラー: {e}")

        # フォールバック: 同梱のスクリプトを呼び出す（存在すれば）
        import subprocess
        python_path = sys.executable
        script_dir = os.path.dirname(os.path.abspath(__file__))
        slack_script = os.path.join(script_dir, "send_slack_notification.py")
        if os.path.exists(slack_script):
            subprocess.run([python_path, slack_script, message, status], check=False)
    except Exception as e:
        log(f"⚠️ Slack通知の送信に失敗: {e}")

def cleanup_latest_files(directory: str, prefix: str, suffix: str, keep: int = 5, date_format: str = "%Y-%m-%d") -> None:
    """指定プレフィックス/サフィックスのファイルを最新keep件だけ残して削除する"""
    try:
        files = []
        for name in os.listdir(directory):
            if not name.startswith(prefix) or not name.endswith(suffix):
                continue
            full_path = os.path.join(directory, name)
            date_part = name[len(prefix):-len(suffix)]
            parsed_date = None
            try:
                parsed_date = datetime.datetime.strptime(date_part, date_format)
            except Exception:
                parsed_date = datetime.datetime.fromtimestamp(os.path.getmtime(full_path))
            files.append((parsed_date, full_path))

        if len(files) <= keep:
            return

        files.sort(key=lambda x: x[0], reverse=True)
        for _, path in files[keep:]:
            try:
                os.remove(path)
                log(f"🗑️ 古いファイル削除: {path}")
            except Exception as e:
                log(f"⚠️ ファイル削除失敗: {path} ({e})")
    except Exception as e:
        log(f"⚠️ クリーンアップ失敗: {e}")

def download_google_sheet(sheet_id, download_dir, format_type="csv", custom_filename=None):
    """Google Sheets をダウンロード（ローカルに一時保存してからネットワークパスに移動）"""
    if format_type == "csv":
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        filename = custom_filename if custom_filename else "google_sheet.csv"
    elif format_type == "xlsx":
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
        filename = custom_filename if custom_filename else "google_sheet.xlsx"
    else:
        log(f"❌ 不正な形式: {format_type}")
        return False
    
    try:
        log(f"📥 Google Sheets をダウンロード中 ({format_type})...")
        response = requests.get(url, timeout=30)
        
        if response.status_code == 200:
            # 直接保存（ローカルダウンロード先）
            save_path = os.path.join(download_dir, filename)
            os.makedirs(download_dir, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(response.content)
            log(f"✅ Google Sheets をダウンロードしました: {save_path} ({len(response.content)} bytes)")
            return True
        else:
            log(f"❌ ダウンロード失敗: HTTP {response.status_code}")
            return False
    except Exception as e:
        log(f"❌ Google Sheets ダウンロードエラー: {e}")
        return False

def download_google_sheet_with_browser(page, sheet_id, download_dir, filename="brand_extraction.xlsx"):
    """Playwrightを使ってGoogle Sheetsをダウンロード（認証が必要なファイル用）"""
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
        log(f"📥 ブラウザセッションでGoogle Sheetsをダウンロード中...")
        
        # ブラウザのクッキーを取得してrequestsで使用
        cookies = page.context.cookies()
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain'))
        
        response = session.get(url, timeout=60)
        if response.status_code == 200:
            save_path = os.path.join(download_dir, filename)
            os.makedirs(download_dir, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(response.content)
            log(f"✅ ダウンロード完了: {save_path} ({len(response.content)} bytes)")
            return True
        else:
            raise Exception(f"HTTP {response.status_code}")
    except Exception as e:
        log(f"❌ ダウンロード失敗: {e}")
        return False

def main():
    success = True
    error_messages = []
    
    # .env読み込み（設定されていれば使用するが、今回は手動ログイン前提）
    load_dotenv(ENV_PATH)
    # 商品登録日時フィルタ（オプション）
    # 環境変数: MERCARI_START_DATETIME, MERCARI_END_DATETIME
    # サポートされる書式例: "2025/10/01 00:00" または "2025-10-01T00:00"
    mercari_start = os.environ.get("MERCARI_START_DATETIME")
    # 終了日時は省略可能にする（未指定の場合は2回目の終了を未設定にして最新まで）
    mercari_end = os.environ.get("MERCARI_END_DATETIME")

    def to_datetime_local(s: str):
        if not s:
            return None
        fmts = ("%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y/%m/%dT%H:%M")
        for f in fmts:
            try:
                d = datetime.datetime.strptime(s, f)
                return d.strftime("%Y-%m-%dT%H:%M")
            except Exception:
                continue
        try:
            d = datetime.datetime.fromisoformat(s)
            return d.strftime("%Y-%m-%dT%H:%M")
        except Exception:
            log(f"⚠️ 日時の解析に失敗しました: {s}")
            return None
    
    # フォルダ作成
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        log(f"📁 ダウンロードフォルダを作成しました: {DOWNLOAD_DIR}")

    log("🚀 ブラウザを起動しています...")
    
    with sync_playwright() as p:
        # Persistent Contextを使用してログイン状態を保持する
        # headless=False にしてブラウザを表示
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            accept_downloads=True,
            channel="chrome", # Chromeブラウザを使用
            args=["--disable-blink-features=AutomationControlled"] # 自動化検知を回避する試み
        )
        
        page = context.pages[0]
        page.set_default_timeout(120000) # タイムアウト120秒

        def perform_download_range(start_val, end_val, label):
            """start_val/end_val are strings like 'YYYY-MM-DDTHH:MM' or None. Returns saved_path or None."""
            # set date filters
            if start_val or end_val:
                try:
                    from_input = page.locator('input[name="period.from"]')
                    to_input = page.locator('input[name="period.to"]')
                    if start_val and from_input.count() > 0:
                        try:
                            from_input.first.fill(start_val)
                        except Exception:
                            page.evaluate('(el, val) => el.value = val', from_input.first, start_val)
                    if end_val and to_input.count() > 0:
                        try:
                            to_input.first.fill(end_val)
                        except Exception:
                            page.evaluate('(el, val) => el.value = val', to_input.first, end_val)
                    time.sleep(1)
                except Exception as e:
                    log(f"⚠️ 日時フィルタ設定に失敗しました: {e}")

            # click generate
            generate_btn = page.locator('button:has-text("CSVファイルを作成"), button:has-text("作成")').first
            if generate_btn.is_visible():
                log(f"⬇️ ({label}) 「CSVファイルを作成」ボタンをクリックします...")
                generate_btn.click()
                # close modal if appears
                try:
                    close_modal_btn = page.locator('section[role="dialog"] footer button:has-text("閉じる")').first
                    close_modal_btn.wait_for(state="visible", timeout=10000)
                    close_modal_btn.click()
                except TimeoutError:
                    pass

            # フォーム検証エラー（例: 終了日は開始日以降を選択してください）を検出して中止
            try:
                time.sleep(0.5)
                validation = page.locator('text=終了日は開始日以降を選択してください')
                if validation.count() > 0 and validation.is_visible():
                    log(f"⚠️ ({label}) 日時バリデーションエラーが発生しました。範囲を確認してください。")
                    return None
            except Exception:
                pass

            # wait for job to appear as processing then complete
            for i in range(6):
                rows = page.locator('table tbody tr')
                if rows.count() == 0:
                    time.sleep(5)
                    continue
                top_row = rows.first
                status_text = top_row.locator('td').nth(0).inner_text().strip()
                if "完了" not in status_text:
                    break
                time.sleep(5)

            max_retries = 60
            for i in range(max_retries):
                rows = page.locator('table tbody tr')
                if rows.count() == 0:
                    time.sleep(5)
                    continue
                top_row = rows.first
                status_text = top_row.locator('td').nth(0).inner_text().strip()
                log(f"   [{label} {i+1}/{max_retries}] ステータス: {status_text}")
                if "完了" in status_text:
                    download_btn = top_row.locator('button:has-text("ダウンロード")')
                    if download_btn.is_enabled():
                        with page.expect_download(timeout=120000) as download_info:
                            download_btn.click()
                        download = download_info.value
                        suggested = download.suggested_filename
                        # label -> part1/part2 -> index 1/2
                        idx = 1 if "part1" in label else 2
                        base, ext = os.path.splitext(suggested)
                        # 期待される suggested: product_data_YYYY-MM-DD.csv
                        save_name = f"{base}-{idx}{ext}"
                        save_path = os.path.join(DOWNLOAD_DIR, save_name)
                        download.save_as(save_path)
                        log(f"✅ ({label}) 保存完了: {save_path}")
                        cleanup_latest_files(DOWNLOAD_DIR, "product_data_", ".csv", keep=5)
                        return save_path
                elif "エラー" in status_text or "失敗" in status_text:
                    log(f"❌ ({label}) CSV作成が失敗ステータスになりました。")
                    return None
                time.sleep(10)
            log(f"❌ ({label}) タイムアウト: 指定時間内に完了になりませんでした。")
            return None

        def download_latest_completed(label):
            """履歴テーブルから最新の完了ジョブをダウンロードして保存パスを返す"""
            try:
                rows = page.locator('table tbody tr')
                if rows.count() == 0:
                    log(f"⚠️ ({label}) 履歴にジョブが見つかりませんでした。")
                    return None

                # 先頭から「完了」かつダウンロード可能なボタンを探す
                for i in range(rows.count()):
                    row = rows.nth(i)
                    status_text = row.locator('td').nth(0).inner_text().strip()
                    if "完了" in status_text:
                        download_btn = row.locator('button:has-text("ダウンロード")')
                        if download_btn.count() > 0 and download_btn.is_enabled():
                            log(f"⬇️ ({label}) 履歴の完了ジョブをダウンロードします（行 {i+1}）...")
                            with page.expect_download(timeout=120000) as download_info:
                                download_btn.click()
                            download = download_info.value
                            suggested = download.suggested_filename
                            idx = 1 if "part1" in label else 2
                            base, ext = os.path.splitext(suggested)
                            save_name = f"{base}-{idx}{ext}"
                            save_path = os.path.join(DOWNLOAD_DIR, save_name)
                            download.save_as(save_path)
                            log(f"✅ ({label}) 履歴ダウンロード保存完了: {save_path}")
                            return save_path
                log(f"⚠️ ({label}) 履歴にダウンロード可能な完了ジョブが見つかりませんでした。")
                return None
            except Exception as e:
                log(f"⚠️ ({label}) 履歴ダウンロードに失敗しました: {e}")
                return None

        log(f"📄 ページに移動します: {TARGET_URL}")
        try:
            page.goto(TARGET_URL)
        except Exception as e:
            log(f"⚠️ ページ移動中にエラーが発生しましたが続行します: {e}")

        # --- ログインフロー (詳細対応) ---
        
        # 0. 既にログイン済みかチェック (ログイン履歴利用)
        is_logged_in = False
        try:
            # ダウンロード画面固有の要素（販売状況チェックボックスなど）が表示されるか確認
            # タイムアウトを短めに設定して、ログイン済みなら即座に検知
            page.wait_for_selector('input[value="IN_STOCK"]', state="visible", timeout=5000)
            is_logged_in = True
            log("✅ ログイン履歴により自動ログインしました。")
        except TimeoutError:
            log("ℹ️ ログインセッションが見つからないか、期限切れです。ログイン処理を実行します。")

        if not is_logged_in:
            # 1. ショップ管理画面での「メルカリアカウントでログイン」ボタン
            try:
                login_shops_btn = page.locator('button[data-testid="login-with-mercari-account"]')
                # 自動ログインできていない場合、ボタンが表示されるのを少し待つ
                try:
                    login_shops_btn.wait_for(state="visible", timeout=5000)
                except TimeoutError:
                    pass

                if login_shops_btn.is_visible():
                    log("🔒 「メルカリアカウントでログイン」ボタンをクリックします。")
                    login_shops_btn.click()
                    page.wait_for_load_state("domcontentloaded")
                    time.sleep(2)
            except Exception:
                pass

            # 2. 新規登録/ログイン選択画面 (signup URL)
            if "signup" in page.url:
                try:
                    # 「アカウントをお持ちの方」エリアの「ログイン」リンク
                    login_link = page.locator('a[href*="/signin"]').first
                    if login_link.is_visible():
                        log("🔒 新規登録画面を検知。「ログイン」リンクをクリックします。")
                        login_link.click()
                        page.wait_for_load_state("domcontentloaded")
                        time.sleep(2)
                except Exception:
                    pass

            # 3. ログイン画面 (signin URL)
            if "login" in page.url or "signin" in page.url or page.locator('input[name="emailOrPhone"]').count() > 0:
                log("🔒 ログイン画面を検知しました。")
                
                # .envから認証情報を取得
                mercari_email = os.environ.get("MERCARI_EMAIL")
                mercari_password = os.environ.get("MERCARI_PASSWORD")

                if mercari_email:
                    log("🔑 .envの認証情報を使って自動入力を試みます...")
                    try:
                        # メールアドレス/電話番号入力
                        email_input = page.locator('input[name="emailOrPhone"]').first
                        # フォールバック
                        if not email_input.is_visible():
                            email_input = page.locator('input[name="email"], input[type="email"]').first
                        
                        if email_input.is_visible():
                            # 入力
                            email_input.fill(mercari_email)
                            log(f"   メールアドレスを入力しました: {mercari_email}")
                            
                            # 「次へ」ボタン
                            next_btn = page.locator('button[data-testid="submit"]').first
                            if next_btn.is_visible():
                                next_btn.click()
                                log("   「次へ」ボタンをクリックしました。")
                                time.sleep(2) # 遷移待ち

                        # パスワード入力 (画面遷移後)
                        pass_input = page.locator('input[name="password"], input[type="password"]').first
                        if pass_input.is_visible() and mercari_password:
                            pass_input.fill(mercari_password)
                            log("   パスワードを入力しました。")
                            
                            # ログインボタン
                            submit_btn = page.locator('button[data-testid="submit"]').first
                            if submit_btn.is_visible():
                                submit_btn.click()
                                log("   ログインボタンをクリックしました。")
                    except Exception as e:
                        log(f"⚠️ 自動入力中にエラーが発生しました: {e}")

                log("👉 ログインを完了してください (SMS認証などが必要な場合があります)。")
                log("=" * 70)
                log("📱 Google認証 / SMS認証 / その他の認証が表示される場合があります")
                log("   認証を完了するまで、このウィンドウは閉じないでください")
                log("=" * 70)

                # ログイン完了を待機（URLがターゲットURLに戻るか、特定の要素が表示されるまで）
                try:
                    # 10分間待機（Google認証など時間がかかる場合に対応）
                    page.wait_for_url(lambda url: "products/download" in url, timeout=600000)
                    log("✅ ログイン完了を検知しました。")
                except TimeoutError:
                    log("❌ ログインがタイムアウトしました。スクリプトを終了します。")
                    context.close()
                    return

        # --- ダウンロード処理 ---
        log("⬇️ CSVダウンロードの準備をしています...")
        
        try:
            # ページが完全に読み込まれるのを待つ
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # 実行フロー: 2回まで日時を分けてダウンロード
            first_end = "2025/10/30 23:59"
            second_start = "2025/10/31 00:00"
            # 既存のenvで上書き可能（先に設定したto_datetime_localで変換）
            first_start_val = to_datetime_local(mercari_start)
            first_end_val = to_datetime_local(os.environ.get("FIRST_END_DATETIME", first_end))
            second_start_val = to_datetime_local(os.environ.get("SECOND_START_DATETIME", second_start))
            second_end_val = to_datetime_local(mercari_end)

            # 1回目実行
            p1 = perform_download_range(first_start_val, first_end_val, "part1")
            # 生成に失敗（例: 日時バリデーション）していれば履歴からダウンロードを試みる
            if not p1:
                log("⚠️ part1 の新規生成に失敗またはスキップされたため、履歴から最新の完了ファイルを取得します。")
                p1 = download_latest_completed("part1")
            rows_p1 = 0
            if p1 and os.path.exists(p1):
                try:
                    import csv
                    with open(p1, newline='', encoding='cp932', errors='replace') as cf:
                        reader = csv.reader(cf)
                        # headerを読み飛ばして正確にレコード数を数える
                        try:
                            next(reader)
                        except StopIteration:
                            rows_p1 = 0
                        else:
                            rows_p1 = sum(1 for _ in reader)
                except Exception:
                    log("⚠️ CSV行数のカウントに失敗しました（CSVパース）")

            log(f"📊 part1 行数: {rows_p1}")

            if rows_p1 > 1000:
                send_slack_notification(f"⚠️ part1 の結果が1000件を超えました: {rows_p1}", "warning")
            else:
                # 1回目が1000件以内なら2回目を実行（日時順を検証）
                p2 = None
                rows_p2 = 0
                # second_start_val / second_end_val は 'YYYY-MM-DDTHH:MM' 形式か None
                if second_start_val and second_end_val:
                    try:
                        s_dt = datetime.datetime.fromisoformat(second_start_val)
                        e_dt = datetime.datetime.fromisoformat(second_end_val)
                        if e_dt < s_dt:
                            log("⚠️ 2回目の日時範囲が無効（終了 < 開始）です。2回目をスキップします。")
                            send_slack_notification("⚠️ 2回目の日時範囲が無効（終了 < 開始）のためスキップしました", "warning")
                        else:
                            p2 = perform_download_range(second_start_val, second_end_val, "part2")
                    except Exception:
                        # 比較に失敗した場合は実行してみる
                        p2 = perform_download_range(second_start_val, second_end_val, "part2")
                else:
                    # 終了日時が未設定の場合は第二期間を実行（最新まで）
                    if second_start_val:
                        p2 = perform_download_range(second_start_val, second_end_val, "part2")

                if p2 is None:
                    # 画面上のバリデーションが残っている可能性があるため、一度リロードして再試行
                    try:
                        log("ℹ️ part2 を再試行します: ページをリロードしてから再度生成を試みます...")
                        page.reload()
                        page.wait_for_load_state("networkidle")
                        time.sleep(1)
                        p2 = perform_download_range(second_start_val, second_end_val, "part2")
                    except Exception as e:
                        log(f"⚠️ part2 の再試行でエラー: {e}")

                if p2 is None:
                    log("⚠️ part2 の新規生成に失敗またはスキップされたため、履歴から最新の完了ファイルを取得します。")
                    p2 = download_latest_completed("part2")

                if p2 and os.path.exists(p2):
                    try:
                        import csv
                        with open(p2, newline='', encoding='cp932', errors='replace') as cf:
                            reader = csv.reader(cf)
                            try:
                                next(reader)
                            except StopIteration:
                                rows_p2 = 0
                            else:
                                rows_p2 = sum(1 for _ in reader)
                    except Exception:
                        log("⚠️ CSV行数のカウントに失敗しました（CSVパース）")
                log(f"📊 part2 行数: {rows_p2}")
                if rows_p2 > 1000:
                    send_slack_notification(f"⚠️ part2 の結果が1000件を超えました: {rows_p2}", "warning")
                else:
                    # part2 が1000件以内なら part1 のレコードを part2 に追記する（重複防止）
                    try:
                        if p1 and p2 and os.path.abspath(p1) != os.path.abspath(p2):
                            log("ℹ️ part2 が1000件以内なので part1 を part2 に追記します...")
                            import csv
                            # 読み取り：part1（cp932）
                            with open(p1, newline='', encoding='cp932', errors='replace') as f1:
                                reader = csv.reader(f1)
                                try:
                                    header = next(reader)
                                except StopIteration:
                                    rows_from_p1 = 0
                                else:
                                    rows_from_p1 = 0
                                    # 追記モードで part2 に書き込む
                                    with open(p2, 'a', newline='', encoding='cp932', errors='replace') as f2:
                                        writer = csv.writer(f2)
                                        for r in reader:
                                            writer.writerow(r)
                                            rows_from_p1 += 1
                            rows_p2 += rows_from_p1
                            log(f"✅ part1 の {rows_from_p1} 件を part2 に追記しました。結合後の part2 行数: {rows_p2}")
                        else:
                            log("ℹ️ part1 と part2 が同一ファイルのため追記をスキップしました。")
                    except Exception as e:
                        log(f"⚠️ part1 を part2 に追記中にエラーが発生しました: {e}")

        except Exception as e:
            log(f"❌ ダウンロード処理中にエラーが発生しました: {e}")
            error_messages.append(f"メルカリCSVダウンロードエラー: {e}")
            success = False

        # --- Google Sheets ダウンロード処理（ブラウザを閉じる前に実行） ---
        log("\n📊 Google Sheets をダウンロード開始します...")
        
        # 1つ目のGoogle Sheets（公開ファイル）
        today_str = time.strftime('%Y-%m-%d')
        dorekai_filename = f"dorekai_sheet_{today_str}.xlsx"
        if not download_google_sheet(GOOGLE_SHEETS_ID, DOWNLOAD_DIR, format_type="xlsx", custom_filename=dorekai_filename):
            error_messages.append("1つ目のGoogle Sheetsダウンロード失敗")
        # dorekai_sheet_*.xlsx を最新5件までに整理
        cleanup_latest_files(DOWNLOAD_DIR, "dorekai_sheet_", ".xlsx", keep=5)
        
        # 2つ目のGoogle Sheets（制限付きファイル - ブラウザセッションで取得）
        log("\n📊 2つ目のGoogle Sheets をダウンロード開始します...")
        try:
            if not download_google_sheet_with_browser(page, GOOGLE_SHEETS_ID_2, DOWNLOAD_DIR, "brand_extraction.xlsx"):
                log("⚠️ 2つ目のGoogle Sheetsダウンロードに失敗しましたが、処理を続行します。")
                error_messages.append("2つ目のGoogle Sheetsダウンロード失敗（スキップ）")
        except Exception as e:
            log(f"⚠️ 2つ目のGoogle Sheetsダウンロードでエラーが発生しましたが、処理を続行します: {e}")
            error_messages.append(f"2つ目のGoogle Sheetsエラー（スキップ）: {e}")

        log("👋 ブラウザを閉じます。")
        context.close()
    
    # Slack通知
    if success and not error_messages:
        send_slack_notification("✅ メルカリCSVダウンロードが正常に完了しました", "success")
    elif error_messages:
        error_summary = "\n".join(error_messages)
        send_slack_notification(f"⚠️ メルカリCSVダウンロード完了（一部エラー）:\n{error_summary}", "warning")
    else:
        send_slack_notification("❌ メルカリCSVダウンロードに失敗しました", "error")
    
    # 常に正常終了（exitcode 0）を返す
    sys.exit(0)

if __name__ == "__main__":
    main()