import os
import glob
import json
import sys
import threading
import argparse
import logging
import pandas as pd
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ---- ログ設定 ----
logger = logging.getLogger("dorekai_scraper")

# ヤフオクスクレイピング機能のインポート
try:
    from yahooku_scraper import scrape_url, save_to_csv, SELLING_URL, CLOSED_URL
    from yahooku_dorekai import setup_driver
    YAHOOKU_AVAILABLE = True
except ImportError as e:
    logger.warning(f"ヤフオクスクレイピング機能が利用できません: {e}")
    YAHOOKU_AVAILABLE = False

def configure_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

def load_brand_name_list_from_master(file_path="brand_master_sjis.csv"):
    """ブランドマスターファイルからブランド名のリストを読み込む（商品名からの抽出用）"""
    brands = []
    try:
        df = pd.read_csv(file_path, encoding='cp932', header=None, usecols=[1])
        brands = df[1].dropna().astype(str).tolist()
        brands.sort(key=len, reverse=True)
        print(f"📚 ブランドマスターから {len(brands)} 件のブランドを読み込みました。")
    except FileNotFoundError:
        print(f"⚠️ ブランドマスターファイルが見つかりません: {file_path}。商品名からのブランド抽出は行われません。")
    return brands

def load_brand_master_map(file_path="brand_master_sjis.csv"):
    """ブランドマスターファイルから {ブランドID: {各名称}} の辞書を作成する"""
    brand_map = {}
    try:
        # Shift_JISで読み込み、ヘッダーがないことを想定
        df = pd.read_csv(file_path, encoding='cp932', header=None, dtype=str)
        # 列名を定義
        df.columns = ['ブランドID', 'ブランド名', 'ブランド名（カナ）', 'ブランド名（英語）']
        df.dropna(subset=['ブランドID'], inplace=True)
        # ブランドIDをインデックスにして辞書化
        brand_map = df.set_index('ブランドID').to_dict('index')
        print(f"📚 ブランドマスター辞書を {len(brand_map)} 件読み込みました。")
    except FileNotFoundError:
        print(f"⚠️ ブランドマスターファイルが見つかりません: {file_path}。IDからのブランド名解決は行われません。")
    except Exception as e:
        print(f"❌ ブランドマスターファイルの読み込み中にエラーが発生しました: {e}")
    return brand_map

def extract_product_number(name):
    """商品名から品番（先頭の3-5桁の数字）を抽出する"""
    if not isinstance(name, str):
        return None
    # 先頭の数字（空白なしでもOK）を優先
    match = re.match(r'^\s*(\d{3,5})', name)
    if match:
        return match.group(1)
    # それでも見つからなければ先頭付近の3-5桁を探す
    match = re.search(r'(\d{3,5})', name)
    return match.group(1) if match else None

def clean_rakuma_title(name):
    """ラクマのタイトル末尾を除去して商品名だけにする"""
    if not isinstance(name, str):
        return name
    suffixes = [" | フリマアプリ ラクマ", "｜フリマアプリ ラクマ"]
    for suffix in suffixes:
        if suffix in name:
            name = name.split(suffix)[0]
            break
    return name.strip()

def add_duplicate_column(df, subset_col='品番'):
    """データフレームに重複チェック列を追加する（最適化版）"""
    if not df.empty and subset_col in df.columns:
        # keep=Falseは重複するすべての行をTrueにする
        duplicates = df.duplicated(subset=[subset_col], keep=False) & df[subset_col].notna()
        duplicate_col = duplicates.map({True: '重複', False: ''})
    else:
        duplicate_col = ['' for _ in range(len(df))]
    
    # pd.concat()で効率的に列を追加
    df = pd.concat([df, pd.DataFrame({'重複': duplicate_col}, index=df.index)], axis=1)
    return df

def build_requests_session(headers):
    """リトライ付きのHTTPセッションを作成"""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(headers)
    return session

def is_logged_in_rakuma(page):
    """ラクマでログイン済みかどうかを判定する"""
    try:
        from bs4 import BeautifulSoup
        html = page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # ログイン済みの場合、ユーザーメニューが存在
        # ログイン未済みの場合、ログインボタンが存在
        login_button = soup.find('a', {'href': re.compile(r'login|signin', re.IGNORECASE)})
        is_logged_in = login_button is None
        
        logger.info(f"  [ラクマログイン状態判定] ログイン済み: {is_logged_in}")
        return is_logged_in
    except Exception as e:
        logger.warning(f"  ログイン状態判定エラー: {e}")
        return False

def is_logged_in_mercari_shops(page):
    """メルカリショップスでログイン済みかどうかを判定する"""
    try:
        from bs4 import BeautifulSoup
        html = page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # ログイン済みの場合、商品要素が表示される
        # ログイン未済みの場合、ログインボタンが表示される
        login_btn = soup.find('button', {'data-testid': 'login-with-mercari-account'})
        product_items = soup.find_all('li', {'data-testid': 'product'})
        is_logged_in = login_btn is None and len(product_items) > 0
        
        logger.info(f"  [メルカリショップスログイン状態判定] ログイン済み: {is_logged_in}, 商品数: {len(product_items)}")
        return is_logged_in
    except Exception as e:
        logger.warning(f"  ログイン状態判定エラー: {e}")
        return False

def wait_for_manual_login(page, site_name, timeout_seconds=30, is_logged_in_func=None):
    """
    ブラウザで手動ログインを行う時間を確保する（ログイン済みなら自動スキップ）
    
    Args:
        page: Playwrite のページオブジェクト
        site_name: サイト名（ログ出力用）
        timeout_seconds: 待機時間（秒）
        is_logged_in_func: ログイン状態を判定する関数（オプション）
    """
    # ログイン状態を確認
    if is_logged_in_func:
        if is_logged_in_func(page):
            logger.info(f"✅ {site_name} は既にログイン済みです。スクレイピングを開始します\n")
            return
    
    logger.info(f"\n⏳ {site_name} に手動でログインしてください")
    logger.info(f"   ブラウザウィンドウでログインを完了してください")
    logger.info(f"   {timeout_seconds}秒間、スクレイピングを待機します...")
    logger.info(f"   準備ができたら、ターミナルで [ENTER] キーを押すか、カウントダウン終了後に続行します\n")
    
    user_pressed_enter = False
    
    def wait_for_input():
        nonlocal user_pressed_enter
        try:
            input()  # ユーザーがENTERを押すまでブロック
            user_pressed_enter = True
        except:
            pass
    
    # inputを別スレッドで実行
    input_thread = threading.Thread(target=wait_for_input, daemon=True)
    input_thread.start()
    
    # カウントダウンを表示（5秒ごと、または最後の1秒のみログ出力）
    for remaining in range(timeout_seconds, 0, -1):
        if user_pressed_enter:
            logger.info(f"✅ ログイン確認: ユーザーが [ENTER] を押しました。スクレイピングを開始します\n")
            return
        # 5秒ごと、または最後の1秒のみログ出力
        if remaining % 5 == 0 or remaining == 1:
            logger.info(f"   カウントダウン: {remaining}秒...")
        time.sleep(1)
    
    if not user_pressed_enter:
        logger.info(f"✅ タイムアウト: カウントダウン終了。スクレイピングを開始します\n")

