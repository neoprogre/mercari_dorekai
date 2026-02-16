import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError, sync_playwright

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = Path(os.getenv("ENV_PATH", str(BASE_DIR / ".env")))
USER_DATA_DIR = Path(os.getenv("USER_DATA_DIR", str(BASE_DIR / "mercari_user_data")))
HEADLESS = os.getenv("HEADLESS", "1").strip() != "0"
DEFAULT_CHANNEL = "chrome" if sys.platform.startswith("win") else ""
PLAYWRIGHT_CHANNEL = os.getenv("PLAYWRIGHT_CHANNEL", DEFAULT_CHANNEL).strip() or None

OPENED_URL = (
    "https://mercari-shops.com/seller/shops/qWxSdPm7yRZ56vy6jEx9mK/products?tab=opened"
)
UPLOAD_URL = (
    "https://mercari-shops.com/seller/shops/qWxSdPm7yRZ56vy6jEx9mK/products/upload"
)

PAGE_TIMEOUT = 60000
WAIT_SHORT = 0.5
WAIT_MEDIUM = 1.0
WAIT_LONG = 2.0


def ensure_logged_in(page) -> bool:
    page.goto(OPENED_URL)
    try:
        page.wait_for_selector(
            'input[name="search"][data-testid="search-input"]',
            state="visible",
            timeout=5000,
        )
        return True
    except TimeoutError:
        pass

    log("Login required. Starting login flow...")

    try:
        login_shops_btn = page.locator('button[data-testid="login-with-mercari-account"]')
        try:
            login_shops_btn.wait_for(state="visible", timeout=5000)
        except TimeoutError:
            pass
        if login_shops_btn.is_visible():
            login_shops_btn.click()
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
    except Exception:
        pass

    if "signup" in page.url:
        try:
            login_link = page.locator('a[href*="/signin"]').first
            if login_link.is_visible():
                login_link.click()
                page.wait_for_load_state("domcontentloaded")
                time.sleep(2)
        except Exception:
            pass

    if "login" in page.url or "signin" in page.url or page.locator('input[name="emailOrPhone"]').count() > 0:
        mercari_email = os.environ.get("MERCARI_EMAIL")
        mercari_password = os.environ.get("MERCARI_PASSWORD")

        if not mercari_email or not mercari_password:
            log("MERCARI_EMAIL or MERCARI_PASSWORD is missing.")
            return False

        try:
            email_input = page.locator('input[name="emailOrPhone"]').first
            if not email_input.is_visible():
                email_input = page.locator('input[name="email"], input[type="email"]').first

            if email_input.is_visible():
                email_input.fill(mercari_email)
                next_btn = page.locator('button[data-testid="submit"]').first
                if next_btn.is_visible():
                    next_btn.click()
                    time.sleep(2)

            pass_input = page.locator('input[name="password"], input[type="password"]').first
            if pass_input.is_visible():
                pass_input.fill(mercari_password)
                submit_btn = page.locator('button[data-testid="submit"]').first
                if submit_btn.is_visible():
                    submit_btn.click()
        except Exception as exc:
            log(f"Login input failed: {exc}")

    try:
        page.wait_for_selector(
            'input[name="search"][data-testid="search-input"]',
            state="visible",
            timeout=20000,
        )
        return True
    except TimeoutError:
        log("Login failed or additional verification required.")
        return False


