r"""
Yahoo topsubmit ページの フォーム構造を確認
"""
import sys
import time
from pathlib import Path

try:
    from yahooku_dorekai import setup_driver
    from selenium.webdriver.common.by import By
except Exception as e:
    print(f"エラー: {e}")
    sys.exit(1)

driver = None
try:
    driver = setup_driver()
    
    # ヤフオク出品ページへ移動
    target_url = "https://auctions.yahoo.co.jp/sell/jp/show/submit?category=0"
    print(f"移動先: {target_url}")
    driver.get(target_url)
    time.sleep(3)
    
    if "login" in driver.current_url:
        print("ログイン完了後、Enterキーを押してください:")
        input()
        driver.get(target_url)
        time.sleep(3)
    
    print("\n【ステップ1】カテゴリを選択してください:")
    input()
    
    # selectCategory() を実行
    print("selectCategory() を実行します...")
    driver.execute_script("""
        if (typeof selectCategory === 'function') {
            selectCategory();
        } else if (document.forms['auction']) {
            document.forms['auction'].submit();
        }
    """)
    print("ページ遷移中...")
    time.sleep(5)
    
    print(f"\n現在のURL: {driver.current_url}")
    
    # 【フォーム構造】
    print("\n【フォーム構造】")
    
    # すべての入力フィールドを列挙
    inputs = driver.find_elements(By.CSS_SELECTOR, "input, textarea, select")
    print(f"すべての入力要素: {len(inputs)}個")
    
    # フィルタリング: 表示されているフィールドのみ
    visible_inputs = []
    for inp in inputs:
        try:
            if inp.is_displayed():
                visible_inputs.append(inp)
        except Exception:
            pass
    
    print(f"表示されているフィールド: {len(visible_inputs)}個")
    for i, inp in enumerate(visible_inputs[:20]):
        _id = inp.get_attribute('id') or '(no id)'
        name = inp.get_attribute('name') or '(no name)'
        _type = inp.get_attribute('type') or inp.tag_name
        placeholder = inp.get_attribute('placeholder') or ''
        value = inp.get_attribute('value') or ''
        print(f"  {i+1}. type={_type:10} id={_id:20} name={name:20} placeholder={placeholder[:20]:20}")
    
    # 特定フィールドを探す
    print("\n【特定フィールドの検索】")
    for selector, desc in [
        ("input[id='fleaTitleForm']", "タイトル (fleaTitleForm)"),
        ("input[name='Title']", "タイトル (name=Title)"),
        ("textarea[name='kanso']", "説明 (kanso)"),
        ("textarea", "テキストエリア（任意）"),
        ("input[id='auc_StartPrice']", "価格 (auc_StartPrice)"),
        ("input[name='StartPrice']", "価格 (name=StartPrice)"),
        ("input[type='number']", "数値入力（任意）"),
        ("input[type='file']", "ファイル入力"),
    ]:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, selector)
            if els:
                el = els[0]
                visible = "✅表示" if el.is_displayed() else "❌非表示"
                print(f"  {visible} {desc}: 見つかった（{len(els)}個）")
                if el.is_displayed():
                    print(f"         id={el.get_attribute('id')}, name={el.get_attribute('name')}, type={el.get_attribute('type')}")
            else:
                print(f"  ❌ {desc}: 見つかりません")
        except Exception as e:
            print(f"  ⚠️ {desc}: エラー - {e}")
    
    print("\nページを表示したままにしています。F12でコンソールを確認できます。")
    input("終了するには Enterキーを押してください: ")
    
finally:
    if driver:
        driver.quit()
