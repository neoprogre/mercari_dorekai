import os
import re
import time
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError
from typing import Optional, Dict, List

# --- 設定 ---
ENV_PATH = r"C:\Users\progr\Desktop\Python\mercari_dorekai\.env"
USER_DATA_DIR = r"C:\Users\progr\Desktop\Python\mercari_dorekai\mercari_user_data"
# ダウンロードフォルダ
DOWNLOAD_DIR = r"C:\Users\progr\Desktop\Python\mercari_dorekai\downloads"
# dorekai_sheet_YYYY-MM-DD.xlsx を使用
XLSX_PREFIX = "dorekai_sheet_"
TARGET_URL = "https://mercari-shops.com/seller/shops/qWxSdPm7yRZ56vy6jEx9mK/products?tab=draft"

# タイムアウト設定（ミリ秒）
PAGE_TIMEOUT = 60000
WAIT_SHORT = 0.5
WAIT_MEDIUM = 1
WAIT_LONG = 2
WAIT_FORM = 3

# 除外キーワード
SKIP_KEYWORDS = ["ミシン待ち", "ミシン"]

# カテゴリー階層
CATEGORY_PATH = [
    "ファッション",
    "レディース",
    "スーツ・フォーマル・ドレス",
    "ドレス・ブライダル",
    "ナイトドレス・キャバドレス"
]

