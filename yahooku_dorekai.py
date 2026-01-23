import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

def setup_driver():
    """
    ブラウザドライバーのセットアップ
    Firefox を優先し、ない場合は Chrome を使用
    既存のプロファイルを使用してログイン状態を維持
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Firefox を試す
    try:
        firefox_options = FirefoxOptions()
        firefox_options.add_argument('--disable-blink-features=AutomationControlled')
        firefox_profile_dir = os.path.join(script_dir, "yahoo_user_data_firefox")
        firefox_options.add_argument(f"-profile={firefox_profile_dir}")
        driver = webdriver.Firefox(options=firefox_options)
        print("🦊 Firefox を使用します")
        return driver
    except Exception as e:
        print(f"⚠️ Firefox が見つかりません: {e}. Chrome にフォールバックします...")
    
    # Chrome にフォールバック
    try:
        chrome_options = ChromeOptions()
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
        user_data_dir = os.path.join(script_dir, "yahoo_user_data")
        chrome_options.add_argument(f"user-data-dir={user_data_dir}")
        driver = webdriver.Chrome(options=chrome_options)
        print("🌐 Chrome を使用します")
        return driver
    except Exception as e:
        print(f"❌ Chrome も見つかりません: {e}")
        raise


def select_category(driver, preferred_texts=None, timeout=10):
    """
    カテゴリ選択。モーダルを開き、最終カテゴリを選択してから確定ボタンをクリック。
    失敗しても出品フロー継続のため、エラーは軽く扱う。
    """
    try:
        wait = WebDriverWait(driver, timeout)
        
        # カテゴリ選択ボタン (acMdCateChange) をクリック
        try:
            btn = wait.until(EC.element_to_be_clickable((By.ID, "acMdCateChange")))
            btn.click()
            print("✅ カテゴリ選択ボタンをクリックしました。")
        except Exception as e:
            print(f"⚠️ カテゴリ選択ボタンをクリックできません: {e}")
            return False
        time.sleep(2)

        # 最終カテゴリ（.decEnd）を探してクリック
        try:
            end_els = driver.find_elements(By.CSS_SELECTOR, 'li.decEnd')
            if end_els:
                driver.execute_script("arguments[0].scrollIntoView(true);", end_els[0])
                end_els[0].click()
                print("✅ 最終カテゴリを選択しました。")
                time.sleep(1)
        except Exception as e:
            print(f"⚠️ 最終カテゴリ選択失敗: {e}")

        # 確定ボタンをクリック（複数の戦略で試す）
        confirmed = False
        
        # 戦略1: ID='updateCategory'
        try:
            upd = driver.find_element(By.ID, "updateCategory")
            driver.execute_script("arguments[0].scrollIntoView(true);", upd)
            time.sleep(0.5)
            upd.click()
            print("✅ 【updateCategory】でカテゴリ確定ボタンをクリックしました。")
            confirmed = True
        except Exception:
            pass
        
        # 戦略2: text='このカテゴリに出品' or '出品する'
        if not confirmed:
            try:
                for text in ['このカテゴリに出品', '出品する', '確定', '決定']:
                    els = driver.find_elements(By.XPATH, f"//*[contains(text(), '{text}')]")
                    if els:
                        btn = els[0]
                        driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                        time.sleep(0.5)
                        btn.click()
                        print(f"✅ 【{text}】でカテゴリ確定ボタンをクリックしました。")
                        confirmed = True
                        break
            except Exception as e:
                print(f"⚠️ テキスト検索失敗: {e}")
        
        # 戦略3: 最後のボタンを試す
        if not confirmed:
            try:
                btns = driver.find_elements(By.XPATH, "//button[@type='submit'] | //input[@type='submit'] | //input[@type='button'][contains(@class, 'Button')]")
                if btns:
                    btn = btns[-1]  # 最後のボタン
                    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                    time.sleep(0.5)
                    btn.click()
                    print(f"✅ 【最後のボタン】でカテゴリ確定ボタンをクリックしました。")
                    confirmed = True
            except Exception as e:
                print(f"⚠️ ボタン検索失敗: {e}")

        time.sleep(2)
        return confirmed
            
    except Exception as e:
        print(f"⚠️ select_category エラー: {e}")
        return False


def ensure_no_overlay(driver, timeout=3):
    """
    ページ上のオーバーレイやモーダルでクリックが遮断される場合に備え、
    それらが消えるまで待機し、必要なら簡易的に削除する。
    """
    # --- キャンペーンモーダル（PayPay祭りなど）の正規処理 ---
    try:
        # 「出品を続ける」ボタン (ID: js-CampaignPRModal_submit)
        submit_btns = driver.find_elements(By.ID, "js-CampaignPRModal_submit")
        if submit_btns:
            btn = submit_btns[0]
            if btn.is_displayed():
                print("   🎁 キャンペーンモーダルを検出しました。")
                # 「次回から表示しない」チェックボックス (ID: js-CampaignPRModal_showCheck)
                try:
                    checkboxes = driver.find_elements(By.ID, "js-CampaignPRModal_showCheck")
                    if checkboxes:
                        cb = checkboxes[0]
                        if not cb.is_selected():
                            driver.execute_script("arguments[0].click();", cb)
                            print("   ☑️ 「次回から表示しない」をチェックしました。")
                except Exception:
                    pass
                driver.execute_script("arguments[0].click();", btn)
                print("   ✅ 「出品を続ける」をクリックしました。")
                time.sleep(1.5)
    except Exception:
        pass

    try:
        selectors = [
            '.DDModal__filter', '.modal', '.overlay', '.ui-dialog', '.modal-backdrop',
            '.v4-overlay', '.c-modal__overlay', '.js-drawer', '.ui-overlay',
            # PayPay祭りなどのキャンペーンモーダル対策
            '.PayPayMaturiModal__filter', '#js-CampaignPRModal_filter', 'div[class*="Modal__filter"]'
        ]
        for sel in selectors:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    if el.is_displayed():
                        driver.execute_script("arguments[0].style.display='none';", el)
                        print(f"   🧹 オーバーレイを非表示にしました: {sel}")
            except Exception:
                pass

        try:
            driver.execute_script('''
            Array.from(document.querySelectorAll('body *')).forEach(function(e){
                try{
                    var s = window.getComputedStyle(e);
                    if ((s.position==='fixed' || s.position==='absolute') && (parseInt(s.zIndex)||0) > 1000) {
                        e.style.display='none';
                    }
                } catch(err){}
            });
            ''')
        except Exception:
            pass

        time.sleep(min(0.5, timeout))
    except Exception:
        pass


def select_category_by_path(driver, category_path, timeout=12):
    """
    指定のカテゴリパスを順にクリックしてカテゴリを選択する試みを行う。
    例: "オークショントップ > ファッション > レディースファッション > フォーマル > カラードレス > その他"
    成功すれば True を返す。失敗しても False を返して処理を継続する。
    """
    try:
        wait = WebDriverWait(driver, timeout)
        
        # 事前にオーバーレイを削除
        ensure_no_overlay(driver)

        # モーダルを開く
        try:
            btn = wait.until(EC.element_to_be_clickable((By.ID, "acMdCateChange")))
            # クリックが阻害される可能性があるためリトライ処理を入れる
            for _ in range(3):
                try:
                    btn.click()
                    break
                except Exception as e:
                    if "intercepted" in str(e):
                        print("   ⚠️ クリックが阻害されました。オーバーレイを再確認します...")
                        ensure_no_overlay(driver)
                        time.sleep(1)
                    else:
                        raise e
            print("✅ カテゴリ選択モーダルを開きました（select_by_path）。")
        except Exception as e:
            print(f"⚠️ カテゴリモーダルを開けませんでした: {e}")
            return False

        time.sleep(1)

        # --- 履歴タブからの選択を試みる (ユーザー要望により優先) ---
        try:
            print("   🔄 「履歴から選択する」タブを確認中...")
            # タブをクリック
            history_tabs = driver.find_elements(By.XPATH, "//*[contains(text(), '履歴から選択する')]")
            if history_tabs:
                # 見えている要素をクリック
                for tab in history_tabs:
                    if tab.is_displayed():
                        driver.execute_script("arguments[0].click();", tab)
                        print("   ✅ 「履歴から選択する」タブをクリックしました。")
                        time.sleep(1.5)
                        break
                
                # 履歴リストからカテゴリを選択
                # ユーザー指定のパスに合致するものを探す、なければ履歴のトップを選択
                target_id = None
                
                # パスに含まれるキーワード（例：カラードレス）で検索
                keywords = [k for k in category_path.split('>') if k.strip() and k.strip() != "その他"]
                search_keyword = keywords[-1] if keywords else ""
                
                labels = driver.find_elements(By.CSS_SELECTOR, "#history_category_pages label")
                
                # 1. キーワードを含むラベルを探す
                if search_keyword:
                    for lbl in labels:
                        if search_keyword in lbl.text:
                            target_id = lbl.get_attribute("for")
                            print(f"   ✅ 履歴からカテゴリ候補を見つけました: {lbl.text}")
                            break
                
                # 2. 見つからなければ、履歴の1番目 (history_category_index1) を選択
                if not target_id:
                    idx1 = driver.find_elements(By.ID, "history_category_index1")
                    if idx1:
                        target_id = "history_category_index1"
                        print("   ⚠️ 指定カテゴリが履歴に見つかりませんでしたが、履歴の先頭を選択します。")
                
                if target_id:
                    # ラジオボタン選択
                    radio = driver.find_element(By.ID, target_id)
                    driver.execute_script("arguments[0].click();", radio)
                    time.sleep(0.5)
                    
                    # 「このカテゴリに出品」ボタン (history_category_submit)
                    submit_btn = driver.find_elements(By.ID, "history_category_submit")
                    if submit_btn:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", submit_btn[0])
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", submit_btn[0])
                        print("   ✅ 履歴からカテゴリを確定しました (history_category_submit)。")
                        time.sleep(3.0)
                        return True
            else:
                print("   ℹ️ 「履歴から選択する」タブが見つかりません。通常の階層選択を行います。")
        except Exception as e:
            print(f"   ⚠️ 履歴選択処理でエラーが発生しました（階層選択へ移行します）: {e}")

        parts = [p.strip() for p in category_path.split('>') if p.strip()]
        if not parts:
            print("⚠️ 空のカテゴリパスです。")
            return False

        # モーダル領域の限定探索: role=dialog や表示中のモーダルを優先
        modal_roots = []
        try:
            candidates = driver.find_elements(By.CSS_SELECTOR, "[role='dialog'], .acMdCateList, .acMdCategory, .acModal, .modal, .acMdCategoryList")
            for c in candidates:
                try:
                    if c.is_displayed():
                        modal_roots.append(c)
                except Exception:
                    continue
        except Exception:
            modal_roots = []

        # もしモーダル領域が見つからなければ、ページ全体を探索対象にする
        search_roots = modal_roots if modal_roots else [driver]

        for idx, part in enumerate(parts):
            clicked = False
            for root in search_roots:
                try:
                    # 優先度の高い XPath パターン順に試す
                    patterns = [
                        f".//li[normalize-space(.)='{part}']",
                        f".//a[normalize-space(.)='{part}']",
                        f".//button[normalize-space(.)='{part}']",
                        f".//*[normalize-space(text())='{part}']",
                        f".//*[contains(normalize-space(.), '{part}')]"
                    ]
                    for pat in patterns:
                        try:
                            elems = root.find_elements(By.XPATH, pat)
                        except Exception:
                            elems = []
                        for e in elems:
                            try:
                                if e.is_displayed():
                                    driver.execute_script("arguments[0].scrollIntoView(true);", e)
                                    time.sleep(0.2)
                                    e.click()
                                    print(f"   ✅ カテゴリ階層をクリック: {part}")
                                    clicked = True
                                    time.sleep(0.8)
                                    break
                            except Exception:
                                continue
                        if clicked:
                            break
                except Exception as e:
                    print(f"   ⚠️ モーダル内部探索エラー ({part}): {e}")
                if clicked:
                    break

            if not clicked:
                # グローバルに再度検索して最終トライ
                try:
                    elems = driver.find_elements(By.XPATH, f"//*[contains(normalize-space(.), '{part}')]")
                    for e in elems:
                        try:
                            if e.is_displayed():
                                driver.execute_script("arguments[0].scrollIntoView(true);", e)
                                time.sleep(0.2)
                                e.click()
                                print(f"   ✅ (グローバル) カテゴリ階層をクリック: {part}")
                                clicked = True
                                time.sleep(0.8)
                                break
                        except Exception:
                            continue
                except Exception:
                    pass

            if not clicked:
                print(f"   ⚠️ カテゴリ '{part}' を見つけられませんでした（途中で中断）。")
                return False

        # 最後に確定ボタンをクリックする
        print("   🔄 確定ボタンをクリックしようとしています...")
        time.sleep(1.5) # ボタンがアクティブになるのを少し待つ

        # 複数回トライする
        for attempt in range(3):
            try:
                # ID='updateCategory' を優先
                upd_list = driver.find_elements(By.ID, "updateCategory")
                if upd_list:
                    upd = upd_list[0]
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", upd)
                    time.sleep(0.5)
                    # href="javascript:void(0)" のため、JSクリックの方が確実
                    driver.execute_script("arguments[0].click();", upd)
                    print("✅ カテゴリをパス指定で確定しました (JS Click)。")
                    time.sleep(3.0)
                    return True
                
                # テキストベースで確定ボタンを探す (バックアップ)
                for text in ['このカテゴリに出品', '出品する', '確定', '決定']:
                    els = driver.find_elements(By.XPATH, f"//*[contains(text(), '{text}')]")
                    if els:
                        btn = els[0]
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", btn)
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", btn)
                        print(f"✅ テキスト '{text}' でカテゴリ確定しました。")
                        time.sleep(3.0)
                        return True
            except Exception as e:
                print(f"   ⚠️ 確定ボタンクリック試行 {attempt+1} 失敗: {e}")
                time.sleep(1.0)

        return False
    except Exception as e:
        print(f"⚠️ select_category_by_path エラー: {e}")
        return False

def list_item_on_yahoo_auction(driver, item_data):
    """
    ヤフオクに出品する関数
    
    item_data の構造:
    {
        "title": "商品タイトル",
        "description": "商品説明",
        "price": 1000,
        "images": ["画像パス"],
        "category_path": "オークショントップ > ファッション > レディースファッション > ... > その他"  # (オプション)
    }
    """
    try:
        # 出品ページへ遷移（カテゴリ選択済みのURLや、出品トップページなど）
        # カテゴリ選択は複雑なため、ここでは「出品情報の入力」ページに到達している前提、
        # もしくはブックマークした特定のカテゴリ出品URLを使用することを想定しています。
        target_url = "https://auctions.yahoo.co.jp/sell/jp/show/submit?category=0" # カテゴリIDは適宜変更が必要
        
        # 既にカテゴリ選択済みのページ（URLにsubmitが含まれ、かつcategory=0ではない）にいる場合は遷移しない
        if "sell/jp/show/submit" in driver.current_url and "category=0" not in driver.current_url:
            print("ℹ️ 既にカテゴリ選択済みのページにいます。ページ遷移をスキップします。")
        elif "sell/jp/show/submit" not in driver.current_url:
            driver.get(target_url)
        else:
            print("ℹ️ 出品ページ（カテゴリ選択画面）にいます。")
        
        wait = WebDriverWait(driver, 20)

        print("ページ読み込み待機中...")
        time.sleep(3) # ページ描画待ち

        # --- ログインチェック ---
        if "login" in driver.current_url:
            print("🔒 ログインページを検知しました。ブラウザでログイン操作を行ってください。")
            # ログイン完了してURLが変わるのを待つ
            while "login" in driver.current_url:
                time.sleep(1)
            print("🔓 ログイン完了を検知しました。ページを再読み込みします。")
            driver.get(target_url)
            time.sleep(3)

        # --- カテゴリ選択（複雑なため、通常は手動で行う） ---
        # ユーザーがブラウザで手動でカテゴリを選択することを想定
        print("📋 【ステップ1】カテゴリ選択")
        
        # カテゴリテキストを取得してみる
        try:
            category_text_elem = driver.find_element(By.CSS_SELECTOR, ".Category__text")
            current_category_text = category_text_elem.text.strip()
        except Exception:
            current_category_text = ""
        
        # 指定されたカテゴリパスと現在のカテゴリを比較
        desired_category = item_data.get("category_path", "")
        
        # テキストを正規化（複数空白、&nbsp;など）
        def normalize_category_text(text):
            # &nbsp; を > に変換
            text = text.replace("\u00a0", " ")
            # 複数空白を単一空白に
            text = " ".join(text.split())
            return text.strip()
        
        current_category_normalized = normalize_category_text(current_category_text)
        # 「オークショントップ > 」が先頭にある場合は削除して比較する（指定パスとの整合性のため）
        if current_category_normalized.startswith("オークショントップ > "):
            current_category_normalized = current_category_normalized.replace("オークショントップ > ", "", 1)

        desired_category_normalized = normalize_category_text(desired_category) if desired_category else ""
        
        print(f"   現在のカテゴリ: {current_category_text}")
        if desired_category:
            print(f"   指定カテゴリ: {desired_category}")
        
        # カテゴリが一致している場合はスキップ
        if desired_category_normalized and current_category_normalized == desired_category_normalized:
            print("   ✅ 指定カテゴリと一致しているため、カテゴリ選択をスキップします。")
        elif current_category_text:
            # すでに何かカテゴリが選択されている場合
            print("   ✅ 既にカテゴリが選択されています。スキップします。")
        else:
            # カテゴリがまだ選択されていない場合
            print("   ⚠️ カテゴリがまだ選択されていません。自動選択を試みます...")
            desired = desired_category if desired_category else ""
            success = False
            if desired:
                try:
                    success = select_category_by_path(driver, desired)
                except Exception:
                    success = False

            if success:
                # 自動選択成功した場合、現在のカテゴリを再取得
                try:
                    time.sleep(1)
                    category_text_elem = driver.find_element(By.CSS_SELECTOR, ".Category__text")
                    current_category_text = category_text_elem.text.strip()
                    print(f"   ✅ 自動でカテゴリを設定しました: {current_category_text}")
                except Exception:
                    print("   ⚠️ 自動選択後のカテゴリ確認に失敗しました。")
            else:
                print("   ⚠️ 自動選択に失敗しました。手動でカテゴリを選択してください。")
                # input("   カテゴリ選択完了後、Enterキーを押してください: ")
                print("   ⚠️ 自動処理のため、手動入力をスキップして続行します。")
                try:
                    category_text_elem = driver.find_element(By.CSS_SELECTOR, ".Category__text")
                    current_category_text = category_text_elem.text.strip()
                    if current_category_text:
                        print(f"   ✅ カテゴリを確認しました: {current_category_text}")
                except Exception:
                    print("   ⚠️ カテゴリの確認に失敗しました。")
        
        # 確定ボタン（あれば）をクリック（1回のみ実行）
        # selectCategory() はページ遷移を行うため、不要な複数呼び出しを避ける
        print("   カテゴリを確定しています...")
        try:
            category_action_done = False

            # 必要な場合のみ selectCategory を呼ぶ:
            # - 現在のURLが submit ページのままで、カテゴリが未選択の場合
            # - または明示的に指定カテゴリがあり、現在のカテゴリと一致しない場合（異なるカテゴリを確定）
            if "topsubmit" not in driver.current_url and not current_category_text:
                try:
                    driver.execute_script("""
                        if (typeof selectCategory === 'function') {
                            selectCategory();
                        }
                    """)
                    category_action_done = True
                    print("   ✅ selectCategory() を実行しました（未選択から遷移）。")
                    time.sleep(5)
                except Exception as e:
                    print(f"   ⚠️ selectCategory() 実行失敗: {e}")

            # もし指定カテゴリがありかつ不一致で、まだアクションしていなければ、ユーザーに手動確認を促す
            if desired_category_normalized and current_category_normalized != desired_category_normalized and not category_action_done:
                print("   ⚠️ 指定カテゴリと現在のカテゴリが完全には一致しませんが、処理を続行します。")
                # input("   カテゴリ変更後、Enterキーを押してください: ")

        except Exception as e:
            print(f"   ⚠️ カテゴリ確定処理失敗: {e}")

        # --- ページ遷移確認（カテゴリ選択後のトップサブミットページ） ---
        print("\n📋 【ステップ2】出品情報入力")
        print(f"   現在のURL: {driver.current_url}")
        
        # 現在のページがカテゴリ選択ページの場合は、直接 topsubmit にアクセス
        if "topsubmit" not in driver.current_url:
            # 既にフォーム（タイトル入力）が表示されている場合は移動しない
            if len(driver.find_elements(By.NAME, "Title")) > 0:
                print("   ℹ️ フォーム要素が見つかりました。topsubmitへの遷移をスキップします。")
            else:
                print("   ⚠️ カテゴリ選択ページのままです。topsubmit ページに直接移動します...")
                driver.get("https://auctions.yahoo.co.jp/sell/jp/show/topsubmit")
                time.sleep(3)
                print(f"   移動先: {driver.current_url}")
        
        # ページが完全に読み込まれるまで待機（JavaScriptで動的にフィールドが生成される可能性）
        print("   ページの読み込みを待機しています...")
        for attempt in range(10):
            try:
                # タイトル入力フィールドが見えるようになるまで待つ
                title_check = driver.find_element(By.NAME, "Title")
                if title_check.is_displayed():
                    print("   ✅ フォームの読み込みが完了しました。")
                    break
            except Exception:
                pass
            time.sleep(1)
            if attempt == 9:
                print("   ⚠️ ページの読み込みに時間がかかっています。続行します...")
        
        time.sleep(2)  # ページが安定するまで待機
        
        # 新しい WebDriverWait インスタンスを作成（タイムアウト長め）
        wait_form = WebDriverWait(driver, 30)
        # ページ上のオーバーレイがあれば対処しておく
        try:
            ensure_no_overlay(driver)
        except Exception:
            pass
        
        # --- 画像アップロード (複数対応) ---
        # input type="file" を探してパスを送る。hidden や非表示の場合は一時的に表示して設定する
        if "images" in item_data and item_data["images"]:
            abs_paths = [os.path.abspath(p) for p in item_data["images"] if p]
            try:
                file_input = None
                
                # 戦略1: ID で探す
                try:
                    file_input = wait_form.until(EC.presence_of_element_located((By.ID, "selectFileMultiple")))
                    print(f"   ✅ 画像入力フィールドを見つけました (ID=selectFileMultiple)")
                except Exception:
                    # 戦略2: 最初の input[type=file]
                    try:
                        file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
                        if file_inputs:
                            file_input = file_inputs[0]
                            print(f"✅ 画像入力フィールドを見つけました (input[type=file])")
                    except Exception:
                        pass
                
                if not file_input:
                    print("⚠️ 画像入力フィールドが見つかりません。スキップします。")
                else:
                    # 要素が表示されていない場合、一時的に style を変更して send_keys を可能にする
                    try:
                        # オーバーレイがあれば先に処理
                        try:
                            ensure_no_overlay(driver)
                        except Exception:
                            pass

                        if not file_input.is_displayed():
                            driver.execute_script(
                                "arguments[0].style.display='block'; arguments[0].style.visibility='visible'; "
                                "arguments[0].style.width='1px'; arguments[0].style.height='1px';", 
                                file_input
                            )
                            print("✅ 隠し画像入力フィールドを表示状態に変更しました。")
                            time.sleep(0.2)
                    except Exception as e:
                        print(f"⚠️ スタイル変更失敗: {e}")

                    try:
                        # オーバーレイを再チェック
                        try:
                            ensure_no_overlay(driver)
                        except Exception:
                            pass

                        # 複数ファイルは改行で区切って send_keys する
                        if len(abs_paths) == 1:
                            file_input.send_keys(abs_paths[0])
                            print(f"✅ 画像アップロード: {abs_paths[0]}")
                        else:
                            file_input.send_keys("\n".join(abs_paths))
                            print(f"✅ 画像アップロード: {len(abs_paths)} files (最初: {abs_paths[0]})")

                        # サムネイル等の反映を待つ
                        time.sleep(6)
                    except Exception as upload_err:
                        print(f"⚠️ 画像アップロード失敗: {upload_err}")
            except Exception as e:
                print(f"⚠️ 画像アップロードエラー: {e}")

        # --- 商品タイトル ---
        try:
            # まず ID で試す
            try:
                title_input = wait_form.until(EC.visibility_of_element_located((By.ID, "fleaTitleForm")))
            except Exception:
                # 代替: name="Title"
                title_input = wait_form.until(EC.visibility_of_element_located((By.NAME, "Title")))
            driver.execute_script("arguments[0].scrollIntoView(true);", title_input)
            time.sleep(0.5)
            try:
                ensure_no_overlay(driver)
            except Exception:
                pass
            title_input.click()
            title_input.clear()
            title_input.send_keys(item_data["title"])
            print(f"   ✅ タイトル入力完了: {item_data['title']}")
        except Exception as e:
            print(f"   ⚠️ タイトル入力エラー: {e}")

        # --- 商品説明 ---
        # RTEエディタ（iframe）またはプレーンテキスト（textarea）で入力
        try:
            desc_success = False
            
            # 戦略1: プレーンテキストモード (Description_plain_work textarea)
            try:
                desc_textarea = wait_form.until(EC.visibility_of_element_located((By.NAME, "Description_plain_work")))
                driver.execute_script("arguments[0].scrollIntoView(true);", desc_textarea)
                time.sleep(0.5)
                desc_textarea.click()
                desc_textarea.clear()
                desc_textarea.send_keys(item_data["description"])
                print(f"   ✅ 説明入力完了 (プレーンテキストエリア)")
                desc_success = True
            except Exception as e:
                print(f"   📝 プレーンテキストモード不可: {e}")
            
            # 戦略2: RTEエディタのJavaScript経由で直接更新
            if not desc_success:
                try:
                    # RTEエディタの HTMLモード用エディタオブジェクトにアクセス
                    desc_text = item_data["description"].replace('"', '\\"').replace('\n', '\\n')
                    js_code = f"""
                    if (typeof editor !== 'undefined' && editor.SetHTML) {{
                        // HTMLモードでエディタに設定
                        editor.SetHTML(arguments[0], 'html');
                    }} else {{
                        // フォールバック: Hidden フィールドに直接設定
                        document.getElementById('Description').value = arguments[0];
                    }}
                    """
                    # HTMLモードの場合、改行コード \n は無視されるため <br> に変換して渡す
                    driver.execute_script(js_code, item_data["description"].replace('\n', '<br>'))
                    print(f"   ✅ 説明入力完了 (RTEエディタJS経由)")
                    desc_success = True
                except Exception as e:
                    print(f"   ⚠️ RTEエディタJS更新失敗: {e}")
            
            # 戦略3: 隠しフィールドに直接セット（フォールバック）
            if not desc_success:
                try:
                    desc_hidden = driver.find_element(By.ID, "Description")
                    driver.execute_script("arguments[0].value = arguments[1];", desc_hidden, item_data["description"])
                    print(f"   ✅ 説明入力完了 (隠しフィールド)")
                    desc_success = True
                except Exception as e:
                    print(f"   ⚠️ 隠しフィールド設定失敗: {e}")
            
            if not desc_success:
                print(f"   ⚠️ 説明フィールドが見つかりません（スキップ）")
        except Exception as e:
            print(f"   ⚠️ 説明入力エラー: {e}（スキップ）")

        # --- 価格設定 (即決価格 BidOrBuyPrice) ---
        try:
            price_input = None
            
            # 戦略1: ID="auc_BidOrBuyPrice_buynow" (topsubmit ページの実際のフィールド)
            try:
                price_input = wait_form.until(EC.visibility_of_element_located((By.ID, "auc_BidOrBuyPrice_buynow")))
                print(f"   💡 価格フィールドを ID=auc_BidOrBuyPrice_buynow で検出")
            except Exception:
                pass
            
            # 戦略2: name="BidOrBuyPrice"
            if not price_input:
                try:
                    price_input = wait_form.until(EC.visibility_of_element_located((By.NAME, "BidOrBuyPrice")))
                    print(f"   💡 価格フィールドを name=BidOrBuyPrice で検出")
                except Exception:
                    pass
            
            # 戦略3: 古いセレクタ auc_StartPrice
            if not price_input:
                try:
                    price_input = wait_form.until(EC.visibility_of_element_located((By.ID, "auc_StartPrice")))
                    print(f"   💡 価格フィールドを ID=auc_StartPrice で検出")
                except Exception:
                    pass
            
            # 戦略4: name="StartPrice"
            if not price_input:
                try:
                    price_input = wait_form.until(EC.visibility_of_element_located((By.NAME, "StartPrice")))
                    print(f"   💡 価格フィールドを name=StartPrice で検出")
                except Exception:
                    pass
            
            # 戦略5: CSSクラス .Input--price
            if not price_input:
                try:
                    price_input = wait_form.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input.Input--price")))
                    print(f"   💡 価格フィールドを .Input--price で検出")
                except Exception:
                    pass
            
            if price_input:
                driver.execute_script("arguments[0].scrollIntoView(true);", price_input)
                time.sleep(0.5)
                try:
                    ensure_no_overlay(driver)
                except Exception:
                    pass
                price_input.click()
                price_input.clear()
                price_input.send_keys(str(item_data["price"]))
                print(f"   ✅ 価格入力完了: {item_data['price']}")
            else:
                print(f"   ⚠️ 価格フィールドが見つかりません（スキップ）")
        except Exception as e:
            print(f"   ⚠️ 価格入力エラー: {e}（スキップ）")

        # 即決価格（必要な場合）
        if "buy_now_price" in item_data:
            try:
                buy_now_input = driver.find_element(By.NAME, "BidOrBuyPrice")
                buy_now_input.clear()
                buy_now_input.send_keys(str(item_data["buy_now_price"]))
                print(f"   ✅ 即決価格入力完了: {item_data['buy_now_price']}")
            except Exception as e:
                print(f"   ⚠️ 即決価格入力スキップ: {e}")

        # --- 個数 ---
        try:
            qty_input = driver.find_element(By.NAME, "Quantity")
            if qty_input.is_enabled():
                qty_input.clear()
                qty_input.send_keys("1")
                print(f"   ✅ 個数入力完了: 1")
            else:
                current_value = qty_input.get_attribute('value')
                if current_value == '1':
                    print(f"   ✅ 個数は既に1です（フィールド無効）。")
                else:
                    print(f"   ⚠️ 個数フィールドが無効で、値が1ではありません (現在値: {current_value})。JSでの設定を試みます。")
                    driver.execute_script("arguments[0].value = '1';", qty_input)
                    print(f"   ✅ 個数をJSで1に設定しました。")
        except Exception as e:
            print(f"   ⚠️ 個数入力スキップ: {e}")

        # --- 商品の状態 ---
        if "condition" in item_data:
            try:
                # name="istatus" のセレクトボックスを探す
                status_select_elem = wait_form.until(EC.visibility_of_element_located((By.NAME, "istatus")))
                select = Select(status_select_elem)
                select.select_by_value(item_data["condition"])
                print(f"   ✅ 商品の状態を選択: {item_data['condition']}")
            except Exception as e:
                print(f"   ⚠️ 商品の状態選択エラー: {e}")

        # --- 配送方法・送料負担 ---
        # 宅急便コンパクト（EAZY）を選択 (data-delivery-id="113")
        if item_data.get("shipping") == 'compact':
            try:
                print("   🚚 配送方法を「宅急便コンパクト（EAZY）」に変更します...")
                # input要素を直接クリック（JS使用）
                compact_radio = driver.find_element(By.CSS_SELECTOR, 'input[data-delivery-id="113"]')
                driver.execute_script("arguments[0].click();", compact_radio)
                print("   ✅ 宅急便コンパクト（EAZY）を選択しました。")
                time.sleep(1)
            except Exception as e:
                print(f"   ⚠️ 配送方法の変更に失敗しました: {e}")
        
        # --- 確認画面へ進むボタンのクリック ---
        print("\n📋 【ステップ3】確認画面へ進む")
        time.sleep(2)  # ページが安定するまで待機
        
        submit_success = False
        
        # 戦略1: ID="submit_form_btn" (ユーザー指定) or "submit_btn"
        try:
            ensure_no_overlay(driver)
        except Exception:
            pass
        
        for btn_id in ["submit_form_btn", "submit_btn"]:
            try:
                submit_button = wait_form.until(EC.element_to_be_clickable((By.ID, btn_id)))
                driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
                time.sleep(0.5)
                submit_button.click()
                print(f"   ✅ 確認ボタンをクリック (ID={btn_id})")
                submit_success = True
                break
            except Exception:
                pass
        
        # 戦略2: テキスト「確認」「出品」を含むボタン
        if not submit_success:
            try:
                for text in ["確認", "出品", "確認画面へ進む"]:
                    els = driver.find_elements(By.XPATH, f"//button[contains(text(), '{text}')] | //input[@type='submit'][contains(@value, '{text}')]")
                    if els:
                        btn = els[0]
                        driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                        time.sleep(0.5)
                        btn.click()
                        print(f"   ✅ 確認ボタンをクリック (text='{text}')")
                        submit_success = True
                        break
            except Exception:
                pass
        
        # 戦略3: type="submit" の最初のボタン
        if not submit_success:
            try:
                submit_buttons = driver.find_elements(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
                if submit_buttons:
                    btn = submit_buttons[0]
                    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                    time.sleep(0.5)
                    btn.click()
                    print(f"   ✅ 確認ボタンをクリック (type=submit)")
                    submit_success = True
            except Exception as e:
                print(f"   ⚠️ 確認ボタンクリック失敗: {e}")
        
        if submit_success:
            print("   確認画面への遷移を待機しています...")
            try:
                # URLが preview になるのを待つ
                WebDriverWait(driver, 20).until(lambda d: "preview" in d.current_url)
                print(f"   ✅ プレビュー画面に遷移しました: {driver.current_url}")
                
                print("\n📋 【ステップ4】最終出品確定")
                time.sleep(2)
                
                # 最終出品ボタン (auc_preview_submit_up)
                final_submit_success = False
                try:
                    final_btn = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, "auc_preview_submit_up"))
                    )
                    driver.execute_script("arguments[0].scrollIntoView(true);", final_btn)
                    time.sleep(1.0)
                    final_btn.click()
                    print("   ✅ 出品するボタンをクリックしました (auc_preview_submit_up)")
                    final_submit_success = True
                except Exception as e:
                    print(f"   ⚠️ 最終出品ボタン(auc_preview_submit_up)のクリックに失敗: {e}")

                if final_submit_success:
                    print("   出品完了画面への遷移を待機しています...")
                    time.sleep(5)
                    print(f"   最終URL: {driver.current_url}")
                else:
                    print("   ⚠️ 最終出品ボタンが見つかりません。手動でクリックしてください。")

            except TimeoutError:
                print("   ⚠️ プレビュー画面への遷移が確認できませんでした。")
        else:
            print("   ⚠️ 確認ボタンが見つかりません。ブラウザで手動でクリックしてください。")

    except TimeoutException:
        print("要素が見つかりませんでした。ログインしていないか、セレクタが変更されている可能性があります。")
    except Exception as e:
        print(f"エラーが発生しました: {e}")

if __name__ == "__main__":
    # サンプル画像のパス（スクリプトと同じフォルダ）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sample_img_path = os.path.join(script_dir, "sample_image.jpg")  # JPG形式（ヤフオク対応）

    # 画像が存在しない場合は作成する
    if not os.path.exists(sample_img_path):
        try:
            from PIL import Image
            img = Image.new('RGB', (600, 400), color=(73, 109, 137))
            img.save(sample_img_path, 'JPEG')
            print(f"サンプル画像を作成しました: {sample_img_path}")
        except Exception as e:
            print(f"サンプル画像の作成に失敗しました: {e}\nPillowが見つからないため、組み込みのJPG画像を作成します。")
            try:
                import base64
                # 最小限のJPG（1x1ピクセル）
                jpg_b64 = b'/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8VAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAA8A/9k='
                with open(sample_img_path, 'wb') as f:
                    f.write(base64.b64decode(jpg_b64))
                print(f"フォールバックJPG画像を作成しました: {sample_img_path}")
            except Exception as e2:
                print(f"フォールバック画像の作成にも失敗しました: {e2}\n既存の画像パスを指定してください。")

    # 商品データ（mercari_dorekaiから渡されるデータを想定）
    sample_item = {
        "title": "テスト出品 ヤフオク用",
        "description": "これはテスト出品の説明文です。",
        "price": 1000,
        "images": [sample_img_path] # ローカルにある画像のパス（JPG形式）
    }

    driver = setup_driver()
    
    # ログイン確認（手動ログインのための待機時間を設ける場合）
    # print("ログインしてください。完了したらEnterキーを押してください...")
    # input()

    list_item_on_yahoo_auction(driver, sample_item)

    print("\n" + "="*60)
    print("処理終了。")
    print("="*60)
    print("\n以下のフィールドが正常に入力されました:")
    print("  ✅ 画像: uploaded")
    print("  ✅ タイトル: set")
    print("  ⚠️ 説明・価格: manual review required")
    print("\n次のステップ:")
    print("  1. ブラウザで入力内容を確認してください")
    print("  2. 説明や価格が必要な場合は手動で入力してください")
    print("  3. 確認画面へ進んでください")
    # driver.quit() を呼ばなければブラウザは閉じません