def scrape_rakuma_selling_stats():
    """ラクマの出品中商品からwatch（いいね）とaccess（閲覧数）を取得する"""
    stats_dict = {}  # {URL: {'watch': 0, 'access': 0}}
    try:
        # user_data_dirを絶対パスに変更
        script_dir = os.path.dirname(os.path.abspath(__file__))
        user_data_dir = os.path.join(script_dir, 'rakuma_user_data')
        
        with sync_playwright() as p:
            logger.info("出品中商品のwatch/access情報を取得中...")
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,  # ログインが必要な場合があるため
                timeout=60000  # タイムアウトを60秒に設定
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            
            # 出品中商品一覧ページに移動（リトライ機能付き）
            max_attempts = 3
            page_loaded = False
            for attempt in range(max_attempts):
                try:
                    page.goto("https://fril.jp/sell", timeout=30000, wait_until='load')
                    page.wait_for_load_state('networkidle', timeout=10000)
                    page_loaded = True
                    logger.info("✅ ラクマページの読み込み完了")
                    break
                except Exception as e:
                    logger.warning(f"  ページ読み込み試行 {attempt+1}/{max_attempts} 失敗: {e}")
                    if attempt < max_attempts - 1:
                        time.sleep(2)
            
            if not page_loaded:
                logger.warning("  ページ読み込みに失敗しましたが、続行します")
            
            time.sleep(1)
            
            # 手動ログイン用の待機（ページ読み込み後、60秒）
            wait_for_manual_login(page, "ラクマ（出品中商品）", timeout_seconds=60, is_logged_in_func=is_logged_in_rakuma)
            
            # ログイン確認（複数回リトライ）
            max_login_retries = 3
            for retry in range(max_login_retries):
                time.sleep(2)
                if is_logged_in_rakuma(page):
                    logger.info(f"  ✅ ログイン確認完了（リトライ {retry+1}/{max_login_retries}）")
                    break
                else:
                    logger.warning(f"  ⚠️ ログイン状態未確認（リトライ {retry+1}/{max_login_retries}）")
                    if retry == max_login_retries - 1:
                        logger.error("  ❌ ログイン確認失敗。スクレイピングを中止します")
                        browser.close()
                        return stats_dict
            
            # ページ再読み込み（ログイン状態で最新のHTMLを取得）
            try:
                page.reload(timeout=30000)
                page.wait_for_load_state('networkidle', timeout=10000)
                logger.info("  ✅ ページを再読み込みしました（ログイン状態を確認）")
            except Exception as e:
                logger.warning(f"  ⚠️ ページ再読み込み失敗（続行します）: {e}")
            
            # ページネーション対応：AJAX ベースのページ読み込み
            from bs4 import BeautifulSoup
            max_page = 1
            
            # 初期ページから総ページ数を特定
            try:
                initial_html = page.content()
                initial_soup = BeautifulSoup(initial_html, 'html.parser')
                # 最後のページへのリンクを探す（例: /ajax/item/selling?page=32）
                last_page_link = initial_soup.find('span', class_='last')
                if last_page_link:
                    last_link = last_page_link.find('a')
                    if last_link and 'href' in last_link.attrs:
                        href = last_link['href']
                        page_match = re.search(r'page=(\d+)', href)
                        if page_match:
                            max_page = int(page_match.group(1))
                            logger.info(f"  📄 総ページ数を取得: {max_page}ページ")
            except Exception as e:
                logger.warning(f"  ⚠️ 総ページ数取得失敗: {e}（1ページのみ処理します）")
                max_page = 1
            
            # すべてのページを訪問して商品を収集（AJAX ベース）
            logger.info(f"  🔄 ページネーション処理開始（{max_page}ページ）")
            all_items_html = []
            
            for page_num in range(1, max_page + 1):
                try:
                    if page_num > 1:
                        # ページ2以降：ページネーションリンクをクリック（AJAX ロード）
                        # href が完全に一致するセレクタを使用（複数マッチ防止）
                        page_link = page.locator(f'a[href="/ajax/item/selling?page={page_num}"]')
                        if page_link.count() > 0:
                            try:
                                page_link.click()
                                # networkidle はラクマではタイムアウトしやすいため、domcontentloaded に短縮
                                try:
                                    page.wait_for_load_state('domcontentloaded', timeout=10000)
                                except Exception:
                                    # DOMContentLoaded すら待たず、単に sleep で対応
                                    pass
                                time.sleep(1)  # バックグラウンド処理完了を待つ
                                logger.info(f"  📄 ページ {page_num} をクリックしてロード中...")
                            except Exception as click_err:
                                logger.warning(f"  ⚠️ ページ {page_num} クリック失敗: {click_err}")
                                continue
                        else:
                            logger.warning(f"  ⚠️ ページ {page_num} のリンクが見つかりません")
                            continue
                    
                    # 現在のページのHTMLを取得
                    page_html = page.content()
                    all_items_html.append(page_html)
                    
                    # ページ内の商品数をカウント
                    page_soup = BeautifulSoup(page_html, 'html.parser')
                    page_items = page_soup.find_all('div', class_='deal-item')
                    logger.info(f"  📄 ページ {page_num}: {len(page_items)}件の商品を取得")
                    
                except Exception as e:
                    logger.warning(f"  ⚠️ ページ {page_num} の取得失敗: {e}")
                    continue
            
            browser.close()
            
            # 統合HTMLをデバッグ用に保存（第1ページのみ）
            if all_items_html:
                debug_html_path = "rakuma_sell_debug.html"
                with open(debug_html_path, "w", encoding="utf-8") as f:
                    f.write(all_items_html[0])
                logger.info(f"🔍 デバッグ用HTMLを保存しました: {debug_html_path}")
            
            # すべてのHTMLから商品を抽出
            total_items = 0
            for html_content in all_items_html:
                soup = BeautifulSoup(html_content, 'html.parser')
                items = soup.find_all('div', class_='deal-item')
                total_items += len(items)
                
                for idx, item in enumerate(items):
                    try:
                        # 商品URL
                        link_tag = item.find('a', class_='deal-item__info')
                        if not link_tag or 'href' not in link_tag.attrs:
                            continue
                        item_url = link_tag['href']
                        if not item_url.startswith('http'):
                            item_url = urljoin('https://item.fril.jp', item_url)
                        
                        # いいね数（watch）
                        watch = 0
                        watch_tag = item.find('span', {'data-test': 'item_like_count'})
                        if watch_tag:
                            watch_text = watch_tag.get_text(strip=True)
                            watch_match = re.search(r'(\d+)', watch_text)
                            if watch_match:
                                watch = int(watch_match.group(1))
                        
                        # 閲覧数（access）
                        access = 0
                        access_tag = item.find('span', {'data-test': 'item_view_count'})
                        if access_tag:
                            access_text = access_tag.get_text(strip=True)
                            access_match = re.search(r'(\d+)', access_text)
                            if access_match:
                                access = int(access_match.group(1))
                        
                        stats_dict[item_url] = {'watch': watch, 'access': access}
                        
                        # 最初の3件をデバッグ出力
                        if idx < 3 and total_items <= 3:
                            logger.info(f"  [デバッグ] 商品 {idx+1}: URL={item_url[:50]}..., watch={watch}, access={access}")
                        
                    except Exception as e:
                        logger.warning(f"  商品のwatch/access取得エラー: {e}")
                        continue
            
            logger.info(f"✅ {total_items} 件の商品のwatch/access情報を取得しました")

            
    except Exception as e:
        logger.error(f"ラクマの出品中商品情報取得エラー: {e}")
    finally:
        # ブラウザが確実に閉じるように待機
        time.sleep(2)
    
    return stats_dict