def log(msg: str) -> None:
    """タイムスタンプ付きログ出力"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def truncate_product_name(name: str, max_length: int = 100) -> str:
    """商品名を指定文字数に切り詰める（全角半角どちらも1文字としてカウント）
    
    Args:
        name: 商品名
        max_length: 最大文字数（デフォルト: 100）
        
    Returns:
        切り詰められた商品名
    """
    if len(name) <= max_length:
        return name
    return name[:max_length]

def wait_for_toast_disappear(page, timeout: int = 10000) -> None:
    """トーストメッセージが消えるまで待機
    
    Args:
        page: Playwrightのページオブジェクト
        timeout: タイムアウト時間（ミリ秒）
    """
    try:
        # トーストが表示されるまで少し待つ
        time.sleep(0.3)
        # トーストが消えるまで待機
        toast = page.locator('div.Toastify__toast')
        if toast.count() > 0:
            toast.wait_for(state="hidden", timeout=timeout)
            time.sleep(0.2)  # 追加の安全マージン
    except Exception:
        # トーストが見つからない場合は無視
        pass

def extract_hinban(product_name: str) -> str:
    """商品名から品番（前方の数字）を抽出
    
    Args:
        product_name: 商品名
        
    Returns:
        抽出された品番（数字のみ）
    """
    hinban = ""
    for char in product_name:
        if char.isdigit():
            hinban += char
        else:
            if hinban:  # 数字が見つかったら終了
                break
    return hinban if hinban else product_name.strip()

def extract_brand_english(brand_name: str) -> str:
    """ブランド名から検索用のブランド名を抽出
    
    Args:
        brand_name: ブランド名
        
    Returns:
        抽出されたブランド名
    """
    brand_name = brand_name.strip()
    
    # 「XXX by YYY」形式の場合、YYYを返す
    if ' by ' in brand_name.lower():
        parts = re.split(r' by ', brand_name, flags=re.IGNORECASE)
        if len(parts) > 1:
            return parts[1].strip()
    
    # 先頭の英数字部分を抽出（スペースを含む最初の単語群）
    match = re.match(r'^([A-Za-z0-9\s]+?)(?:\s*[ぁ-んァ-ヶー一-龠]|$)', brand_name)
    if match:
        return match.group(1).strip()
    
    return brand_name.split()[0] if brand_name else ""

def get_latest_dorekai_sheet_path() -> Optional[str]:
    """downloads から最新の dorekai_sheet_*.xlsx を取得"""
    try:
        files = []
        for name in os.listdir(DOWNLOAD_DIR):
            if not name.startswith(XLSX_PREFIX) or not name.endswith(".xlsx"):
                continue
            full_path = os.path.join(DOWNLOAD_DIR, name)
            files.append(full_path)
        if not files:
            return None
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return files[0]
    except Exception:
        return None

def load_product_data() -> Optional[pd.DataFrame]:
    """xlsxファイルから商品データを読み込む
    
    Returns:
        商品データのDataFrame、失敗時はNone
    """
    try:
        xlsx_path = get_latest_dorekai_sheet_path()
        if not xlsx_path:
            log(f"❌ dorekai_sheet_*.xlsx が見つかりません: {DOWNLOAD_DIR}")
            return None
        log(f"📊 商品データを読み込んでいます: {xlsx_path}")
        df = pd.read_excel(xlsx_path, sheet_name="自動生成結果")
        log(f"✅ {len(df)} 件の商品データを読み込みました")
        return df
    except Exception as e:
        log(f"❌ xlsxファイルの読み込みエラー: {e}")
        return None

def get_draft_products(page) -> List[Dict[str, str]]:
    """下書きタブの商品一覧を取得
    
    Args:
        page: Playwrightのページオブジェクト
        
    Returns:
        商品情報のリスト
    """
    try:
        log("📋 下書きタブの商品を取得中...")
        
        # 下書きタブをクリック
        draft_tab = page.locator('button[data-testid="draft-tab"]')
        if draft_tab.count() > 0:
            draft_tab.click()
            time.sleep(WAIT_LONG)
        
        # 商品リストを取得
        products = []
        product_items = page.locator('li[data-testid="product"]')
        count = product_items.count()
        
        log(f"📦 下書き商品数: {count}")
        
        for i in range(count):
            item = product_items.nth(i)
            product_name = item.locator('p[data-testid="product-name"]').inner_text().strip()
            products.append({
                "index": i,
                "product_name": product_name
            })
            log(f"   {i+1}. {product_name}")
        
        return products
    except Exception as e:
        log(f"❌ 下書き商品取得エラー: {e}")
        return []

def select_category(page) -> bool:
    """カテゴリーを自動選択
    
    Args:
        page: Playwrightのページオブジェクト
        
    Returns:
        成功時True、失敗時False
    """
    try:
        # カテゴリー選択ボタンの状態を確認
        category_button = page.locator('div[data-testid="categories"]')
        category_text = category_button.inner_text()
        
        # 既に選択されているかチェック（最後のカテゴリ名が表示されているか）
        if CATEGORY_PATH[-1] in category_text:
            log(f"   ✅ カテゴリー: {' > '.join(CATEGORY_PATH)} (既に選択済み)")
            return True
        
        # カテゴリー選択が必要
        log(f"   📂 カテゴリーを選択中...")
        category_button.click()
        time.sleep(WAIT_MEDIUM)
        
        # カテゴリー階層を順番に選択
        for i, category_name in enumerate(CATEGORY_PATH):
            # 該当するカテゴリーを探して選択
            option = page.locator(f'text="{category_name}"').first
            
            # 要素が見つかるまで少し待つ
            try:
                option.wait_for(state="visible", timeout=5000)
            except:
                log(f"   ⚠️ カテゴリー '{category_name}' が見つかりません")
                return False
            
            option.click()
            time.sleep(WAIT_SHORT)
            
            # 最後のカテゴリー選択後は長めに待つ
            if i == len(CATEGORY_PATH) - 1:
                wait_for_toast_disappear(page)
                time.sleep(WAIT_MEDIUM)  # サイズドロップダウンが有効になるまで待つ
        
        log(f"   ✅ カテゴリー: {' > '.join(CATEGORY_PATH)}")
        return True
    except Exception as e:
        log(f"   ⚠️ カテゴリー選択エラー: {e}")
        return False

def select_size(page, product_data: Dict) -> bool:
    """サイズを自動選択
    
    Args:
        page: Playwrightのページオブジェクト
        product_data: 商品データ
        
    Returns:
        成功時True、失敗時False
    """
    if 'サイズ' not in product_data or pd.isna(product_data['サイズ']):
        log(f"   ⚠️ サイズ: データなし")
        return False
    
    size_input = str(product_data['サイズ']).strip().upper()
    
    # サイズマッピング（大文字小文字両対応）
    size_mapping = {
        'XXS以下': ['XXS'],
        'XS(SS)': ['XS', 'SS'],
        'S': ['S'],
        'M': ['M'],
        'L': ['L'],
        'XL(LL)': ['XL', 'LL', '2L'],
        '2XL(3L)': ['2XL', '3L'],
        '3XL(4L)': ['3XL', '4L', 'XXXL'],
        '4XL(5L)以上': ['4XL', '5L', 'XXXXL'],
        'FREE SIZE': ['FREE', 'フリー', 'F']
    }
    
    try:
        size_select = page.locator('select[name="サイズ"]')
        options = size_select.locator('option')

        # 入力サイズからターゲットカテゴリを決定
        target_size = None
        for size_key, keywords in size_mapping.items():
            if any(size_input == kw.upper() for kw in keywords):
                target_size = size_key
                break

        if not target_size:
            log(f"   ⚠️ サイズ: '{size_input}' が見つかりません")
            return False

        # 選択肢を完全一致で探す（部分一致は禁止）
        for j in range(options.count()):
            option_value = options.nth(j).get_attribute('value')
            option_text = options.nth(j).inner_text().strip()
            if option_text == target_size:
                size_select.select_option(option_value)
                log(f"   ✅ サイズ: {option_text}")
                wait_for_toast_disappear(page)
                return True

        log(f"   ⚠️ サイズ: '{target_size}' が選択肢にありません")
        return False
    except Exception as e:
        log(f"   ⚠️ サイズ選択エラー: {e}")
        return False

def input_brand(page, product_data: Dict) -> bool:
    """ブランドを入力（手動選択を待機）
    
    Args:
        page: Playwrightのページオブジェクト
        product_data: 商品データ
        
    Returns:
        成功時True、スキップ時False
    """
    if 'ブランド名' not in product_data or pd.isna(product_data['ブランド名']):
        log(f"   ⚠️ ブランド: データなし")
        return False
    
    brand_full = str(product_data['ブランド名']).strip()
    
    # ノーブランドの場合はスキップ
    if brand_full.upper() in ["ノーブランド", "NO BRAND"]:
        log(f"   ⚠️ ブランド: ノーブランド（スキップ）")
        return False
    
    # 特例: ROBE de FLEURS は固定で検索
    if "robe de fleurs" in brand_full.lower():
        brand_search = "ROBE de FLEURS"
    else:
        # 英語部分のみを抽出
        brand_search = extract_brand_english(brand_full)
    
    if not brand_search:
        log(f"   ⚠️ ブランド: 抽出失敗")
        return False
    
    try:
        log("⏸️  ブランドを手動で選択してください：")
        log(f"      入力値: {brand_search}")
        
        brand_input = page.locator('input[data-testid="auto-complete-input"]')
        brand_input.clear()
        brand_input.fill(brand_search)
        time.sleep(WAIT_MEDIUM)
        
        log(f"   ⏸️  ブランド検索欄に入力されました。候補から選択してください")
        log("   💡 公開ボタンをクリックすると自動的に次の商品に進みます...")
        
        # 公開完了後のページ遷移を待機（最大5分）
        try:
            # URLパターンを複数試す（opened タブまたは draft タブ）
            page.wait_for_url(lambda url: "products" in url and ("tab=opened" in url or "tab=draft" in url), timeout=300000)
            log("   ✅ 公開が完了しました！")
            return True
        except Exception as timeout_e:
            # タイムアウトでもスキップ扱いにして次の商品へ進める
            log(f"   ⚠️ ブランド選択のタイムアウト: 手動で公開してください")
            log(f"   💡 次の商品へ進みます...")
            return False
    except Exception as e:
        log(f"   ⚠️ ブランド入力エラー: {e}")
        return False

def fill_product_form(page, product_data: Dict) -> bool:
    """商品情報をフォームに入力
    
    Args:
        page: Playwrightのページオブジェクト
        product_data: 商品データ
        
    Returns:
        成功時True、失敗時False
    """
    try:
        log(f"\n📝 商品情報を入力中: {product_data.get('品番', 'N/A')}")
        
        # 商品名（メルカリタイトル）
        if 'メルカリタイトル' in product_data and pd.notna(product_data['メルカリタイトル']):
            # 商品名を100文字に制限
            original_name = str(product_data['メルカリタイトル'])
            truncated_name = truncate_product_name(original_name, max_length=100)
            
            name_input = page.locator('input[name="name"]')
            name_input.clear()
            name_input.fill(truncated_name)
            
            if len(original_name) > 100:
                log(f"   ✅ 商品名: {truncated_name} (元: {len(original_name)}文字 → 100文字に切詰)")
            else:
                log(f"   ✅ 商品名: {truncated_name}")
            
            wait_for_toast_disappear(page)
        else:
            log(f"   ⚠️ 商品名: データなし")
        
        # 商品の説明（メルカリ説明文）
        if 'メルカリ説明文' in product_data and pd.notna(product_data['メルカリ説明文']):
            # ＊素材 生地 質感を修正
            description = str(product_data['メルカリ説明文'])
            description = re.sub(
                r'＊素材 生地 質感\s*\n([^\n]+)\n([^\n]+)',
                r'＊素材 生地 質感\n\1\n生地、質感\n\2',
                description
            )
            
            desc_textarea = page.locator('textarea[name="description"]')
            desc_textarea.clear()
            desc_textarea.fill(description)
            log(f"   ✅ 商品の説明: {len(description)} 文字")
            wait_for_toast_disappear(page, timeout=3000)
        else:
            log(f"   ⚠️ 商品の説明: データなし")
        
        # 商品の状態（コンディション1,2,3に基づいて判定）
        condition_map = {
            'コンディション3': ("CONDITION_BAD", "全体的に状態が悪い"),
            'コンディション2': ("CONDITION_DIRTY", "傷や汚れあり"),
            'コンディション1': ("CONDITION_LITTLE_DIRTY", "やや傷や汚れあり"),
        }
        
        condition_value = "CONDITION_CLEAN"
        condition_label = "目立った傷や汚れなし (デフォルト)"
        
        for cond_key, (cond_val, cond_lbl) in condition_map.items():
            if cond_key in product_data and pd.notna(product_data[cond_key]):
                condition_value = cond_val
                condition_label = f"{cond_lbl} ({cond_key})"
                break
        
        condition_select = page.locator('select[name="condition.id"]')
        condition_select.select_option(condition_value)
        log(f"   ✅ 商品の状態: {condition_label}")
        wait_for_toast_disappear(page)
        
        # クール区分は常に「通常」を選択
        cool_select = page.locator('select[name="mercaribinForBusinessCoolType"]')
        cool_select.select_option("MERCARIBIN_FOR_BUSINESS_COOL_TYPE_NORMAL")
        log(f"   ✅ クール区分: 通常")
        wait_for_toast_disappear(page)
        
        # 販売価格（販売単価）
        if '販売単価' in product_data and pd.notna(product_data['販売単価']):
            try:
                price = int(float(product_data['販売単価']))
                price_input = page.locator('input[name="price"]')
                price_input.clear()
                price_input.fill(str(price))
                log(f"   ✅ 販売価格: ¥{price:,}")
                wait_for_toast_disappear(page, timeout=3000)
            except (ValueError, TypeError) as e:
                log(f"   ⚠️ 販売価格: 数値変換失敗 ({product_data['販売単価']})")
        else:
            log(f"   ⚠️ 販売価格: データなし")
        
        # カテゴリー自動選択
        select_category(page)
        
        # サイズ選択（カテゴリー選択後に表示される）
        size_selected = select_size(page, product_data)
        
        log("✅ 自動入力完了\n")
        
        # ブランドとサイズが両方ない場合は手動入力を待機
        has_brand = 'ブランド名' in product_data and pd.notna(product_data['ブランド名']) and product_data['ブランド名'].upper() not in ["ノーブランド", "NO BRAND"]
        
        if not has_brand and not size_selected:
            log("⚠️ ⚠️ ⚠️ ブランド・サイズ両方がありません ⚠️ ⚠️ ⚠️")
            log("🔒 以下を手動で設定してください：")
            log("   1. ブランドを選択")
            log("   2. サイズを選択")
            log("   3. 公開ボタンをクリック")
            log("=" * 70)
            
            # ブランドを入力してから公開を待機
            input_brand(page, product_data)
        else:
            # ブランド（英語部分のみ入力してストップ、ノーブランドは無視）
            input_brand(page, product_data)
        
        return True
        
    except Exception as e:
        log(f"❌ フォーム入力エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

def find_and_click_product(page, hinban: str) -> bool:
    """品番に一致する商品を検索してクリック
    
    Args:
        page: Playwrightのページオブジェクト
        hinban: 検索する品番
        
    Returns:
        成功時True、失敗時False
    """
    try:
        product_items = page.locator('li[data-testid="product"]')
        
        for i in range(product_items.count()):
            item = product_items.nth(i)
            current_product_name = item.locator('p[data-testid="product-name"]').inner_text().strip()
            current_hinban = extract_hinban(current_product_name)
            
            if str(current_hinban) == str(hinban):
                log(f"   ✅ 商品が見つかりました: {current_product_name}")
                item.click()
                time.sleep(WAIT_FORM)
                return True
        
        log(f"⚠️ 商品が現在の一覧に見つかりません")
        return False
    except Exception as e:
        log(f"❌ 商品検索エラー: {e}")
        return False

def should_skip_product(product_name: str) -> bool:
    """商品をスキップすべきか判定
    
    Args:
        product_name: 商品名
        
    Returns:
        スキップすべき場合True
    """
    return any(keyword in product_name for keyword in SKIP_KEYWORDS)

def main() -> None:
    """メイン処理"""
    load_dotenv(ENV_PATH)
    
    # xlsxファイルから商品データを読み込む
    df = load_product_data()
    if df is None:
        return
    
    log("\n🚀 ブラウザを起動しています...")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        page = context.pages[0]
        page.set_default_timeout(PAGE_TIMEOUT)
        
        log(f"📄 ページに移動します: {TARGET_URL}")
        page.goto(TARGET_URL)
        time.sleep(WAIT_FORM)
        
        # 下書き商品を取得
        draft_products = get_draft_products(page)
        
        if not draft_products:
            log("⚠️ 下書き商品が見つかりませんでした")
            context.close()
            return
        
        # 各商品を処理
        processed_count = 0
        skipped_count = 0
        
        for idx, draft_product in enumerate(draft_products):
            product_name = draft_product['product_name']
            
            # スキップ判定
            if should_skip_product(product_name):
                log(f"\n⏭️  スキップ: {product_name}（ミシン処理中のため編集禁止）")
                skipped_count += 1
                continue
            
            # 品番を抽出
            hinban = extract_hinban(product_name)
            log(f"\n🔍 品番抽出: '{product_name}' → '{hinban}'")
            
            # xlsxから該当する品番のデータを検索
            matching_row = df[df['品番'].astype(str) == str(hinban)]
            
            if matching_row.empty:
                log(f"⚠️ 品番 {hinban} のデータがxlsxに見つかりません")
                skipped_count += 1
                continue
            
            product_data = matching_row.iloc[0].to_dict()
            
            # 商品を検索してクリック
            log(f"\n📦 商品を開いています: {hinban} ({idx+1}/{len(draft_products)})")
            
            if not find_and_click_product(page, hinban):
                skipped_count += 1
                continue
            
            # フォームに入力
            if fill_product_form(page, product_data):
                processed_count += 1
            else:
                # 公開されずにタイムアウトした場合もカウント
                log(f"⚠️ 商品 {hinban} の処理を中断します")
            
            # 下書き一覧に戻る（公開済みページから戻る）
            log(f"\n📋 下書き一覧に戻ります...")
            page.goto(TARGET_URL)
            time.sleep(WAIT_LONG)
        
        log(f"\n✅ すべての商品の処理が完了しました")
        log(f"   処理済み: {processed_count} 件")
        log(f"   スキップ: {skipped_count} 件")
        log("👋 ブラウザを閉じます")
        context.close()

if __name__ == "__main__":
    main()
