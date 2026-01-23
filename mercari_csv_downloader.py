import os
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError

# --- 設定 ---
# .envファイルのパス
ENV_PATH = r"C:\Users\progr\Desktop\Python\mercari_dorekai\.env"
# ブラウザのユーザーデータを保存するフォルダ（ログイン状態を維持するため）
USER_DATA_DIR = r"C:\Users\progr\Desktop\Python\mercari_dorekai\mercari_user_data"
# ダウンロードしたCSVを保存するフォルダ
DOWNLOAD_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\downloads"
# メルカリShops 商品ダウンロードページURL
TARGET_URL = "https://mercari-shops.com/seller/shops/qWxSdPm7yRZ56vy6jEx9mK/products/download"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def main():
    # .env読み込み（設定されていれば使用するが、今回は手動ログイン前提）
    load_dotenv(ENV_PATH)
    
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
        page.set_default_timeout(60000) # タイムアウト60秒

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

                # ログイン完了を待機（URLがターゲットURLに戻るか、特定の要素が表示されるまで）
                try:
                    # 5分間待機
                    page.wait_for_url(lambda url: "products/download" in url, timeout=300000)
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

            # 1. 販売状況の選択: 「販売中」のみにする
            log("⚙️ 販売状況を設定中: 「販売中」のみ選択します...")
            
            # 「販売中」をチェック (value="IN_STOCK")
            in_stock_cb = page.locator('input[value="IN_STOCK"]')
            if in_stock_cb.count() > 0 and not in_stock_cb.is_checked():
                # inputがhiddenの場合があるため、親のlabelをクリックするアプローチ
                page.locator('label:has(input[value="IN_STOCK"])').click()
                log("   ✅ 「販売中」をチェックしました。")
            
            # 「在庫切れ」のチェックを外す (value="OUT_OF_STOCK")
            out_of_stock_cb = page.locator('input[value="OUT_OF_STOCK"]')
            if out_of_stock_cb.count() > 0 and out_of_stock_cb.is_checked():
                page.locator('label:has(input[value="OUT_OF_STOCK"])').click()
                log("   ✅ 「在庫切れ」のチェックを外しました。")
            
            time.sleep(1)

            # 2. CSV生成ボタンをクリック
            generate_btn = page.locator('button:has-text("CSVファイルを作成"), button:has-text("作成")').first
            if generate_btn.is_visible():
                log("⬇️ 「CSVファイルを作成」ボタンをクリックします...")
                generate_btn.click()
                
                # 3. モーダルが表示されたら閉じる
                log("   モーダルの表示を待機中...")
                try:
                    # モーダル内の「閉じる」ボタンを探す
                    close_modal_btn = page.locator('section[role="dialog"] footer button:has-text("閉じる")').first
                    close_modal_btn.wait_for(state="visible", timeout=10000)
                    close_modal_btn.click()
                    log("   ✅ 生成開始モーダルを閉じました。")
                except TimeoutError:
                    log("   ⚠️ モーダルが表示されなかったか、閉じるボタンが見つかりませんでした。")
            
            # 4. 履歴からダウンロード (完了になるまで待機)
            log("⏳ 最新のCSVが「完了」になるのを待機してダウンロードします...")
            
            # 最大待機時間 (例: 10分)
            max_retries = 60
            for i in range(max_retries):
                # 履歴テーブルの1行目を取得
                first_row = page.locator('table tbody tr').first
                if first_row.count() == 0:
                    log("   ⚠️ 履歴が表示されていません。少し待ちます...")
                    time.sleep(5)
                    continue

                # ステータス列 (1列目) のテキスト
                status_text = first_row.locator('td').nth(0).inner_text().strip()
                log(f"   [{i+1}/{max_retries}] 現在のステータス: {status_text}")

                if "完了" in status_text:
                    # ダウンロードボタン (3列目あたり)
                    download_btn = first_row.locator('button:has-text("ダウンロード")')
                    
                    if download_btn.is_enabled():
                        log("   ✅ ダウンロードボタンが有効になりました。クリックします。")
                        
                        with page.expect_download(timeout=60000) as download_info:
                            download_btn.click()
                        
                        download = download_info.value
                        suggested_filename = download.suggested_filename
                        save_path = os.path.join(DOWNLOAD_DIR, suggested_filename)
                        
                        log(f"📥 ダウンロード中: {suggested_filename}")
                        download.save_as(save_path)
                        log(f"✅ 保存完了: {save_path}")
                        break
                    else:
                        log("   ⚠️ ステータスは完了ですが、ボタンがまだ無効です。")
                
                elif "エラー" in status_text or "失敗" in status_text:
                    log("❌ CSV作成が失敗ステータスになりました。")
                    break
                
                # 10秒待機して再確認 (自動更新される前提)
                time.sleep(10)
            else:
                log("❌ タイムアウト: 指定時間内に完了ステータスになりませんでした。")

        except Exception as e:
            log(f"❌ ダウンロード処理中にエラーが発生しました: {e}")

        log("👋 ブラウザを閉じます。")
        context.close()

if __name__ == "__main__":
    main()