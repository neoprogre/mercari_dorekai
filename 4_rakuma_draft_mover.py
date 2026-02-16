"""
ラクマの商品を削除するスクリプト
products_rakuma.csv から削除対象・重複対象の商品を読み込み、削除する
"""

import os
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time

# --- 設定 ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAKUMA_CSV = os.path.join(SCRIPT_DIR, 'products_rakuma.csv')
USER_DATA_DIR = os.path.join(SCRIPT_DIR, 'rakuma_user_data_firefox')
PROCESSED_URLS_FILE = os.path.join(SCRIPT_DIR, 'processed_rakuma_urls.txt')

def load_processed_rakuma_urls():
    """処理済みラクマURLのリストを読み込む"""
    if os.path.exists(PROCESSED_URLS_FILE):
        try:
            with open(PROCESSED_URLS_FILE, 'r', encoding='utf-8') as f:
                processed = set(line.strip() for line in f if line.strip())
            print(f"📋 処理済みURL {len(processed)} 件を読み込みました。")
            return processed
        except Exception as e:
            print(f"⚠️ 処理済みURLファイルの読み込みエラー: {e}")
            return set()
    return set()

def save_processed_rakuma_url(url):
    """処理済みURLをファイルに追記"""
    try:
        with open(PROCESSED_URLS_FILE, 'a', encoding='utf-8') as f:
            f.write(url + '\n')
    except Exception as e:
        print(f"⚠️ 処理済みURLの保存エラー: {e}")

def load_target_urls_from_csv():
    """products_rakuma.csv から削除対象・重複対象のURLを抽出（重複は古い方を削除）"""
    if not os.path.exists(RAKUMA_CSV):
        print(f"❌ CSVファイルが見つかりません: {RAKUMA_CSV}")
        return []
    
    try:
        df = pd.read_csv(RAKUMA_CSV, encoding='utf-8-sig')
        
        # 削除対象
        delete_targets = pd.DataFrame()
        if '削除' in df.columns:
            delete_targets = df[df['削除'] == '削除'].copy()
        
        # 重複対象（品番ごとに新しい1件を残して古い方を削除）
        duplicate_targets = pd.DataFrame()
        if '重複' in df.columns and '品番' in df.columns:
            dup_df = df[df['重複'] == '重複'].copy()
            if not dup_df.empty and 'URL' in dup_df.columns:
                date_col = None
                for col in ['最終更新日時', '商品登録日時']:
                    if col in dup_df.columns:
                        date_col = col
                        break

                dup_df = dup_df.dropna(subset=['URL']).copy()

                if date_col:
                    dup_df['_sort_dt'] = pd.to_datetime(dup_df[date_col], errors='coerce')
                    dup_df['_sort_dt'] = dup_df['_sort_dt'].fillna(pd.Timestamp.min)
                    dup_df = dup_df.sort_values(['品番', '_sort_dt', 'URL'], ascending=[True, False, True])
                    dup_df['_dup_rank'] = dup_df.groupby('品番').cumcount()
                else:
                    dup_df['_dup_rank'] = dup_df.groupby('品番').cumcount()

                duplicate_targets = dup_df[dup_df['_dup_rank'] > 0].copy()
        
        # 統合
        if 'URL' in df.columns:
            combined = pd.concat([delete_targets, duplicate_targets], ignore_index=True)
            combined = combined.dropna(subset=['URL']).drop_duplicates(subset=['URL'])
            urls = combined['URL'].tolist()
            
            print(f"📦 削除対象: {len(delete_targets)} 件")
            print(f"🔁 重複対象（古い方）: {len(duplicate_targets)} 件")
            print(f"✅ 合計: {len(urls)} 件のURLを抽出しました")
            
            return urls
        else:
            print("❌ CSVに'URL'列がありません")
            return []
            
    except Exception as e:
        print(f"❌ CSV読み込みエラー: {e}")
        return []

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