def scrape_rakuma_draft_items():
    """ラクマの下書きタブ（出品していた）から商品URLリストを取得する（高速化版）"""
    draft_urls = []
    try:
        # user_data_dirを絶対パスに変更
        script_dir = os.path.dirname(os.path.abspath(__file__))
        user_data_dir = os.path.join(script_dir, 'rakuma_user_data')
        
        with sync_playwright() as p:
            logger.info("下書きタブの商品をスクレイピング中（高速化版）...")
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,  # ログインが必要な場合があるため
                timeout=60000  # タイムアウトを60秒に設定
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            
            # 下書きページに直接移動（リトライ機能付き）
            max_attempts = 3
            page_loaded = False
            for attempt in range(max_attempts):
                try:
                    page.goto("https://fril.jp/draft", timeout=30000, wait_until='load')
                    page.wait_for_load_state('networkidle', timeout=10000)
                    page_loaded = True
                    logger.info("✅ ラクマドラフトページの読み込み完了")
                    break
                except Exception as e:
                    logger.warning(f"  ページ読み込み試行 {attempt+1}/{max_attempts} 失敗: {e}")
                    if attempt < max_attempts - 1:
                        time.sleep(2)
            
            if not page_loaded:
                logger.warning("  ページ読み込みに失敗しましたが、続行します")
            
            time.sleep(1)
            
            # 手動ログイン用の待機（ページ読み込み後、60秒）
            wait_for_manual_login(page, "ラクマ（下書きタブ）", timeout_seconds=60, is_logged_in_func=is_logged_in_rakuma)
            
            # 「出品していた」タブをクリック
            try:
                after_selling_tab = page.locator('a[href="#after-selling-tab"]')
                if after_selling_tab.count() > 0:
                    after_selling_tab.click()
                    time.sleep(1)  # 2秒→1秒に短縮
                    
                    # 「続きを見る」ボタンを最大10回までクリック（無限ループ防止）
                    for _ in range(10):
                        try:
                            more_button = page.locator('#after-selling-container_button a')
                            if more_button.is_visible(timeout=1000):
                                more_button.click()
                                time.sleep(0.5)  # 1秒→0.5秒に短縮
                            else:
                                break
                        except:
                            break
                    
                    # 商品の編集リンクを一括取得
                    edit_links = page.locator('a[href*="/drafts/"][href*="/edit"]')
                    count = edit_links.count()
                    logger.info(f"  下書き商品数（出品していた）: {count}")
                    
                    # 一括で href を取得して処理（個別にアクセスしない）
                    hrefs = edit_links.evaluate_all('links => links.map(l => l.href)')
                    for href in hrefs:
                        match = re.search(r'/drafts/([a-f0-9]+)/edit', href)
                        if match:
                            item_id = match.group(1)
                            item_url = f"https://item.fril.jp/{item_id}"
                            draft_urls.append(item_url)
                    
                    logger.info(f"✅ 下書きから {len(draft_urls)} 件のURLを取得しました")
            except Exception as e:
                logger.warning(f"下書きタブのアクセスに失敗: {e}")
            
            browser.close()
    except Exception as e:
        logger.error(f"下書きスクレイピングエラー: {e}")
    finally:
        # ブラウザが確実に閉じるように待機
        time.sleep(2)
    
    return set(draft_urls)

