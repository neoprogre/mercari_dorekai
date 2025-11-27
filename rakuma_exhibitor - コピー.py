import os
import glob
import csv
import time
from playwright.sync_api import sync_playwright, TimeoutError

# --- 設定 ---
IMAGE_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images"
RAKUMA_LOGIN_URL = "https://fril.jp/login"
RAKUMA_NEW_ITEM_URL = "https://fril.jp/item/new"
USER_DATA_DIR = "rakuma_user_data_firefox"
PROCESSED_LOG = "processed_ids.txt"

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

# --- ユーティリティ ---
def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

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

def get_column_indices(header):
    indices = {}
    columns = [
        ('商品ID', 0),
        ('商品名', 62),
        ('商品説明', 63),
        ('販売価格', 151),
        ('商品の状態', 153),
        ('配送料の負担', 157),
        ('発送元の地域', 155),
        ('発送までの日数', 156),
    ]
    for name, fallback in columns:
        indices[name] = header.index(name) if name in header else fallback
    return indices

# --- メイン処理 ---
def process_products():
    csv_pattern = "product_data_*.csv"
    latest_csv = find_latest_csv(csv_pattern)
    if not latest_csv:
        log(f"❌ CSVファイルが見つかりません: {csv_pattern}")
        return
    log(f"📂 最新CSVを読み込み: {latest_csv}")

    try:
        with open(latest_csv, "r", encoding="cp932", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader)
            indices = get_column_indices(header)
            products = list(reader)
    except Exception as e:
        log(f"CSV読み込み中にエラー: {e}")
        return

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
        page.goto(RAKUMA_NEW_ITEM_URL)
        if "login" in page.url:
            log("🔒 ログインが必要です。ブラウザでログインを完了してください。")
            try:
                page.wait_for_selector('h2:has-text("商品の情報を入力")', timeout=300000)
                log("🔓 ログインを検知しました。処理を再開します。")
            except TimeoutError:
                log("⚠️ ログインが完了しませんでした。終了します。")
                return
        else:
            log("✅ すでにログイン済みです。")

        # --- 商品ループ ---
        for i, row in enumerate(products):
            product_id = row[indices['商品ID']]
            if product_id in processed:
                log(f"⏩ スキップ: {product_id} (既に処理済み)")
                continue

            product_name = row[indices['商品名']] or ""
            # 全角スペースを半角スペースに統一し、連続する空白は単一の半角スペースに
            product_name = product_name.replace('\u3000', ' ')
            product_name = ' '.join(product_name.split())
            # 商品名は40文字以内。40文字を超える場合は40文字目までを取得し、
            # 可能なら直前のスペース（半角）で切る
            if product_name and len(product_name) > 40:
                cut = product_name[:40]
                # 半角スペースを優先して最後の位置を探す
                idx = cut.rfind(' ')
                if idx > 0:
                    cut = cut[:idx]
                product_name = cut.rstrip()
            description = row[indices['商品説明']]
            price = row[indices['販売価格']]
            condition = row[indices['商品の状態']]
            shipping_payer = row[indices['配送料の負担']]
            prefecture = row[indices['発送元の地域']]
            days_to_ship = row[indices['発送までの日数']]

            log(f"\n🚀 {i+1}件目: {product_name} を出品処理中...")

            try:
                # ページ移動
                page.goto(RAKUMA_NEW_ITEM_URL, wait_until='domcontentloaded')
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
                image_pattern = os.path.join(IMAGE_DIR, f"{product_id}-*.jpg")
                image_paths = sorted(glob.glob(image_pattern))
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
                            preview_locator = page.locator('div.css-1021eg4 img, div.css-1021eg4 picture img, div._uploaded img, div.uploaded-images img')
                            ok = False
                            start = time.time()
                            timeout = 120  # 秒
                            while time.time() - start < timeout:
                                try:
                                    count = preview_locator.count()
                                    if count >= expected and count > 0:
                                        ok = True
                                        break
                                except Exception:
                                    pass
                                time.sleep(0.5)
                            if ok:
                                log(f"✅ 画像アップロード完了を検知 (selector={used_selector}, preview_count={preview_locator.count()})")
                            else:
                                log("⚠️ 画像プレビューの検知に失敗しました（タイムアウト）。スクリーンショットを保存します。")
                                os.makedirs("error_artifacts", exist_ok=True)
                                ts = int(time.time())
                                ss = os.path.join("error_artifacts", f"{product_id}_{ts}.png")
                                htmlf = os.path.join("error_artifacts", f"{product_id}_{ts}.html")
                                page.screenshot(path=ss, full_page=True)
                                with open(htmlf, "w", encoding="utf-8") as hf:
                                    hf.write(page.content())
                                log(f"🖼️ スクリーンショットとHTMLを保存しました: {ss}, {htmlf}")
                        else:
                            log("⚠️ アップロードに失敗しました（input/button が操作できませんでした）。")
                    except Exception as e:
                        log(f"⚠️ 画像アップロード中に例外が発生しました: {e}")
                        try:
                            os.makedirs("error_artifacts", exist_ok=True)
                            ts = int(time.time())
                            ss = os.path.join("error_artifacts", f"{product_id}_{ts}.png")
                            htmlf = os.path.join("error_artifacts", f"{product_id}_{ts}.html")
                            page.screenshot(path=ss, full_page=True)
                            with open(htmlf, "w", encoding="utf-8") as hf:
                                hf.write(page.content())
                            log(f"🖼️ スクリーンショットとHTMLを保存しました: {ss}, {htmlf}")
                        except Exception:
                            log("⚠️ エラー情報の保存に失敗しました")
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

                # --- カテゴリ選択（アコーディオン→子項目を直接クリックして高速化） ---
                try:
                    # 固定で選びたいパス（必要に応じて CSV 等から取得するよう変更）
                    parent_text = "フォーマル/ドレス"
                    child_text = "ロングドレス"

                    # アコーディオン内の子要素を直接クリックする高速版
                    parent_btn = page.locator(f'button:has-text("{parent_text}")')
                    if parent_btn.count() > 0:
                        parent_btn.first.scroll_into_view_if_needed()
                        parent_btn.first.click()
                    else:
                        hdr = page.locator(f'div.css-1eziwv:has-text("{parent_text}")')
                        if hdr.count() > 0:
                            hdr.first.scroll_into_view_if_needed()
                            hdr.first.click(force=True)

                    # 速攻で子要素を探してクリック（最初に見つかった要素を使う）
                    child_loc = page.locator(f'div.chakra-accordion__panel div.css-1eziwv:has-text("{child_text}")')
                    if child_loc.count() == 0:
                        # 別候補
                        child_loc = page.locator(f'div.css-1161qt5 div.css-1eziwv:has-text("{child_text}")')
                    if child_loc.count() > 0:
                        child_loc.first.scroll_into_view_if_needed()
                        child_loc.first.click()
                        log(f"✅ カテゴリを選択しました: {parent_text} -> {child_text}")
                    else:
                        # フォールバック: button[name='category'] に値を直接セットして表示だけ更新
                        try:
                            page.evaluate("""(v,t) => {
                                const btn = document.querySelector('button[name=\"category\"]');
                                if(btn){ btn.value = v; btn.textContent = t; btn.dispatchEvent(new Event('change',{bubbles:true})); }
                            }""", "200", f"{parent_text} > {child_text}")
                            log(f"⚠️ カテゴリはフォールバックで設定しました（要確認）: {parent_text} -> {child_text}")
                        except Exception as e:
                            log(f"⚠️ カテゴリ選択に失敗しました（フォールバックも不可）: {e}")
                except Exception as e:
                    log(f"⚠️ カテゴリ処理で例外が発生しました: {e}")

                # --- サイズ ---（要実装：CSVにサイズ情報があれば indices へ追加してここで設定してください）
                try:
                    # 代表的なセレクタを試す。CSVでサイズ情報がある場合は 'size_value' 変数を使って select_option してください。
                    size_selectors = [
                        'select[name="size"]',
                        'select[name^="size"]',
                        'button[name="size"]',
                        'input[name="size"]',
                    ]
                    found_size = False
                    for ssel in size_selectors:
                        if page.locator(ssel).count() > 0:
                            # デフォルトは「指定なし」にしておく
                            if ssel.startswith('select'):
                                # try set to first option other than empty
                                opts = page.locator(f"{ssel} option")
                                for i in range(opts.count()):
                                    v = opts.nth(i).get_attribute("value")
                                    if v and v.strip():
                                        page.locator(ssel).select_option(value=v)
                                        found_size = True
                                        break
                            else:
                                # button/input 型はスキップしてログだけ
                                page.locator(ssel).first.scroll_into_view_if_needed()
                                found_size = True
                            break
                    if not found_size:
                        log("⚠️ サイズ項目が見つかりませんでした（ページ構造を確認してください）")
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
                                loc = page.locator(f"label:has-text(\"{cond}\")")
                                if loc.count() > 0:
                                    loc.first.click(force=True)
                                else:
                                    log(f"⚠️ 商品状態用要素が見つかりません: {cond}")
                    except Exception as e:
                        log(f"⚠️ 商品状態選択に失敗しました: {e}")

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

                log("✅ 入力完了。ブラウザで内容を確認してください。")
                input("手動で出品ボタンを押したら Enter で次へ進みます...")

                save_processed_id(product_id)
                log(f"✅ {product_name} の処理完了。")

            except Exception as e:
                log(f"❌ エラー発生 ({product_name}): {e}")
                if input("続行しますか？(y/n): ").lower() != 'y':
                    break

        log("🎉 全商品処理完了！")
        input("Enterでブラウザを閉じます...")
        context.close()

# --- 実行 ---
if __name__ == "__main__":
    process_products()
