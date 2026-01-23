import time
import csv
import os
import re
import random
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError, Page

# --- 設定 ---
# スクレイピング対象のURL
TARGET_URL = "https://jp.mercari.com/user/profile/175075619"
# 出力するCSVファイル名
OUTPUT_CSV = "mercari_profile_products.csv"
# --- 設定ここまで ---

def log(message):
    """タイムスタンプ付きでログを出力する"""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def extract_product_number(name: str) -> Optional[str]:
    """商品名から品番（先頭の3-5桁の数字）を抽出する"""
    if not isinstance(name, str):
        return None
    match = re.match(r'^(\d{3,5})\s', name)
    return match.group(1) if match else None

def get_product_details(page: Page, url: str) -> dict:
    """商品詳細ページから情報を抽出する"""
    log(f"  詳細ページにアクセス: {url}")
    page.goto(url, wait_until='domcontentloaded', timeout=60000)
    time.sleep(1)

    product_data = {"URL": url}

    # 商品名
    if page.locator('[data-testid="name"]').count() > 0:
        name = page.locator('[data-testid="name"]').text_content().strip()
    else:
        name = page.locator('h1').first.text_content().strip()

    product_data["品番"] = extract_product_number(name)
    product_data["商品名"] = name

    # 価格
    if page.locator('[data-testid="price"]').count() > 0:
        price_text = page.locator('[data-testid="price"]').text_content()
        product_data["価格"] = re.sub(r'[^\d]', '', price_text)
    else:
        product_data["価格"] = ""

    # いいね数
    if page.locator('[data-testid="icon-heart-button"]').count() > 0:
        product_data["いいね数"] = page.locator('[data-testid="icon-heart-button"]').text_content().strip()
    else:
        product_data["いいね数"] = "0"

    # コメント数
    if page.locator('[data-location="item_details:item_info:comment_icon_button"]').count() > 0:
        product_data["コメント数"] = page.locator('[data-location="item_details:item_info:comment_icon_button"]').text_content().strip()
    else:
        product_data["コメント数"] = "0"

    # 商品説明
    if page.locator('[data-testid="description"]').count() > 0:
        product_data["商品説明"] = page.locator('[data-testid="description"]').text_content().strip()
    else:
        product_data["商品説明"] = ""

    # 画像URL (カルーセルから全画像取得)
    images = page.locator('[data-testid="carousel-item"] img').all()
    image_urls = []
    for img in images:
        src = img.get_attribute('src')
        if src:
            # クエリパラメータ削除
            src_clean = src.split('?')[0]
            image_urls.append(src_clean)
    # 重複排除してカンマ区切りで保存
    product_data["画像URL"] = ",".join(list(dict.fromkeys(image_urls)))

    product_data["商品ID"] = url.split('/item/')[1] if '/item/' in url else ''

    # 詳細情報 (data-testid ベースで取得)
    def get_detail(testid):
        loc = page.locator(f'[data-testid="{testid}"]')
        if loc.count() > 0:
            return loc.text_content().strip()
        return ""

    # カテゴリー (パンくずリストから取得)
    if page.locator('[data-testid="item-detail-category"]').count() > 0:
        product_data["カテゴリー"] = " > ".join(page.locator('[data-testid="item-detail-category"] a').all_text_contents())
    else:
        product_data["カテゴリー"] = ""

    product_data["サイズ"] = get_detail("サイズ")
    product_data["ブランド"] = get_detail("ブランド")
    product_data["状態"] = get_detail("商品の状態")
    product_data["配送料の負担"] = get_detail("配送料の負担")
    product_data["配送の方法"] = get_detail("配送の方法")
    product_data["発送元の地域"] = get_detail("発送元の地域")
    product_data["発送までの日数"] = get_detail("発送までの日数")

    return product_data


