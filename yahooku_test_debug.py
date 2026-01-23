r"""
ヤフオク出品テスト（デバッグ版）
実際の出品画面でセレクタを検証しながら進められるバージョン
"""
import os
import time
import sys
import datetime
from pathlib import Path

try:
    from yahooku_dorekai import setup_driver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except Exception as e:
    print(f"必要なモジュールをインポートできませんでした: {e}")
    sys.exit(1)

script_dir = Path(__file__).parent
sample_img = script_dir / 'sample_image.jpg'

# 画像がなければ作成
if not sample_img.exists():
    try:
        import base64
        jpg_b64 = b'/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8VAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAA8A/9k='
        sample_img.parent.mkdir(parents=True, exist_ok=True)
        with open(sample_img, 'wb') as f:
            f.write(base64.b64decode(jpg_b64))
        print(f"サンプル画像を作成しました: {sample_img}")
    except Exception as e:
        print(f"サンプル画像の作成に失敗しました: {e}")

item_data = {
    'title': 'テスト出品 (ヤフオク)',
    'description': 'これはテストです。',
    'price': 1000,
    'images': [str(sample_img)]
}

print("--- ヤフオク出品テスト（デバッグ版） ---")
print("ブラウザが起動します。出品ページまで進んでから、ターミナルに戻って Enter を押してください。")

driver = None
try:
    driver = setup_driver()
    
    # ヤフオク出品ページへ移動
    target_url = "https://auctions.yahoo.co.jp/sell/jp/show/submit?category=0"
    print(f"\n移動先: {target_url}")
    driver.get(target_url)
    time.sleep(5)
    
    # ログイン確認
    if "login" in driver.current_url:
        print("🔒 ログインページが表示されています。ブラウザでログインしてください。")
        input("ログイン完了後、Enter を押してください: ")
        driver.get(target_url)
        time.sleep(3)
    else:
        print("✅ ログイン済みまたは出品ページが表示されています。")
    
    input("\n出品ページが表示されたら、Enter を押してセレクタ検査を開始してください: ")
    
    # スクリーンショット保存
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    ss_path = f"yahoo_debug_{timestamp}.png"
    driver.save_screenshot(ss_path)
    print(f"✅ スクリーンショット保存: {ss_path}")
    
    # ページソース保存
    html_path = f"yahoo_debug_{timestamp}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"✅ ページソース保存: {html_path}")
    
    # セレクタ検査（ユーザーが確認できるように表示）
    print("\n--- セレクタ検査結果 ---")
    
    selectors_to_test = {
        'タイトル入力 (ID=Title)': (By.ID, 'Title'),
        'タイトル入力 (name=itemName)': (By.NAME, 'itemName'),
        'タイトル入力 (type=text)': (By.CSS_SELECTOR, 'input[type="text"]'),
        '説明テキストエリア (ID=Description)': (By.ID, 'Description'),
        '説明テキストエリア (textarea)': (By.CSS_SELECTOR, 'textarea'),
        '画像アップロード (input[type=file])': (By.CSS_SELECTOR, 'input[type="file"]'),
        '価格入力 (NAME=StartPrice)': (By.NAME, 'StartPrice'),
        '価格入力 (type=text number)': (By.CSS_SELECTOR, 'input[type="number"]'),
    }
    
    for desc, (by, selector) in selectors_to_test.items():
        try:
            elements = driver.find_elements(by, selector)
            status = f"✅ 見つかった（{len(elements)}個）" if elements else "❌ 見つかりません"
            print(f"  {desc}: {status}")
            if elements and len(elements) > 0:
                el = elements[0]
                print(f"     -> タグ: {el.tag_name}, ID: {el.get_attribute('id')}, name: {el.get_attribute('name')}, placeholder: {el.get_attribute('placeholder')}")
        except Exception as e:
            print(f"  {desc}: ❌ エラー - {e}")
    
    print("\n上のセレクタ検査結果を参考に、yahooku_dorekai.py のセレクタを修正してください。")
    print(f"ページソースを確認: {html_path}")
    print(f"スクリーンショットを確認: {ss_path}")
    
except Exception as e:
    print(f"❌ エラー: {e}")
    import traceback
    traceback.print_exc()

finally:
    if driver:
        print("\nブラウザを開いたままにします。F12でDevToolsも確認できます。")
        input("終了するには Enter を押してください: ")
