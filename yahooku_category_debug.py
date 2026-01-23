r"""
ヤフオク カテゴリ選択フロー デバッグ
モーダル内のHTMLを保存して、updateCategory等の確定ボタンを探す
"""
import os
import time
import sys
import datetime
from pathlib import Path

try:
    from yahooku_dorekai import setup_driver, select_category
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except Exception as e:
    print(f"必要なモジュールをインポートできませんでした: {e}")
    sys.exit(1)

print("--- ヤフオク カテゴリ選択 デバッグ ---")

driver = None
try:
    driver = setup_driver()
    
    # ヤフオク出品ページへ移動
    target_url = "https://auctions.yahoo.co.jp/sell/jp/show/submit?category=0"
    print(f"\n移動先: {target_url}")
    driver.get(target_url)
    time.sleep(3)
    
    # ログイン確認
    if "login" in driver.current_url:
        print("🔒 ログインページが表示されています。ブラウザでログインしてください。")
        input("ログイン完了後、Enter を押してください: ")
        driver.get(target_url)
        time.sleep(3)
    else:
        print("✅ ログイン済みまたは出品ページが表示されています。")
    
    input("\n出品ページが表示されたら、Enter を押してカテゴリ選択を開始してください: ")
    
    # Step 1: acMdCateChange ボタンをクリック
    print("\n【Step 1】カテゴリ選択ボタンをクリック...")
    try:
        btn = driver.find_element(By.ID, "acMdCateChange")
        btn.click()
        print("✅ クリック成功。モーダルが開くはずです。")
        time.sleep(2)
    except Exception as e:
        print(f"❌ エラー: {e}")
        driver.quit()
        sys.exit(1)
    
    # Step 2: モーダル内のHTMLを保存
    print("\n【Step 2】モーダル内のHTMLを保存...")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # モーダル要素を待つ
    try:
        WebDriverWait(driver, 10).until(
            lambda d: d.find_elements(By.XPATH, "//*[contains(@class, 'Modal') or contains(@class, 'modal')]")
        )
        print("✅ モーダルが検出されました。")
    except Exception:
        print("⚠️ モーダル要素が見つかりませんでしたが、続行します。")
    
    time.sleep(1)
    
    # HTMLを保存
    html_path = f"yahoo_category_debug_{timestamp}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"✅ HTMLを保存: {html_path}")
    
    # スクリーンショット保存
    ss_path = f"yahoo_category_debug_{timestamp}.png"
    driver.save_screenshot(ss_path)
    print(f"✅ スクリーンショット保存: {ss_path}")
    
    # Step 3: モーダル内の要素を調査
    print("\n【Step 3】モーダル内の要素を調査...")
    
    # updateCategory を探す
    try:
        upd = driver.find_element(By.ID, "updateCategory")
        print("✅ updateCategory を見つけました!")
        print(f"   タグ: {upd.tag_name}, 表示: {upd.is_displayed()}")
    except Exception:
        print("❌ updateCategory が見つかりません")
    
    # 「このカテゴリに出品」テキストを持つボタン
    try:
        btns = driver.find_elements(By.XPATH, "//*[contains(text(), 'このカテゴリに出品')]")
        if btns:
            print(f"✅ 「このカテゴリに出品」を含む要素: {len(btns)}個")
            for i, b in enumerate(btns[:3]):
                print(f"   {i+1}. {b.tag_name}, id={b.get_attribute('id')}, class={b.get_attribute('class')}")
    except Exception as e:
        print(f"❌ エラー: {e}")
    
    # モーダル内のすべてのボタンを列挙
    try:
        btns = driver.find_elements(By.XPATH, "//button | //input[@type='submit'] | //input[@type='button']")
        print(f"\n✅ ボタン要素の合計: {len(btns)}個")
        for i, b in enumerate(btns[-5:]):  # 最後の5個を表示
            print(f"   {i+1}. {b.tag_name}, value/text={b.get_attribute('value') or b.text or b.get_attribute('class')}")
    except Exception as e:
        print(f"❌ エラー: {e}")
    
    print("\n" + "="*60)
    print(f"保存されたファイル:")
    print(f"  HTML: {html_path}")
    print(f"  スクリーンショット: {ss_path}")
    print("\nこれらのファイルを確認して、updateCategory ボタンのセレクタを特定してください。")
    print("="*60)
    
    input("\n終了するには Enter を押してください: ")
    
except Exception as e:
    print(f"❌ エラー: {e}")
    import traceback
    traceback.print_exc()

finally:
    if driver:
        print("ブラウザを閉じています...")
        try:
            driver.quit()
        except Exception:
            pass
