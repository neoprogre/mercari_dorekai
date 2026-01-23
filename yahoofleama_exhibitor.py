import os
import glob
import csv
import time
import logging
import pyautogui
import pyperclip
import sys

# --- ログ設定 ---
logging.basicConfig(
    filename="yahoofleama_exhibit.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding='utf-8'
)

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")
    logging.info(msg)

# --- 設定: ここからユーザーが設定 ---

# [TODO] BlueStacksの画面で撮影したボタン画像などを保存するフォルダ
YAHOO_IMAGES_DIR = r"C:\Users\progr\Desktop\Python\mercari_dorekai\images"

# [TODO] 以下のファイル名で、BlueStacksアプリの各ボタンのスクリーンショットを撮影し、
# 上記のフォルダに保存してください。
# 画像はボタン部分だけをタイトに切り取ってください。
IMG_EXHIBIT_BUTTON1 = "exhibit_button1.png"  # アプリのメイン画面にある「出品」ボタン
IMG_EXHIBIT_BUTTON2 = "exhibit_button2.png"  # アプリのメイン画面にある「出品」ボタン
IMG_SELECT_IMAGES = "select_images.png"    # 出品画面の「アルバムから選ぶ」や「+」ボタン
IMG_IMAGE_SELECT_DONE = "image_select_done.png" # 画像選択後の「完了」ボタン
IMG_CATEGORY_SELECT = "category_select.png" # 「カテゴリー」を選択するボタン
IMG_CATEGORY_LADIES = "category_ladies.png" # カテゴリ選択画面の「レディース」
IMG_CATEGORY_DRESS = "category_dress.png"   # 「ワンピース」など
IMG_CATEGORY_MINI_DRESS = "category_mini_dress.png" # 「ミニワンピース」など
IMG_CATEGORY_CONFIRM = "category_confirm.png" # カテゴリ選択後の「決定」ボタン
IMG_CONDITION_NEW = "condition_new.png" # 商品の状態で「新品、未使用」
IMG_SHIPPING_METHOD = "shipping_method.png" # 「配送の方法」を選択するボタン
IMG_SHIPPING_YAMATO = "shipping_yamato.png" # 配送方法の「おてがる配送（ヤマト運輸）'
IMG_SHIPPING_CONFIRM = "shipping_confirm.png" # 配送方法選択後の「決定」ボタン
IMG_PUBLISH_BUTTON = "publish_button.png" # 全て入力した後の「出品する」ボタン
IMG_PUBLISH_CONFIRM_BUTTON = "publish_confirm_button.png" # 出品確認画面の「出品する」ボタン
IMG_PUBLISH_COMPLETE = "publish_complete.png" # 出品完了を示す画面の何か（「続けて出品する」など）

# [TODO] 以下の座標を、お使いPCのBlueStacks画面に合わせて調整してください。
# コマンドプロンプトで `python -c "import pyautogui; pyautogui.displayMousePosition()"` を実行すると
# マウスの座標を調べることができます。
COORDS_PRODUCT_NAME = (500, 600)  # 商品名を入力するテキストエリアの座標
COORDS_DESCRIPTION = (500, 750)   # 商品説明を入力するテキストエリアの座標
COORDS_PRICE = (500, 1200)        # 販売価格を入力するテキストエリアの座標

# --- データマッピング ---
# CSVの値と、撮影するボタン画像ファイル名を対応させます
CONDITION_IMAGE_MAP = {
    '1': IMG_CONDITION_NEW,
    '2': "condition_like_new.png", # [TODO] 「未使用に近い」のボタン画像を撮影
    '3': "condition_good.png",     # [TODO] 「目立った傷や汚れなし」のボタン画像を撮影
    '4': "condition_fair.png",     # [TODO] 「やや傷や汚れあり」のボタン画像を撮影
    '5': "condition_poor.png",     # [TODO] 「傷や汚れあり」のボタン画像を撮影
    '6': "condition_bad.png",      # [TODO] 「全体的に状態が悪い」のボタン画像を撮影
}

# --- 基本操作 ---