def log(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def read_csv_file(csv_path: str) -> pd.DataFrame:
    encodings = ["utf-8-sig", "cp932", "shift_jis"]
    last_error: Optional[Exception] = None

    for encoding in encodings:
        try:
            return pd.read_csv(csv_path, encoding=encoding, low_memory=False)
        except Exception as exc:
            last_error = exc

    raise ValueError(f"Failed to read CSV with supported encodings: {last_error}")


def extract_hinban(value: str) -> str:
    hinban = ""
    for char in value:
        if char.isdigit():
            hinban += char
        elif hinban:
            break
    return hinban if hinban else value.strip()


def extract_size_from_name(product_name: str) -> str:
    """商品名の末尾からサイズを抽出"""
    name = product_name.strip().upper()
    
    # 末尾のサイズを抽出（スペース区切りの最後の要素）
    parts = name.split()
    if not parts:
        return ""
    
    last_part = parts[-1].strip()
    
    # Fはフリーサイズ
    if last_part == "F":
        return "FREE SIZE"
    
    # XXS以下
    if "XXS" in last_part:
        return "XXS以下"
    
    # XS (SS含む)
    if last_part in ["XS", "SS", "XS(SS)"]:
        return "XS(SS)"
    
    # S（XSやSSを除外）
    if last_part == "S":
        return "S"
    
    # M
    if last_part == "M":
        return "M"
    
    # L（XLやLLを除外）
    if last_part == "L":
        return "L"
    
    # XL (LL含む)
    if last_part in ["XL", "LL", "2L", "XL(LL)"]:
        return "XL(LL)"
    
    # 2XL (3L含む)
    if last_part in ["2XL", "3L", "XXL", "2XL(3L)"]:
        return "2XL(3L)"
    
    # 3XL (4L含む)
    if last_part in ["3XL", "4L", "XXXL", "3XL(4L)"]:
        return "3XL(4L)"
    
    # 4XL以上
    if last_part in ["4XL", "5L", "XXXXL", "4XL(5L)以上"]:
        return "4XL(5L)以上"
    
    # FREEと明示されている場合
    if "FREE" in last_part or "フリー" in product_name:
        return "FREE SIZE"
    
    return ""


def get_search_code(row: Dict) -> str:
    sku_code = row.get("SKU1_商品管理コード")
    if pd.notna(sku_code):
        sku_code = str(sku_code).strip()
        if sku_code:
            return sku_code

    product_name = str(row.get("商品名", "")).strip()
    if product_name:
        return extract_hinban(product_name)

    return ""


def wait_for_toast_disappear(page, timeout: int = 10000) -> None:
    try:
        time.sleep(0.3)
        toast = page.locator('div.Toastify__toast')
        if toast.count() > 0:
            toast.wait_for(state="hidden", timeout=timeout)
            time.sleep(0.2)
    except Exception:
        pass


def open_product_and_set_private(page, search_code: str) -> bool:
    try:
        page.goto(OPENED_URL)
        time.sleep(WAIT_LONG)

        search_input = page.locator('input[name="search"][data-testid="search-input"]')
        if search_input.count() == 0:
            log("Search input not found on opened page.")
            return False

        search_input.clear()
        search_input.fill(search_code)
        search_input.press("Enter")
        time.sleep(WAIT_MEDIUM)

        product_items = page.locator('li[data-testid="product"]')
        count = product_items.count()
        if count == 0:
            log(f"No products found for code: {search_code}")
            return False

        log(f"  Found {count} product(s) in search results")
        target_item = None
        for idx in range(count):
            item = product_items.nth(idx)
            name_locator = item.locator('p[data-testid="product-name"]')
            name_text = name_locator.inner_text().strip() if name_locator.count() else ""
            if not name_text:
                continue

            name_hinban = extract_hinban(name_text)
            log(f"  Product {idx+1}: '{name_text[:50]}...' -> hinban: '{name_hinban}'")
            
            # 完全一致のみ（前方一致で誤爆を防ぐ）
            if str(name_hinban) == str(search_code):
                target_item = item
                log(f"  ✓ Match found!")
                break

        if target_item is None:
            log(f"Exact match not found, skipping: {search_code}")
            return False

        target_item.click()
        time.sleep(WAIT_LONG)

        open_modal_button = page.locator('button[data-testid="open-update-modal-button"]')
        if open_modal_button.count() == 0:
            log(f"Open modal button not found for: {search_code}")
            return False

        open_modal_button.first.click()
        modal = page.locator('section[data-testid="modal"]')
        modal.wait_for(state="visible", timeout=10000)

        unopened_button = page.locator('button[data-testid="unopened-button"]')
        if unopened_button.count() == 0:
            log(f"Unopened button not found for: {search_code}")
            return False

        unopened_button.first.click()
        wait_for_toast_disappear(page)
        try:
            modal.wait_for(state="hidden", timeout=10000)
        except Exception:
            pass
        time.sleep(WAIT_SHORT)
        log(f"Set private: {search_code}")
        return True
    except Exception as exc:
        log(f"Error while setting private for {search_code}: {exc}")
        return False


def upload_csv(page, csv_path: str) -> bool:
    try:
        page.goto(UPLOAD_URL)
        time.sleep(WAIT_LONG)

        file_input = page.locator('div[data-testid="fileInput"] input[type="file"]')
        if file_input.count() == 0:
            log("File input not found on upload page.")
            return False

        file_input.set_input_files(csv_path)
        time.sleep(WAIT_MEDIUM)

        upload_button = page.locator('button[data-testid="product-upload"]')
        if upload_button.count() > 0:
            upload_button.first.click()
            wait_for_toast_disappear(page)
        else:
            log("Upload button not found!")
            return False

        # 画面遷移を待つ（upload/xxxのようなURLに変わる）
        log("Waiting for page transition after upload...")
        try:
            page.wait_for_url("**/products/upload/**", timeout=30000)
            log(f"Page transitioned to: {page.url}")
        except Exception as exc:
            log(f"Page transition timeout: {exc}")
            return False
        
        # ボタンが表示されるまで待機
        log("Waiting for bulk register button to appear...")
        time.sleep(3)
        
        # 「一括で登録する」ボタンをクリック
        bulk_register_button = page.get_by_role("button", name="一括で登録する")
        try:
            bulk_register_button.wait_for(state="visible", timeout=10000)
            log(f"Bulk register button found, count: {bulk_register_button.count()}")
        except Exception as exc:
            log(f"Bulk register button not visible: {exc}")
            log(f"Current button count: {bulk_register_button.count()}")
            return False
        
        if bulk_register_button.count() > 0:
            bulk_register_button.first.click()
            log("First bulk register button clicked, waiting for confirmation modal...")
            
            # モーダルが表示されるまで待機
            modal = page.locator('section[data-testid="modal"]')
            try:
                modal.wait_for(state="visible", timeout=10000)
                log("Confirmation modal appeared")
            except Exception as exc:
                log(f"Modal wait timeout: {exc}")
                return False
            
            time.sleep(WAIT_SHORT)
            
            # モーダル内の「一括で登録する」ボタンをクリック
            final_submit_button = page.locator('button[data-testid="register-submit"]')
            if final_submit_button.count() > 0:
                final_submit_button.first.click()
                log("Final registration button clicked, starting bulk registration...")
                wait_for_toast_disappear(page)
            else:
                log("Final submit button not found in modal!")
                return False
            
            # 登録完了まで待機（アップロードページに戻るまで、最大5分）
            try:
                page.wait_for_url("**/products/upload", timeout=300000)
                log("Returned to upload page")
            except Exception as exc:
                log(f"Wait for page return timeout: {exc}")
            
            # 登録履歴で「登録完了」が表示されるまで待機
            filename = os.path.basename(csv_path)
            log(f"Waiting for registration completion of: {filename}")
            
            for attempt in range(60):  # 最大10分待機（10秒×60回）
                time.sleep(10)
                
                # テーブルの該当行を探す
                rows = page.locator('table tbody tr')
                for i in range(rows.count()):
                    row = rows.nth(i)
                    row_text = row.inner_text()
                    
                    if filename in row_text:
                        if "登録完了" in row_text:
                            log(f"Registration completed: {filename}")
                            time.sleep(WAIT_LONG)
                            log(f"Uploaded CSV: {csv_path}")
                            return True
                        elif "登録を再開する" in row_text:
                            log(f"Still processing... ({attempt + 1}/60)")
                            break
                        elif "エラー" in row_text:
                            log(f"Registration error detected: {filename}")
                            return False
            
            log(f"Registration timeout after 10 minutes: {filename}")
            return False
        else:
            log("Bulk register button not found!")
            return False
    except Exception as exc:
        log(f"CSV upload failed: {exc}")
        return False


def set_size_for_product(page, product_name: str) -> bool:
    """商品ページでサイズを設定"""
    try:
        size_text = extract_size_from_name(product_name)
        if not size_text:
            log(f"  No size found in product name: {product_name}")
            return False
        
        log(f"  Size to set: {size_text}")
        
        # サイズマッピング（表示テキスト → value）
        size_mapping = {
            "XXS以下": "0c1712c6-6466-47b5-8820-ee22c9b557bb",
            "XS(SS)": "58b92459-1dd3-453a-9f48-27e678d3c4f2",
            "S": "8a58efd8-34a0-4e4a-9202-e95a08b2a4bc",
            "M": "d5dbe802-d454-4368-b988-5c14f003e507",
            "L": "7cbcbdb2-e79a-412e-b568-6e519620c9aa",
            "XL(LL)": "e69a18b7-3a5b-4f20-855e-ae143007a36c",
            "2XL(3L)": "897918aa-7b7b-4da6-b7be-06accb9b4cac",
            "3XL(4L)": "54979258-8c53-47d7-8475-dbb156547650",
            "4XL(5L)以上": "05995a6d-063c-4d34-9a88-182b2abdfe2a",
            "FREE SIZE": "365b8ece-31a7-4141-9b6f-1df1c13caee1",
        }
        
        if size_text not in size_mapping:
            log(f"  Size not in mapping: {size_text}")
            return False
        
        size_value = size_mapping[size_text]
        
        # サイズセレクトボックスを探す
        size_select = page.locator('select[name="サイズ"]')
        if size_select.count() == 0:
            log(f"  Size select not found")
            return False
        
        # 現在の値を確認
        current_value = size_select.input_value()
        if current_value == size_value:
            log(f"  Size already set: {size_text}")
            return True
        
        # サイズを選択
        size_select.select_option(size_value)
        wait_for_toast_disappear(page)
        time.sleep(WAIT_SHORT)
        
        # 「公開設定に進む」ボタンをクリック
        open_modal_button = page.locator('button[data-testid="open-update-modal-button"]')
        if open_modal_button.count() == 0:
            log(f"  Open modal button not found")
            return False
        
        open_modal_button.first.click()
        
        # モーダルが表示されるまで待機
        modal = page.locator('section[data-testid="modal"]')
        try:
            modal.wait_for(state="visible", timeout=10000)
        except Exception:
            log(f"  Modal not appeared")
            return False
        
        time.sleep(WAIT_SHORT)
        
        # モーダル内の「更新する」ボタンをクリック
        publish_button = page.locator('button[data-testid="publish-button"]')
        if publish_button.count() == 0:
            log(f"  Publish button not found in modal")
            return False
        
        publish_button.first.click()
        wait_for_toast_disappear(page)
        
        # モーダルが閉じるまで待機
        try:
            modal.wait_for(state="hidden", timeout=10000)
        except Exception:
            pass
        
        time.sleep(WAIT_SHORT)
        log(f"  ✅ Size set: {size_text}")
        return True
            
    except Exception as exc:
        log(f"  Error setting size: {exc}")
        return False


def set_sizes_for_uploaded_products(page, df: pd.DataFrame) -> Tuple[int, int]:
    """アップロードした商品のサイズを設定"""
    processed = 0
    skipped = 0
    try:
        log("\n📝 Setting sizes for uploaded products...")
        
        # 公開中商品一覧へ移動
        page.goto(OPENED_URL)
        time.sleep(WAIT_LONG)
        
        for _, row in df.iterrows():
            product_name = str(row.get("商品名", "")).strip()
            if not product_name:
                skipped += 1
                continue
            
            search_code = get_search_code(row)
            if not search_code:
                skipped += 1
                continue
            
            log(f"\n🔍 Searching for: {search_code}")
            
            # 検索
            search_input = page.locator('input[name="search"][data-testid="search-input"]')
            if search_input.count() > 0:
                search_input.clear()
                search_input.fill(search_code)
                search_input.press("Enter")
                time.sleep(WAIT_MEDIUM)
            
            # 商品を探してクリック
            product_items = page.locator('li[data-testid="product"]')
            count = product_items.count()
            
            if count == 0:
                log("  No products found")
                skipped += 1
                continue
            
            target_item = None
            for idx in range(count):
                item = product_items.nth(idx)
                name_locator = item.locator('p[data-testid="product-name"]')
                name_text = name_locator.inner_text().strip() if name_locator.count() else ""
                
                if not name_text:
                    continue
                
                name_hinban = extract_hinban(name_text)
                if str(name_hinban) == str(search_code):
                    target_item = item
                    break
            
            if target_item is None:
                log("  Exact match not found")
                skipped += 1
                continue
            
            target_item.click()
            time.sleep(WAIT_LONG)
            
            # サイズを設定
            if set_size_for_product(page, product_name):
                processed += 1
            else:
                skipped += 1
            
            # 一覧に戻る
            page.goto(OPENED_URL)
            time.sleep(WAIT_MEDIUM)
        
        log(f"\n✅ Size setting complete. processed={processed}, skipped={skipped}")
        return processed, skipped
        
    except Exception as exc:
        log(f"Error in set_sizes_for_uploaded_products: {exc}")
        return processed, skipped


def main(csv_path: str) -> Dict[str, object]:
    result = {
        "csv_path": csv_path,
        "rows": 0,
        "private_processed": 0,
        "private_skipped": 0,
        "upload_success": False,
        "size_processed": 0,
        "size_skipped": 0,
    }
    if not csv_path:
        log("CSV path is empty.")
        return result

    if not os.path.exists(csv_path):
        log(f"CSV not found: {csv_path}")
        return result

    load_dotenv(ENV_PATH)

    df = read_csv_file(csv_path)
    if df.empty:
        log("CSV has no rows.")
        return result

    log(f"Loaded CSV rows: {len(df)}")
    result["rows"] = len(df)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=HEADLESS,
            channel=PLAYWRIGHT_CHANNEL,
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.pages[0]
        page.set_default_timeout(PAGE_TIMEOUT)

        if not ensure_logged_in(page):
            context.close()
            return result

        processed = 0
        skipped = 0

        for _, row in df.iterrows():
            search_code = get_search_code(row)
            if not search_code:
                skipped += 1
                continue

            if open_product_and_set_private(page, search_code):
                processed += 1
            else:
                skipped += 1

        log(f"Private set complete. processed={processed}, skipped={skipped}")
        result["private_processed"] = processed
        result["private_skipped"] = skipped

        upload_success = upload_csv(page, csv_path)
        result["upload_success"] = upload_success
        
        if upload_success:
            log("✅ All operations completed successfully")
            
            # 登録完了後、サイズを設定
            size_processed, size_skipped = set_sizes_for_uploaded_products(page, df)
            result["size_processed"] = size_processed
            result["size_skipped"] = size_skipped
        else:
            log("⚠️ Upload operation failed or incomplete")
        
        context.close()
    return result


if __name__ == "__main__":
    import sys

    csv_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    main(csv_arg)