def scrape_mercari_shops_stats():
    """メルカリショップスの公開タブからwatch（いいね）とaccess（閲覧数）を取得する"""
    from bs4 import BeautifulSoup
    stats_dict = {}  # {商品ID: {'watch': 0, 'access': 0, 'name': 商品名, 'price': 販売価格}}
    
    try:
        # user_data_dirを絶対パスに変更してログイン情報を保存
        script_dir = os.path.dirname(os.path.abspath(__file__))
        user_data_dir = os.path.join(script_dir, 'mercari_shops_user_data')

        with sync_playwright() as p:
            logger.info("メルカリショップスの公開商品情報を取得中... (Firefox)")
            browser = p.firefox.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                timeout=60000,
                accept_downloads=True
            )

            def handle_popup(popup):
                logger.info(f"  ポップアップが開かれました: {popup.url}")
            browser.on("page", handle_popup)
            page = browser.pages[0] if browser.pages else browser.new_page()
            
            shop_url = "https://mercari-shops.com/seller/shops/qWxSdPm7yRZ56vy6jEx9mK/products"

            # 最初に手動ログイン待機を実行（ページ読み込み後）
            page.goto(shop_url, timeout=60000, wait_until='load')
            page.wait_for_load_state('networkidle', timeout=10000)
            time.sleep(1)
            wait_for_manual_login(page, "メルカリショップス", timeout_seconds=60, is_logged_in_func=is_logged_in_mercari_shops)

            max_retries = 3
            for attempt in range(max_retries):
                page.goto(shop_url, timeout=60000, wait_until='load')
                page.wait_for_load_state('networkidle', timeout=10000)
                time.sleep(2)
                current_url = page.url
                html_content = page.content()
                soup = BeautifulSoup(html_content, 'html.parser')
                test_items = soup.find_all('li', {'data-testid': 'product'})
                login_btn = soup.find('button', {'data-testid': 'login-with-mercari-account'})
                # 商品要素が存在し、URLも正しい場合はOK
                if (
                    'qWxSdPm7yRZ56vy6jEx9mK' in current_url and
                    'login' not in current_url.lower() and
                    len(test_items) > 0 and not login_btn
                ):
                    logger.info("✅ 商品一覧ページに遷移成功。商品情報を全件取得します...")
                    break
                else:
                    logger.warning(f"  [リトライ{attempt+1}/{max_retries}] 商品一覧ページ遷移失敗または商品要素未検出。再遷移します...")
                    time.sleep(3)
            else:
                logger.error(f"❌ 商品一覧ページに遷移できていません。URL: {current_url}")
                logger.error("   ページにログインボタンが存在します。ログイン後に再実行してください")
                logger.error("   ブラウザは自動で閉じません。手動でログイン後、ウィンドウを閉じてください。")
                input("[ENTER]で続行（ブラウザを手動で閉じた後）: ")
                return stats_dict

            # スクロールしてすべての商品を読み込む
            logger.info("  商品リストを自動スクロール中...")
            prev_count = 0
            same_count = 0
            max_scroll = 100
            for i in range(max_scroll):
                current_url_during_scroll = page.url
                if 'login' in current_url_during_scroll.lower() or 'signin' in current_url_during_scroll.lower():
                    logger.warning("  ⚠️ スクロール中にログインページにリダイレクトされました。スクロールを中止します。")
                    break
                try:
                    last_item = page.locator('li[data-testid="product"]:last-child')
                    if last_item.count() > 0:
                        last_item.scroll_into_view_if_needed()
                    else:
                        page.evaluate("window.scrollBy(0, 500)")
                except Exception as e:
                    logger.warning(f"  スクロールエラー: {e}")
                    page.evaluate("window.scrollBy(0, 500)")
                time.sleep(1.5)
                page.wait_for_load_state('networkidle', timeout=5000)
                html_content = page.content()
                soup = BeautifulSoup(html_content, 'html.parser')
                items = soup.find_all('li', {'data-testid': 'product'})
                curr_count = len(items)
                logger.info(f"    スクロール{i+1}回目: 商品数={curr_count}")
                if curr_count == prev_count:
                    same_count += 1
                else:
                    same_count = 0
                if same_count >= 5:
                    logger.info(f"    商品数が増えなくなったためスクロール終了（{curr_count}件）")
                    break
                prev_count = curr_count
            # スクロール完了後のHTMLを使用
            browser.close()
            # デバッグ用: HTMLを保存
            debug_html_path = "mercari_shops_debug.html"
            with open(debug_html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"🔍 デバッグ用HTMLを保存しました: {debug_html_path}")
            # BeautifulSoupで解析
            soup = BeautifulSoup(html_content, 'html.parser')
            items = soup.find_all('li', {'data-testid': 'product'})
            logger.info(f"  公開商品数: {len(items)}")
            # デバッグ: 最初の商品要素の内容を確認
            if items:
                first_item = items[0]
                logger.info(f"  [デバッグ] 最初の商品要素のHTML: {str(first_item)[:200]}...")
            else:
                logger.warning("  ⚠️ 商品要素が見つかりません。HTML構造が変更された可能性があります。")
                # 他のセレクタを試す
                alt_items = soup.find_all('li', class_=re.compile(r'product'))
                logger.info(f"  代替セレクタでの商品数: {len(alt_items)}")
                if alt_items:
                    items = alt_items
                    logger.info("  代替セレクタを使用します。")
            
            for idx, item in enumerate(items):
                    try:
                        # 商品要素のHTMLをデバッグ出力（最初の10件）
                        if idx < 10:
                            logger.info(f"  [デバッグ] 商品要素HTML({idx}): {str(item)[:200]}...")

                        # 商品名
                        name_tag = item.find('p', {'data-testid': 'product-name'})
                        product_name = name_tag.get_text(strip=True) if name_tag else None
                        if not product_name:
                            logger.warning(f"  商品名が見つかりません（idx={idx}）")

                        # 品番を抽出（先頭でなくても3-5桁の数字があればOK）
                        hinban_match = re.search(r'(\d{3,5})', product_name) if product_name else None
                        hinban = hinban_match.group(1) if hinban_match else None
                        # 品番が見つかった場合のみログ出力（見つからない場合はスキップ）
                        if hinban and idx < 10:
                            logger.info(f"  [デバッグ] 品番を抽出: {hinban}（idx={idx}）")

                        # 商品ID（URLの末尾）
                        product_id = None
                        item_url = None

                        # 価格
                        price_tag = item.find('span', class_='css-1wgdpkr')
                        price_text = price_tag.get_text(strip=True) if price_tag else None
                        price = int(re.sub(r'[^\d]', '', price_text)) if price_text and re.search(r'\d', price_text) else 0

                        # 在庫数の抽出（販売中商品のみ）
                        stock = ''
                        # 1. div構造から取得（css-k008qsクラスがある場合のみ）
                        stock_div = item.find('div', class_='css-k008qs')
                        if stock_div:
                            stock_label = stock_div.find('span', string='在庫数')
                            if stock_label:
                                stock_value = stock_div.find('p', class_='chakra-text')
                                if stock_value:
                                    stock = stock_value.get_text(strip=True)
                        # ※ 売却済み商品では在庫数divが存在しないため、空のままにする

                        # リクエスト件数の抽出
                        request_count = 0
                        request_tag = item.find('p', class_='chakra-text css-15vrkfh')
                        if request_tag:
                            request_text = request_tag.get_text(strip=True)
                            request_match = re.search(r'(\d+)', request_text)
                            if request_match:
                                request_count = int(request_match.group(1))

                        # アクション数を取得（いいね、閲覧数）
                        p_tags = item.find_all('p', class_='chakra-text')
                        watch = 0
                        access = 0
                        if stock:  # 在庫数がある場合（販売中）
                            if len(p_tags) >= 4:
                                watch_text = p_tags[2].get_text(strip=True)
                                if watch_text.isdigit():
                                    watch = int(watch_text)
                                access_text = p_tags[3].get_text(strip=True)
                                if access_text.isdigit():
                                    access = int(access_text)
                        else:  # 在庫数がない場合（売却済み）
                            if len(p_tags) >= 3:
                                watch_text = p_tags[1].get_text(strip=True)
                                if watch_text.isdigit():
                                    watch = int(watch_text)
                                access_text = p_tags[2].get_text(strip=True)
                                if access_text.isdigit():
                                    access = int(access_text)

                        # 商品名をキーにして格納（重複時はidx付き）
                        dict_key = product_name or f'idx_{idx}'
                        if dict_key in stats_dict:
                            dict_key = f'{dict_key}_{idx}'
                        stats_dict[dict_key] = {
                            'watch': watch,
                            'access': access,
                            'name': product_name,
                            'price': price,
                            'hinban': hinban,
                            'item_url': item_url,
                            '在庫数': stock,
                            'リクエスト': request_count
                        }

                        if idx < 3:
                            logger.info(f"  [デバッグ] 商品名 {product_name[:30]}..., price={price}, watch={watch}, access={access}, hinban={hinban}, stock={stock}, request={request_count}")

                    except Exception as e:
                        logger.warning(f"  商品のwatch/access取得エラー: {e}, idx={idx}")
                        continue
            
            logger.info(f"✅ {len(stats_dict)} 件のメルカリショップス商品情報を取得しました")
            
    except Exception as e:
        logger.error(f"メルカリショップススクレイピングエラー: {e}")
    
    return stats_dict

