import os
import glob
import re
import pandas as pd
import shutil

# ==============================================================================
#
#   目的: 新規で商品を出品する
#
# ==============================================================================
import csv
import time
import codecs
from playwright.sync_api import sync_playwright, TimeoutError
import random

# --- 設定 ---
IMAGE_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images"
NETWORK_DIR = r"C:\Users\progr\Desktop\Python\mercari_dorekai\downloads"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAKUMA_LOGIN_URL = "https://fril.jp/login"
RAKUMA_NEW_ITEM_URL = "https://fril.jp/item/new"
USER_DATA_DIR = "rakuma_user_data_firefox"
PROCESSED_LOG = "processed_ids.txt"
RAKUMA_PRODUCTS_CSV = r"C:\Users\progr\Desktop\Python\mercari_dorekai\products_rakuma.csv"

# キャッシュディレクトリを削除
cache_dir = os.path.join(SCRIPT_DIR, USER_DATA_DIR, "cache2")
if os.path.exists(cache_dir):
    try:
        shutil.rmtree(cache_dir)
        print(f"🗑️ キャッシュを削除: {cache_dir}")
    except Exception as e:
        print(f"⚠️ キャッシュ削除エラー: {e}")

# --- データマッピング ---
CONDITION_MAP = {
    '1': '新品、未使用',
    '2': '未使用に近い',
    '3': '目立った傷や汚れなし',
    '4': 'やや傷や汚れあり',
    '5': '傷や汚れあり',
    '6': '全体的に状態が悪い',
}
SHIPPING_PAYER_MAP = {
    '1': '送料込み(出品者負担)',
    '2': '着払い(購入者負担)',
}
DAYS_TO_SHIP_MAP = {
    '1': '1-2日で発送',
    '2': '2-3日で発送',
    '3': '4-7日で発送',
}
PREFECTURE_MAP = {
    'jp27': '大阪府',
    'jp13': '東京都',
    # 必要に応じて追加
}

# --- 商品名の長さ制限（プラットフォーム別） ---
PRODUCT_NAME_LIMITS = {
    'rakuma': 40,      # 全角・半角ともに1文字
    'mercari': 100,    # 全角・半角ともに1文字
    'yahoo': 65,       # 全角は1文字、半角は0.5文字
}

# --- ラクマのサイズ選択肢（モーダル内に出現） ---
# カテゴリが「レディース > フォーマル/ドレス > ナイトドレス」の場合
RAKUMA_SIZE_OPTIONS_LADIES_FORMAL = [
    "FREE / ONESIZE",
    "~XS",
    "S",
    "M",
    "L",
    "XL",
    "XXL~",
]

# --- メルカリ ↔ ラクマ サイズ対応表 ---
# メルカリのCSVから取得したサイズを、ラクマの選択肢にマップ
SIZE_MAPPING_MERCARI_TO_RAKUMA = {
    # メルカリから取得: ラクマで選択
    "FREE / ONESIZE": "FREE / ONESIZE",
    "フリーサイズ": "FREE / ONESIZE",
    "XS": "~XS",
    "S": "S",
    "M": "M",
    "L": "L",
    "XL": "XL",
    "XXL": "XXL~",
    "2XL": "XXL~",
    "指定なし": "FREE / ONESIZE",  # デフォルト
}

# --- ユーティリティ ---
def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def is_internal_error_page(page):
    try:
        # h1 に「内部エラーが発生しました」があれば内部エラーページと判定
        if page.locator('h1:has-text("内部エラーが発生しました")').count() > 0:
            return True
        # 念のため body テキストでも確認
        body = ""
        try:
            body = page.locator('body').inner_text()
        except Exception:
            body = page.content()
        if "内部エラーが発生しました" in body:
            return True
    except Exception:
        return False
    return False

def safe_goto(page, url, **kwargs):
    """内部エラーを検知してリトライする page.goto"""
    max_retries = 3
    for i in range(max_retries):
        try:
            # ナビゲーション衝突を回避するため、少し待機
            if i > 0:
                time.sleep(2 + i)
            response = page.goto(url, timeout=60000, **kwargs)
            if is_internal_error_page(page):
                log(f"⚠️ goto後に内部エラーを検出。リトライします ({i+1}/{max_retries})")
                time.sleep(2 ** i) # 指数バックオフ
                continue
            return response
        except Exception as e:
            log(f"goto中にエラー: {e}")
            if i == max_retries - 1:
                raise # 最後のリトライでも失敗したら例外を送出
            time.sleep(2 ** i)
    raise Exception(f"{url} への移動に失敗しました。")

def safe_click(locator, **kwargs):
    """内部エラーを検知してリトライする locator.click"""
    page = locator.page
    max_retries = 3
    for i in range(max_retries):
        try:
            locator.click(**kwargs)
            if is_internal_error_page(page):
                log(f"⚠️ クリック後に内部エラーを検出。リトライします ({i+1}/{max_retries})")
                # エラーページから戻る試み
                try:
                    page.go_back(wait_until='domcontentloaded')
                except Exception:
                    # 戻れない場合は出品ページに再アクセス
                    safe_goto(page, RAKUMA_NEW_ITEM_URL, wait_until='domcontentloaded')
                time.sleep(2 ** i)
                continue # ループの最初に戻って再クリックを試みる
            return
        except Exception as e:
            log(f"クリック中にエラー: {e}")
            if i == max_retries - 1:
                raise
            time.sleep(2 ** i)
    raise Exception("クリック操作に失敗しました。")

