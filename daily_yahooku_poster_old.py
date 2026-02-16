#!/usr/bin/env python3
"""
毎日14品番自動出品スクリプト
- 再出品 4品番：終了商品から「入札数→ウォッチ数→アクセス数」の降順
- 新規 10品番：products_rakuma.csv から古い品番（下から順に）
- 期間：1週間、終了時間：午後11時から午前0時
- 1回出品したら二度と出品しない（重複なし）
"""

import os
import csv
import time
import sys
import re
import pandas as pd
import logging
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

try:
    from yahooku_dorekai import setup_driver
except ImportError:
    print("yahooku_dorekai.py が見つかりません。同じディレクトリに配置してください。")
    sys.exit(1)

# --- 設定 ---
SELLING_URL = "https://auctions.yahoo.co.jp/my/selling"
CLOSED_URL = "https://auctions.yahoo.co.jp/my/closed?hasWinner=0"
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "products_yahooku.csv")
RAKUMA_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "products_rakuma.csv")

# ログファイル
PROCESSED_RELIST_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed_relist_ids.txt")
POSTED_HINBAN_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posted_hinban_history.txt")

# 出品設定
MAX_ACTIVE_ITEMS = 100
DAILY_POST_COUNT = 14
DAILY_RELIST_COUNT = 4
DAILY_NEW_POST_COUNT = 10
AUCTION_DURATION = 7  # 1週間
AUCTION_END_TIME = 23  # 午後11時から午前0時

# 待機設定
PAGE_LOAD_TIMEOUT = 20
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

def wait_for_items(driver):
    """商品リストが表示されるまで待機"""
    try:
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#itm ul > li"))
        )
        return True
    except TimeoutException:
        return False

def scrape_page_items(driver, status_label):
    """ページから商品情報を抽出"""
    page_items = []
    
    try:
        product_elements = driver.find_elements(By.CSS_SELECTOR, "#itm ul > li")
        
        if not product_elements:
            log("⚠️ 商品リストが見つかりません", level="warning")
            return []

        log(f"📊 {len(product_elements)} 件の商品を検出")

        for elem in product_elements:
            try:
                # タイトルとURL
                title_elem = elem.find_element(By.CSS_SELECTOR, "a[data-cl-params*='_cl_link:tc']")
                title = title_elem.text.strip()
                url = title_elem.get_attribute('href')
                
                # 価格
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
                        'time_left': time_left,
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

def scrape_all_items(driver):
    """出品中と終了商品をスクレイピング"""
    all_items = []
    
    # 出品中
    log("\n--- 出品中の商品をスクレイピング ---")
    driver.get(SELLING_URL)
    if wait_for_items(driver):
        items = scrape_page_items(driver, "出品中")
        all_items.extend(items)
        log(f"✅ 出品中: {len(items)} 件取得")
    
    # 終了（落札者なし）
    log("\n--- 終了商品をスクレイピング ---")
    driver.get(CLOSED_URL)
    if wait_for_items(driver):
        items = scrape_page_items(driver, "終了（落札者なし）")
        all_items.extend(items)
        log(f"✅ 終了: {len(items)} 件取得")
    
    return all_items

def get_new_post_candidates():
    """CSVから新規出品候補を取得（古い順）"""
    if not os.path.exists(RAKUMA_CSV):
        log(f"⚠️ CSV が見つかりません: {RAKUMA_CSV}", level="warning")
        return []
    
    try:
        df = pd.read_csv(RAKUMA_CSV, encoding='utf-8-sig')
        posted_hinban = load_posted_hinban(POSTED_HINBAN_LOG)
        
        candidates = []
        # 古い順（下から）で品番を取得
        for idx in range(len(df) - 1, -1, -1):
            row = df.iloc[idx]
            hinban = str(row.get('品番', '')) if '品番' in df.columns else None
            title = str(row.get('商品名', '')) if '商品名' in df.columns else ""
            
            if hinban and hinban not in posted_hinban and hinban != 'nan' and hinban != '':
                candidates.append({
                    'hinban': hinban,
                    'title': title,
                })
        
        log(f"📦 CSV候補: {len(candidates)} 件（既出品: {len(posted_hinban)} 件）")
        return candidates
    except Exception as e:
        log(f"❌ CSV読み込みエラー: {e}", level="error")
        return []