def process_rakuma_data(base_url, scrape_all_pages=True, request_timeout=10, page_sleep=0.6, item_sleep=0.4, rakuma_stats=None):
    """指定されたURLからラクマのデータを抽出し、ページネーションを処理して整形する（簡易版）"""
    # --- データマッピング（逆引き用） ---
    CONDITION_MAP_INV = {'新品、未使用': '1', '未使用に近い': '2', '目立った傷や汚れなし': '3', 'やや傷や汚れあり': '4', '傷や汚れあり': '5', '全体的に状態が悪い': '6'}
    SHIPPING_PAYER_MAP_INV = {'送料込み(出品者負担)': '1', '着払い(購入者負担)': '2', '送料込': '1'}
    DAYS_TO_SHIP_MAP_INV = {'1-2日で発送': '1', '2-3日で発送': '2', '4-7日で発送': '3', '支払い後、1～2日で発送': '1', '支払い後、2～3日で発送': '2', '支払い後、4～7日で発送': '3'}

    logger.info("Processing Rakuma data from web (簡易モード: 商品一覧のみ)...")
    page = 1
    all_products = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    session = build_requests_session(headers)

    while True:
        url = f"{base_url}?page={page}"
        logger.info(f"Scraping Rakuma page: {url}")
        try:
            response = session.get(url, timeout=request_timeout)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Rakuma page: {e}")
            break

        # デバッグ用: 最初のページのHTMLを保存
        if page == 1:
            debug_html_path = "rakuma_debug.html"
            with open(debug_html_path, "w", encoding="utf-8") as f:
                f.write(response.text)
            logger.info(f"🔍 デバッグ用HTMLを保存しました: {debug_html_path}")

        soup = BeautifulSoup(response.content, 'html.parser')
        items = soup.find_all('div', class_='item', attrs={'data-test': 'item'})

        if not items:
            logger.info(f"No more items found on page {page}. Stopping.")
            break

        # 商品一覧ページから直接情報を抽出（詳細ページにアクセスしない）
        for item in items:
            try:
                # 商品リンク
                link_tag = item.find('a', class_='link_shop_image')
                item_url = urljoin(base_url, link_tag['href']) if link_tag and 'href' in link_tag.attrs else ''
                
                # 商品名（spanタグの data-test="item_name" から取得）
                name_tag = item.find('span', attrs={'data-test': 'item_name'})
                name = name_tag.text.strip() if name_tag else 'N/A'
                
                # 価格（spanタグの data-test="item_price" から取得）
                price_tag = item.find('span', attrs={'data-test': 'item_price'})
                price = 'N/A'
                if price_tag:
                    price_text = price_tag.get_text(strip=True)
                    price_match = re.search(r'[\d,]+', price_text)
                    if price_match:
                        price = price_match.group(0).replace(',', '')
                
                # SOLD OUT判定（一覧ページから）
                is_sold_out = item.find('div', class_='soldout') is not None or \
                             item.find('span', class_='soldout') is not None
                
                product_data = {
                    '商品名': name,
                    '価格': price,
                    'URL': item_url,
                    'is_sold_out': is_sold_out,
                    '商品説明': '',  # 一覧ページには無いため空
                    'ブランド': '',
                    'カテゴリ': '',
                    'サイズ': '',
                    '商品の状態': '',
                    '配送料の負担': '',
                    '配送方法': '',
                    '発送日の目安': '',
                    '発送元の地域': '',
                }
                all_products.append(product_data)
            except Exception as e:
                logger.warning(f"  Error parsing item: {e}")
                continue
        
        # 1ページのみを対象とする場合、ここでループを抜ける
        if not scrape_all_pages:
            logger.info("1ページ目のみをスクレイピングしました。")
            break

        page += 1
        time.sleep(page_sleep)  # サーバーへの負荷を軽減するための待機

    logger.info(f"Found {len(all_products)} products in Rakuma data (簡易モード).")

    if not all_products:
        logger.warning("No products found in Rakuma data.")
        return pd.DataFrame()

    df = pd.DataFrame(all_products)
    df['品番'] = df['商品名'].apply(extract_product_number)
    
    # watch/access列を追加
    if rakuma_stats:
        logger.info(f"ラクマstats辞書に {len(rakuma_stats)} 件の情報があります")
        df['watch'] = df['URL'].apply(lambda url: rakuma_stats.get(url, {}).get('watch', 0))
        df['access'] = df['URL'].apply(lambda url: rakuma_stats.get(url, {}).get('access', 0))
        
        # デバッグ: 紐付け成功数を確認
        matched_count = (df['watch'] > 0).sum() + (df['access'] > 0).sum()
        logger.info(f"ラクマ: watch/accessが設定された行数 = {matched_count}")
        if matched_count == 0 and len(rakuma_stats) > 0:
            logger.warning("⚠️ ラクマのURL紐付けに失敗しています")
            # サンプル表示
            if len(df) > 0:
                logger.info(f"  CSV URL例: {df['URL'].iloc[0]}")
            if len(rakuma_stats) > 0:
                sample_key = list(rakuma_stats.keys())[0]
                logger.info(f"  stats URL例: {sample_key}")
    else:
        df['watch'] = 0
        df['access'] = 0
        logger.warning("rakuma_statsが空です")

    # データマッピングを適用してコードに変換（簡易モードでは空のままも多い）
    df['商品の状態コード'] = df['商品の状態'].map(CONDITION_MAP_INV)
    df['配送料負担コード'] = df['配送料の負担'].map(SHIPPING_PAYER_MAP_INV)
    df['発送日の目安コード'] = df['発送日の目安'].map(DAYS_TO_SHIP_MAP_INV)

    df = add_duplicate_column(df)
    
    # 出力する列を定義
    output_cols = [
        '品番', '重複', '商品名', '価格', 'URL', 'watch', 'access', '商品説明', 'ブランド',
        'カテゴリ', 'サイズ', '商品の状態', '配送料の負担', '配送方法',
        '発送日の目安', '発送元の地域', '商品の状態コード', '配送料負担コード', '発送日の目安コード', 'is_sold_out'
    ]
    # 存在しない列があれば空文字で埋める
    for col in output_cols:
        if col not in df.columns:
            df[col] = ''

    df = df[output_cols]
    logger.info(f"Rakuma data processing complete: {len(df)} products.")
    return df

def process_mercari_data(mercari_path=None, mercari_stats=None):
    """ネットワーク上の最新のMercari CSVからデータを抽出し、整形する"""
    logger.info("Processing Mercari data...")
    try:
        if mercari_path is None:
            mercari_path = r'C:\Users\progr\Desktop\Python\mercari_dorekai\downloads'
        search_pattern = os.path.join(mercari_path, 'product_data_*.csv')
        
        files = glob.glob(search_pattern)
        if not files:
            logger.warning(f"No Mercari CSV files found at: {search_pattern}")
            return pd.DataFrame(), {} # [修正] 空の辞書も返す
        
        latest_file = max(files, key=os.path.getmtime)
        logger.info(f"Processing latest Mercari file: {latest_file}")
        
        df = pd.read_csv(latest_file, encoding='cp932')
        
        df = df.rename(columns={'販売価格': '価格'})
        
        # 列名の揺れに対応
        id_candidates = ['商品ID', '商品ID(必須)', '商品id', 'item_id']
        id_col = next((c for c in id_candidates if c in df.columns), None)
        if id_col:
            df.rename(columns={id_col: '商品ID'}, inplace=True)
        else:
            logger.warning("'商品ID' column not found in Mercari CSV.")

        # 品番は数字のみ抽出
        hinban_series = df['商品名'].apply(extract_product_number)

        # URL列が存在しない場合は空のリストを作成
        if 'URL' in df.columns:
            url_series = df['URL']
        else:
            url_series = [''] * len(df)

        # watch/access列を追加（商品名全体でマッチング）
        watch_series = [0] * len(df)
        access_series = [0] * len(df)
        if mercari_stats:
            logger.info(f"メルカリstats辞書に {len(mercari_stats)} 件の情報があります")
            matched_count = 0
            for idx, product_name in enumerate(df['商品名'].astype(str)):
                if product_name in mercari_stats:
                    watch_series[idx] = mercari_stats[product_name].get('watch', 0)
                    access_series[idx] = mercari_stats[product_name].get('access', 0)
                    matched_count += 1
            logger.info(f"メルカリ: {matched_count} 件の商品名がstatsと紐付けられました")
            if matched_count == 0 and len(mercari_stats) > 0:
                logger.warning("⚠️ メルカリの商品名紐付けに失敗しています")
                if len(df) > 0:
                    logger.info(f"  CSV商品名例: {df['商品名'].iloc[0]}")
                if len(mercari_stats) > 0:
                    sample_key = list(mercari_stats.keys())[0]
                    logger.info(f"  stats商品名例: {sample_key}")
        else:
            logger.warning("mercari_statsが空です")
        # 複数列を一度に追加（最適化）
        # 注意: 商品登録日時と最終更新日時は元のCSVに既に存在するため追加しない
        new_cols = pd.DataFrame({
            'URL': url_series,
            '品番': hinban_series,
            'watch': watch_series,
            'access': access_series
        }, index=df.index)
        df = pd.concat([df, new_cols], axis=1)
        df = add_duplicate_column(df)

        # 商品ステータス列を追加（存在しない場合）
        if '商品ステータス' not in df.columns:
            df['商品ステータス'] = '0'  # デフォルト値として '0' (販売中) を設定
        
        # [追加] ブランドIDと品番のマップを作成
        hinban_to_brandid_map = {}
        if '品番' in df.columns and 'ブランドID' in df.columns:
            df_map = df[['品番', 'ブランドID']].copy()
            df_map.dropna(subset=['品番', 'ブランドID'], inplace=True)
            df_map['品番'] = df_map['品番'].astype(str)
            hinban_to_brandid_map = pd.Series(df_map['ブランドID'].values, index=df_map['品番']).to_dict()
            print(f"📚 品番->ブランドID辞書を {len(hinban_to_brandid_map)} 件読み込みました。")

        # 在庫数とリクエスト列を追加（mercari_statsから取得）
        stock_series = ['' for _ in range(len(df))]
        request_series = [0 for _ in range(len(df))]
        if mercari_stats:
            for idx, product_name in enumerate(df['商品名'].astype(str)):
                if product_name in mercari_stats:
                    stats_info = mercari_stats[product_name]
                    stock_series[idx] = stats_info.get('在庫数', '')
                    request_series[idx] = stats_info.get('リクエスト', 0)
        
        stock_col = pd.DataFrame({'在庫数': stock_series}, index=df.index)
        request_col = pd.DataFrame({'リクエスト': request_series}, index=df.index)
        df = pd.concat([df, stock_col, request_col], axis=1)

        final_cols = ['品番', '重複', '商品名', '価格', '在庫数', 'watch', 'access', 'リクエスト', '商品登録日時', '最終更新日時', '商品ステータス', '商品ID', 'ブランドID']
        for col in final_cols:
            if col not in df.columns:
                df[col] = ''
        
        logger.info(f"Found {len(df)} products in Mercari data.")
        return df[final_cols].copy(), hinban_to_brandid_map

    except Exception as e:
        logger.error(f"An error occurred while processing Mercari data: {e}")
        # エラー時も最低限の商品名・価格・watch/access列でCSV出力
        try:
            if '商品名' in df.columns:
                minimal_cols = ['商品名', '価格']
                if 'watch' in df.columns and 'access' in df.columns:
                    minimal_cols += ['watch', 'access']
                minimal_df = df[minimal_cols].copy()
                # 重複列を追加
                minimal_df = add_duplicate_column(minimal_df)
                logger.warning("エラー時の簡易CSV出力（重複列付き）を実施")
                return minimal_df, {}
        except Exception as e2:
            logger.error(f"簡易CSV出力も失敗: {e2}")
        return pd.DataFrame(), {}

