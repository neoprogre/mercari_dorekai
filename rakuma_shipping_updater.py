import os
import csv
import time
import random
from playwright.sync_api import sync_playwright, TimeoutError

# --- 設定 ---
RAKUMA_LOGIN_URL = "https://fril.jp/login"
USER_DATA_DIR = "rakuma_user_data_firefox"
PRODUCTS_FILE = "products_rakuma.csv" # スクレイパーが生成したファイル
PROCESSED_LOG = "rakuma_shipping_processed_ids.txt" # このスクリプト専用の処理済みログ

# 実行オプション: 最初の商品からやり直す場合は True にする（処理済みログを削除）
RESTART_FROM_START = True

# --- ユーティリティ ---
def log(msg):
    """タイムスタンプ付きでログを出力する"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def load_processed_ids():
    """処理済みのIDをファイルから読み込む"""
    if not os.path.exists(PROCESSED_LOG):
        return set()
    with open(PROCESSED_LOG, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_processed_id(uid):
    """処理済みのIDをファイルに追記する"""
    with open(PROCESSED_LOG, "a", encoding="utf-8") as f:
        f.write(uid + "\n")

def get_product_id_from_url(url):
    """URLから商品IDを抽出する"""
    if not url:
        return None
    try:
        path = url.split('?')[0]
        product_id = path.split('/')[-1]
        return product_id if product_id else None
    except Exception:
        return None

# --- メイン処理 ---
def update_shipping_to_japan_post():
    # 1. 更新対象の商品URLをCSVから読み込む
    products_to_update = []
    try:
        with open(PRODUCTS_FILE, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('削除') != '削除' and row.get('URL'):
                    products_to_update.append(row['URL'])
        log(f"📚 {len(products_to_update)} 件の商品を更新対象として読み込みました。")
    except FileNotFoundError:
        log(f"❌ エラー: {PRODUCTS_FILE} が見つかりません。先に dorekai_scraper.py を実行してください。")
        return
    except Exception as e:
        log(f"❌ {PRODUCTS_FILE} の読み込み中にエラーが発生しました: {e}")
        return

    if not products_to_update:
        log("✅ 更新対象の商品はありませんでした。")
        return

    processed_ids = load_processed_ids()
    # 最初からやり直すオプション: 処理済みログを削除して空リストにする
    if RESTART_FROM_START:
        if os.path.exists(PROCESSED_LOG):
            try:
                os.remove(PROCESSED_LOG)
                log("🔁 RESTART_FROM_START=True のため、処理済みログを削除しました。最初からやり直します。")
            except Exception as e:
                log(f"⚠️ 処理済みログの削除に失敗しました: {e}")
        processed_ids = set()
    # 保存と in-memory 更新をまとめるヘルパー
    def mark_processed(uid):
        try:
            save_processed_id(uid)
        except Exception:
            pass
        processed_ids.add(uid)
    log(f"✅ これまでに {len(processed_ids)} 件を処理済みです。")

    with sync_playwright() as p:
        try:
            context = p.firefox.launch_persistent_context(
                USER_DATA_DIR,
                headless=False,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
            )
        except Exception as e:
            log(f"❌ ブラウザの起動に失敗しました。多重起動していないか確認してください。: {e}")
            return

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(30000)

        # ヘルパー: 安全な goto（リトライ、429 検知、指数バックオフ）
        def safe_goto(url, retries=4, timeout=30000):
            backoff = 1
            for attempt in range(1, retries+1):
                try:
                    resp = page.goto(url, wait_until='domcontentloaded', timeout=timeout)
                    # Playwright returns a Response or None
                    status = resp.status if resp is not None else None
                    if status == 429:
                        # サーバがレート制限中
                        sleep_sec = random.randint(60, 120) * attempt
                        log(f"⚠️ 429 Too Many Requests を検出（attempt {attempt}）。{sleep_sec}s 待機します。")
                        time.sleep(sleep_sec)
                        continue
                    return True
                except Exception as e:
                    # NS_ERROR_NET_EMPTY_RESPONSE などの一時エラーは再試行
                    log(f"⚠️ goto失敗 ({attempt}/{retries}): {e}")
                    try:
                        page.reload(timeout=timeout)
                    except Exception:
                        pass
                    sleep_sec = backoff + random.random() * 2
                    time.sleep(sleep_sec)
                    backoff *= 2
            return False

        # 簡易レート制限管理（頻度を上げて長めに休止）
        requests_since_pause = 0
        def maybe_pause_for_rate_limit():
            nonlocal requests_since_pause
            requests_since_pause += 1
            # 10件ごとに長めの休止（より保守的）
            if requests_since_pause % 10 == 0:
                t = random.randint(60, 180)
                log(f"⏸️ 連続処理が {requests_since_pause} 件に到達しました。{t}s 休止します。")
                time.sleep(t)
            else:
                # 各処理間に小さなジッターを入れる
                time.sleep(random.uniform(1.0, 2.5))

        # ヘルパー: 安全なクリック（標準 -> scroll -> evaluate フォールバック）
        def safe_click(locator, timeout=10000):
            try:
                locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            try:
                locator.click(timeout=timeout)
                return True
            except Exception as e:
                log(f"⚠️ direct click failed, trying evaluate: {e}")
                try:
                    # locator.evaluate は element を引数に取れる
                    locator.evaluate("el => el.click()")
                    return True
                except Exception as e2:
                    log(f"⚠️ evaluate click も失敗: {e2}")
                    return False

        # --- ログイン処理 ---
        log("ログイン状態を確認します...")
        if not safe_goto("https://fril.jp/mypage", retries=5):
            log("❌ マイページへの移動に失敗しました。終了します。")
            context.close()
            return
        if "login" in page.url:
            log("🔒 ログインが必要です。ブラウザでログインを完了してください。")
            try:
                page.wait_for_url("https://fril.jp/mypage", timeout=300000)
                log("🔓 ログインを検知しました。処理を再開します。")
            except TimeoutError:
                log("⚠️ ログインが時間内に完了しませんでした。終了します。")
                context.close()
                return
        else:
            log("✅ ログイン済みです。")

        # --- 商品ループ ---
        try:
            for i, product_url in enumerate(products_to_update):
                product_id = get_product_id_from_url(product_url)
                if not product_id:
                    log(f"⚠️ 無効なURLです、スキップします: {product_url}")
                    continue

                if product_id in processed_ids:
                    log(f"⏩ スキップ: {product_id} (処理済み)")
                    continue

                log(f"🚀 {i+1}/{len(products_to_update)} 件目: {product_id} の処理を開始します。")
                edit_url = f"https://fril.jp/item/{product_id}/edit"

                try:
                    # --- 必須: 編集ページへ遷移 ---
                    if not safe_goto(edit_url, retries=3):
                        log(f"❌ 編集ページに到達できませんでした: {edit_url}。スキップします。")
                        mark_processed(product_id)
                        continue
                    time.sleep(1)
                    time.sleep(0.5)

                    content = page.content()
                    if "このページは存在しません" in content or "リクエストされたページは存在しません" in content:
                        log(f"❌ 編集ページが存在しません、スキップします: {edit_url}")
                        mark_processed(product_id)
                        continue

                    # --- 現在の配送方法を確認 ---
                    log("🚚 現在の配送方法を確認します...")
                    shipping_button = None
                    try:
                        shipping_button = page.locator('text="配送方法"').first
                        if shipping_button.count() == 0:
                            shipping_button = page.locator('button:has-text("配送方法")').first
                        if shipping_button.count() == 0:
                            shipping_button = page.locator('button:has-text("かんたんラクマパック")').first

                        if shipping_button.count() == 0:
                            raise Exception("配送方法ボタンが見つかりません")

                        try:
                            current_shipping_method = shipping_button.inner_text().strip()
                            log(f"    現在の設定（ボタン表示）: {current_shipping_method}")
                            if "日本郵便" in current_shipping_method or "かんたんラクマパック" in current_shipping_method:
                                log("✅ 既に日本郵便に設定済みの可能性があります。スキップします。")
                                mark_processed(product_id)
                                continue
                        except Exception:
                            pass
                    except Exception as e:
                        log(f"⚠️ 配送方法ボタンの取得に失敗: {e}")

                    # --- 配送方法選択処理（既存ロジック） ---
                    log("🔧 配送方法を「かんたんラクマパック(日本郵便)」に変更します...")
                    try:
                        if shipping_button and shipping_button.count() > 0:
                            if not safe_click(shipping_button):
                                btn = page.locator('button:has-text("配送方法")').first
                                if not safe_click(btn):
                                    raise Exception("配送方法ボタンクリックに失敗（再試行も含む）")
                        else:
                            btn = page.locator('button:has-text("配送方法")').first
                            if not safe_click(btn):
                                raise Exception("配送方法ボタンクリックに失敗")
                    except Exception as e:
                        log(f"❌ 配送方法ボタンクリックに失敗しました: {e}")
                        mark_processed(product_id)
                        continue

                    modal_selector = 'section[role="dialog"]'
                    try:
                        page.wait_for_selector(modal_selector, timeout=7000)
                        log("    モーダルを開きました。")
                    except TimeoutError:
                        log("⚠️ モーダルが開かれませんでした。スキップします。")
                        mark_processed(product_id)
                        continue

                    try:
                        # robust option search (regex, various element types, longer timeout + debug artifacts)
                        option = page.locator(f'{modal_selector} >> text=/日本郵便|かんたんラクマパック/').first
                        if option.count() == 0:
                            option = page.locator(f'{modal_selector} >> xpath=//*[contains(text(),"郵便") or contains(text(),"ラクマパック")]').first
                        if option.count() == 0:
                            option = page.locator(f'{modal_selector} >> role=option >> text=/郵便|ラクマ/').first
                        if option.count() == 0:
                            option = page.locator(f'{modal_selector} img[alt*="かんたんラクマパック"]').first

                        if option.count() == 0:
                            # デバッグ出力: モーダルのHTML/スクリーンショットを保存して原因追跡
                            try:
                                modal = page.locator(modal_selector).first
                                html = modal.inner_html() if modal.count() else page.content()
                                dbg_dir = "debug_modal"
                                os.makedirs(dbg_dir, exist_ok=True)
                                html_path = os.path.join(dbg_dir, f"modal_{product_id}.html")
                                with open(html_path, "w", encoding="utf-8") as fh:
                                    fh.write(html)
                                try:
                                    ss_path = os.path.join(dbg_dir, f"modal_{product_id}.png")
                                    modal.screenshot(path=ss_path)
                                    log(f"    モーダルのスクリーンショットを保存: {ss_path}")
                                except Exception:
                                    pass
                                log(f"    モーダルHTMLを保存: {html_path}")
                            except Exception:
                                pass
                            raise Exception("モーダル内の「日本郵便」オプションが見つかりません (debug info saved)")
 
                        try:
                            option.scroll_into_view_if_needed()
                        except Exception:
                            pass

                        if not safe_click(option):
                            time.sleep(0.5)
                            if not safe_click(option):
                                log("⚠️ モーダル内のオプション選択に失敗しました（再試行も含む）。")
                                try:
                                    os.makedirs("debug_modal", exist_ok=True)
                                    page.locator(modal_selector).first.screenshot(path=os.path.join("debug_modal", f"fail_click_{product_id}.png"))
                                except Exception:
                                    pass
                                mark_processed(product_id)
                                continue

                        log("    「かんたんラクマパック(日本郵便)」のオプションを選択しました。")
                        # モーダル内の確定ボタン（あれば）を押す
                        try:
                            for t in ("決定", "選択", "OK", "保存"):
                                btn2 = page.locator(f'{modal_selector} >> button:has-text("{t}")').first
                                if btn2.count() > 0 and safe_click(btn2):
                                    log(f"    モーダル内の「{t}」ボタンをクリックしました。")
                                    break
                        except Exception:
                            pass
                    except Exception as e:
                        log(f"⚠️ モーダル内のオプション選択に失敗しました: {e}")
                        mark_processed(product_id)
                        continue

                    # wait until modal hidden (or timeout), then verify change by polling page content for up to 10s
                    try:
                        page.wait_for_selector(modal_selector, state='hidden', timeout=8000)
                        log("    モーダルが閉じられました。")
                    except Exception:
                        log("    モーダルの自動閉鎖を検出できませんでした。続行します。")
                        try:
                            time.sleep(0.5)
                            page.reload()
                            log("    ページを再読み込みしました。")
                        except Exception:
                            pass

                    # verify change by polling page content for up to 10s
                    found = False
                    for _ in range(20):
                        content_after = page.content()
                        if "かんたんラクマパック" in content_after or "日本郵便" in content_after:
                            found = True
                            break
                        time.sleep(0.5)
                    if found:
                        log("✅ 配送方法が「かんたんラクマパック(日本郵便)」に設定されました。")
                    else:
                        log("⚠️ 配送方法表示の更新が確認できませんでした。デバッグを残して次へ進みます。")
                        try:
                            os.makedirs("debug_modal", exist_ok=True)
                            page.screenshot(path=os.path.join("debug_modal", f"after_{product_id}.png"))
                        except Exception:
                            pass

                    # --- 発送日の目安 を "支払い後、4～7日で発送" に設定 ---
                    try:
                        sel = page.locator('select[name="deliveryDate"]').first
                        if sel.count() > 0:
                            try:
                                sel.select_option("3")
                                log("    発送日の目安を「支払い後、4～7日で発送」に設定しました。")
                            except Exception:
                                page.evaluate('''() => {
                                    const el = document.querySelector('select[name="deliveryDate"]');
                                    if (el) { el.value = "3"; el.dispatchEvent(new Event('change', {bubbles:true})); }
                                }''')
                                log("    発送日の目安を JS フォールバックで設定しました。")
                        else:
                            log("    発送日の目安セレクトが見つかりませんでした。")
                    except Exception as e:
                        log(f"⚠️ 発送日の目安設定でエラー: {e}")

                    # --- 変更を保存 ---
                    log("💾 変更を保存します...")
                    try:
                        # 1. 「確認する」ボタンをクリック
                        log("    「確認する」をクリックします。")
                        confirm_button = page.locator('button:has-text("確認する")').first
                        if not safe_click(confirm_button):
                            raise Exception("「確認する」ボタンのクリックに失敗しました。")

                        # ページ遷移を待つ
                        page.wait_for_load_state('domcontentloaded', timeout=15000)
                        time.sleep(random.uniform(0.5, 1.5)) # 念のため待機
                        log("    確認ページに遷移しました。")

                        # 2. 「更新する」ボタンをクリック
                        log("    「更新する」をクリックします。")
                        update_button = page.locator('button:has-text("更新する")').first
                        if not safe_click(update_button):
                            raise Exception("「更新する」ボタンのクリックに失敗しました。")

                        # 3. 更新完了を待機 (URLが編集ページでなくなるまで)
                        log("    更新処理の完了を待っています...")
                        page.wait_for_url(lambda url: "/edit" not in url, timeout=20000)
                        log("✅ 商品が正常に更新されました。")

                    except TimeoutError:
                        log("⚠️ 更新処理がタイムアウトしました。ページの状態を確認してください。")
                        # 失敗してもログには残す
                        mark_processed(product_id)
                        continue
                    except Exception as e:
                        log(f"❌ 更新処理中にエラーが発生しました: {e}")
                        # 失敗しても次の商品のためにログに記録
                        mark_processed(product_id)
                        continue

                    # 処理成功として保存（メモリも更新）
                    mark_processed(product_id)
                    maybe_pause_for_rate_limit()
                    time.sleep(0.6)
                except Exception as e:
                    log(f"❌ 商品処理中に例外が発生しました: {e}")
                    mark_processed(product_id)
                    continue
        except KeyboardInterrupt:
            log("⏹️ ユーザーによって処理が中断されました。状態を保存して終了します。")
        finally:
            try:
                context.close()
            except Exception:
                pass

    log("✅ 全ての処理が完了しました。")

if __name__ == "__main__":
    update_shipping_to_japan_post()
