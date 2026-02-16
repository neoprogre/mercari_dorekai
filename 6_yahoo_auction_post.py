#!/usr/bin/env python3
"""
毎日14品番自動出品スクリプト（Playwright版）
- 再出品 4品番：終了商品から「入札数→ウォッチ数→アクセス数」の降順
- 新規 10品番：downloads/product_data_*.csv から古い品番（下から順に）
- 期間：2日間、終了時間：午後11時から午前0時
- 1回出品したら二度と出品しない（重複なし）
"""

import os
import time
import sys
import re
import glob
import pandas as pd
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --- 設定 ---
SELLING_URL = "https://auctions.yahoo.co.jp/my/selling"
CLOSED_URL = "https://auctions.yahoo.co.jp/my/closed?hasWinner=0"
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "products_yahooku.csv")
PRODUCT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
USER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yahooku_user_data_firefox")
IMAGE_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images"
BRAND_MASTER_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand_master_sjis.csv")

# ログファイル
PROCESSED_RELIST_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed_relist_ids.txt")
POSTED_HINBAN_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posted_hinban_history.txt")

# 出品設定
MAX_ACTIVE_ITEMS = 100
DAILY_POST_COUNT = 50
DAILY_RELIST_COUNT = 12
DAILY_NEW_POST_COUNT = 12
AUCTION_DURATION = 2  # 2日間
AUCTION_END_TIME = 23  # 午後11時から午前0時

# 待機設定
PAGE_LOAD_TIMEOUT = 60000  # ミリ秒（60秒）
SCROLL_PAUSE = 1.0
DETAIL_WAIT = 0.8

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

def log(msg, level="info"):
    """ログ出力"""
    getattr(logging, level)(msg)

def load_brand_master():
    """ブランドマスターを読み込み、ブランドID→ブランド名の辞書を作成"""
    try:
        if not os.path.exists(BRAND_MASTER_CSV):
            log(f"ℹ️ ブランドマスターが見つかりません: {BRAND_MASTER_CSV}", level="info")
            return {}
        
        # 複数のエンコーディングを試す
        encodings = ['utf-8', 'shift_jis', 'cp932', 'utf-8-sig', 'latin-1']
        df = None
        used_encoding = None
        
        for encoding in encodings:
            try:
                df = pd.read_csv(BRAND_MASTER_CSV, encoding=encoding)
                used_encoding = encoding
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        if df is None:
            log(f"⚠️ ブランドマスターのエンコーディングが不明です", level="warning")
            return {}
        
        if 'ブランドID' not in df.columns or 'ブランド名' not in df.columns:
            log(f"⚠️ ブランドマスターに必要な列がありません", level="warning")
            return {}
        
        # ブランドID→ブランド名の辞書を作成（nanを除外）
        brand_dict = {}
        for _, row in df.iterrows():
            brand_id = row.get('ブランドID')
            brand_name = row.get('ブランド名')
            if pd.notna(brand_id) and pd.notna(brand_name):
                brand_dict[str(brand_id)] = str(brand_name)
        
        log(f"✅ ブランドマスター読み込み完了: {len(brand_dict)}件 ({used_encoding})")
        return brand_dict
    except Exception as e:
        log(f"⚠️ ブランドマスター読み込みエラー: {e}", level="warning")
        return {}