def convert_to_edit_url(url):
    """URLを編集ページ形式に変換"""
    if '/edit' in url:
        return url
    
    if 'item.fril.jp/' in url:
        # クエリパラメータを除去
        base_url = url.split('?')[0]
        # item.fril.jp/{id} から {id} を抽出
        parts = base_url.split('item.fril.jp/')
        if len(parts) > 1:
            item_id = parts[1].rstrip('/')
            # fril.jp/item/{id}/edit 形式に変換
            return f"https://fril.jp/item/{item_id}/edit"
    
    return url

def move_to_draft_auto(draft_urls):
    """【自動化版】ラクマの商品を下書きに保存する"""
    if not draft_urls:
        logger.info("✅ 下書き移动対象がありません")
        return 0
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    user_data_dir = os.path.join(script_dir, 'rakuma_user_data')
    
    # URLを編集ページ形式に変換
    edit_urls = [convert_to_edit_url(url) for url in draft_urls]
    
    logger.info(f"\n📝 {len(edit_urls)} 件の商品を下書きに移動します")
    
    success_count = 0
    fail_count = 0
    
    try:
        with sync_playwright() as p:
            # Chromiumブラウザを起動（既存インスタンスと同じprofile使用）
            logger.info("🌐 ブラウザを起動中（下書き移动用）...")
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                timeout=60000
            )
            
            page = browser.pages[0] if browser.pages else browser.new_page()
            
            # マイページへのアクセスでセッション確認
            logger.info("🔍 ログイン状態を確認中...")
            try:
                page.goto("https://fril.jp/mypage", timeout=30000, wait_until='domcontentloaded')
                time.sleep(2)
            except:
                logger.warning("  マイページへのアクセスに失敗。続行します...")
            
            current_url = page.url
            if "login" in current_url.lower():
                logger.error("❌ ログインが必要です（セッション切れ）")
                browser.close()
                return 0
            
            logger.info("✅ ログイン状態確認完了")
            
            for idx, url in enumerate(edit_urls, 1):
                logger.info(f"[{idx}/{len(edit_urls)}] 処理中: {url}")
                
                try:
                    # 商品編集ページにアクセス
                    page.goto(url, timeout=30000, wait_until='domcontentloaded')
                    time.sleep(2)
                    
                    current_url = page.url
                    
                    # 404チェック
                    if page.locator('h1:has-text("お探しのページ")').count() > 0:
                        logger.info(f"  ⚠️ ページが見つかりません（削除済み）")
                        success_count += 1
                        continue
                    
                    # ログイン状態チェック
                    if "login" in current_url.lower():
                        logger.warning(f"  ❌ ログインページにリダイレクト")
                        fail_count += 1
                        continue
                    
                    # 「下書きに保存する」ボタンを探してクリック
                    draft_button = None
                    try:
                        draft_button = page.locator('button:has-text("下書きに保存する")').first
                        if draft_button.count() > 0:
                            draft_button.click(timeout=5000)
                            logger.info(f"  📝 「下書きに保存する」をクリック")
                    except:
                        pass
                    
                    if not draft_button:
                        logger.warning(f"  ⚠️ ボタンが見つかりません（既に下書き or 売却済み）")
                        success_count += 1
                        continue
                    
                    # 確認ボタンをクリック
                    time.sleep(1)
                    try:
                        confirm_button = page.locator('button:has-text("下書きに戻す")').first
                        if confirm_button.count() > 0:
                            confirm_button.click(timeout=5000)
                            logger.info(f"  ✅ 下書きに移動しました")
                            success_count += 1
                            time.sleep(2)
                        else:
                            logger.warning(f"  ⚠️ 確認ボタンが見つかりません")
                            fail_count += 1
                    except Exception as e:
                        logger.warning(f"  ⚠️ 確認ボタンクリック失敗: {e}")
                        fail_count += 1
                    
                except Exception as e:
                    logger.warning(f"  ❌ エラー: {e}")
                    fail_count += 1
            
            browser.close()
    
    except Exception as e:
        logger.error(f"❌ ドラフト移动処理エラー: {e}")
        return 0
    
    logger.info(f"\n📊 ドラフト移动完了: 成功 {success_count} 件 / 失敗 {fail_count} 件")
    return success_count

def parse_args():
    parser = argparse.ArgumentParser(description="Rakuma/Mercari data scraper")
    parser.add_argument("--base-url", default="https://fril.jp/shop/3c65d78bc0e1eadbe2a3528b344d8311")
    parser.add_argument("--scrape-all-pages", action="store_true", default=True)
    parser.add_argument("--mercari-path", default=None)
    parser.add_argument("--page-sleep", type=float, default=0.6)
    parser.add_argument("--item-sleep", type=float, default=0.4)
    parser.add_argument("--request-timeout", type=int, default=10)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()