def delete_products(product_urls):
    """ラクマの商品を削除する"""
    if not product_urls:
        print("✅ 処理対象のURLがありません")
        return
    
    # URLを編集ページ形式に変換
    # https://item.fril.jp/{id} → https://fril.jp/item/{id}/edit
    edit_urls = []
    for url in product_urls:
        edit_url = convert_to_edit_url(url)
        edit_urls.append(edit_url)
        if edit_url != url:
            print(f"📝 変換: {url}")
            print(f"    → {edit_url}")
    
    with sync_playwright() as p:
        # Firefoxブラウザを起動（ユーザーデータを保持）
        print("🌐 ブラウザを起動中...")
        browser = p.firefox.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            slow_mo=500
        )
        
        page = browser.pages[0] if browser.pages else browser.new_page()
        
        # 手動ログインの機会を提供
        print("\n" + "=" * 70)
        print("🔐 ログイン確認と手動ログインの時間")
        print("=" * 70)
        print("📌 ブラウザを起動してログイン状態を確認します")
        print("=" * 70)
        
        # マイページに直接遷移（ログイン済みならそのまま表示、未ログインならログインページへ）
        print("\n🌐 マイページを開いています...")
        try:
            page.goto("https://fril.jp/mypage", timeout=30000)
            page.wait_for_timeout(3000)
            
            # 現在のURLを確認
            current_url = page.url
            print(f"📍 現在のURL: {current_url}")
            
            # ログインページにリダイレクトされた場合
            if "login" in current_url.lower():
                print("⚠️ ログインが必要です。")
                # Persistent Contextを使用しているため、通常は自動ログインされるはず
                # 数秒待ってから再確認
                page.wait_for_timeout(5000)
                current_url = page.url
                if "login" in current_url.lower():
                    print("❌ ログインできませんでした。ブラウザで一度手動ログインしてから再実行してください。")
                    browser.close()
                    return
            
            print("✅ ログイン済みです")
        except Exception as e:
            print(f"⚠️ ページ遷移エラー: {e}")
            print("処理を続行します...")
        
        # ログイン後のリダイレクト完了を待つ
        print("\n⏳ ログイン処理の完了を待っています...")
        page.wait_for_timeout(5000)  # 5秒待機してリダイレクト完了を待つ
        
        # 現在のページがログインページやリダイレクト中でないか確認
        current_url = page.url
        print(f"📍 ログイン後のURL: {current_url}")
        
        # もしまだログイン関連のURLなら、リダイレクト完了を待つ
        if "login" in current_url.lower() or "authorize" in current_url.lower() or "callback" in current_url.lower():
            print("🔄 リダイレクト処理中です。完了を待っています...")
            try:
                # ログイン関連のURLでなくなるまで待機（最大30秒）
                page.wait_for_url(
                    lambda url: "login" not in url.lower() and "authorize" not in url.lower() and "callback" not in url.lower(),
                    timeout=30000
                )
                print("✅ リダイレクト完了")
                page.wait_for_timeout(2000)
            except:
                print("⚠️ リダイレクトのタイムアウト。そのまま続行します")
        
        # ログイン確認
        print("\n🔍 ログイン状態を確認中...")
        try:
            page.goto("https://fril.jp/mypage", timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"⚠️ マイページへの遷移エラー: {e}")
            print("現在のページで確認を続けます...")
        
        current_url = page.url
        print(f"📍 確認URL: {current_url}")
        
        if "login" in current_url.lower():
            print("❌ ログインが確認できませんでした")
            print("⚠️ ログインが必要です。処理を中止します。")
            
            # Slack通知を送信（ログイン切れ）
            try:
                import subprocess
                subprocess.run([
                    r"..\venv\Scripts\python.exe", 
                    "send_slack_notification.py",
                    "❌ ラクマ削除: ログインセッションが切れています。手動でログインが必要です。",
                    "error"
                ], cwd=os.path.dirname(os.path.abspath(__file__)))
            except:
                pass
            
            browser.close()
            return
        
        print("✅ ログイン完了を確認しました")
        
        # Cookieを確認してセッション情報を表示
        cookies = browser.cookies()
        fril_cookies = [c for c in cookies if 'fril.jp' in c.get('domain', '')]
        print(f"🍪 ラクマのCookie数: {len(fril_cookies)}")
        
        if fril_cookies:
            print("✅ セッションが確立されました")
            # 主要なCookie名を表示
            cookie_names = [c.get('name', '') for c in fril_cookies]
            print(f"   Cookie名: {', '.join(cookie_names[:5])}")  # 最初の5つを表示
        else:
            print("⚠️ Cookie が見つかりません。セッションが不安定な可能性があります")
        
        # 処理開始
        print(f"\n🗑️ {len(edit_urls)} 件の商品を削除します\n")
        
        success_count = 0
        fail_count = 0
        
        for idx, url in enumerate(edit_urls, 1):
            print(f"[{idx}/{len(edit_urls)}] {url}")
            
            try:
                # 商品ページにアクセス
                try:
                    # まずマイページにアクセスしてセッションを確認（リトライ付き）
                    retry_count = 0
                    max_retries = 2
                    
                    while retry_count <= max_retries:
                        try:
                            page.goto("https://fril.jp/mypage", timeout=60000, wait_until="domcontentloaded")
                            page.wait_for_timeout(1000)
                            break
                        except Exception as retry_error:
                            retry_count += 1
                            if retry_count > max_retries:
                                raise retry_error
                            print(f"  🔄 リトライ {retry_count}/{max_retries}...")
                            page.wait_for_timeout(3000)
                    
                    if "login" in page.url.lower():
                        print("  ⚠️ セッションが切れています。この商品をスキップします。")
                        continue
                    
                    # 商品編集ページにアクセス
                    page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    
                    # ページ遷移後のURLを確認してログイン状態をチェック
                    current_url = page.url
                    print(f"  📍 アクセス先: {current_url}")
                    
                    # 404エラーページのチェック
                    if page.locator('h1.css-s6ybq1:has-text("お探しのページは見つかりませんでした")').count() > 0:
                        print("  ⚠️ ページが見つかりません（削除済みまたは無効なURL）")
                        print("  → 処理済みに記録してスキップします")
                        save_processed_rakuma_url(url)
                        success_count += 1
                        continue
                    
                    if "login" in current_url.lower():
                        print("  ❌ ログインページにリダイレクトされました")
                        print("  🔒 ブラウザでログインしてください...")
                        # ログイン完了を待つ（最大60秒）
                        try:
                            page.wait_for_url(lambda u: "login" not in u.lower() and "edit" in u.lower(), timeout=60000)
                            print("  ✅ ログイン完了、処理を続行します")
                            page.wait_for_timeout(2000)
                        except:
                            print("  ❌ ログインタイムアウト、この商品をスキップします")
                            fail_count += 1
                            continue
                    
                except Exception as goto_error:
                    print(f"  ❌ アクセス失敗: {goto_error}")
                    fail_count += 1
                    continue
                
                # 「削除する」ボタンを探す
                delete_button = None

                # パターン1: テキストで検索
                try:
                    delete_button = page.get_by_text("削除する", exact=False).first
                    if delete_button and delete_button.is_visible(timeout=2000):
                        delete_button.click()
                        print("  🗑️ 「削除する」をクリック")
                    else:
                        delete_button = None
                except:
                    delete_button = None

                # パターン2: CSSセレクタで検索
                if not delete_button:
                    try:
                        delete_button = page.locator('button:has-text("削除する")').first
                        if delete_button.count() > 0:
                            delete_button.click(timeout=3000)
                            print("  🗑️ 「削除する」をクリック")
                        else:
                            delete_button = None
                    except:
                        delete_button = None

                # パターン3: aタグで検索
                if not delete_button:
                    try:
                        delete_button = page.locator('a:has-text("削除する")').first
                        if delete_button.count() > 0:
                            delete_button.click(timeout=3000)
                            print("  🗑️ 「削除する」をクリック")
                        else:
                            delete_button = None
                    except:
                        delete_button = None

                if not delete_button:
                    print("  ⚠️ 削除ボタンが見つかりません（既に削除済み or 売却済み）")
                    fail_count += 1
                    continue

                # モーダルの確認ボタンをクリック
                page.wait_for_timeout(1000)
                
                try:
                    confirm_clicked = False
                    dialog = page.locator('div[role="dialog"]').last
                    if dialog.count() > 0:
                        confirm_button = dialog.locator('button:has-text("削除")').first
                        if confirm_button.count() > 0:
                            confirm_button.click(timeout=5000)
                            confirm_clicked = True
                        else:
                            confirm_button = dialog.locator('button:has-text("はい")').first
                            if confirm_button.count() > 0:
                                confirm_button.click(timeout=5000)
                                confirm_clicked = True

                    if not confirm_clicked:
                        confirm_button = page.locator('button:has-text("削除")').first
                        if confirm_button.count() > 0 and confirm_button.is_visible(timeout=2000):
                            confirm_button.click(timeout=5000)
                            confirm_clicked = True

                    if not confirm_clicked:
                        print("  ❌ 確認ボタンが見つかりません")
                        fail_count += 1
                        continue

                    # ページ遷移または通知を待つ（最大10秒）
                    before_url = page.url
                    page.wait_for_timeout(3000)

                    # 結果を確認
                    after_url = page.url

                    # パターン1: URL変化で成功判定（編集ページから離脱）
                    if before_url != after_url and "/edit" not in after_url:
                        print("  ✅ 削除しました（ページ遷移）")
                        success_count += 1
                        save_processed_rakuma_url(url)
                    else:
                        # 成功通知を確認
                        try:
                            notice = page.locator('p#notice').first
                            if notice.count() > 0 and notice.is_visible():
                                notice_text = notice.text_content()
                                if "削除" in notice_text:
                                    print(f"  ✅ 削除しました: {notice_text}")
                                    success_count += 1
                                    save_processed_rakuma_url(url)
                                else:
                                    print(f"  ⚠️ 予期しない通知: {notice_text}")
                                    fail_count += 1
                            else:
                                # 通知が表示されない = 売却済みまたは削除済み
                                print("  ⚠️ この商品は既に売却済みまたは削除済みです（処理済みに記録）")
                                save_processed_rakuma_url(url)
                                success_count += 1
                        except Exception as e:
                            print(f"  ⚠️ 通知確認エラー: {e}")
                            fail_count += 1
                        
                except PlaywrightTimeoutError:
                    print("  ❌ 確認ボタンのタイムアウト")
                    fail_count += 1
                    
            except Exception as e:
                print(f"  ❌ エラー: {e}")
                fail_count += 1
            
            # 次の商品までの待機
            if idx < len(edit_urls):
                page.wait_for_timeout(2000)
        
        print(f"\n📊 処理完了: 成功 {success_count} 件 / 失敗 {fail_count} 件")
        
        browser.close()

def main():
    print("=" * 60)
    print("ラクマ商品 削除ツール")
    print("=" * 60)
    
    # 処理済みURLを読み込み
    processed_urls = load_processed_rakuma_urls()
    
    # CSVから対象URLを読み込み
    target_urls = load_target_urls_from_csv()
    
    if not target_urls:
        print("✅ 処理対象がありません")
        return
    
    # URLを編集ページ形式に変換してから比較
    target_edit_urls = [convert_to_edit_url(url) for url in target_urls]
    
    # 未処理のURLのみをフィルタリング
    unprocessed_urls = [url for url in target_edit_urls if url not in processed_urls]
    
    if not unprocessed_urls:
        print(f"✅ すべて処理済みです（既処理: {len(target_edit_urls)} 件）")
        return
    
    print(f"\n📋 未処理: {len(unprocessed_urls)} 件")
    print(f"📋 既処理: {len(target_edit_urls) - len(unprocessed_urls)} 件")
    
    # 削除
    delete_products(unprocessed_urls)

if __name__ == '__main__':
    main()