def load_processed_ids(log_file):
    """処理済みIDをファイルから読み込む"""
    if not os.path.exists(log_file):
        return set()
    with open(log_file, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def save_processed_id(item_id, log_file):
    """処理済みIDをファイルに追記"""
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{item_id}\n")

def load_posted_hinban(log_file):
    """出品済み品番を読み込む"""
    if not os.path.exists(log_file):
        return set()
    with open(log_file, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def save_posted_hinban(hinban, log_file):
    """出品済み品番を追記"""
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{hinban}\n")

def wait_for_items(page):
    """商品リストが表示されるまで待機"""
    try:
        page.wait_for_selector("#itm ul > li", timeout=PAGE_LOAD_TIMEOUT)
        return True
    except PlaywrightTimeoutError:
        return False

def scrape_page_items(page, status_label):
    """ページから商品情報を抽出"""
    page_items = []
    
    try:
        # 商品リストを取得
        product_elements = page.query_selector_all("#itm ul > li")
        
        if not product_elements:
            log("⚠️ 商品リストが見つかりません", level="warning")
            return []

        log(f"📊 {len(product_elements)} 件の商品を検出")

        for elem in product_elements:
            try:
                # タイトルとURL
                title_elem = elem.query_selector("a[data-cl-params*='_cl_link:tc']")
                if not title_elem:
                    continue
                    
                title = title_elem.text_content().strip()
                url = title_elem.get_attribute('href')
                
                # 価格
                price = "0"
                text_content = elem.text_content()
                price_match = re.search(r'([\d,]+)円', text_content)
                if price_match:
                    price = price_match.group(1).replace(',', '')

                # オークションIDを抽出
                auction_id = ""
                if url:
                    match = re.search(r'/auction/([a-zA-Z0-9]+)', url)
                    if match:
                        auction_id = match.group(1)

                if auction_id:
                    page_items.append({
                        'auction_id': auction_id,
                        'title': title,
                        'price': price,
                        'url': url,
                        'status': status_label,
                        'bids': '0',
                        'watch': '0',
                        'access': '0',
                    })
            except Exception as e:
                log(f"❌ 商品抽出エラー: {e}", level="error")
                continue

    except Exception as e:
        log(f"❌ ページ解析エラー: {e}", level="error")
    
    return page_items

def scrape_all_items(page):
    """出品中と終了商品をスクレイピング"""
    all_items = []
    
    # 出品中
    log("\n--- 出品中の商品をスクレイピング ---")
    page.goto(SELLING_URL)
    if wait_for_items(page):
        items = scrape_page_items(page, "出品中")
        all_items.extend(items)
        log(f"✅ 出品中: {len(items)} 件取得")
    
    # 終了（落札者なし）
    log("\n--- 終了商品をスクレイピング ---")
    page.goto(CLOSED_URL)
    if wait_for_items(page):
        items = scrape_page_items(page, "終了（落札者なし）")
        all_items.extend(items)
        log(f"✅ 終了: {len(items)} 件取得")
    
    return all_items

def get_latest_product_csv():
    """最新のproduct_data_*.csvファイルを取得"""
    pattern = os.path.join(PRODUCT_DATA_DIR, "product_data_*.csv")
    csv_files = glob.glob(pattern)
    if not csv_files:
        log(f"⚠️ product_data_*.csv が見つかりません: {pattern}", level="warning")
        return None
    
    # 最新のファイルを取得
    latest_file = max(csv_files, key=os.path.getmtime)
    return latest_file

def get_new_post_candidates():
    """CSVから新規出品候補を取得（古い順）"""
    csv_path = get_latest_product_csv()
    if not csv_path:
        return []
    
    try:
        df = pd.read_csv(csv_path, encoding='shift_jis')
        posted_hinban = load_posted_hinban(POSTED_HINBAN_LOG)
        
        log(f"📁 使用するCSV: {os.path.basename(csv_path)}")
        
        candidates = []
        seen_hinban = set()
        # 古い順（下から）で品番を取得
        for idx in range(len(df) - 1, -1, -1):
            row = df.iloc[idx]
            title = str(row.get('商品名', '')) if '商品名' in df.columns else ""
            title_match = re.match(r'^\s*(\d+)', title)
            if not title_match:
                continue

            product_status = str(row.get('商品ステータス', '')).strip()
            if product_status != '2':
                continue

            stock_raw = row.get('SKU1_現在の在庫数', 0)
            try:
                stock_num = int(float(str(stock_raw).replace(',', '').strip()))
            except Exception:
                stock_num = 0
            if stock_num < 1:
                continue

            if '品番' in df.columns:
                hinban = str(row.get('品番', '')).strip()
                if not hinban:
                    hinban = title_match.group(1)
            else:
                hinban = title_match.group(1)
            price = str(row.get('販売価格', '')) if '販売価格' in df.columns else "1000"
            description = str(row.get('商品説明', '')) if '商品説明' in df.columns else ""
            condition = str(row.get('商品の状態', '')) if '商品の状態' in df.columns else ""
            brand_id = str(row.get('ブランドID', '')) if 'ブランドID' in df.columns and pd.notna(row.get('ブランドID')) else ""
            
            # 価格を数値に変換（カンマ除去、空の場合は1000円）
            try:
                price = str(int(float(str(price).replace(',', '').replace('円', ''))))
            except:
                price = "1000"
            
            if (
                hinban
                and hinban not in posted_hinban
                and hinban not in seen_hinban
                and hinban != 'nan'
            ):
                candidates.append({
                    'hinban': hinban,
                    'title': title,
                    'price': price,
                    'description': description,
                    'condition': condition,
                    'brand_id': brand_id,
                })
                seen_hinban.add(hinban)
        
        log(f"📦 CSV候補: {len(candidates)} 件（既出品: {len(posted_hinban)} 件）")
        return candidates
    except Exception as e:
        log(f"❌ CSV読み込みエラー: {e}", level="error")
        return []

def relist_item(page, auction_id, hinban_hint=None):
    """商品を再出品する（全情報を更新）"""
    relist_url = f"https://auctions.yahoo.co.jp/sell/jp/show/resubmit?aID={auction_id}"
    log(f"  📝 再出品ページ: {relist_url}")
    page.goto(relist_url)
    time.sleep(3)

    try:        # ページ読み込み待機
        page.wait_for_load_state("networkidle", timeout=60000)
        time.sleep(2)
        # フォームが読み込まれるまで待機
        page.wait_for_selector("input[name='Title']", timeout=PAGE_LOAD_TIMEOUT)
        log("  ✅ フォーム読み込み完了")

        # --- 【新規追加】再出品時にも画像・価格・説明を更新 ---
        
        # タイトルから品番を抽出
        title_elem = page.query_selector("input[name='Title']")
        current_title = title_elem.get_attribute("value") if title_elem else ""
        
        extracted_hinban = None
        if hinban_hint:
            extracted_hinban = hinban_hint
        else:
            # タイトルから品番を抽出
            match = re.match(r'^(\d+)', current_title)
            if match:
                extracted_hinban = match.group(1).lstrip('0')
        
        if extracted_hinban:
            log(f"  🔍 品番を検出: {extracted_hinban}")
            # CSVから該当商品の情報を取得
            try:
                csv_path = get_latest_product_csv()
                if csv_path:
                    df = pd.read_csv(csv_path, encoding='shift_jis')
                    # 品番が一致する行を探す
                    for idx, row in df.iterrows():
                        csv_hinban = str(row.get('品番', ''))
                        if csv_hinban == extracted_hinban or csv_hinban.lstrip('0') == extracted_hinban:
                            # 画像を更新
                            image_pattern = os.path.join(IMAGE_DIR, f"{extracted_hinban}-*.jpg")
                            image_files = glob.glob(image_pattern)
                            if image_files:
                                # 自然順ソート
                                def natural_sort_key(s):
                                    match = re.search(r'-(\d+)\.jpg$', s)
                                    return int(match.group(1)) if match else 0
                                image_paths = sorted(image_files, key=natural_sort_key)
                                image_paths = [os.path.abspath(p) for p in image_paths[:10]]
                                
                                try:
                                    file_input = page.query_selector('input[type="file"]')
                                    if file_input:
                                        file_input.set_input_files(image_paths)
                                        log(f"  ✅ 画像を更新: {len(image_paths)}枚")
                                        time.sleep(2)
                                except Exception as e:
                                    log(f"  ⚠️ 画像更新エラー: {e}")
                            
                            # 価格を更新
                            try:
                                price = str(row.get('販売価格', ''))
                                if price and price != 'nan':
                                    price = str(int(float(str(price).replace(',', '').replace('円', ''))))
                                    price_input = page.query_selector("input[name='BidOrBuyPrice']")
                                    if not price_input:
                                        price_input = page.query_selector("input[name='StartPrice']")
                                    if price_input:
                                        price_input.click()
                                        price_input.fill("")
                                        price_input.type(price)
                                        log(f"  💰 価格を更新: {price}円")
                                        time.sleep(0.5)
                            except Exception as e:
                                log(f"  ⚠️ 価格更新エラー: {e}")
                            
                            # 説明を更新
                            try:
                                description = str(row.get('商品説明', ''))
                                if description and description != 'nan':
                                    iframe = page.frame(name="rteEditorComposition0")
                                    if not iframe:
                                        try:
                                            iframe = page.query_selector("iframe#rteEditorComposition0").content_frame()
                                        except:
                                            pass
                                    if iframe:
                                        desc_html = description.replace('\n', '<br>')
                                        iframe.evaluate(f"document.body.innerHTML = `{desc_html}`")
                                        log(f"  ✅ 説明を更新: {len(description)}文字")
                                        time.sleep(0.5)
                            except Exception as e:
                                log(f"  ⚠️ 説明更新エラー: {e}")
                            
                            break
            except Exception as e:
                log(f"  ⚠️ CSVから情報取得エラー: {e}")

        # 期間と終了時間を設定
        set_auction_duration_and_time(page)

        # 確認画面ボタンまでスクロール
        confirm_button = page.query_selector("#submit_form_btn")
        if confirm_button:
            # ボタンをビューポートの中央にスクロール
            page.evaluate("element => element.scrollIntoView({behavior: 'smooth', block: 'center'})", confirm_button)
            time.sleep(1.5)
            
            # ボタンをクリック
            confirm_button.click(timeout=10000)
            log("  ✅ 確認画面へ進みました")
            time.sleep(2)

        # 「出品する」ボタン
        final_submit = page.query_selector("#auc_preview_submit_up")
        if final_submit:
            final_submit.click()
            log("  ✅ 出品しました")

            # 完了を待つ
            try:
                page.wait_for_url(lambda url: "show/complete" in url or "my/selling" in url, timeout=30000)
            except:
                pass
            
            log(f"  ✅ {auction_id} の再出品完了（全情報更新）")
            return True

    except Exception as e:
        log(f"  ❌ 再出品エラー: {e}", level="error")
        return False
    
    return False

def post_new_item(page, hinban, title, price="1000", description="", condition="", brand_id=""):
    """CSVから新規出品する"""
    new_post_url = "https://auctions.yahoo.co.jp/jp/show/submit?category=0"
    log(f"  📝 新規出品ページ: {new_post_url}")
    
    # ページ遷移（最大2回リトライ）
    for attempt in range(2):
        try:
            page.goto(new_post_url, wait_until="domcontentloaded", timeout=60000)
            
            # ページ読み込み待機
            try:
                page.wait_for_load_state("networkidle", timeout=45000)
            except:
                log("　　⚠️ networkidleタイムアウト、続行します")
            
            time.sleep(5)  # 3秒→5秒に延長
            
            # タイトル入力フィールドが表示されるまで待機
            page.wait_for_selector("input[name='Title']", timeout=45000)
            log("  ✅ フォーム読み込み完了")
            
            # カテゴリ選択処理
            try:
                category_button = page.query_selector("#acMdCateChange")
                if category_button and category_button.get_attribute("value") == "選択する":
                    log("  📂 カテゴリを選択中...")
                    # スクロールしてからクリック
                    page.evaluate("element => element.scrollIntoView({behavior: 'smooth', block: 'center'})", category_button)
                    time.sleep(0.5)
                    category_button.click(timeout=10000)
                    time.sleep(2)
                    
                    # topsubmit ページに遷移したことを確認
                    page.wait_for_url("**/topsubmit*", timeout=10000)
                    
                    # 「履歴から選択する」タブをクリック
                    history_tab = page.query_selector('a[data-cl-params*="sellhis"]')
                    if history_tab:
                        history_tab.click()
                        time.sleep(1)
                        log("  ✅ 履歴タブに切り替えました")
                        
                        # 履歴ローダーが消えるまで待機
                        try:
                            page.wait_for_selector("#historyLoader.is-hide", timeout=10000)
                        except:
                            pass
                        
                        # 最初のカテゴリラジオボタンを選択
                        first_category = page.query_selector('input[name="category"][type="radio"]')
                        if first_category:
                            first_category.click()
                            time.sleep(0.5)
                            
                            # カテゴリ名を取得
                            category_label = page.query_selector(f'label[for="{first_category.get_attribute("id")}"]')
                            if category_label:
                                category_text = category_label.text_content().split('（')[0].strip()
                                log(f"  ✅ カテゴリ選択: {category_text[:60]}")
                            
                            # 「このカテゴリに出品」ボタンをクリック
                            submit_button = page.query_selector("#history_category_submit")
                            if submit_button:
                                # ボタンをスクロールして表示
                                page.evaluate("element => element.scrollIntoView({behavior: 'smooth', block: 'center'})", submit_button)
                                time.sleep(0.5)
                                submit_button.click(timeout=10000)
                                time.sleep(2)
                                
                                # submit ページに戻るまで待機
                                page.wait_for_url("**/submit", timeout=10000)
                                page.wait_for_selector("input[name='Title']", timeout=10000)
                                log("  ✅ カテゴリ選択完了")
                            else:
                                log("  ⚠️ 「このカテゴリに出品」ボタンが見つかりません")
                        else:
                            log("  ⚠️ 履歴にカテゴリが見つかりません")
                    else:
                        log("  ⚠️ 履歴タブが見つかりません")
                elif category_button and category_button.get_attribute("value") == "変更する":
                    log("  ℹ️ カテゴリは既に選択されています")
                else:
                    log("  ℹ️ カテゴリ選択ボタンが見つかりません")
            except Exception as e:
                log(f"  ⚠️ カテゴリ選択でエラー（続行します）: {str(e)[:80]}")
            
            break  # 成功したらループを抜ける
            
        except Exception as e:
            if attempt == 0:
                log(f"  ⚠️ ページ読み込み失敗、リトライします... ({str(e)[:80]})")
                time.sleep(5)
            else:
                # 最終試行でも失敗 - デバッグ情報を保存
                log(f"  ❌ 新規出品ページの読み込みに失敗: 現在のURL: {page.url}")
                try:
                    # スクリーンショット保存
                    screenshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                                   f"error_new_post_{hinban}_{int(time.time())}.png")
                    page.screenshot(path=screenshot_path)
                    log(f"  📸 エラー画面を保存: {screenshot_path}")
                    
                    # HTML保存
                    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                            f"error_new_post_{hinban}_{int(time.time())}.html")
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(page.content())
                    log(f"  📄 HTMLを保存: {html_path}")
                except:
                    pass
                raise

    try:
        # 画像アップロード
        image_number = None
        # 品番から先頭の数字を抽出
        match = re.match(r'^(\d+)', hinban)
        if match:
            image_number = match.group(1).lstrip('0')
        # 品番にない場合はタイトルから抽出
        if not image_number:
            match = re.match(r'^(\d+)', title)
            if match:
                image_number = match.group(1).lstrip('0')
        
        if not image_number:
            log(f"  ⚠️ 品番・タイトルから数字が抽出できませんでした: {hinban}")
            log(f"     品番: {hinban}, タイトル: {title[:50]}")
            return False
        
        image_pattern = os.path.join(IMAGE_DIR, f"{image_number}-*.jpg")
        image_files = glob.glob(image_pattern)
        
        # 画像が存在しない場合は失敗
        if not image_files:
            log(f"  ⚠️ 画像が見つかりません: {hinban}", level="warning")
            log(f"     検索パターン: {image_pattern}")
            return False
        
        # 自然順ソート
        def natural_sort_key(s):
            match = re.search(r'-(\d+)\.jpg$', s)
            return int(match.group(1)) if match else 0
        image_paths = sorted(image_files, key=natural_sort_key)
        image_paths = [os.path.abspath(p) for p in image_paths]
        
        # 最大10枚まで
        if len(image_paths) > 10:
            image_paths = image_paths[:10]
            log(f"  ℹ️ 画像が10枚を超えているため、最初の10枚のみ使用します")
        
        log(f"  📸 画像 {len(image_paths)} 枚をアップロード中...")
        
        # 画像アップロード処理
        uploaded = False
        try:
            # Yahoo Auctionsの画像アップロード input を探す
            file_input = page.query_selector('input[type="file"][name="auc_image"]')
            if not file_input:
                file_input = page.query_selector('input[type="file"][multiple]')
            if not file_input:
                file_input = page.query_selector('input[type="file"]')
            
            if file_input:
                # 複数画像を一度にアップロード
                page.locator('input[type="file"]').first.set_input_files(image_paths)
                uploaded = True
                log(f"  ✅ 画像アップロード完了")
                
                # プレビュー読み込みを待つ
                time.sleep(3)
            else:
                log(f"  ⚠️ 画像アップロード input が見つかりません")
                return False
        except Exception as e:
            log(f"  ❌ 画像アップロードエラー: {e}", level="error")
            return False

        # タイトルを入力
        title_input = page.query_selector("input[name='Title']")
        if title_input:
            title_input.fill(title)
            log(f"  ✅ タイトル入力完了: {title[:30]}")

        # ブランド入力
        if brand_id:
            try:
                brand_master = load_brand_master()
                brand_name = brand_master.get(brand_id, '')
                
                if brand_name:
                    log(f"  🏷️ ブランド入力中: {brand_name}")
                    brand_input = page.query_selector("input#brand_line_text")
                    if brand_input:
                        # フィールドをクリックしてフォーカス
                        brand_input.click()
                        time.sleep(0.3)
                        
                        # 既存の値をクリア（Ctrl+Aで全選択して削除）
                        brand_input.press('Control+A')
                        brand_input.press('Backspace')
                        time.sleep(0.3)
                        
                        # ブランド名を1文字ずつタイピング（人間のように）
                        log(f"  ✏️ 入力中: {brand_name}")
                        brand_input.type(brand_name, delay=100)  # 100msの遅延でタイピング
                        time.sleep(1.5)  # AutoCompleteの表示を待つ
                        
                        # AutoCompleteのリストが表示されるまで待つ
                        try:
                            page.wait_for_selector(".AutoComplete__items li", timeout=5000)
                            time.sleep(0.5)  # 追加待機
                            
                            # 全ての候補を取得
                            all_items = page.query_selector_all(".AutoComplete__items li")
                            log(f"  🔍 候補数: {len(all_items)}件")
                            
                            # 完全一致を探す
                            matched_item = None
                            for item_el in all_items:
                                item_text = item_el.text_content().strip()
                                if item_text == brand_name:
                                    matched_item = item_el
                                    log(f"  ✅ 完全一致見つかりました: {item_text}")
                                    break
                            
                            # 完全一致がなければ最初の候補を使用
                            if not matched_item and all_items:
                                matched_item = all_items[0]
                                log(f"  ℹ️ 完全一致なし、最初の候補を使用: {matched_item.text_content().strip()}")
                            
                            if matched_item:
                                matched_text = matched_item.text_content().strip()
                                # JavaScriptでクリックイベントを発火
                                page.evaluate("""(element) => {
                                    element.click();
                                    element.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                                    element.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                                }""", matched_item)
                                time.sleep(1.5)  # 待機時間を延長
                                
                                # 選択が成功したか確認
                                brand_line_id_input = page.query_selector("input#brand_line_id")
                                brand_text_input = page.query_selector("input#brand_line_text")
                                
                                if brand_line_id_input and brand_line_id_input.get_attribute("value"):
                                    selected_id = brand_line_id_input.get_attribute("value")
                                    
                                    # テキストフィールドに値が設定されているか確認
                                    text_value = brand_text_input.get_attribute("value") if brand_text_input else ""
                                    if not text_value or text_value == "":
                                        # 明示的にテキストフィールドに値を設定
                                        log(f"  ℹ️ テキストフィールドが空のため、明示的に設定します")
                                    matched_text_escaped = matched_text.replace("\\", "\\\\").replace("'", "\\'")
                                    brand_text_input.evaluate(f"""
                                        (input) => {{
                                            input.value = '{matched_text_escaped}';
                                        }}
                                    """)
                            else:
                                log(f"  ℹ️ ブランド候補が見つかりません", level="info")
                        except:
                            log(f"  ℹ️ ブランド自動補完が表示されませんでした", level="info")
                    else:
                        log(f"  ⚠️ ブランド入力欄が見つかりません", level="warning")
                else:
                    log(f"  ℹ️ ブランドID {brand_id} はマスタに存在しません", level="info")
            except Exception as e:
                log(f"  ⚠️ ブランド入力エラー: {str(e)[:80]}", level="warning")

        # 商品説明を入力
        if description and description != 'nan':
            try:
                # RTEエディタのiframeに入力
                iframe = page.frame(name="rteEditorComposition0")
                if not iframe:
                    iframe = page.query_selector("iframe#rteEditorComposition0").content_frame()
                
                if iframe:
                    # iframeのbodyにJavaScriptで直接HTML/テキストを設定
                    # 改行をbrタグに変換
                    desc_html = description.replace('\n', '<br>')
                    iframe.evaluate(f"document.body.innerHTML = `{desc_html}`")
                    log(f"  ✅ 商品説明入力完了: {len(description)}文字")
                    time.sleep(0.5)
                else:
                    log(f"  ℹ️ 商品説明エディタが見つかりません", level="info")
            except Exception as e:
                log(f"  ⚠️ 商品説明入力エラー: {str(e)[:80]}", level="warning")

        # 価格を入力
        try:
            # まず即決価格（フリマモード）を試す
            price_input = page.query_selector("input[name='BidOrBuyPrice']")
            if not price_input:
                # オークションモードの開始価格
                price_input = page.query_selector("input[name='StartPrice']")
            
            if price_input:
                # フィールドをクリアしてから入力
                price_input.click()
                price_input.fill("")
                price_input.type(price)
                log(f"  💰 価格設定: {price}円")
                time.sleep(0.5)
            else:
                log(f"  ⚠️ 価格入力フィールドが見つかりません", level="warning")
                # デバッグ: 価格関連のフィールドを探す
                all_inputs = page.query_selector_all("input[type='text'], input[type='number']")
                log(f"  🔍 入力フィールド数: {len(all_inputs)}")
        except Exception as e:
            log(f"  ⚠️ 価格設定エラー: {e}", level="warning")

        # 期間と終了時間を設定
        set_auction_duration_and_time(page)

        # スクロール
        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        # 「確認画面へ」ボタン
        confirm_button = page.query_selector("#submit_form_btn")
        if confirm_button:
            confirm_button.click()
            log("  ✅ 確認画面へ進みました")
            time.sleep(3)  # 確認画面の読み込み待機を延長
            
            # 確認画面のURLチェック
            current_url = page.url
            log(f"  🔍 現在のURL: {current_url}")
            
            # エラーメッセージの確認
            error_msgs = page.query_selector_all(".error, .ErrorMessage, .Warning__text, [class*='error'], [class*='Error']")
            if error_msgs:
                for msg in error_msgs[:3]:  # 最初の3つまで
                    error_text = msg.text_content().strip()
                    if error_text:
                        log(f"  ⚠️ エラーメッセージ: {error_text[:100]}", level="warning")
        else:
            log("  ❌ 確認画面ボタンが見つかりません", level="error")
            return False

        # 「出品する」ボタン
        final_submit = page.query_selector("#auc_preview_submit_up")
        if final_submit:
            log("  🔘 最終出品ボタンをクリック中...")
            final_submit.click()
            log("  ✅ 出品ボタンをクリックしました")

            # 完了を待つ
            try:
                page.wait_for_url(lambda url: "show/complete" in url or "my/selling" in url, timeout=30000)
                log(f"  ✅ {hinban} の新規出品完了")
                return True
            except Exception as wait_error:
                # タイムアウト後のURL確認
                final_url = page.url
                log(f"  ⚠️ 完了待機タイムアウト。現在のURL: {final_url}", level="warning")
                
                # エラーメッセージの再確認
                error_msgs = page.query_selector_all(".error, .ErrorMessage, .Warning__text, [class*='error'], [class*='Error']")
                if error_msgs:
                    for msg in error_msgs[:3]:
                        error_text = msg.text_content().strip()
                        if error_text:
                            log(f"  ❌ エラー: {error_text[:150]}", level="error")
                
                # デバッグ情報を保存
                try:
                    debug_dir = os.path.dirname(os.path.abspath(__file__))
                    timestamp = int(time.time())
                    
                    # スクリーンショット
                    screenshot_path = os.path.join(debug_dir, f"error_submit_{hinban}_{timestamp}.png")
                    page.screenshot(path=screenshot_path)
                    log(f"  📸 スクリーンショット: {screenshot_path}")
                    
                    # HTML保存
                    html_path = os.path.join(debug_dir, f"error_submit_{hinban}_{timestamp}.html")
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(page.content())
                    log(f"  📄 HTML保存: {html_path}")
                except Exception as save_error:
                    log(f"  ⚠️ デバッグ情報保存失敗: {save_error}")
                
                return False
        else:
            log("  ❌ 最終出品ボタンが見つかりません", level="error")
            log(f"  🔍 現在のURL: {page.url}")
            
            # デバッグ情報を保存
            try:
                debug_dir = os.path.dirname(os.path.abspath(__file__))
                timestamp = int(time.time())
                screenshot_path = os.path.join(debug_dir, f"error_no_submit_btn_{hinban}_{timestamp}.png")
                page.screenshot(path=screenshot_path)
                log(f"  📸 スクリーンショット: {screenshot_path}")
            except:
                pass
            
            return False

    except Exception as e:
        log(f"  ❌ 新規出品エラー: {e}", level="error")
        return False
    
    return False