def save_error_artifacts(page, identifier):
    """エラー時のスクリーンショットとHTMLを保存する"""
    try:
        os.makedirs("error_artifacts", exist_ok=True)
        ts = int(time.time())
        ss_path = os.path.join("error_artifacts", f"error_{identifier}_{ts}.png")
        html_path = os.path.join("error_artifacts", f"error_{identifier}_{ts}.html")
        page.screenshot(path=ss_path, full_page=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        log(f"💾 エラー情報を保存しました: {ss_path}, {html_path}")
    except Exception as e:
        log(f"⚠️ エラー情報の保存に失敗しました: {e}")

def handle_internal_error(page, product_id, attempt, max_attempts=3):
    # スクリーンショットと HTML を残す
    save_error_artifacts(page, f"internal_{product_id}")

    if attempt >= max_attempts:
        log(f"❌ 内部エラーが継続しています（試行 {attempt}/{max_attempts}）。この商品をスキップします。")
        return False
    # 再試行前に短い待機（指数バックオフ）
    wait_sec = 2 ** attempt
    log(f"⏳ 内部エラー: {wait_sec}s 後に再読み込みしてリトライします（{attempt}/{max_attempts}）")
    time.sleep(wait_sec)
    try:
        safe_goto(page, RAKUMA_NEW_ITEM_URL, wait_until='domcontentloaded')
    except Exception as e:
        log(f"⚠️ 再読み込みに失敗しました: {e}")
    return True

def find_latest_csv(pattern):
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None

def load_processed_ids():
    if not os.path.exists(PROCESSED_LOG):
        return set()
    with open(PROCESSED_LOG, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def save_processed_id(pid):
    with open(PROCESSED_LOG, "a", encoding="utf-8") as f:
        f.write(pid + "\n")

def load_brand_map(path):
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
    except Exception:
        log(f"⚠️ ブランドマスタの読み込みに失敗しました: {path}")
    return m

def load_category_map(path):
    m = {}
    try:
        with open(path, "r", encoding="cp932", errors="replace") as f:
            r = csv.reader(f)
            for row in r:
                if len(row) >= 3:
                    cid = row[0].strip()
                    # 3列目にフルパスがある想定（なければ2列目を使う）
                    name = row[2].strip() or row[1].strip()
                    if cid:
                        m[cid] = name
                elif len(row) >= 2:
                    cid = row[0].strip()
                    name = row[1].strip()
                    if cid:
                        m[cid] = name
    except Exception:
        log(f"⚠️ カテゴリマスタの読み込みに失敗しました: {path}")
    return m

def get_column_indices(header):
    indices = {}
    columns = [
        ('品番', None),
        ('商品ID', 0),
        ('商品名', 62),
        ('商品説明', 63),
        ('販売価格', 151),
        ('商品の状態', 153),
        ('配送料の負担', 157),
        ('発送元の地域', 155),
        ('発送までの日数', 156),
        ('サイズ', None),  # CSV にサイズ列があればここで拾う
        ('商品ステータス', None),  # 追加: 1 = 売切れとしてスキップ
        # ここでブランド/カテゴリのヘッダがあれば使う。見つからなければ None を入れる
        ('ブランドID', None),
        ('カテゴリID', None),
    ]
    for name, fallback in columns:
        if name in header:
            indices[name] = header.index(name)
        else:
            indices[name] = fallback
    return indices

def truncate_product_name(name, platform='rakuma'):
    """プラットフォーム別に商品名を制限する
    
    Args:
        name: 元の商品名
        platform: プラットフォーム名（'rakuma'、'mercari'、'yahoo'）
    
    Returns:
        制限された商品名
    """
    if not name:
        return ''
    
    if platform == 'yahoo':
        # ヤフオク: 全角1文字、半角0.5文字のカウント
        max_length = PRODUCT_NAME_LIMITS['yahoo']
        current_length = 0
        result = []
        
        for char in name:
            # 全角判定（簡易版）: Unicode コードポイント > 127 で全角と判定
            char_width = 1 if ord(char) > 127 else 0.5
            
            if current_length + char_width > max_length:
                break
            
            result.append(char)
            current_length += char_width
        
        name = ''.join(result)
    else:
        # ラクマ・メルカリ: 全角・半角ともに1文字
        max_length = PRODUCT_NAME_LIMITS.get(platform, 40)
        
        if len(name) > max_length:
            cut = name[:max_length]
            # 半角スペースを優先して最後の位置を探す
            idx = cut.rfind(' ')
            if idx > 0:
                cut = cut[:idx]
            name = cut.rstrip()
    
    return name

def convert_size_mercari_to_rakuma(mercari_size):
    """メルカリのサイズ値をラクマのサイズに変換する
    
    Args:
        mercari_size: メルカリCSVから取得したサイズ文字列
    
    Returns:
        ラクマで選択可能なサイズ文字列（見つからない場合は「FREE / ONESIZE」）
    """
    if not mercari_size:
        return "FREE / ONESIZE"
    
    mercari_size = mercari_size.strip()
    
    # 完全一致で探す
    if mercari_size in SIZE_MAPPING_MERCARI_TO_RAKUMA:
        return SIZE_MAPPING_MERCARI_TO_RAKUMA[mercari_size]
    
    # 部分一致で探す（例：「S」を含む値を検索）
    mercari_size_upper = mercari_size.upper()
    for key, value in SIZE_MAPPING_MERCARI_TO_RAKUMA.items():
        if key.upper() in mercari_size_upper or mercari_size_upper in key.upper():
            return value
    
    # マッピングに見つからない場合はデフォルト
    log(f"⚠️ サイズマッピングに見つかりません（メルカリ: {mercari_size}）。「FREE / ONESIZE」を使用します。")
    return "FREE / ONESIZE"

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
             shipping_button = page.locator('div.css-67lmaz:has-text("配送方法")').locator('..').locator('button')

        safe_click(shipping_button)
        
        # 2. モーダルが表示されるのを待つ
        page.wait_for_selector('section[role="dialog"]', timeout=5000)
        log("    モーダルを開きました。")
        
        # 3. モーダル内で「かんたんラクマパック(日本郵便)」を選択
        # より確実に選択するため、複数のテキスト候補を試す
        option_found = False
        # "日本郵便" を含む要素を探し、その親要素をクリックする
        jp_post_option = page.locator('section[role="dialog"] img[alt*="日本郵便"], section[role="dialog"] div:has-text("日本郵便")').first
        if jp_post_option.count() > 0:
            # imgやテキスト要素の親であるクリック可能な要素を探してクリックする
            jp_post_option.locator('xpath=./ancestor-or-self::div[contains(@class, "css-")]').first.click()
            log("    「かんたんラクマパック(日本郵便)」のオプションを選択しました。")
            option_found = True
        if not option_found:
            raise Exception("モーダル内で日本郵便のオプションが見つかりませんでした。")

        # 4. モーダルが閉じるのを待つ
        page.wait_for_selector('section[role="dialog"]', state='hidden', timeout=5000)
        log(f"✅ 配送方法を固定設定しました: {ship_text}")

    except Exception as e:
        log(f"⚠️ 配送方法の固定設定に失敗しました: {e}")
        # エラーが発生しても処理を続行する

def _fill_product_form(page, product_data):
    """
    商品出品ページのフォームを埋める.
    product_data は、ヘッダをキーにした辞書。
    """
    # この関数内で、商品名、説明、価格などの具体的な入力処理を実装する
    # (元のコードのメインループから、この関数にロジックを移動させる)
    # このリファクタリング例では、簡潔さのために関数定義のみを示します。
    # 実際の移行では、元のメインループ内の `log` や `try-except` ブロックも
    # 適宜この関数内に移動させることになります。
    log("✏️ 商品情報を入力します...")
    # page.locator(...).fill(product_data['商品名'])
    # page.locator(...).fill(product_data['商品説明'])
    # ...
    # set_shipping_method(page)
    # ...
    # page.locator(...).fill(product_data['販売価格'])
    log("✅ 商品情報の入力が完了しました。")


# --- メイン処理 ---
def process_products():
    # 1. ラクマに出品済みの商品IDを読み込む
    rakuma_product_ids = set()
    try:
        rakuma_csv = RAKUMA_PRODUCTS_CSV
        if not os.path.exists(rakuma_csv):
            log(f"⚠️ products_rakuma.csv が見つかりません: {rakuma_csv}")
            raise FileNotFoundError("products_rakuma.csv")

        df_rakuma = pd.read_csv(rakuma_csv, encoding='utf-8')
        if '商品ID' in df_rakuma.columns:
            rakuma_product_ids = set(df_rakuma['商品ID'].astype(str))
            log(f"📚 ラクマ出品済み商品: {len(rakuma_product_ids)} 件の商品ID")
        else:
            log(f"❌ products_rakuma.csvに「商品ID」列がありません")
            return
    except Exception as e:
        log(f"⚠️ products_rakuma.csv 読み込みエラー: {e}")
        import traceback
        traceback.print_exc()
        return

    # 2. メルカリCSVから、ラクマに存在しない商品のIDを抽出
    target_product_ids = set()
    try:
        # 最新のproduct_data_*.csvを探す
        mercari_csv = None
        product_data_files = glob.glob(os.path.join(NETWORK_DIR, "product_data_*.csv"))
        if product_data_files:
            mercari_csv = max(product_data_files, key=os.path.getctime)
        
        if not mercari_csv:
            # フォールバック: ローカルディレクトリで探す
            product_data_files = glob.glob(os.path.join(SCRIPT_DIR, "downloads", "product_data_*.csv"))
            if product_data_files:
                mercari_csv = max(product_data_files, key=os.path.getctime)
        
        if not mercari_csv:
            log(f"⚠️ product_data_*.csv が見つかりません。")
            raise FileNotFoundError("product_data_*.csv")
        
        log(f"📂 メルカリCSVを読み込み: {mercari_csv}")
        
        df_mercari = pd.read_csv(mercari_csv, encoding='shift-jis', low_memory=False)
        
        if '商品ID' not in df_mercari.columns:
            log(f"❌ メルカリCSVに「商品ID」列がありません")
            return
        
        # メルカリの全商品ID
        mercari_product_ids = set(df_mercari['商品ID'].astype(str))
        
        # メルカリにあってラクマに無い商品ID
        candidate_ids = mercari_product_ids - rakuma_product_ids
        
        # フィルタリング: 商品ステータスが1または在庫数が0の商品を除外
        for product_id in candidate_ids:
            row = df_mercari[df_mercari['商品ID'] == product_id]
            if row.empty:
                continue
            
            # 商品ステータスが1（売り切れ）の場合はスキップ
            if '商品ステータス' in df_mercari.columns:
                status = row['商品ステータス'].iloc[0]
                if pd.notna(status) and str(status).strip() == '1':
                    log(f"⏸️ スキップ: {product_id} (商品ステータス=1: 売り切れ)")
                    continue
            
            # SKU1_現在の在庫数が0の場合はスキップ
            if 'SKU1_現在の在庫数' in df_mercari.columns:
                stock = row['SKU1_現在の在庫数'].iloc[0]
                if pd.notna(stock) and int(stock) == 0:
                    log(f"⏸️ スキップ: {product_id} (SKU1_現在の在庫数=0)")
                    continue
            
            target_product_ids.add(product_id)
        
        log(f"🔍 抽出完了: {len(target_product_ids)} 件の商品（メルカリにあってラクマに無し、かつ販売可能）")
        
    except Exception as e:
        log(f"❌ product_data_*.csv 処理エラー: {e}")
        import traceback
        traceback.print_exc()
        return

    if not target_product_ids:
        log("✅ アップロード対象の商品はありませんでした。")
        return

    # 3. 詳細情報を持つマスターCSVファイルを使用
    latest_csv = mercari_csv
    log(f"📂 最新の詳細データCSVを使用: {latest_csv}")

    # 4. マスターCSVから対象商品IDの行だけを抽出
    products = []
    header = []
    seen_product_ids = set()
    try:
        with open(latest_csv, "r", encoding="cp932", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader)
            indices = get_column_indices(header)
            product_id_idx = indices.get('商品ID')
            if product_id_idx is None:
                log(f"❌ 詳細データCSVに '商品ID' 列がありません: {latest_csv}")
                return

            for row in reader:
                if len(row) > product_id_idx:
                    row_product_id = row[product_id_idx].strip() if row[product_id_idx] else ""
                    if row_product_id in target_product_ids:
                        if row_product_id in seen_product_ids:
                            continue
                        seen_product_ids.add(row_product_id)
                        products.append(row)
        log(f"📤 最終的なアップロード対象: {len(products)} 件")
    except Exception as e:
        log(f"❌ 詳細データCSVの読み込み/フィルタリングエラー: {e}")
        return

    if not products:
        log("✅ アップロード対象の商品はありませんでした。")
        return

    # --- ここから下は、抽出した商品(products)に対する出品処理 ---
    indices = get_column_indices(header)
    brand_map = load_brand_map("brand_master_sjis.csv")
    category_map = load_category_map("category_master_updated_sjis.csv")
    log(f"📚 ブランド数: {len(brand_map)} / カテゴリ数: {len(category_map)}")

    processed = load_processed_ids()
    log(f"✅ 処理済み商品数: {len(processed)} 件")

    with sync_playwright() as p:
        context = p.firefox.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
        )
        page = context.pages[0] if context.pages else context.new_page()
        # 高速化: デフォルトタイムアウトを短めに設定（必要なら元に戻す）
        page.set_default_timeout(30000)
        # ページ描画のアニメーションを無効化して待ち時間を減らす
        page.add_init_script("() => { const s=document.createElement('style'); s.innerHTML='*{transition:none!important;animation:none!important}'; document.documentElement.appendChild(s); }")

        # --- 自動ログイン検知 ---
        log("ログイン状態を確認中...")
        safe_goto(page, RAKUMA_NEW_ITEM_URL, wait_until='domcontentloaded')
        if "login" in page.url:
            log("⚠️ ログインが必要です。自動ログインを待機中...")
            try:
                # ログイン完了を自動検知（最大60秒待機）
                page.wait_for_url(lambda url: "login" not in url, timeout=60000)
                log("🔓 ログインを検知しました。処理を再開します。")
            except TimeoutError:
                log("❌ ログインが完了しませんでした。処理を中止します。")
                
                # Slack通知を送信（ログイン切れ）
                try:
                    import subprocess
                    subprocess.run([
                        r"..\venv\Scripts\python.exe", 
                        "send_slack_notification.py",
                        "❌ ラクマ新規出品: ログインセッションが切れています。手動でログインが必要です。",
                        "error"
                    ], cwd=SCRIPT_DIR)
                except:
                    pass
                
                context.close()
                return
        else:
            log("✅ すでにログイン済みです。")

        # --- レート制限対策 ---
        requests_since_pause = 0
        def maybe_pause_for_rate_limit():
            nonlocal requests_since_pause
            requests_since_pause += 1
            # 10件ごとに60〜180秒の長めの休止
            if requests_since_pause % 10 == 0:
                t = random.randint(60, 180)
                log(f"⏸️ 連続処理が {requests_since_pause} 件に到達しました。レートリミット対策のため {t}秒 休止します。")
                time.sleep(t)
            else:
                # 各処理間に1〜3秒の短いランダムな待機
                t = random.uniform(1.0, 3.0)
                log(f"   次の処理まで {t:.1f}秒 待機します。")
                time.sleep(t)

        # --- 商品ループ ---
        for i, row in enumerate(products):
            product_id = row[indices['商品ID']]
            if product_id in processed:
                log(f"⏩ スキップ: {product_id} (既に処理済み)")
                continue
            # 商品ステータス列が存在し、値が '1' の場合は売切れ扱いでスキップ（自動で処理済みに記録）
            status_idx = indices.get('商品ステータス')
            try:
                if status_idx is not None and row[status_idx].strip() == '1':
                    log(f"⏸️ スキップ: {product_id} (商品ステータス=1: 売切れ扱い)")
                    save_processed_id(product_id)
                    continue
            except Exception:
                # 参照エラーが出たら通常処理を続行
                pass

            product_name = row[indices['商品名']] or ""
            # 全角スペースを半角スペースに統一し、連続する空白は単一の半角スペースに
            product_name = product_name.replace('\u3000', ' ')
            product_name = ' '.join(product_name.split())
            # ラクマ用に商品名を制限（40文字以内）
            product_name = truncate_product_name(product_name, platform='rakuma')
            description = row[indices['商品説明']]
            price = row[indices['販売価格']]
            condition = row[indices['商品の状態']]
            shipping_payer = row[indices['配送料の負担']]
            prefecture = row[indices['発送元の地域']]
            days_to_ship = row[indices['発送までの日数']]
            days_to_ship = '3' # 「4-7日で発送」に固定

            log(f"\n🚀 {i+1}件目: {product_name} を出品処理中...")

            try:
                # ページ移動
                safe_goto(page, RAKUMA_NEW_ITEM_URL, wait_until='domcontentloaded')
                # 内部エラーページが出ていたらリトライ／スキップ処理
                ie_attempt = 0
                while is_internal_error_page(page):
                    ie_attempt += 1
                    if not handle_internal_error(page, product_id, ie_attempt, max_attempts=3):
                        raise Exception("内部エラーが継続したためスキップ")
                    # 再読み込み後にループ継続して確認

                # 不要な sleep を廃止。まずは要素が DOM に追加されているかだけ短くポーリングして確認する（visible を必須としない）
                selectors = ['input[type="file"][multiple]', 'input[placeholder="40文字まで"]', 'textarea']
                found = False
                start = time.time()
                timeout_sec = 5
                while time.time() - start < timeout_sec:
                    for sel in selectors:
                        try:
                            if page.locator(sel).count() > 0:
                                found = True
                                break
                        except Exception:
                            continue
                    if found:
                        break
                    time.sleep(0.1)
                if not found:
                    log("⚠️ 主要な入力要素が見つかりませんでした（続行します）")

                # --- 画像アップロード ---
                # 商品名または商品説明の先頭の数字を抽出
                image_number = None
                # 商品名から先頭の数字を抽出
                match = re.match(r'^(\d+)', product_name)
                if match:
                    image_number = match.group(1).lstrip('0')
                # 商品名にない場合は商品説明から抽出
                if not image_number:
                    match = re.match(r'^(\d+)', description)
                    if match:
                        image_number = match.group(1).lstrip('0')
                
                if not image_number:
                    log(f"⚠️ 商品名・説明から数字が抽出できませんでした: {product_id}")
                    log(f"   商品名: {product_name[:50]}")
                    continue
                
                image_pattern = os.path.join(IMAGE_DIR, f"{image_number}-*.jpg")
                # [修正] 文字列ソートの問題を解決するため、自然順ソートを行う
                image_files = glob.glob(image_pattern)
                
                # 画像が存在しない場合はスキップ
                if not image_files:
                    log(f"⚠️ 画像が見つかりません。この商品をスキップします: {product_id}")
                    log(f"   検索パターン: {image_pattern}")
                    
                    # Slack通知を送信
                    try:
                        import subprocess
                        subprocess.run([
                            r"..\venv\Scripts\python.exe", 
                            "send_slack_notification.py",
                            f"⚠️ ラクマ新規出品: 商品ID {product_id} の画像が見つかりません。\n商品名: {product_name[:50]}\n検索パターン: {image_pattern}",
                            "warning"
                        ], cwd=SCRIPT_DIR, check=False)
                    except Exception as e:
                        log(f"   Slack通知失敗: {e}")
                    
                    # 処理済みとしてマークしない（次回再試行できるように）
                    continue
                
                def natural_sort_key(s):
                    # ファイル名末尾の数字を抽出して数値として返す
                    match = re.search(r'-(\d+)\.jpg$', s)
                    return int(match.group(1)) if match else 0
                image_paths = sorted(image_files, key=natural_sort_key)

                if image_paths:
                    # 絶対パスに変換（UNC 等対策）
                    image_paths = [os.path.abspath(p) for p in image_paths]
                    log(f"📸 画像 {len(image_paths)} 枚をアップロード中... ({image_paths[0]} ...)")
                    try:
                        uploaded = False
                        used_selector = None

                        # 1) main uploader: multiple 属性を持つ input を優先
                        try:
                            multi_input = page.locator('input[type="file"][multiple]').first
                            if multi_input.count() > 0:
                                multi_input.set_input_files(image_paths)
                                uploaded = True
                                used_selector = 'input[type="file"][multiple]'
                                log(f"🔌 set_input_files を実行: {used_selector}")
                        except Exception as e:
                            log(f"⚠️ multiple input set_input_files 失敗: {e}")

                        # 2) accept 属性や汎用 input を試す（フォールバック）
                        if not uploaded:
                            file_input_selectors = [
                                'input[type="file"][accept="image/png, image/jpeg"]',
                                'input[type="file"][accept^="image"]',
                                'input[type="file"].chakra-input',
                                'input[type="file"]',
                            ]
                            for fi in file_input_selectors:
                                try:
                                    loc = page.locator(fi)
                                    if loc.count() > 0:
                                        loc.first.set_input_files(image_paths)
                                        uploaded = True
                                        used_selector = fi
                                        log(f"🔌 set_input_files を実行 (フォールバック): {fi}")
                                        break
                                except Exception as e:
                                    log(f"⚠️ set_input_files フォールバック例外 ({fi}): {e}")
                                    continue

                        # 3) 見た目のボタン→ file chooser（最後の手段）
                        if not uploaded:
                            upload_selectors = [
                                'label:has-text("画像を選択する") input[type="file"]',
                                'label input[type="file"][multiple]',
                                'div.chakra-button:has-text("画像を選択する")',
                                'button:has-text("画像を選択")',
                            ]
                            for sel in upload_selectors:
                                try:
                                    # input を直接見つけられれば set_input_files、なければボタンで file chooser
                                    loc = page.locator(sel)
                                    if loc.count() == 0:
                                        continue
                                    if loc.evaluate("el => el.tagName.toLowerCase() === 'input'"):
                                        loc.first.set_input_files(image_paths)
                                    else:
                                        with page.expect_file_chooser(timeout=30000) as fc_info:
                                            loc.first.click(force=True)
                                        fc = fc_info.value
                                        fc.set_files(image_paths)
                                    uploaded = True
                                    used_selector = sel
                                    log(f"🔌 file chooser フォールバックを実行: {sel}")
                                    break
                                except Exception as e:
                                    log(f"⚠️ file chooser フォールバック例外 ({sel}): {e}")
                                    continue

                        # 4) アップロード完了の検出 — HTML にある画像プレビュー要素を待つ
                        if uploaded:
                            # ページの実装に依らず、画像プレビュー領域の img タグを確認する
                            expected = len(image_paths)
                            preview_selector = 'div.css-1021eg4 img, div.css-1021eg4 picture img, div[data-testid^="image-"] img'
                            ok = False
                            timeout = 120  # タイムアウトを120秒に延長
                            try:
                                # プレビュー画像が表示されるまで待機
                                page.wait_for_function(
                                    expression=f"""(selector) => {{
                                        const count = document.querySelectorAll(selector).length;
                                        return count >= {expected};
                                    }}""",
                                    arg=preview_selector,
                                    timeout=timeout * 1000
                                )
                                ok = True
                            except Exception as e:
                                log(f"⚠️ 画像プレビューの待機中にエラー: {e}")
                                ok = False

                            if ok:
                                try:
                                    # 可能なら現在のプレビュー数を取得してログ
                                    cnt = 0
                                    try:
                                        cnt = page.locator(preview_selector).count()
                                    except Exception:
                                        cnt = expected
                                    log(f"✅ 画像アップロード完了を検知 (selector={used_selector}, preview_count={cnt})")
                                except Exception:
                                    log(f"✅ 画像アップロードを検知しました (selector={used_selector})")
                            else:
                                log("⚠️ 画像アップロードの検知に失敗しました（短時間で確認）。続行します。スクリーンショットを保存します。")
                                save_error_artifacts(page, product_id)
                        else:
                            log("⚠️ アップロードに失敗しました（input/button が操作できませんでした）。")
                    except Exception as e:
                        log(f"⚠️ 画像アップロード中に例外が発生しました: {e}")
                        save_error_artifacts(page, product_id)
                else:
                    log("⚠️ 該当する画像が見つかりません。")

                # --- 商品情報 ---
                log("✏️ 商品名・説明を入力...")
                # 複数候補のセレクタを試す（サイトにより name 属性が変わる）
                name_selectors = [
                    'input[name="item[name]"]',
                    'input[name="itemName"]',
                    'input[name="itemName"]',
                    'input[name^="item"]',
                    'input[placeholder="40文字まで"]',
                    'input.chakra-input[name]'
                ]
                filled_name = False
                for sel in name_selectors:
                    try:
                        if page.locator(sel).count() > 0:
                            el = page.locator(sel).first
                            el.scroll_into_view_if_needed()
                            try:
                                el.fill(product_name)
                            except Exception:
                                el.click(force=True)
                                el.fill(product_name)
                            filled_name = True
                            break
                    except Exception:
                        continue
                if not filled_name:
                    # JS フォールバック
                    try:
                        page.evaluate(
                            """(data) => {
                                const el = document.querySelector(data.selector);
                                if(!el) return false;
                                el.value = data.value;
                                el.dispatchEvent(new Event('input', {bubbles:true}));
                                el.dispatchEvent(new Event('change', {bubbles:true}));
                                return true;
                            }""",
                            {"selector": 'input[name="item[name]"], input[name="itemName"], input[placeholder="40文字まで"]', "value": product_name}
                        )
                    except Exception as e:
                        log(f"⚠️ 商品名のフォールバック設定に失敗しました: {e}")

                # 商品説明
                desc_selectors = [
                    'textarea[name="item[detail]"]',
                    'textarea[name="detail"]',
                    'textarea[name^="item"]',
                    'textarea.chakra-textarea'
                ]
                filled_desc = False
                for sel in desc_selectors:
                    try:
                        if page.locator(sel).count() > 0:
                            el = page.locator(sel).first
                            el.scroll_into_view_if_needed()
                            try:
                                el.fill(description)
                            except Exception:
                                el.click(force=True)
                                el.fill(description)
                            filled_desc = True
                            break
                    except Exception:
                        continue
                if not filled_desc:
                    # JS フォールバック
                    try:
                        page.evaluate(
                            """(data) => {
                                const el = document.querySelector(data.selector);
                                if(!el) return false;
                                el.value = data.value;
                                el.dispatchEvent(new Event('input', {bubbles:true}));
                                el.dispatchEvent(new Event('change', {bubbles:true}));
                                return true;
                            }""",
                            {"selector": 'textarea[name="item[detail]"], textarea[name="detail"]', "value": description}
                        )
                    except Exception as e:
                        log(f"⚠️ 商品説明のフォールバック設定に失敗しました: {e}")

                # --- カテゴリ選択（モーダルを開いて「レディース」→「フォーマル/ドレス」を順にクリック） ---
                try:
                    cat_value = "203"
                    cat_text = "レディース > フォーマル/ドレス > ナイトドレス"

                    # 1) カテゴリボタンを押してモーダルを開く
                    btn = None
                    if page.locator('button[name="category"]').count() > 0:
                        btn = page.locator('button[name="category"]').first
                    else:
                        grp_btn = page.locator('div.css-67lmaz:has-text("カテゴリ")').locator('..').locator('button')
                        if grp_btn.count() > 0:
                            btn = grp_btn.first
                    if btn:
                        try:
                            btn.scroll_into_view_if_needed()
                            safe_click(btn)
                        except Exception:
                            safe_click(btn, force=True)
                        try:
                            page.wait_for_selector('section[role="dialog"]', timeout=5000)
                        except Exception:
                            pass
                    else:
                        log("⚠️ カテゴリボタンが見つかりません。フォールバック処理を続行します。")

                    # 2) モーダル内でまず「レディース」をクリック（中間クリックを省くため明示的に実行）
                    top_group = "レディース"
                    try:
                        top_btn = page.locator(f'section[role="dialog"] button:has-text("{top_group}")')
                        if top_btn.count() == 0:
                            top_btn = page.locator(f'button:has-text("{top_group}")')
                        if top_btn.count() > 0:
                            try:
                                top_btn.first.scroll_into_view_if_needed()
                                safe_click(top_btn.first)
                            except Exception:
                                safe_click(top_btn.first, force=True)
                            # 少し待って子項目が展開されるのを待つ
                            try:
                                page.wait_for_timeout(200)
                            except Exception:
                                pass
                        else:
                            log(f"⚠️ モーダル内のトップカテゴリが見つかりません: {top_group}")
                    except Exception as e:
                        log(f"⚠️ トップカテゴリクリックで例外: {e}")

                    # 3) 「フォーマル/ドレス」をクリック
                    parent_text = "フォーマル/ドレス"
                    child_text = "ナイトドレス"
                    try:
                        # モーダル内で見る（優先）
                        parent_btn = page.locator(f'section[role="dialog"] div.css-1eziwv:has-text("{parent_text}")')
                        if parent_btn.count() == 0:
                            parent_btn = page.locator(f'section[role="dialog"] button:has-text("{parent_text}")')
                        if parent_btn.count() == 0:
                            parent_btn = page.locator(f'button:has-text("{parent_text}")')
                        if parent_btn.count() > 0:
                            try:
                                parent_btn.first.scroll_into_view_if_needed()
                                safe_click(parent_btn.first)
                            except Exception:
                                safe_click(parent_btn.first, force=True)
                        else:
                            log(f"⚠️ モーダル内の中カテゴリが見つかりません: {parent_text}")
                    except Exception as e:
                        log(f"⚠️ 中カテゴリクリックで例外: {e}")

                    # 4) 子項目「ナイトドレス」をクリック
                    try:
                        child_loc = page.locator(f'section[role="dialog"] div.css-1eziwv:has-text("{child_text}")')
                        if child_loc.count() == 0:
                            child_loc = page.locator(f'div.chakra-accordion__panel div.css-1eziwv:has-text("{child_text}")')
                        if child_loc.count() > 0:
                            try:
                                child_loc.first.scroll_into_view_if_needed()
                                safe_click(child_loc.first)
                                log(f"✅ モーダル内でカテゴリを選択しました: {top_group} -> {parent_text} -> {child_text}")
                            except Exception:
                                safe_click(child_loc.first, force=True)
                                log(f"✅ モーダル内でカテゴリを強制選択しました: {top_group} -> {parent_text} -> {child_text}")
                        else:
                            log("⚠️ モーダル内の子カテゴリ要素が見つかりませんでした。フォールバックでボタンを直接セットします。")
                            page.evaluate(
                                """(v, t) => {
                                    const b = document.querySelector('button[name="category"]');
                                    if (b) {
                                        b.value = v;
                                        b.textContent = t;
                                        b.dispatchEvent(new Event('input', {bubbles:true}));
                                        b.dispatchEvent(new Event('change', {bubbles:true}));
                                        return true;
                                    }
                                    return false;
                                }""",
                                cat_value,
                                cat_text
                            )
                    except Exception as e:
                        log(f"⚠️ 子カテゴリクリックで例外: {e}")

                    # 5) 保険: メイン画面のボタン表示と value を保証する
                    try:
                        page.evaluate(
                            """(v, t) => {
                                const b = document.querySelector('button[name="category"]');
                                if (b) {
                                    if ((b.textContent || '').indexOf(t) === -1) {
                                        b.value = v;
                                        b.textContent = t;
                                        b.dispatchEvent(new Event('input', {bubbles:true}));
                                        b.dispatchEvent(new Event('change', {bubbles:true}));
                                    }
                                }
                            }""",
                            cat_value,
                            cat_text
                        )
                    except Exception:
                        pass
                except Exception as e:
                    log(f"⚠️ カテゴリ選択処理で例外: {e}")

                # --- 配送方法を固定（かんたんラクマパック(日本郵便)） ---
                # --- 配送方法を固定（リファクタリングした関数を呼び出し） ---
                set_shipping_method(page)

                # --- サイズ ---（メルカリのサイズをラクマの選択肢に変換して設定）
                try:
                    # CSV にサイズ列があれば取得
                    mercari_size = None
                    if indices.get('サイズ') is not None:
                        try:
                            mercari_size = row[indices['サイズ']].strip()
                            if not mercari_size:
                                mercari_size = None
                        except Exception:
                            mercari_size = None
                    
                    # メルカリのサイズをラクマのサイズに変換
                    rakuma_size = convert_size_mercari_to_rakuma(mercari_size)
                    log(f"📏 サイズ変換: メルカリ「{mercari_size}」→ ラクマ「{rakuma_size}」")

                    # 1) サイズボタンを探してクリックしてモーダルを開く
                    size_btn = None
                    if page.locator('button[name="size"]').count() > 0:
                        size_btn = page.locator('button[name="size"]').first
                    else:
                        # ラベル近傍から探すフォールバック
                        grp_btn = page.locator('div.css-67lmaz:has-text("サイズ")').locator('..').locator('button')
                        if grp_btn.count() > 0:
                            size_btn = grp_btn.first
                    if size_btn:
                        try:
                            size_btn.scroll_into_view_if_needed()
                            safe_click(size_btn)
                        except Exception:
                            safe_click(size_btn, force=True)
                        # モーダルが開くのを待つ（短時間）
                        try:
                            page.wait_for_selector('section[role="dialog"]', timeout=3000)
                        except Exception:
                            pass

                    # 2) モーダル内の選択肢を探してクリック
                    picked = False
                    # 優先: モーダル内の代表的な選択肢要素
                    candidates = [
                        f'section[role="dialog"] div.css-17rawrb:has-text("{rakuma_size}")',
                        f'section[role="dialog"] div:has-text("{rakuma_size}")',
                        f'div.css-17rawrb:has-text("{rakuma_size}")',
                        f'div:has-text("{rakuma_size}")',
                    ]
                    for cs in candidates:
                        try:
                            loc = page.locator(cs)
                            if loc.count() > 0:
                                loc.first.scroll_into_view_if_needed()
                                safe_click(loc.first)
                                picked = True
                                break
                        except Exception:
                            continue

                    # 3) フォールバック: 部分一致で探す
                    if not picked and mercari_size:
                        try:
                            loc = page.locator(f'section[role="dialog"] div.css-17rawrb').filter(has_text=rakuma_size)
                            if loc.count() > 0:
                                safe_click(loc.first)
                                picked = True
                        except Exception:
                            pass

                    # 4) 最終フォールバック: モーダル内の最初の選択肢を選ぶ
                    if not picked:
                        try:
                            any_opt = page.locator('section[role="dialog"] div.css-17rawrb, section[role="dialog"] div div').first
                            if any_opt and any_opt.count() > 0:
                                any_opt.scroll_into_view_if_needed()
                                safe_click(any_opt)
                                picked = True
                        except Exception:
                            picked = False

                    if picked:
                        log(f"✅ サイズを選択しました: {rakuma_size}（メルカリ: {mercari_size}）")
                        # モーダル選択後、メイン画面のボタンに反映されているか確認。反映されていなければ強制セット
                        try:
                            page.wait_for_timeout(200)  # 少し待つ
                            # 確認: ボタンのテキストに選択済みのテキストが含まれるか
                            btn_text = ""
                            try:
                                if page.locator('button[name="size"]').count() > 0:
                                    btn_text = page.locator('button[name="size"]').first.inner_text().strip()
                            except Exception:
                                btn_text = ""
                            if rakuma_size not in btn_text:
                                # 強制セット
                                page.evaluate("""(t) => {
                                    const b = document.querySelector('button[name="size"]');
                                    if(b){ b.textContent = t; b.dispatchEvent(new Event('input',{bubbles:true})); b.dispatchEvent(new Event('change',{bubbles:true})); }
                                }""", rakuma_size)
                        except Exception:
                            pass
                    else:
                        log("⚠️ サイズ選択に失敗しました（要調整）")
                except Exception as e:
                    log(f"⚠️ サイズ処理で例外が発生しました: {e}")

                # --- 商品状態 (select またはラベル) ---
                cond = CONDITION_MAP.get(condition)
                if cond:
                    try:
                        # 優先: select[name="status"]
                        if page.locator('select[name="status"]').count() > 0:
                            page.locator('select[name="status"]').select_option(label=cond)
                        else:
                            # ラベル／ラジオの可能性を試す
                            lbl = page.get_by_label(cond, exact=True)
                            if lbl.count() > 0:
                                lbl.first.check()
                            else:
                                loc = page.locator(f'label:has-text("{cond}")')
                                if loc.count() > 0:
                                    loc.first.click(force=True)
                                else:
                                    log(f"⚠️ 商品状態用要素が見つかりません: {cond}")
                    except Exception as e:
                        log(f"⚠️ 商品状態選択に失敗しました: {e}")

                # --- 配送方法を固定（かんたんラクマパック(日本郵便)） ---
                # --- 配送方法を固定（リファクタリングした関数を呼び出し） ---
                # このブロックは重複しているため削除します。最初の呼び出しで十分です。

                # --- 配送料負担 ---
                payer = SHIPPING_PAYER_MAP.get(shipping_payer)
                if payer:
                    try:
                        if page.locator('select[name="carriage"]').count() > 0:
                            # select の option 表示は微妙に文言が違うことがあるので部分一致で探す
                            opts = page.locator('select[name="carriage"] option')
                            for i in range(opts.count()):
                                txt = opts.nth(i).inner_text().strip()
                                if payer in txt or txt in payer or payer.replace('（','(') in txt:
                                    val = opts.nth(i).get_attribute('value')
                                    page.locator('select[name="carriage"]').select_option(value=val)
                                    break
                        else:
                            page.get_by_label(payer, exact=True).check()
                    except Exception as e:
                        log(f"⚠️ 配送料負担選択に失敗しました: {e}")

                # --- 発送元地域 ---
                pref = PREFECTURE_MAP.get(prefecture)
                if pref:
                    try:
                        if page.locator('select[name="deliveryArea"]').count() > 0:
                            page.locator('select[name="deliveryArea"]').select_option(label=pref)
                        else:
                            page.locator('select[name="item[prefecture_code]"]').select_option(label=pref)
                    except Exception as e:
                        log(f"⚠️ 発送元地域選択に失敗しました: {e}")

                # --- 発送までの日数 ---
                days = DAYS_TO_SHIP_MAP.get(days_to_ship)
                if days:
                    try:
                        # select の option は value が 1/2/3 になっているので value で選択する（高速）
                        if page.locator('select[name="deliveryDate"]').count() > 0:
                            page.locator('select[name="deliveryDate"]').select_option(value=days_to_ship)
                        else:
                            page.get_by_label(days, exact=True).check()
                    except Exception as e:
                        # JS フォールバックで直接 value を設定
                        try:
                            page.evaluate("""(val) => {
                                const s = document.querySelector('select[name=\"deliveryDate\"]');
                                if(s){ s.value = val; s.dispatchEvent(new Event('change',{bubbles:true})); }
                            }""", days_to_ship)
                        except Exception:
                            log(f"⚠️ 発送までの日数選択に失敗しました: {e}")

                # --- 価格 ---
                log(f"💰 販売価格: {price}円")
                price_selectors = [
                    'input[name="item[sell_price]"]',
                    'input[name="sellPrice"]',
                    'input[name="sell_price"]',
                    'input[name="sellprice"]'
                ]
                for sel in price_selectors:
                    try:
                        if page.locator(sel).count() > 0:
                            page.locator(sel).first.fill(price)
                            break
                    except Exception:
                        continue

                log("✅ 入力完了。自動で確認→出品を実行します...")
                try:
                    # 1) 「確認する」ボタンを押す（モーダルではなく画面内のボタン）
                    confirm_btn = None
                    try:
                        confirm_btn = page.locator('button:has-text("確認する")')
                    except Exception:
                        pass
                    if confirm_btn and confirm_btn.count() > 0:
                        try:
                            confirm_btn.first.scroll_into_view_if_needed()
                            safe_click(confirm_btn.first)
                            log("🔁 「確認する」をクリックしました。")
                        except Exception:
                            safe_click(confirm_btn.first, force=True)
                            log("🔁 「確認する」を強制クリックしました。")
                    else:
                        log("⚠️ 「確認する」ボタンが見つかりません。手動確認ページへ進めない可能性があります。")

                    # 2) 確認ページの「出品する」ボタンを待ってクリックする
                    try:
                        # 確認ページのボタンを待つ
                        page.wait_for_selector('button:has-text("出品する"), button[type="submit"]:has-text("出品する")', timeout=10000)
                        submit_btn = page.locator('button:has-text("出品する"), button[type="submit"]:has-text("出品する")')
                        if submit_btn.count() > 0:
                            try:
                                submit_btn.first.scroll_into_view_if_needed()
                                # クリックして送信。送信後は遷移を少し待つ
                                safe_click(submit_btn.first)
                                log("🚀 「出品する」をクリックしました。送信中...")
                                # 送信によるページ遷移完了を待つ（URLが編集ページでなくなるまで）
                                try:
                                    page.wait_for_url(lambda url: "/edit" not in url, timeout=20000)
                                except Exception as wait_e:
                                    log(f"   完了ページの検出に失敗しました: {wait_e}")
                                    time.sleep(2)
                            except Exception:
                                safe_click(submit_btn.first, force=True)
                                log("🚀 「出品する」を強制クリックしました。")
                        else:
                            log("⚠️ 「出品する」ボタンが確認ページに見つかりませんでした。")
                    except Exception:
                        log("⚠️ 確認ページの「出品する」ボタン検出タイムアウト。手動確認が必要かもしれません。")

                    # 3) 成功扱いで加工済みに登録（必要なら成功判定を更に追加）
                    save_processed_id(product_id)
                    log(f"✅ {product_name} の処理完了（自動送信済み）。")
                except Exception as e:
                    log(f"❌ 自動送信処理で例外: {e}")
                    log("⚠️ 次の商品に進みます...")
                    # エラーが発生した場合はスキップして次へ
                    time.sleep(3)
                
                # 1件処理するごとに待機処理を入れる
                maybe_pause_for_rate_limit()

            except Exception as e:
                log(f"❌ エラー発生 ({product_name}): {e}")
                log("⚠️ 3秒後に次の商品に進みます...")
                time.sleep(3)
                # エラーが発生しても続行

        log("🎉 全商品処理完了！")
        context.close()

# --- 実行 ---
if __name__ == "__main__":
    process_products()
