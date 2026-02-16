import os
import glob
import shutil

# ==============================================================================
#
#   目的: 既存の商品情報を更新する
#
# ==============================================================================
import csv
import time
import random
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError
import re

# --- 設定 ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images"
RAKUMA_LOGIN_URL = "https://fril.jp/login"
USER_DATA_DIR = os.path.join(SCRIPT_DIR, "rakuma_user_data_firefox")
PRODUCTS_FILE = os.path.join(SCRIPT_DIR, "products_rakuma.csv") # スクレイパーが生成したファイル
PROCESSED_LOG = os.path.join(SCRIPT_DIR, "rakuma_update_processed_ids.txt") # このスクリプト専用の処理済みログ

# キャッシュディレクトリを削除
cache_dir = os.path.join(USER_DATA_DIR, "cache2")
if os.path.exists(cache_dir):
    try:
        shutil.rmtree(cache_dir)
        print(f"🗑️ キャッシュを削除: {cache_dir}")
    except Exception as e:
        print(f"⚠️ キャッシュ削除エラー: {e}")

# 実行オプション: Trueにすると最初からやり直す
#RESTART_FROM_START = False
RESTART_FROM_START = True

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

def extract_product_number(name):
    """商品名から品番（先頭の3-5桁の数字）を抽出する"""
    if not isinstance(name, str):
        return None
    match = re.match(r'^(\d{3,5})\s', name)
    return match.group(1) if match else None

def get_latest_product_data_csv(path):
    """最新の product_data_*.csv ファイルを取得する"""
    search_pattern = os.path.join(path, 'product_data_*.csv')
    files = glob.glob(search_pattern)
    return max(files, key=os.path.getmtime) if files else None

def load_descriptions_from_master():
    """マスターCSVから品番と商品説明のマップを作成する"""
    descriptions = {}
    master_csv_path = get_latest_product_data_csv(os.path.join(SCRIPT_DIR, "downloads"))
    if not master_csv_path:
        log("⚠️ マスターデータ(product_data_*.csv)が見つかりません。商品説明は更新されません。")
        return descriptions
    
    # '品番'列が存在しないため、'商品名'と'商品説明'を読み込んでから'品番'を生成する
    df = pd.read_csv(master_csv_path, encoding='cp932', usecols=['商品名', '商品説明'])
    
    # dorekai_scraper.py と同じロジックで品番を生成
    df['品番'] = df['商品名'].apply(extract_product_number)

    df.dropna(subset=['品番'], inplace=True)
    return df.set_index('品番')['商品説明'].to_dict()

def get_product_id_from_url(url):
    """URLから商品IDを抽出する"""
    if not url or "item.fril.jp" not in url:
        return None
    return url.split('/')[-1].split('?')[0]

def load_brand_map(path):
    """ブランドマスターから品番→ブランド名のマップを作成する"""
    m = {}
    try:
        with open(path, "r", encoding="cp932", errors="replace") as f:
            r = csv.reader(f)
            for row in r:
                if len(row) >= 2:
                    bid = row[0].strip()
                    name = row[1].strip() or (row[-1].strip() if row[-1:] else "")
                    if bid:
                        m[bid] = name
    except Exception as e:
        log(f"⚠️ ブランドマスタの読み込みに失敗しました: {path} - {e}")
    return m

def safe_click(locator, timeout=10000):
    """安全なクリック操作（フォールバック機能付き）"""
    try:
        locator.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    try:
        locator.click(timeout=timeout)
        return True
    except Exception as e:
        log(f"⚠️ direct click 失敗、evaluate フォールバック試行: {e}")
        try:
            locator.evaluate("el => el.click()")
            return True
        except Exception as e2:
            log(f"⚠️ evaluate click も失敗: {e2}")
            return False