def relist_item(driver, auction_id):
    """商品を再出品する"""
    relist_url = f"https://auctions.yahoo.co.jp/sell/jp/show/resubmit?aID={auction_id}"
    log(f"  📝 再出品ページ: {relist_url}")
    driver.get(relist_url)
    time.sleep(3)

    try:
        # フォームが読み込まれるまで待機
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.NAME, "Title"))
        )
        log("  ✅ フォーム読み込み完了")

        # 期間と終了時間を設定
        set_auction_duration_and_time(driver)

        # スクロール
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        # 「確認画面へ」ボタン
        confirm_button = WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.element_to_be_clickable((By.ID, "submit_form_btn"))
        )
        confirm_button.click()
        log("  ✅ 確認画面へ進みました")
        time.sleep(2)

        # 「出品する」ボタン
        final_submit = WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.element_to_be_clickable((By.ID, "auc_preview_submit_up"))
        )
        final_submit.click()
        log("  ✅ 出品しました")

        # 完了を待つ
        WebDriverWait(driver, 30).until(
            EC.any_of(
                EC.url_contains("show/complete"),
                EC.url_contains("my/selling")
            )
        )
        log(f"  ✅ {auction_id} の再出品完了")
        return True

    except Exception as e:
        log(f"  ❌ 再出品エラー: {e}", level="error")
        return False

def post_new_item(driver, hinban, title):
    """CSVから新規出品する（新規出品ページへ）"""
    # ヤフオクの新規出品ページへ移動
    new_post_url = "https://auctions.yahoo.co.jp/sell/jp/show/create"
    log(f"  📝 新規出品ページ: {new_post_url}")
    driver.get(new_post_url)
    time.sleep(3)

    try:
        # タイトル入力フィールドが表示されるまで待機
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.NAME, "Title"))
        )
        log("  ✅ フォーム読み込み完了")

        # タイトルを入力
        title_input = driver.find_element(By.NAME, "Title")
        title_input.clear()
        title_input.send_keys(title)
        log(f"  ✅ タイトル入力完了: {title[:30]}")

        # 期間と終了時間を設定
        set_auction_duration_and_time(driver)

        # スクロール
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        # 「確認画面へ」ボタン
        confirm_button = WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.element_to_be_clickable((By.ID, "submit_form_btn"))
        )
        confirm_button.click()
        log("  ✅ 確認画面へ進みました")
        time.sleep(2)

        # 「出品する」ボタン
        final_submit = WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.element_to_be_clickable((By.ID, "auc_preview_submit_up"))
        )
        final_submit.click()
        log("  ✅ 出品しました")

        # 完了を待つ
        WebDriverWait(driver, 30).until(
            EC.any_of(
                EC.url_contains("show/complete"),
                EC.url_contains("my/selling")
            )
        )
        log(f"  ✅ {hinban} の新規出品完了")
        return True

    except Exception as e:
        log(f"  ❌ 新規出品エラー: {e}", level="error")
        return False

def set_auction_duration_and_time(driver):
    """期間と終了時間を設定"""
    try:
        # 期間を設定（1週間 = 7日）
        duration_select = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "AuctionDuration"))
        )
        from selenium.webdriver.support.select import Select
        select = Select(duration_select)
        select.select_by_value(str(AUCTION_DURATION))
        log(f"  ✅ 期間を {AUCTION_DURATION} 日に設定")

        # 終了時間を設定（午後11時から午前0時）
        time_select = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "AuctionEndHour"))
        )
        select_time = Select(time_select)
        select_time.select_by_value(str(AUCTION_END_TIME))
        log(f"  ✅ 終了時間を {AUCTION_END_TIME} 時（午後11時～午前0時）に設定")

        # 配送方法を設定（ゆうパケット）
        try:
            yupacket_radio = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[data-delivertype='is_jp_yupacket_official_ship']"))
            )
            yupacket_radio.click()
            log("  ✅ 配送方法を『ゆうパケット』に設定")
        except TimeoutException:
            log("  ⚠️ ゆうパケットの選択肢が見つかりません", level="warning")

    except Exception as e:
        log(f"  ⚠️ 期間/時間設定エラー: {e}", level="warning")

def main():
    log("=" * 50)
    log("🚀 毎日自動出品スクリプト開始")
    log("=" * 50)

    driver = setup_driver()
    
    try:
        # スクレイピング
        log("\n【ステップ1】現在の出品状況をスクレイピング")
        all_items = scrape_all_items(driver)
        
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

        # 本日の出品数を決定
        relist_count = min(DAILY_RELIST_COUNT, available_slots)
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
                    log(f"\n【{idx}/{len(items_to_relist)}】再出品: {item['title'][:40]}")
                    
                    if relist_item(driver, auction_id):
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
                log(f"\n【{idx}/{len(items_to_post)}】新規出品: {hinban} - {title}")
                
                if post_new_item(driver, hinban, title):
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

if __name__ == "__main__":
    main()