def set_auction_duration_and_time(page):
    """期間と終了時間を設定、発送方法も確認"""
    try:
        # 終了日時を2日後に設定
        from datetime import datetime, timedelta
        today = datetime.now()
        target_date = today + timedelta(days=2)
        target_date_str = target_date.strftime("%Y-%m-%d")
        
        date_select = page.query_selector("select[name='ClosingYMD']")
        if date_select:
            date_select.select_option(target_date_str)
            log(f"  ✅ 終了日を {target_date.strftime('%Y年%m月%d日')} に設定")

        # 終了時間を設定（午後11時から午前0時）
        time_select = page.query_selector("select[name='AuctionEndHour']")
        if time_select:
            time_select.select_option(str(AUCTION_END_TIME))
            log(f"  ✅ 終了時間を {AUCTION_END_TIME} 時（午後11時～午前0時）に設定")

        # 配送方法を設定（ゆうパケット優先）
        time.sleep(2)
        try:
            # ゆうパケット（優先）
            shipping_methods = [
                ("input[data-delivertype='is_jp_yupacket_official_ship']", "ゆうパケット"),
                ("input[data-delivertype*='yupacket']", "ゆうパケット（フォールバック）"),
            ]
            
            shipping_set = False
            for selector, label in shipping_methods:
                shipping_radio = page.query_selector(selector)
                if shipping_radio:
                    # ページの一番下までスクロール
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(1)
                    
                    # 要素の位置までスクロール
                    try:
                        shipping_radio.scroll_into_view_if_needed()
                    except:
                        pass
                    time.sleep(1)
                    
                    # JavaScriptで直接クリック（より確実）
                    try:
                        page.evaluate(f"document.querySelector(\"{selector}\").click()")
                    except:
                        shipping_radio.click()
                    
                    log(f"  ✅ 配送方法を『{label}』に設定")
                    time.sleep(0.5)
                    shipping_set = True
                    break
            
            if not shipping_set:
                log("  ℹ️ 推奨配送方法が見つかりません（デフォルト設定のまま続行）", level="info")
                
        except Exception as e:
            log(f"  ℹ️ 配送方法設定スキップ: {str(e)[:80]}", level="info")

    except Exception as e:
        log(f"  ⚠️ 期間/時間設定エラー: {e}", level="warning")

