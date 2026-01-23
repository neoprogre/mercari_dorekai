import os
import csv
import time
import sys
import re
import pandas as pd
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

try:
    # 既存のドライバセットアップ関数を再利用
    from yahooku_dorekai import setup_driver
except ImportError:
    print("yahooku_dorekai.py が見つかりません。同じディレクトリに配置してください。")
    sys.exit(1)

# --- 設定 ---
# 出品中
SELLING_URL = "https://auctions.yahoo.co.jp/my/selling"
# 落札者なし（終了分）
CLOSED_URL = "https://auctions.yahoo.co.jp/my/closed?hasWinner=0"
# 出力するCSVファイル名
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "products_yahooku.csv")
# 再出品処理済みログ
PROCESSED_RELIST_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed_relist_ids.txt")
# アクティブな出品数の上限
MAX_ACTIVE_ITEMS = 100

def log(msg):
    """タイムスタンプ付きでログを出力する"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def get_management_info(driver, url):
    """商品詳細ページ（管理画面）からアクセス数・ウォッチ数・入札数を取得"""
    info = {'access': '0', 'watch': '0', 'bids': '0'}
    if not url:
        return info
        
    original_window = driver.current_window_handle
    
    try:
        # 新しいタブを開く
        driver.switch_to.new_window('tab')
        driver.get(url)
        time.sleep(1.5) # ページ読み込み待ち

        # 管理セクション (id="management") 内の情報を取得
        # アクセス数
        try:
            elem = driver.find_element(By.XPATH, "//*[@id='management']//p[contains(text(), 'アクセス')]/ancestor::li[1]//span")
            info['access'] = elem.text.strip()
        except NoSuchElementException:
            pass

        # ウォッチ数
        try:
            elem = driver.find_element(By.XPATH, "//*[@id='management']//p[contains(text(), 'ウォッチ')]/ancestor::li[1]//span")
            info['watch'] = elem.text.strip()
        except NoSuchElementException:
            pass

        # 入札数
        try:
            elem = driver.find_element(By.XPATH, "//*[@id='management']//p[contains(text(), '入札')]/ancestor::li[1]//span")
            info['bids'] = elem.text.strip()
        except NoSuchElementException:
            pass

    except Exception as e:
        log(f"  ❌ 詳細情報取得エラー: {e}")
    finally:
        # タブを閉じて元のウィンドウに戻る
        try:
            if len(driver.window_handles) > 1:
                driver.close()
            driver.switch_to.window(original_window)
        except Exception:
            pass
        
    return info

def scrape_page_items(driver, status_label):
    """現在のページから商品情報を抽出する"""
    page_items = []
    
    # マイ・オークション用のセレクタ戦略
    # div#itm 以下の li 要素を取得
    try:
        # 商品リストのコンテナを探す
        product_elements = driver.find_elements(By.CSS_SELECTOR, "#itm ul > li")
        
        if not product_elements:
            log("⚠️ 商品リストが見つかりません (#itm ul > li)。")
            return []

        log(f"📊 {len(product_elements)} 件の商品要素が見つかりました。")

        for elem in product_elements:
            try:
                # タイトルとURL
                # data-cl-params に _cl_link:tc が含まれるリンクを探す
                title_elem = elem.find_element(By.CSS_SELECTOR, "a[data-cl-params*='_cl_link:tc']")
                title = title_elem.text.strip()
                url = title_elem.get_attribute('href')
                
                # 画像
                # data-cl-params に _cl_link:ic が含まれるリンク内の img
                try:
                    img_elem = elem.find_element(By.CSS_SELECTOR, "a[data-cl-params*='_cl_link:ic'] img")
                    image_url = img_elem.get_attribute('src')
                except NoSuchElementException:
                    image_url = ""

                # 価格
                # 円を含む要素を探す
                price = "0"
                try:
                    text_content = elem.text
                    price_match = re.search(r'([\d,]+)円', text_content)
                    if price_match:
                        price = price_match.group(1).replace(',', '')
                except Exception:
                    pass

                # 残り時間
                time_left = ""
                try:
                    time_elem = elem.find_element(By.CSS_SELECTOR, "svg[aria-label='残り時間'] + span")
                    time_left = time_elem.text.strip()
                except NoSuchElementException:
                    pass

                # URLからオークションIDを抽出
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
                        'time_left': time_left,
                    })
            except NoSuchElementException:
                continue
            except Exception as e:
                log(f"❌ 商品情報抽出中にエラー: {e}")
                continue

        # 各商品の詳細ページから追加情報を取得
        for item in page_items:
            log(f"  🔍 詳細情報を取得中: {item['title'][:20]}...")
            mgmt_info = get_management_info(driver, item['url'])
            item.update(mgmt_info)
            time.sleep(1) # 負荷軽減

    except Exception as e:
        log(f"❌ ページ解析中にエラー: {e}")
    
    return page_items

def scrape_url(driver, start_url, status_label):
    """指定されたURLからページネーションしながら全商品をスクレイピング"""
    all_items = []
    current_url = start_url
    
    while True:
        log(f"ページ移動: {current_url}")
        driver.get(current_url)
        time.sleep(3) # 読み込み待機

        # --- ログイン処理 ---
        if "login.yahoo.co.jp" in driver.current_url:
            log("🔒 ログインが必要です。ブラウザでログインを完了してください。")
            input("👉 ログイン完了後、このターミナルでEnterキーを押してください: ")
            log("✅ ログインを検知しました。処理を再開します。")
            driver.get(current_url)
            time.sleep(3)

        # スクロールして読み込み
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        # アイテム抽出
        items = scrape_page_items(driver, status_label)
        if items:
            all_items.extend(items)
            log(f"  -> {len(items)} 件取得 (合計: {len(all_items)} 件)")
        else:
            log("  -> 商品が見つかりませんでした。")

        # --- 次のページがあるか確認 ---
        try:
            # "次へ" リンクを探す
            next_link = None
            links = driver.find_elements(By.TAG_NAME, "a")
            for link in links:
                if "次へ" in link.text:
                    next_link = link
                    break
            
            if next_link:
                current_url = next_link.get_attribute("href")
            else:
                log("次のページはありません。")
                break
        except Exception as e:
            log(f"ページネーション確認中にエラー: {e}")
            break

    return all_items

def load_processed_ids(log_file):
    """処理済みのIDをファイルから読み込む"""
    if not os.path.exists(log_file):
        return set()
    with open(log_file, "r", encoding="utf-8") as f:
        return {line.strip() for line in f}

def save_processed_id(auction_id, log_file):
    """処理済みのIDをファイルに追記する"""
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{auction_id}\n")

def relist_item(driver, auction_id):
    """指定されたオークションIDの商品を再出品する"""
    relist_url = f"https://auctions.yahoo.co.jp/sell/jp/show/resubmit?aID={auction_id}"
    log(f"  再出品ページに移動: {relist_url}")
    driver.get(relist_url)
    time.sleep(4) # ページ読み込みとJSの実行を待つ

    try:
        # ページが完全に読み込まれるまで待機
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.NAME, "Title"))
        )
        log("  再出品フォームが読み込まれました。")

        # スクロールしてボタンを表示させる
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        # 「確認画面へ」ボタンをクリック
        confirm_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "submit_form_btn"))
        )
        confirm_button.click()
        log("  ✅ 確認画面へ進むボタンをクリックしました。")

        # 「出品する」ボタンをクリック
        final_submit_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.ID, "auc_preview_submit_up"))
        )
        final_submit_button.click()
        log("  ✅ 出品するボタンをクリックしました。")

        # 完了を待つ (出品完了ページ or 出品中リストに遷移するのを待つ)
        WebDriverWait(driver, 30).until(
            EC.any_of(
                EC.url_contains("show/complete"),
                EC.url_contains("my/selling")
            )
        )
        log(f"  ✅ {auction_id} の再出品が完了したようです。")
        return True

    except Exception as e:
        log(f"  ❌ 再出品処理中にエラーが発生しました: {e}")
        error_dir = "error_artifacts"
        os.makedirs(error_dir, exist_ok=True)
        ss_path = os.path.join(error_dir, f"relist_error_{auction_id}_{int(time.time())}.png")
        driver.save_screenshot(ss_path)
        log(f"  📸 エラー時のスクリーンショットを保存しました: {ss_path}")
        return False

def save_to_csv(items):
    """
    取得した商品情報をCSVファイルに保存する
    """
    if not items:
        log("保存するデータがありません。")
        return

    # 重複除去 (auction_id)
    unique_items = {}
    for item in items:
        unique_items[item['auction_id']] = item
    
    items = list(unique_items.values())

    log(f"抽出した {len(items)} 件のデータを {OUTPUT_CSV} に保存します...")
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
        fieldnames = ['auction_id', 'status', 'title', 'price', 'bids', 'watch', 'access', 'time_left']
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        
        writer.writeheader()
        writer.writerows(items)
    log(f"✅ CSVファイルへの保存が完了しました: {OUTPUT_CSV}")

def relist_if_needed(driver, all_items):
    log("\n--- [3/3] 自動再出品チェック ---")

    if not all_items:
        log("商品データがないため、再出品処理をスキップします。")
        return

    df = pd.DataFrame(all_items)
    
    # 数値に変換
    for col in ['bids', 'watch', 'access', 'price']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    active_items = df[df['status'] == '出品中']
    ended_items = df[df['status'] == '終了（落札者なし）'].copy()

    log(f"現在の出品数: {len(active_items)}件")
    if len(active_items) >= MAX_ACTIVE_ITEMS:
        log(f"✅ 出品数が上限({MAX_ACTIVE_ITEMS}件)に達しているため、再出品は行いません。")
        return

    num_to_relist = MAX_ACTIVE_ITEMS - len(active_items)
    log(f"ℹ️ {num_to_relist} 件の再出品枠があります。")

    processed_ids = load_processed_ids(PROCESSED_RELIST_LOG)
    ended_items = ended_items[~ended_items['auction_id'].isin(processed_ids)]
    
    # タイトル重複チェック: 出品中の商品と同じタイトルのものは除外
    active_titles = set(active_items['title'].unique())
    original_count = len(ended_items)
    ended_items = ended_items[~ended_items['title'].isin(active_titles)]
    if len(ended_items) < original_count:
        log(f"ℹ️ タイトル重複により {original_count - len(ended_items)} 件の商品を再出品対象から除外しました。")

    if ended_items.empty:
        log("✅ 再出品可能な（未処理の）終了商品がありません。")
        return

    # 優先順位でソート
    ended_items.sort_values(by=['bids', 'watch', 'access'], ascending=False, inplace=True)
    
    items_to_relist = ended_items.head(num_to_relist)
    log(f"再出品対象として {len(items_to_relist)} 件を選択しました。")
    if len(items_to_relist) > 0:
        print(items_to_relist[['auction_id', 'title', 'bids', 'watch', 'access']].to_string())

    for index, item in items_to_relist.iterrows():
        auction_id = item['auction_id']
        log(f"\n--- 再出品処理中 ({items_to_relist.index.get_loc(index) + 1}/{len(items_to_relist)}): {auction_id} ---")
        if relist_item(driver, auction_id):
            save_processed_id(auction_id, PROCESSED_RELIST_LOG)
            log("  ...次の処理まで5秒待機...")
            time.sleep(5)
        else:
            log(f"  ⚠️ {auction_id} の再出品に失敗しました。次の商品に進みます。")
            save_processed_id(auction_id, PROCESSED_RELIST_LOG) # 失敗しても次回はスキップ
            continue

def main():
    log("=== ヤフオク マイ・オークション スクレイパー ===")
    driver = setup_driver()
    
    all_scraped_items = []
    
    # 1. 出品中
    log("\n--- [1/2] 出品中の商品をスクレイピング ---")
    items_selling = scrape_url(driver, SELLING_URL, "出品中")
    all_scraped_items.extend(items_selling)
    
    # 2. 落札者なし（終了分）
    log("\n--- [2/2] 落札者なし（終了分）をスクレイピング ---")
    items_closed = scrape_url(driver, CLOSED_URL, "終了（落札者なし）")
    all_scraped_items.extend(items_closed)
    
    save_to_csv(all_scraped_items)

    # 3. 必要であれば再出品
    relist_if_needed(driver, all_scraped_items)
    
    log("\n完了しました。ブラウザは開いたままにします。手動で閉じてください。")

if __name__ == "__main__":
    main()