def set_shipping_method(page):
    """配送方法を「かんたんラクマパック(日本郵便)」に固定設定する"""
    try:
        ship_text = "かんたんラクマパック(日本郵便)"
        log(f"🚚 配送方法を「{ship_text}」に設定します...")
        
        # 1. 配送方法のボタンをクリックしてモーダルを開く
        # ページ構造の変更に備え、複数のセレクタを試す
        shipping_button = page.locator('button:has-text("配送方法")').first
        if shipping_button.count() == 0:
            shipping_button = page.locator('div:has-text("配送方法") + button').first
        if shipping_button.count() == 0:
            shipping_button = page.locator('div.css-67lmaz:has-text("配送方法")').locator('..').locator('button').first
        
        if shipping_button.count() == 0:
            log("❌ 配送方法ボタンが見つかりません")
            return False
        
        safe_click(shipping_button)
        
        # 2. モーダルが表示されるのを待つ
        try:
            page.wait_for_selector('section[role="dialog"]', timeout=5000)
        except:
            log("⚠️ モーダルの表示待機がタイムアウト。続行します...")
        
        log("    モーダルを開きました。")
        
        # 3. モーダル内で「かんたんラクマパック(日本郵便)」を選択
        option_found = False
        try:
            jp_post_option = page.locator('section[role="dialog"] img[alt*="日本郵便"], section[role="dialog"] div:has-text("日本郵便")').first
            if jp_post_option.count() > 0:
                jp_post_option.locator('xpath=./ancestor-or-self::div[contains(@class, "css-")]').first.click()
                log("    「かんたんラクマパック(日本郵便)」のオプションを選択しました。")
                option_found = True
        except Exception as e:
            log(f"⚠️ 日本郵便オプション選択エラー: {e}")
        
        if not option_found:
            log("⚠️ モーダル内で日本郵便のオプションが見つかりませんでした")
            return False

        # 4. モーダルが閉じるのを待つ
        try:
            page.wait_for_selector('section[role="dialog"]', state='hidden', timeout=5000)
        except:
            log("⚠️ モーダルクローズ待機がタイムアウト。続行します...")
        
        log(f"✅ 配送方法を固定設定しました: {ship_text}")
        return True

    except Exception as e:
        log(f"⚠️ 配送方法の固定設定に失敗しました: {e}")
        return False