def click_image(image_name, confidence=0.65, timeout=10):
    """
    画像を探してクリック。RGBA->RGB変換、低めのデフォルト信頼度、OpenCVフォールバックあり。
    """
    import re, traceback
    from PIL import Image
    image_path = os.path.join(YAHOO_IMAGES_DIR, image_name)
    log(f"🔎 画像パス: {image_path}")
    if not os.path.exists(image_path):
        log(f"⚠️ 画像ファイルが見つかりません: {image_path}")
        return False

    # 画像情報取得
    try:
        img = Image.open(image_path)
        log(f"   画像サイズ: {img.size}, mode={img.mode}")
    except Exception as e:
        log(f"⚠️ 画像読み込みエラー: {e}")
        img = None

    # RGBA 等は一時的に RGB に変換して保存
    tmp_path = None
    search_path = image_path
    try:
        if img is not None and img.mode in ('RGBA', 'LA', 'P'):
            tmp_path = os.path.join(YAHOO_IMAGES_DIR, f"_tmp_rgb_{image_name}")
            img.convert('RGB').save(tmp_path)
            search_path = tmp_path
            log(f"   RGBA->RGB変換を行って検索します: {tmp_path}")
    except Exception as e:
        log(f"⚠️ 画像変換エラー: {e}")
        search_path = image_path

    last_highest_conf = None
    start = time.time()
    log(f"🖱️ \"{image_name}\" を探しています... (initial confidence={confidence})")
    while time.time() - start < timeout:
        try:
            location = pyautogui.locateCenterOnScreen(search_path, confidence=confidence)
            if location:
                log(f"   -> 見つかりました: {location}。クリックします。")
                pyautogui.click(location)
                if tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)
                return True
        except Exception as e:
            tb = traceback.format_exc()
            m = re.search(r'highest confidence\s*=\s*([0-9.]+)', tb, re.IGNORECASE) or re.search(r'highest confidence\s*=\s*([0-9.]+)', str(e), re.IGNORECASE)
            if m:
                try:
                    last_highest_conf = float(m.group(1))
                except Exception:
                    pass
            log(f"⚠️ locateCenterOnScreen で例外: {repr(e)}")

        time.sleep(0.3)

    # フォールバック: 低めの閾値とグレースケールを順に試す
    for conf in (0.6, 0.55):
        try:
            log(f"🔁 フォールバック検索: confidence={conf}, grayscale=True")
            loc = pyautogui.locateCenterOnScreen(search_path, confidence=conf, grayscale=True)
            if loc:
                log(f"   -> 見つかりました (fallback): {loc}。クリックします。")
                pyautogui.click(loc)
                if tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)
                return True
        except Exception as e:
            log(f"⚠️ フォールバック検索で例外: {e}")

    # OpenCV フォールバック（インストールされていれば）
    try:
        import cv2, numpy as np
        log("🔬 OpenCV フォールバック（matchTemplate）を実行します")
        ss = pyautogui.screenshot()
        ss_np = cv2.cvtColor(np.array(ss), cv2.COLOR_RGB2BGR)
        tpl = cv2.imread(search_path)
        if tpl is not None:
            res = cv2.matchTemplate(ss_np, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            log(f"   OpenCV max_val={max_val:.3f} at {max_loc}")
            if max_val >= 0.6:
                h, w = tpl.shape[:2]
                center = (max_loc[0] + w//2, max_loc[1] + h//2)
                log(f"   -> OpenCV で見つかりました: center={center} (val={max_val:.3f})。クリックします。")
                pyautogui.click(center)
                if tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)
                return True
        else:
            log(f"⚠️ OpenCV がテンプレートを読み込めませんでした: {search_path}")
    except Exception as e:
        log(f"⚠️ OpenCV フォールバックエラー: {e}")

    # デバッグ用スクリーンショット
    try:
        os.makedirs("error_artifacts", exist_ok=True)
        ss_path = os.path.join("error_artifacts", f"debug_search_{os.path.basename(image_name)}.png")
        pyautogui.screenshot(ss_path)
        log(f"🖼️ 画面全体スクリーンショットを保存: {ss_path}")
    except Exception as e:
        log(f"⚠️ スクリーンショット保存エラー: {e}")

    if tmp_path and os.path.exists(tmp_path):
        try: os.remove(tmp_path)
        except Exception: pass

    extra = f" (OpenCV max ~ {last_highest_conf:.3f})" if last_highest_conf else ""
    log(f"❌ \"{image_name}\" が見つかりませんでした{extra}。confidence を 0.6〜0.65 に下げるか、画像を RGB で再保存してください。")
    return False

def click_any(image_names, confidence=0.65, timeout=8):
    """
    複数の候補画像を順に試す。最初に見つかったものをクリックする。
    """
    for name in image_names:
        log(f"➡️ 試行: {name}")
        if click_image(name, confidence=confidence, timeout=timeout):
            log(f"✅ クリック成功: {name}")
            return True
    return False

def type_text(text, coords):
    """
    指定された座標をクリックし、クリップボード経由でテキストを入力する
    """
    log(f"⌨️ 座標 {coords} に \"{text[:30]}...\" を入力します。")
    pyautogui.click(coords)
    time.sleep(0.5)
    pyperclip.copy(text)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.5)