def main():
    """
    指定されたメルカリのプロフィールページから出品中の商品情報をスクレイピングし、
    CSVファイルに保存するメイン関数。
    """
    log("処理を開始します。")
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False) # headless=Trueにするとブラウザ非表示
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            log(f"ページにアクセスします: {TARGET_URL}")
            page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=90000) # タイムアウトを90秒に延長
            time.sleep(2) # ページが安定するのを待つ

            # 「もっと見る」ボタンがなくなるまでクリックし続ける
            log("「もっと見る」ボタンを順次クリックして全商品を表示します...")
            while True:
                try:
                    item_count_before = page.locator('li[data-testid="item-cell"]').count()

                    # ページ最下部までスクロール
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    log(f"    スクロールしました (現在 {item_count_before}件)。新しいボタン/アイテムの読み込みを待ちます...")
                    time.sleep(1.5) # スクロールイベントが処理されるのを待つ時間を延長

                    # 「もっと見る」ボタンを探す
                    load_more_button = page.locator('button:has-text("もっと見る")')
                    
                    # ボタンが表示されるのを待つ (少し長めに)
                    load_more_button.wait_for(state="visible", timeout=7000)
                    
                    # ボタンをクリック
                    load_more_button.click()
                    log("    「もっと見る」ボタンをクリックしました。")

                    # クリック後、アイテム数が増えるのを待つ (これが最も確実な待機方法)
                    page.wait_for_function(
                        expression=f"document.querySelectorAll('li[data-testid=\"item-cell\"]').length > {item_count_before}",
                        timeout=15000 # 15秒待っても増えなければ、読み込み完了かエラーと判断
                    )
                    
                    item_count_after = page.locator('li[data-testid="item-cell"]').count()
                    log(f"    アイテム数が増加しました: {item_count_before} -> {item_count_after}")
                    
                    # 次のループのために少し間を置く
                    time.sleep(1)

                except TimeoutError:
                    log("「もっと見る」ボタンが見つからないか、タイムアウトしました。全件読み込み完了と判断します。")
                    break
                except Exception as e:
                    log(f"「もっと見る」処理中に予期せぬエラーが発生しました: {e}")
                    break

            # まずは販売中の商品のURLをすべて取得
            all_items = page.locator('li[data-testid="item-cell"]').all()
            log(f"合計 {len(all_items)} 件のアイテム要素を取得しました。")
            
            products_to_scrape = []
            for item in all_items:
                try:
                    item.scroll_into_view_if_needed(timeout=5000)
                    if item.locator('div[data-testid="thumbnail-sticker"]').count() == 0:
                        link_loc = item.locator('a[data-testid="thumbnail-link"]')
                        if link_loc.count() > 0:
                            relative_url = link_loc.get_attribute('href')
                            url = f"https://jp.mercari.com{relative_url}"
                            products_to_scrape.append(url)
                except Exception as e:
                    log(f"URLの取得中にエラーが発生しました（スキップします）: {e}")

            # 各商品ページを巡回して詳細情報を取得
            scraped_data = []
            try:
                for i, url in enumerate(products_to_scrape):
                    log(f"--- 商品 {i+1}/{len(products_to_scrape)} を処理中 ---")
                    
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            product_details = get_product_details(page, url)
                            scraped_data.append(product_details)
                            time.sleep(random.uniform(3.0, 6.0)) # 待機時間を少し延長して安定化
                            break # 成功したらループを抜ける
                        except Exception as e:
                            if attempt < max_retries - 1:
                                wait_time = 10 * (attempt + 1)
                                log(f"⚠️ エラー (試行 {attempt+1}/{max_retries}): {e}。{wait_time}秒待機して再試行します...")
                                time.sleep(wait_time)
                            else:
                                log(f"❌ 詳細ページの処理中にエラーが発生しました（スキップします）: {url} - {e}")
                                scraped_data.append({"URL": url, "商品名": f"SCRAPE_FAILED: {e}"})
            except KeyboardInterrupt:
                log("🛑 ユーザーによって処理が中断されました。これまでのデータを保存します。")

            # CSVに保存
            if scraped_data:
                log(f"全 {len(scraped_data)} 件の商品のスクレイピングが完了しました。")
                fieldnames = [
                    '品番', '商品ID', '商品名', '価格', 'いいね数', 'コメント数', '商品説明', 'カテゴリー', 'ブランド', 
                    'サイズ', '状態', '配送料の負担', '配送の方法', 
                    '発送元の地域', '発送までの日数', 'URL', '画像URL'
                ]
                script_dir = os.path.dirname(os.path.abspath(__file__))
                output_path = os.path.join(script_dir, OUTPUT_CSV)
                with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(scraped_data)
                log(f"データを {output_path} に保存しました。")
            
            browser.close()

        except Exception as e:
            log(f"エラーが発生しました: {e}")

    log("処理が完了しました。")

if __name__ == "__main__":
    main()