# --- メイン処理 ---
def update_products():
    # 1. 更新対象の商品URLをCSVから読み込む
    products_to_update = []
    try:
        with open(PRODUCTS_FILE, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # '削除'フラグが立っているもの、URLや商品IDがないものは除外
                if row.get('削除') != '削除' and row.get('URL') and row.get('商品ID'):
                    products_to_update.append(row)
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

    # 商品説明をマスターから読み込む
    description_map = load_descriptions_from_master()
    
    # ブランドマスターから品番→ブランド名マップを作成
    brand_map_path = os.path.join(SCRIPT_DIR, "brand_master_sjis.csv")
    brand_map = load_brand_map(brand_map_path) if os.path.exists(brand_map_path) else {}
    if brand_map:
        log(f"📚 ブランドマスター：{len(brand_map)}件読み込み")
    else:
        log(f"⚠️ ブランドマスターが利用できません（{brand_map_path}）")

    processed_ids = load_processed_ids()
    if RESTART_FROM_START and os.path.exists(PROCESSED_LOG):
        os.remove(PROCESSED_LOG)
        processed_ids = set()
        log("🔁 処理済みログをリセットしました。")
    log(f"✅ これまでに {len(processed_ids)} 件を処理済みです。")

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                USER_DATA_DIR,
                headless=False, # Falseでブラウザの動きが見える
                args=["--disable-gpu", "--disable-software-rasterizer"]
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
        for i, product in enumerate(products_to_update):
            product_id = get_product_id_from_url(product['URL'])
            if not product_id:
                log(f"⚠️ 無効なURLです、スキップします: {product.get('URL')}")
                continue

            if product_id in processed_ids:
                log(f"⏩ スキップ: {product_id} (処理済み)")
                continue

            log(f"\n🚀 {i+1}/{len(products_to_update)} 件目: {product['品番']} ({product_id}) の処理を開始します。")
            
            edit_url = f"https://fril.jp/item/{product_id}/edit"
            
            try:
                page.goto(edit_url, wait_until='domcontentloaded')
                time.sleep(1) # ページ描画の安定化

                # ページが存在しない、または編集できない場合
                if "このページは存在しません" in page.content() or "リクエストされたページは存在しません" in page.content():
                    log(f"❌ 編集ページが存在しません、スキップします: {edit_url}")
                    save_processed_id(product_id) # 再試行しないように記録
                    continue

                # --- 画像の再アップロード ---
                # [修正] 文字列ソートの問題を解決するため、自然順ソートを行う
                image_files = glob.glob(os.path.join(IMAGE_DIR, f"{product['商品ID']}-*.jpg"))
                def natural_sort_key(s):
                    # ファイル名末尾の数字を抽出して数値として返す
                    match = re.search(r'-(\d+)\.jpg$', s)
                    return int(match.group(1)) if match else 0
                image_paths = sorted(image_files, key=natural_sort_key)

                if not image_paths:
                    log("⚠️ 対応する画像が見つかりません。画像の更新はスキップします。")
                else:
                    log(f"📸 {len(image_paths)}枚の画像を再アップロードします...")
                    # --- [修正] 既存の画像を削除するロジックを強化 ---
                    try:
                        # 各画像に付随するメニューボタン（三点リーダー）をすべて取得
                        menu_buttons_locator = page.locator('button[aria-haspopup="menu"]')
                        count = menu_buttons_locator.count()
                        log(f"    既存の画像が {count} 個見つかりました。削除処理を開始します。")

                        # 既存の画像がなくなるまで、最初の画像を削除し続ける
                        while menu_buttons_locator.count() > 0:
                            current_count = menu_buttons_locator.count()
                            # 常に最初のメニューボタンをクリック
                            menu_buttons_locator.first.click(timeout=5000)
                            
                            # [修正] 表示されている(visible)メニュー内の「削除」ボタンを正確に特定してクリック
                            visible_menu_delete_button = page.locator(
                                'div.chakra-menu__menu-list[style*="visibility: visible"] button[role="menuitem"]:has-text("削除")'
                            )
                            # 表示されるまで少し待つ
                            visible_menu_delete_button.wait_for(state="visible", timeout=5000)
                            visible_menu_delete_button.click(force=True)

                            # [重要] 画像が1つ減るのを待つ
                            page.wait_for_function(
                                # 削除後に要素が確実に減ることを確認する
                                f'() => document.querySelectorAll(\'button[aria-haspopup="menu"]\').length === {current_count - 1}',
                                timeout=5000
                            )
                            log(f"    画像が1枚削除されました (残り: {menu_buttons_locator.count()}枚)")

                        log("    既存の画像の削除が完了しました。")
                    except Exception as e:
                        log(f"⚠️ 画像削除中にエラーが発生しました: {e}")
                        # 画像削除に失敗した場合は、この商品の処理を中断して次に進む
                        raise Exception("画像削除に失敗したため、この商品の更新を中断します。")

                    # [修正] 複数ファイルを受け付ける input 要素を直接特定し、ファイルをセットする
                    log("    新しい画像をアップロードします...")
                    # `multiple` 属性を持つ input を探す
                    multi_file_input = page.locator('input[type="file"][multiple]').first
                    multi_file_input.set_input_files(image_paths)

                    # --- [修正] アップロード完了をより確実に待つ ---
                    log("    画像のアップロード処理を開始しました。プレビュー表示を待ちます...")
                    expected_count = len(image_paths)
                    # プレビュー画像のセレクタを複数候補で試す
                    preview_selector = 'div.css-1021eg4 img, div[data-testid^="image-"] img'
                    
                    try:
                        # 指定した枚数のプレビューが表示されるまで最大120秒待機
                        page.wait_for_function(
                            expression=f"""(selector) => {{
                                const count = document.querySelectorAll(selector).length;
                                return count >= {expected_count};
                            }}""",
                            arg=preview_selector,
                            timeout=120000  # 120秒に延長
                        )
                        
                        # 念のため、現在のプレビュー数をログに出力
                        actual_count = page.locator(preview_selector).count()
                        log(f"✅ 画像のプレビュー表示を{actual_count}枚確認しました。")

                    except TimeoutError:
                        log(f"⚠️ 画像プレビューの待機がタイムアウトしました（{expected_count}枚を期待）。処理を続行しますが、画像が正しく反映されない可能性があります。")
                    except Exception as e:
                        log(f"⚠️ 画像プレビューの待機中にエラーが発生しました: {e}")


                # --- 商品名、商品説明、価格の更新 ---
                log("✏️ 商品名、説明、価格を更新します...")
                # 商品名: 新旧のセレクタに対応
                name_input = page.locator('input[name="itemName"], input[name="item[name]"]').first
                name_input.fill(product['商品名'])
                
                # 品番から商品説明を取得
                description_to_set = description_map.get(product['品番'], product.get('商品説明', ''))
                if not description_to_set:
                     # マスターにない場合、元の説明を維持しようと試みる（ただし、編集ページでは取得が難しい）
                     log("⚠️ マスターに商品説明が見つかりませんでした。商品説明は空の可能性があります。")
                # 商品説明: 新旧のセレクタに対応
                desc_input = page.locator('textarea[name="detail"], textarea[name="item[detail]"]').first
                desc_input.fill(description_to_set)

                # 価格: 新旧のセレクタに対応
                price_input = page.locator('input[name="sellPrice"], input[name="item[sell_price]"]').first
                price_input.fill(product['価格'])

                # --- 配送方法を「かんたんラクマパック(日本郵便)」に固定 ---
                set_shipping_method(page)

                # --- 発送日の目安 を "支払い後、4～7日で発送" に設定 ---
                try:
                    log("🗓️ 発送日の目安を「4~7日で発送」に設定します...")
                    # name属性が "delivery_date" に変更されている可能性も考慮
                    sel = page.locator('select[name="deliveryDate"], select[name="delivery_date"]').first
                    sel.select_option("3")
                    log("    発送日の目安を設定しました。")
                except Exception as e:
                    log(f"⚠️ 発送日の目安設定に失敗しました: {e}")
                
                # --- 更新フローの修正 ---
                log("💾 変更を保存します...")

                # 1. 「確認する」ボタンをクリック
                log("    「確認する」をクリックします。")
                confirm_button = page.locator('button:has-text("確認する")').first
                confirm_button.scroll_into_view_if_needed()
                confirm_button.click()

                # 2. 確認画面に遷移し、「更新する」ボタンをクリック
                log("    確認画面で「更新する」をクリックします。")
                # type="submit" を持つボタンを優先的に探す
                update_button = page.locator('button[type="submit"]:has-text("更新する")').first
                # 念のため、表示されるまで待機
                update_button.wait_for(state="visible", timeout=15000)
                update_button.click()

                # 更新完了を待つ (リダイレクト先が変更された可能性に対応)
                # "**/mypage/exhibit/sell" または "**/sell?is_new=0" のどちらかに遷移するのを待つ
                log("    更新完了ページの読み込みを待っています...")
                page.wait_for_url(re.compile(r"(/mypage/exhibit/sell|/sell\?is_new=0)"), timeout=30000)

                log(f"✅ {product_id} の更新が完了しました。")
                
                save_processed_id(product_id) # 処理済みとして記録

            except TimeoutError as e:
                log(f"❌ タイムアウトエラーが発生しました: {product_id} - {e}")
                log("    ページの読み込みが遅いか、UIが変更された可能性があります。")
                save_processed_id(product_id) # エラーが発生しても次回はスキップするように記録
            except Exception as e:
                log(f"❌ 不明なエラーが発生しました: {product_id} - {e}")
                # エラー発生時も、次回からスキップするためにIDを保存するかどうかは要検討
                save_processed_id(product_id) # エラーが発生しても次回はスキップするように記録

            # レート制限対策
            time.sleep(random.uniform(2.0, 5.0))

        log("\n🎉 全商品の更新処理が完了しました！")
        input("Enterキーを押すとブラウザを閉じます...")
        context.close()

# --- 実行 ---
if __name__ == "__main__":
    update_products()