def scroll_down(clicks=5):
    """
    画面を下にスクロールする
    """
    log("⏬ 画面を下にスクロールします。")
    # BlueStacksウィンドウの中央あたりをクリックしてフォーカスを合わせる
    # (ウィンドウサイズに合わせて調整が必要な場合があります)
    win_size = pyautogui.size()
    pyautogui.click(win_size.width / 2, win_size.height / 2)
    
    # ホイール操作でスクロール
    pyautogui.scroll(-100 * clicks) # マイナス値で下にスクロール
    time.sleep(1)

# --- 出品ステップごとの関数 ---

def step_select_images(image_paths_on_host):
    """
    [最難関] 画像を選択するステップ
    """
    log("--- ステップ: 画像選択 ---")
    if not click_image(IMG_SELECT_IMAGES):
        return False
    
    # [TODO] ここが最も難しい部分です。
    # BlueStacksの「メディアマネージャー」でPCから画像をインポートした後、
    # アプリのギャラリー画面でどうやって目的の画像を選択するか、というロジックが必要です。
    # 
    # 例:
    # 1. ギャラリーの特定のアルバムをクリックする
    # 2. 最新の画像が一番上にあると仮定し、上からN個をクリックする
    # 
    # この部分は環境依存性が非常に高いため、最初は手動での操作を推奨します。
    # 自動化する場合、目的の画像サムネイルのスクリーンショットを撮ってクリックするなどの方法が考えられます。
    log("⚠️ [手動操作のお願い] 1分以内にBlueStacks内で以下の画像を選択し、「完了」を押してください。")
    for p in image_paths_on_host:
        log(f"  - {os.path.basename(p)}")
    
    # ユーザーが手動で選択し、「完了」を押すのを待つ
    time.sleep(60)
    
    # 完了後、出品画面に戻っているはず
    return True


def step_fill_details(product):
    """
    商品名、説明、カテゴリなどを入力する
    """
    log("--- ステップ: 詳細入力 ---")

    # 商品名
    type_text(product['name'], COORDS_PRODUCT_NAME)

    # カテゴリ
    if not click_image(IMG_CATEGORY_SELECT): return False
    time.sleep(1)
    if not click_image(IMG_CATEGORY_LADIES): return False
    time.sleep(1)
    if not click_image(IMG_CATEGORY_DRESS): return False
    time.sleep(1)
    if not click_image(IMG_CATEGORY_MINI_DRESS): return False
    time.sleep(1)
    if not click_image(IMG_CATEGORY_CONFIRM): return False
    
    # 商品説明
    type_text(product['description'], COORDS_DESCRIPTION)
    
    scroll_down() # 画面をスクロールして下の項目を表示

    # 商品の状態
    condition_img = CONDITION_IMAGE_MAP.get(product['condition'])
    if condition_img:
        if not click_image(condition_img):
            log(f"⚠️ 商品状態({condition_img})のクリックに失敗しました。")
            # 失敗しても処理を続ける
    else:
        log(f"⚠️ 対応する商品状態の画像がありません: {product['condition']}")

    # 配送の方法
    if not click_image(IMG_SHIPPING_METHOD): return False
    time.sleep(1)
    if not click_image(IMG_SHIPPING_YAMATO): return False
    time.sleep(1)
    # 確認ボタンがあれば押す
    click_image(IMG_SHIPPING_CONFIRM) 

    scroll_down()

    # 価格
    type_text(product['price'], COORDS_PRICE)

    return True