def main():
    log("=" * 50)
    log("🚀 毎日自動出品スクリプト開始")
    log("=" * 50)

    # Playwright コンテキスト起動
    with sync_playwright() as p:
        # ユーザーデータを保持してブラウザを起動
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        context = p.firefox.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,  # ブラウザを表示
        )
        page = context.pages[0] if context.pages else context.new_page()
        
        try:
            # ログイン確認
            log("\n🔑 ログイン状態を確認中...")
            page.goto("https://auctions.yahoo.co.jp/jp/show/mystatus?select=selling", timeout=60000)
            
            # ログインページの場合は手動ログインを待つ
            if "login" in page.url.lower():
                log("⚠️ ログインが必要です。ブラウザで手動ログインしてください。")
                log("⏳ ログイン完了後、Enterキーを押してください...")
                input()  # ユーザーがEnterを押すまで待機
                
                # ログイン後のURL確認（最大10分待機）
                try:
                    page.wait_for_url(lambda url: "login" not in url.lower(), timeout=600000)
                    log("✅ ログイン完了を確認しました")
                except PlaywrightTimeoutError:
                    log("❌ ログインタイムアウト", level="error")
                    return
            else:
                log("✅ すでにログイン済みです")
            
            # スクレイピング
            log("\n【ステップ1】現在の出品状況をスクレイピング")
            all_items = scrape_all_items(page)
            
            df = pd.DataFrame(all_items)
            for col in ['bids', 'watch', 'access', 'price']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            active_items = df[df['status'] == '出品中']
            ended_items = df[df['status'] == '終了（落札者なし）'].copy()
            
            log(f"\n📊 現況: 出品中 {len(active_items)} 件 / 終了 {len(ended_items)} 件")
            
            available_slots = MAX_ACTIVE_ITEMS - len(active_items)
            if available_slots <= 0:
                log(f"⚠️ 出品数が上限に達しています。出品できません。", level="warning")
                return
            
            log(f"📍 本日の出品枠: {available_slots} 件")

            # 本日の出品数を決定（再出品と新規を公平に配分）
            if available_slots >= DAILY_POST_COUNT:
                # 枠が十分ある場合：再出品7 + 新規7
                relist_count = DAILY_RELIST_COUNT
                new_post_count = DAILY_NEW_POST_COUNT
            else:
                # 枠が不足している場合：半分ずつ配分
                relist_count = min(DAILY_RELIST_COUNT, available_slots // 2)
                new_post_count = min(DAILY_NEW_POST_COUNT, available_slots - relist_count)
            
            total_to_post = relist_count + new_post_count

            log(f"\n🎯 本日の出品予定: {total_to_post} 件（再出品 {relist_count} + 新規 {new_post_count}）")

            # ========== 再出品（アルゴリズム） ==========
            if relist_count > 0 and not ended_items.empty:
                log(f"\n【ステップ2】再出品対象を選定（入札>ウォッチ>アクセス）")
                
                processed_ids = load_processed_ids(PROCESSED_RELIST_LOG)
                ended_items_relist = ended_items[~ended_items['auction_id'].isin(processed_ids)].copy()
                
                # タイトル重複排除
                active_titles = set(active_items['title'].unique())
                ended_items_relist = ended_items_relist[~ended_items_relist['title'].isin(active_titles)]
                
                if not ended_items_relist.empty:
                    ended_items_relist.sort_values(by=['bids', 'watch', 'access'], ascending=False, inplace=True)
                    items_to_relist = ended_items_relist.head(relist_count)
                    
                    log(f"✅ 再出品対象: {len(items_to_relist)} 件")
                    
                    for idx, (_, item) in enumerate(items_to_relist.iterrows(), 1):
                        auction_id = item['auction_id']
                        title = item['title']
                        log(f"\n【{idx}/{len(items_to_relist)}】再出品: {title[:40]}")
                        
                        # タイトルから品番を抽出（ヒント情報として渡す）
                        hinban_hint = None
                        match = re.match(r'^(\d+)', title)
                        if match:
                            hinban_hint = match.group(1).lstrip('0')
                        
                        if relist_item(page, auction_id, hinban_hint):
                            save_processed_id(auction_id, PROCESSED_RELIST_LOG)
                            time.sleep(5)
                        else:
                            log(f"⚠️ {auction_id} 再出品失敗", level="warning")
                            save_processed_id(auction_id, PROCESSED_RELIST_LOG)
                else:
                    log("ℹ️ 再出品対象なし", level="info")

            # ========== 新規出品（CSV古い順） ==========
            if new_post_count > 0:
                log(f"\n【ステップ3】新規出品対象を選定（CSV古い順）")
                
                candidates = get_new_post_candidates()
                items_to_post = candidates[:new_post_count]
                
                log(f"✅ 新規出品対象: {len(items_to_post)} 件")
                
                for idx, item in enumerate(items_to_post, 1):
                    hinban = item['hinban']
                    title = item['title'][:50]
                    price = item.get('price', '1000')
                    description = item.get('description', '')
                    condition = item.get('condition', '')
                    brand_id = item.get('brand_id', '')
                    log(f"\n【{idx}/{len(items_to_post)}】新規出品: {hinban} - {title}")
                    
                    if post_new_item(page, hinban, title, price, description, condition, brand_id):
                        save_posted_hinban(hinban, POSTED_HINBAN_LOG)
                        time.sleep(5)
                    else:
                        log(f"⚠️ {hinban} 新規出品失敗", level="warning")
                        save_posted_hinban(hinban, POSTED_HINBAN_LOG)

            log("\n" + "=" * 50)
            log("✅ 本日の出品処理完了")
            log("=" * 50)

        except Exception as e:
            log(f"❌ エラー: {e}", level="error")
        
        finally:
            log("\n💤 ブラウザを開いたままにします。手動で閉じてください。")
            context.close()

if __name__ == "__main__":
    main()
