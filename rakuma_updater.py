import os
import csv
import time
from playwright.sync_api import sync_playwright, TimeoutError

# --- 設定 ---
RAKUMA_LOGIN_URL = "https://fril.jp/login"
USER_DATA_DIR = "rakuma_user_data_firefox"
PRODUCTS_FILE = "products_rakuma.csv" # スクレイパーが生成したファイル
PROCESSED_LOG = "rakuma_processed_uids.txt" # 更新済みIDのログファイル

# --- ユーティリティ ---
def log(msg):
    """タイムスタンプ付きでログを出力する"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def load_processed_ids():
    """処理済みのIDをファイルから読み込む"""
    if not os.path.exists(PROCESSED_LOG):
        return set()
    with open(PROCESSED_LOG, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def save_processed_id(uid):
    """処理済みのIDをファイルに追記する"""
    with open(PROCESSED_LOG, "a", encoding="utf-8") as f:
        f.write(uid + "\n")

def get_product_id_from_url(url):
    """URLから商品IDを抽出する"""
    if not url or "item.fril.jp" not in url:
        return None
    return url.split('/')[-1].split('?')[0]

# --- メイン処理 ---
def update_shipping_method():
    # 1. 更新対象の商品URLをCSVから読み込む
    products_to_update = []
    try:
        with open(PRODUCTS_FILE, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # '削除'フラグが立っているものと、URLがないものは除外
                if row.get('削除') != '削除' and row.get('URL'):
                    products_to_update.append(row['URL'])
        log(f"📚 {len(products_to_update)} 件の商品を更新対象として読み込みました。")
    except FileNotFoundError:
        log(f"❌ エラー: {PRODUCTS_FILE} が見つかりません。先に dorekai_scraper.py を実行してください。")
        return
    except Exception as e:
        log(f"❌ {PRODUCTS_FILE} の読み込み中にエラーが発生しました: {e}")
        return

    if not products_to_update:
        log("✅ 更新対象の商品はありませんでした。")
        return

    processed_ids = load_processed_ids()
    log(f"✅ これまでに {len(processed_ids)} 件を処理済みです。")

    with sync_playwright() as p:
        try:
            context = p.firefox.launch_persistent_context(
                USER_DATA_DIR,
                headless=False, # Falseでブラウザの動きが見える
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
            )
        except Exception as e:
            log(f"❌ ブラウザの起動に失敗しました。多重起動していないか確認してください。: {e}")
            return
            
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(30000) # タイムアウトを30秒に設定

        # --- ログイン処理 ---
        log("ログイン状態を確認します...")
        # マイページなど、ログインが必要なページにアクセスしてみる
        page.goto("https://fril.jp/mypage", wait_until='domcontentloaded')
        
        if "login" in page.url:
            log("🔒 ログインが必要です。ブラウザでログインを完了してください。")
            try:
                # ログイン後、マイページにリダイレクトされるのを待つ
                page.wait_for_url("https://fril.jp/mypage", timeout=300000) # 5分間待つ
                log("🔓 ログインを検知しました。処理を再開します。")
            except TimeoutError:
                log("⚠️ ログインが時間内に完了しませんでした。終了します。")
                return
        else:
            log("✅ ログイン済みです。")

        # --- 商品ループ ---
        for i, product_url in enumerate(products_to_update):
            product_id = get_product_id_from_url(product_url)
            if not product_id:
                log(f"⚠️ 無効なURLです、スキップします: {product_url}")
                continue

            if product_id in processed_ids:
                log(f"⏩ スキップ: {product_id} (処理済み)")
                continue

            log(f"
🚀 {i+1}/{len(products_to_update)} 件目: {product_id} の処理を開始します。")
            
            edit_url = f"https://fril.jp/item/{product_id}/edit"
            
            try:
                page.goto(edit_url, wait_until='domcontentloaded')
                time.sleep(1) # ページ描画の安定化

                # ページが存在しない、または編集できない場合
                if "このページは存在しません" in page.content() or "リクエストされたページは存在しません" in page.content():
                    log(f"❌ 編集ページが存在しません、スキップします: {edit_url}")
                    save_processed_id(product_id) # 再試行しないように記録
                    continue

                # --- 配送方法を「かんたんラクマパック(日本郵便)」に設定 ---
                ship_text = "かんたんラクマパック(日本郵便)"
                log(f"🚚 配送方法を「{ship_text}」に設定します...")

                # 1. 配送方法のボタンをクリックしてモーダルを開く
                shipping_button = page.locator('div:has-text("配送方法") + div').locator('button')
                shipping_button.click()
                
                # 2. モーダルが表示されるのを待つ
                page.wait_for_selector('section[role="dialog"]', timeout=5000)
                log("    モーダルを開きました。")

                # 3. モーダル内で「かんたんラクマパック(日本郵便)」を選択
                # テキストが完全一致しない可能性を考慮し、'has-text' を使用
                option_selector = 'section[role="dialog"] div:has-text("日本郵便")'
                japan_post_option = page.locator(option_selector).first
                japan_post_option.click()
                log(f"    「{ship_text}」のオプションを選択しました。")

                # 4. 「決定」ボタンを押してモーダルを閉じる
                page.locator('section[role="dialog"] button:has-text("決定")').click()
                log("    「決定」ボタンをクリックしました。")

                # 5. メイン画面のボタンのテキストが更新されるのを待つ
                page.wait_for_function(
                    "(text) => document.querySelector('div:has-text(\"配送方法\") + div button').textContent.includes(text)",
                    "日本郵便",
                    timeout=5000
                )
                log(f"✅ 配送方法が「{ship_text}」に設定されました。")
                
                # --- 更新ボタンを押す ---
                log("💾 更新ボタンを探してクリックします...")
                update_button = page.locator('button:has-text("更新する")')
                update_button.scroll_into_view_if_needed()
                update_button.click()

                # 更新完了を待つ (マイページなどにリダイレクトされることを期待)
                page.wait_for_url("**/mypage/exhibit/sell", timeout=30000)
                log(f"✅ {product_id} の更新が完了しました。")
                
                save_processed_id(product_id) # 処理済みとして記録

            except TimeoutError as e:
                log(f"❌ タイムアウトエラーが発生しました: {product_id} - {e}")
                log("    ページの読み込みが遅いか、UIが変更された可能性があります。")
            except Exception as e:
                log(f"❌ 不明なエラーが発生しました: {product_id} - {e}")
                # エラー発生時も、次回からスキップするためにIDを保存するかどうかは要検討
                # save_processed_id(product_id) 

            time.sleep(2) # 次の商品へ行く前に少し待つ

        log("\n🎉 全商品の更新処理が完了しました！")
        input("Enterキーを押すとブラウザを閉じます...")
        context.close()

# --- 実行 ---
if __name__ == "__main__":
    update_shipping_method()