def step_publish():
    """
    出品ボタンを押して完了させる
    """
    log("--- ステップ: 出品実行 ---")
    if not click_image(IMG_PUBLISH_BUTTON):
        return False
    
    time.sleep(2) # 確認画面の表示を待つ
    
    if not click_image(IMG_PUBLISH_CONFIRM_BUTTON, timeout=15):
        log("⚠️ 確認画面の出品ボタンが見つかりませんでした。")
        return False
        
    # 出品完了を待つ
    if not click_image(IMG_PUBLISH_COMPLETE, timeout=30):
        log("⚠️ 出品完了画面を検出できませんでした。")
        return False
    
    log("✅ 出品が完了しました。")
    return True


# --- CSV読み込みとメイン処理 ---

def get_column_indices(header):
    indices = {}
    columns = [
        ('商品ID', 0), ('商品名', 62), ('商品説明', 63), ('販売価格', 151),
        ('商品の状態', 153), ('品番', None)
    ]
    for name, fallback in columns:
        try:
            indices[name] = header.index(name)
        except ValueError:
            indices[name] = fallback
            log(f"ヘッダーに'{name}'が見つかりません。インデックス {fallback} を使用します。")
    return indices

def main():
    log("=== Yahoo!フリマ出品処理を開始します ===")
    
    # [TODO] BlueStacksのウィンドウを前面に表示し、操作可能な状態にしてください。
    log("3秒後に処理を開始します。BlueStacksをアクティブにしてください...")
    time.sleep(3)

    # --- 出品対象の商品を決定するロジック (rakuma_exhibitor.pyから流用) ---
    # (この部分はPC上のファイルで完結するため、そのまま使えます)
    
    # 1. Yahooフリマに出品済みの品番を読み込む
    yahoofleama_hinban_set = set()
    try:
        with open("products_yahoofleama.csv", "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader)
            hinban_idx = header.index('品番')
            for row in reader:
                if len(row) > hinban_idx and row[hinban_idx]:
                    yahoofleama_hinban_set.add(row[hinban_idx])
        log(f"📚 Yahooフリマ商品 {len(yahoofleama_hinban_set)} 件の品番を読み込みました。")
    except FileNotFoundError:
        log("⚠️ products_yahoofleama.csv が見つかりません。初回出品として処理を続行します。")
    except Exception as e:
        log(f"⚠️ products_yahoofleama.csv 読み込みエラー: {e}")

    # 2. メルカリCSVから、ステータスが2で、かつYahooフリマに存在しない商品のIDを抽出
    target_product_ids = set()
    try:
        with open("products_mercari.csv", "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader)
            hinban_idx = header.index('品番')
            status_idx = header.index('商品ステータス')
            url_idx = header.index('URL')
            for row in reader:
                if len(row) > max(hinban_idx, status_idx, url_idx):
                    hinban = row[hinban_idx]
                    status = row[status_idx]
                    url = row[url_idx]
                    if status == '2' and hinban not in yahoofleama_hinban_set:
                        product_id = url.replace('https://jp.mercari.com/shops/product/', '')
                        if product_id:
                            target_product_ids.add(product_id)
        log(f"🔍 抽出条件: {len(target_product_ids)} 件のメルカリ商品を対象とします。")
    except Exception as e:
        log(f"❌ products_mercari.csv 処理エラー: {e}")
        return

    if not target_product_ids:
        log("✅ アップロード対象の商品はありませんでした。")
        return

    # 3. 詳細情報を持つマスターCSVファイルを探して読み込む
    network_dir = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai"
    csv_pattern = os.path.join(network_dir, "product_data_*.csv")
    latest_csv = max(glob.glob(csv_pattern), key=os.path.getmtime, default=None)
    if not latest_csv:
        log(f"❌ 詳細データCSVが見つかりません: {csv_pattern}")
        return
    log(f"📂 最新の詳細データCSVを読み込み: {latest_csv}")

    # 4. マスターCSVから対象商品IDの行だけを抽出
    products_to_process = []
    try:
        with open(latest_csv, "r", encoding="cp932", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader)
            indices = get_column_indices(header)
            product_id_idx = indices.get('商品ID')
            if product_id_idx is None: return

            for row in reader:
                if len(row) > product_id_idx and row[product_id_idx] in target_product_ids:
                    product_data = {
                        'id': row[indices['商品ID']],
                        'name': row[indices['商品名']],
                        'description': row[indices['商品説明']],
                        'price': row[indices['販売価格']],
                        'condition': row[indices['商品の状態']],
                    }
                    products_to_process.append(product_data)
        log(f"📤 最終的なアップロード対象: {len(products_to_process)} 件")
    except Exception as e:
        log(f"❌ 詳細データCSVの読み込み/フィルタリングエラー: {e}")
        return

    # --- 1件ずつ出品処理 ---
    for i, product in enumerate(products_to_process):
        log(f"\n--- {i+1}/{len(products_to_process)} 件目: {product['name']} の処理を開始 ---")
        
        try:
            # 1. メイン画面の「出品」ボタンを押す
            if not click_any([IMG_EXHIBIT_BUTTON1, IMG_EXHIBIT_BUTTON2]):
                log("❌ 出品ボタンが見つかりませんでした（exhibit_button1, exhibit_button2 の両方を試行）。")
                return False

            # 2. 画像を選択
            image_dir_on_host = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images"
            image_paths = sorted(glob.glob(os.path.join(image_dir_on_host, f"{product['id']}-*.jpg")))
            if not image_paths:
                log("⚠️ 商品画像が見つかりません。この商品をスキップします。")
                continue
            
            if not step_select_images(image_paths):
                raise Exception("Image selection failed")

            # 3. 商品詳細を入力
            if not step_fill_details(product):
                raise Exception("Failed to fill details")

            # 4. 出品を実行
            if not step_publish():
                raise Exception("Publishing failed")

            log(f"✅ {product['name']} の処理が正常に完了しました。")
            # 成功ログなどを別途保存しても良い

        except Exception as e:
            log(f"🛑 エラーが発生したため、{product['name']} の処理を中断します: {e}")
            pyautogui.screenshot(os.path.join("error_artifacts", f"error_screen_{product['id']}.png"))
            log("🖼️ エラー発生時のスクリーンショットを error_artifacts に保存しました。")
            
            user_input = input("続行しますか？ (y/n): ").lower()
            if user_input != 'y':
                log("処理を中断します。")
                break
            else:
                # 次の商品のためにメイン画面に戻るなどの操作が必要かもしれない
                log("次の商品の処理に進みます... (必要なら手動でアプリをメイン画面に戻してください)")
                time.sleep(5)

    log("🎉 全ての処理が完了しました。")


if __name__ == "__main__":
    # フォルダが存在しない場合は作成
    if not os.path.exists(YAHOO_IMAGES_DIR):
        os.makedirs(YAHOO_IMAGES_DIR)
        log(f"📁 画像フォルダ '{YAHOO_IMAGES_DIR}' を作成しました。")
    if not os.path.exists("error_artifacts"):
        os.makedirs("error_artifacts")

    try:
        main()
    except KeyboardInterrupt:
        log("⏹️ ユーザーによって処理が中断されました。")
        sys.exit(0)
    except Exception as e:
        log(f"💥 予期せぬ致命的なエラーが発生しました: {e}")
        pyautogui.screenshot(os.path.join("error_artifacts", "critical_error_screen.png"))
        sys.exit(1)