def main():
    """メイン処理"""
    args = parse_args()
    configure_logging(args.verbose)

    # 先にラクマの出品中商品のwatch/accessを取得
    logger.info("\n=== ラクマ出品中商品のwatch/access取得 ===")
    rakuma_stats = scrape_rakuma_selling_stats()
    logger.info("ブラウザプロセスの完全終了を待機中...")
    time.sleep(5)  # ブラウザプロセスが完全に終了するまで待機
    
    # 下書きタブの商品をスクレイピング（ラクマなので同じブラウザ使用可能）
    logger.info("\n=== ラクマ下書きタブのスクレイピング ===")
    draft_urls = scrape_rakuma_draft_items()
    logger.info("ブラウザプロセスの完全終了を待機中...")
    time.sleep(5)  # ブラウザプロセスが完全に終了するまで待機
    
    # メルカリショップスの公開商品のwatch/accessを取得（最後に実行）
    logger.info("\n=== メルカリショップス公開商品のwatch/access取得 ===")
    mercari_stats = scrape_mercari_shops_stats()
    logger.info("ブラウザプロセスの完全終了を待機中...")
    time.sleep(3)  # ブラウザプロセスが完全に終了するまで待機

    logger.info("\n=== ラクマ商品データの処理 ===")
    # 既に取得したラクマのwatch/accessデータとdraft URLsを使用してDataFrameを構築
    logger.info(f"ラクマ処理を開始します（取得済みstats: {len(rakuma_stats)}件, draft URLs: {len(draft_urls)}件）")
    
    if rakuma_stats:
        # rakuma_stats から DataFrame を直接構築
        # ただし stats には商品名が含まれないため、各URLから商品名を軽量に取得して品番を抽出
        logger.info("rakuma_stats が存在するため、URL一覧から商品名を取得して DataFrame を構築します")
        rakuma_data_list = []

        # 軽量な requests セッションを作成
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        session = build_requests_session(headers)

        for url, stats_info in rakuma_stats.items():
            name = ''
            try:
                # 軽い GET でタイトルを取得（タイムアウト短め）
                resp = session.get(url, timeout=5)
                if resp.status_code == 200:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.content, 'html.parser')
                    # 優先: og:title -> data-test item_name -> title
                    og = soup.find('meta', property='og:title')
                    if og and og.get('content'):
                        name = og.get('content')
                    else:
                        name_tag = soup.find(attrs={'data-test': 'item_name'})
                        if name_tag:
                            name = name_tag.get_text(strip=True)
                        else:
                            if soup.title and soup.title.string:
                                name = soup.title.string.strip()
            except Exception:
                # 取得失敗でも続行（空の name でも問題ない）
                name = ''

            name = clean_rakuma_title(name)

            rakuma_data_list.append({
                '商品名': name,
                'URL': url,
                'watch': stats_info.get('watch', 0),
                'access': stats_info.get('access', 0)
            })

        rakuma_df = pd.DataFrame(rakuma_data_list)
        # 品番を抽出
        if '商品名' in rakuma_df.columns:
            rakuma_df['品番'] = rakuma_df['商品名'].apply(extract_product_number)
        else:
            rakuma_df['品番'] = ''

        # 重複列を追加
        rakuma_df = add_duplicate_column(rakuma_df)

        logger.info(f"✅ ラクマデータを構築しました（{len(rakuma_df)}件）")
    else:
        logger.warning("ラクマの取得データが空です")
        rakuma_df = pd.DataFrame()
    
    logger.info("\n=== メルカリ商品データの処理 ===")
    mercari_df, hinban_to_brandid_map = process_mercari_data(
        mercari_path=args.mercari_path,
        mercari_stats=mercari_stats
    )
    
    # メルカリショップスのstatsはproducts_mercari.csvに統合済み
    
    brand_master_map = load_brand_master_map()

    # --- [新規] ラクマデータにブランドマスターから引いたブランド名を設定 ---
    if not rakuma_df.empty and hinban_to_brandid_map and brand_master_map:
        rakuma_df['ブランドID'] = rakuma_df['品番'].astype(str).map(hinban_to_brandid_map)

        # ブランドIDに基づいて各ブランド名を設定する関数
        def get_brand_details(brand_id, column_name):
            if pd.isna(brand_id):
                return None
            return brand_master_map.get(str(brand_id), {}).get(column_name, None)

        # 新しい列を追加
        rakuma_df['ブランド名'] = rakuma_df['ブランドID'].apply(lambda x: get_brand_details(x, 'ブランド名'))
        rakuma_df['ブランド名（カナ）'] = rakuma_df['ブランドID'].apply(lambda x: get_brand_details(x, 'ブランド名（カナ）'))
        rakuma_df['ブランド名（英語）'] = rakuma_df['ブランドID'].apply(lambda x: get_brand_details(x, 'ブランド名（英語）'))
        # [削除] 既存のブランド列の更新ロジックを削除

    # --- ラクマデータにメルカリの商品IDを紐付ける処理を追加 ---
    logger.info("ラクマデータにメルカリの商品IDを紐付けます...")
    if not rakuma_df.empty and not mercari_df.empty and '品番' in mercari_df.columns and '商品ID' in mercari_df.columns:
        # メルカリデータから品番と商品IDのみを抽出（重複は最初のものを採用）
        mercari_id_map = mercari_df.drop_duplicates(subset=['品番'])[['品番', '商品ID']].copy()
        # 品番を文字列に統一してマージエラーを防ぐ
        mercari_id_map['品番'] = mercari_id_map['品番'].astype(str)
        if '品番' in rakuma_df.columns:
            rakuma_df['品番'] = rakuma_df['品番'].astype(str)
            # ラクマのデータフレームにメルカリの情報をマージする
            rakuma_df = pd.merge(rakuma_df, mercari_id_map, on='品番', how='left')
            # マージによって '商品ID_x', '商品ID_y' ができるのを防ぐため、元の '商品ID' を優先
            rakuma_df.rename(columns={'商品ID_x': '商品ID'}, inplace=True)
            logger.info("メルカリ商品IDの紐付けが完了しました。")
        else:
            logger.warning("ラクマデータに '品番' 列がないため、マージをスキップします。")
    elif rakuma_df.empty:
        logger.warning("ラクマデータが空のため、メルカリとのマージをスキップします。")
    # ---------------------------------------------------------
    
    logger.info("ラクマデータに削除列を追加する処理を開始...")
    
    # 下書きに既にある商品は処理対象から除外
    if draft_urls and not rakuma_df.empty:
        original_count = len(rakuma_df)
        rakuma_df = rakuma_df[~rakuma_df['URL'].isin(draft_urls)]
        excluded_count = original_count - len(rakuma_df)
        if excluded_count > 0:
            logger.info(f"✅ 下書きに既にある {excluded_count} 件の商品を処理対象から除外しました")
    
    # Mercariの品番をキー、商品ステータスを値とする辞書を作成
    if not rakuma_df.empty and '品番' in mercari_df.columns and '商品ステータス' in mercari_df.columns:
        # NaNを考慮し、dropna()を追加。ステータスは文字列として扱う
        mercari_status_map = pd.Series(mercari_df['商品ステータス'].astype(str).values, index=mercari_df['品番']).dropna().to_dict()
    else:
        logger.warning("Mercariデータに'品番'または'商品ステータス'列がないため、削除ロジックをスキップします。")
        mercari_status_map = {}

    def get_delete_status(row):
        # ラクマでSOLD OUTの場合は削除しない
        if row.get('is_sold_out', False):
            return ''

        hinban = row['品番']
        # 品番がNaNやNoneの場合はチェックしない
        if pd.isna(hinban):
            return ''
        
        mercari_status = mercari_status_map.get(str(hinban))
        
        if mercari_status is None: # 条件1: Mercariに品番が存在しない
            return '削除'

        # ステータスが '1' (売切れ) の場合
        if str(mercari_status) == '1': # 条件2: Mercariでのステータスが'1'
            return '削除'
            
        return ''

    # '品番'列が存在する場合のみ削除列を追加
    if '品番' in rakuma_df.columns:
        # is_sold_out列を先に処理
        if 'is_sold_out' not in rakuma_df.columns:
            rakuma_df['is_sold_out'] = False
        else:
            rakuma_df['is_sold_out'] = rakuma_df['is_sold_out'].fillna(False)

        rakuma_df['削除'] = rakuma_df.apply(get_delete_status, axis=1)
        # is_sold_out列を削除
        if 'is_sold_out' in rakuma_df.columns:
            rakuma_df = rakuma_df.drop(columns=['is_sold_out'])

        # --- 列の順序を最終調整 ---
        # 基本となる列の順序を定義
        final_cols_order = [
            '品番', '重複', '商品ID', '削除', '商品名', '価格', 'URL', 'watch', 'access', '商品説明', 'ブランド', 'ブランド名', 'ブランド名（カナ）', 'ブランド名（英語）',
            'カテゴリ', 'サイズ', '商品の状態', '配送料の負担', '配送方法', 'ブランドID',
            '発送日の目安', '発送元の地域', '商品の状態コード', '配送料負担コード', '発送日の目安コード'
        ]
        
        # 実際に存在する列のみで順序を再構築
        current_cols = rakuma_df.columns.tolist()
        ordered_cols = [col for col in final_cols_order if col in current_cols]
        
        # 順序定義に含まれないが、万が一存在する列があれば末尾に追加
        ordered_cols.extend([col for col in current_cols if col not in ordered_cols])
        
        rakuma_df = rakuma_df[ordered_cols]
    else:
        rakuma_df['削除'] = ''
        logger.warning("Rakumaデータに'品番'列がないため、削除ロジックをスキップします。")

    logger.info("削除列の処理完了。")

    # --- 注意: 下書き処理は rakuma_draft_mover.py で実行してください ---
    delete_count = len(rakuma_df[rakuma_df['削除'] == '削除']) if '削除' in rakuma_df.columns else 0
    duplicate_count = 0
    if '重複' in rakuma_df.columns and '品番' in rakuma_df.columns:
        dup_df = rakuma_df[rakuma_df['重複'] == '重複']
        if not dup_df.empty:
            duplicate_count = dup_df['品番'].nunique()
    
    if delete_count > 0 or duplicate_count > 0:
        print(f"\n📋 削除対象: {delete_count} 件")
        print(f"📋 重複対象: {duplicate_count} 品番")
        print("💡 下書きに移動するには: python rakuma_draft_mover.py を実行してください\n")

    # スクリプトが置かれているディレクトリを取得
    script_dir = os.path.dirname(os.path.abspath(__file__))

    output_rakuma_file = os.path.join(script_dir, 'products_rakuma.csv')
    output_mercari_file = os.path.join(script_dir, 'products_mercari.csv')
    
    logger.info(f"Writing Rakuma data to '{output_rakuma_file}'...")
    rakuma_df.to_csv(output_rakuma_file, index=False, encoding='utf-8-sig')
    
    logger.info(f"Writing Mercari data to '{output_mercari_file}'...")
    mercari_df.to_csv(output_mercari_file, index=False, encoding='utf-8-sig')
    
    # --- ヤフオクデータのスクレイピング ---
    if YAHOOKU_AVAILABLE:
        logger.info("\n=== ヤフオクデータのスクレイピングを開始 ===")
        try:
            driver = setup_driver()
            all_yahooku_items = []
            
            # 出品中の商品をスクレイピング
            logger.info("[1/2] 出品中の商品をスクレイピング...")
            items_selling = scrape_url(driver, SELLING_URL, "出品中")
            all_yahooku_items.extend(items_selling)
            
            # 終了商品（落札者なし）をスクレイピング
            logger.info("[2/2] 終了商品（落札者なし）をスクレイピング...")
            items_closed = scrape_url(driver, CLOSED_URL, "終了（落札者なし）")
            all_yahooku_items.extend(items_closed)
            
            # CSVに保存
            save_to_csv(all_yahooku_items)
            logger.info(f"✅ ヤフオクデータを products_yahooku.csv に保存しました（{len(all_yahooku_items)}件）")
            
            # ドライバを閉じる
            driver.quit()
            logger.info("ヤフオクスクレイピング完了")
            
        except Exception as e:
            logger.error(f"ヤフオクスクレイピング中にエラーが発生しました: {e}")
    else:
        logger.warning("ヤフオクスクレイピング機能が利用できないためスキップしました")
    
    # === 【自動化】ドラフト移动処理 ===
    logger.info("\n=== 【自動化】ラクマ商品の下書き移动を開始 ===")
    
    if not rakuma_df.empty and '削除' in rakuma_df.columns and 'URL' in rakuma_df.columns and '重複' in rakuma_df.columns:
        # 削除対象と重複対象を合わせてURL抽出
        draft_target_urls = []
        
        # 削除対象（削除 == '削除'）
        delete_targets = rakuma_df[rakuma_df['削除'] == '削除']['URL'].dropna().tolist()
        draft_target_urls.extend(delete_targets)
        
        # 重複対象（重複 == '重複' で、品番ごとに複数件ある場合は最後のものだけ残す）
        if '品番' in rakuma_df.columns:
            dup_df = rakuma_df[rakuma_df['重複'] == '重複'].copy()
            if not dup_df.empty:
                # 品番ごとにグループ化して、最後の1件だけを対象とする
                dup_targets = (
                    dup_df.dropna(subset=['URL'])
                          .groupby('品番', as_index=False)
                          .tail(1)
                          ['URL']
                          .tolist()
                )
                draft_target_urls.extend(dup_targets)
        
        # 重複削除（同じURLが削除対象・重複対象両方に含まれる場合がある）
        draft_target_urls = list(set(draft_target_urls))
        
        if draft_target_urls:
            logger.info(f"📋 下書き移动対象: {len(draft_target_urls)} 件")
            
            # 手動確認（オプション）
            logger.info("準備完了。下書き移动を開始します...")
            time.sleep(2)
            
            # ドラフト移动実行
            try:
                move_to_draft_auto(draft_target_urls)
            except Exception as e:
                logger.error(f"❌ ドラフト移动中にエラーが발생しました: {e}")
                logger.warning("スクレイピングは完了しました。下書き移动は失敗しましたが、products_rakuma.csv は出力済みです。")
        else:
            logger.info("✅ 下書き移动対象がありません")
    else:
        logger.warning("⚠️ ラクマ商品データが不完全なため、下書き移动をスキップします")
        
    logger.info("Script finished successfully.")

if __name__ == '__main__':
    main()
