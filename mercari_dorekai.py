from playwright.sync_api import sync_playwright
from urllib.parse import urlparse
import os, time, requests, json, glob, csv, re

# === 設定 =========================
# SHOP_URL はもう使いません（個別商品ページにアクセスします。）
IMAGE_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images"
# product_data_*.csv を探すディレクトリ
DATA_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\downloads"
PRODUCT_DATA_GLOB = os.path.join(DATA_DIR, "product_data_*.csv")
SCROLL_TIMES = 10  # 下までスクロール回数（商品ページ内の画像取得のため）
WAIT_BETWEEN_IMAGES = 0.3  # 秒
# =================================

os.makedirs(IMAGE_DIR, exist_ok=True)

def get_extension_from_content_type(content_type):
    """Content-Type 文字列から拡張子を推測する"""
    mapping = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
    return mapping.get(content_type.split(";")[0].strip().lower(), ".jpg")

def safe_filename(url):
    return os.path.basename(urlparse(url).path)

def download_image(url, path):
    if os.path.exists(path):
        print(f"  ⏩ 既に保存済み: {path}")
        return
    try:
        # まず HEAD で Content-Type を確認（トラッカーや非画像を除外）
        try:
            head = requests.head(url, allow_redirects=True, timeout=5)
        except Exception:
            head = None

        if head:
            if head.status_code != 200:
                print(f"  ❌ ダウンロードスキップ: HEAD returned {head.status_code} - {url}")
                return
            ctype = head.headers.get("Content-Type", "")
            if not ctype.startswith("image/"):
                print(f"  ⏩ 非画像コンテンツのためスキップ: {ctype} - {url}")
                return
            # 拡張子がなければ Content-Type から決定
            if not os.path.splitext(path)[1]:
                ext = get_extension_from_content_type(ctype)
                path = path + ext if not path.endswith(ext) else path

        # 実ダウンロード（GET）
        r = requests.get(url, stream=True, timeout=15)
        if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/"):
            # 拡張子がまだ付いていなければ Content-Type から再決定
            if not os.path.splitext(path)[1]:
                ctype = r.headers.get("Content-Type", "")
                ext = get_extension_from_content_type(ctype)
                path += ext
            with open(path, "wb") as f:
                for chunk in r.iter_content(1024):
                    if chunk:
                        f.write(chunk)
            print(f"  ✅ 保存完了: {path}")
            time.sleep(WAIT_BETWEEN_IMAGES)
        else:
            status = r.status_code if r is not None else "N/A"
            ctype = r.headers.get("Content-Type", "") if r is not None else ""
            print(f"  ❌ ダウンロード失敗: HTTP {status} / {ctype} - {url}")
    except Exception as e:
        print(f"  ❌ ダウンロード失敗: {e} - {url}")

def find_latest_product_csv():
    files = glob.glob(PRODUCT_DATA_GLOB)
    if not files:
        return None
    latest = max(files, key=os.path.getmtime)
    return latest

def read_product_ids_from_csv(csv_path):
    """
    CSV から product_id を読み、商品ステータス列が '2' の行のみ返す。
    - ヘッダ名をログ出力して検出状況を確認
    - ステータス値は全角数字や小数表記等を正規化して判定
    - 複数エンコーディングを試行
    """
    product_ids = []
    encodings_to_try = ['utf-8-sig', 'utf-8', 'cp932', 'shift_jis', 'euc_jp', 'iso2022_jp', 'latin-1']
    last_exc = None

    def normalize_digits(s):
        if s is None:
            return ""
        s = str(s).strip().strip('"').strip("'")
        trans = str.maketrans('０１２３４５６７８９', '0123456789')
        return s.translate(trans)

    for enc in encodings_to_try:
        try:
            with open(csv_path, newline='', encoding=enc) as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames

                print(f"[debug] try encoding={enc}, detected fieldnames={fieldnames}")

                def guess_id_field(fns):
                    for fn in fns:
                        if re.search(r'product.*id|product_id|商品.*id|商品id|^id$', fn or '', re.I):
                            return fn
                    for fn in fns:
                        if re.search(r'\bid\b', fn or '', re.I):
                            return fn
                    return fns[0] if fns else None

                # ここを修正：まず「商品ステータス」を優先で探す（以前は「状態」を先に取ってしまっていた）
                def guess_status_field(fns):
                    for fn in fns:
                        if re.search(r'商品ステータス|product.*status|product_status|^status$', fn or '', re.I):
                            return fn
                    for fn in fns:
                        if re.search(r'商品.*ステータス|ステータス|status', fn or '', re.I):
                            return fn
                    for fn in fns:
                        if re.search(r'状態', fn or '', re.I):
                            return fn
                    return None

                status_counts = {}

                if not fieldnames:
                    f.seek(0)
                    rows = [r for r in csv.reader(f) if any(cell.strip() for cell in r)]
                    if not rows:
                        product_ids = []
                        break
                    header = rows[0]
                    data_rows = rows[1:]
                    id_idx = None
                    status_idx = None
                    for i, hn in enumerate(header):
                        if re.search(r'product.*id|product_id|商品.*id|商品id|^id$', hn or '', re.I):
                            id_idx = i
                            break
                    if id_idx is None:
                        for i, hn in enumerate(header):
                            if re.search(r'\bid\b', hn or '', re.I):
                                id_idx = i
                                break
                    if id_idx is None:
                        id_idx = 0

                    for i, hn in enumerate(header):
                        if re.search(r'商品ステータス|product.*status|status|状態', hn or '', re.I):
                            status_idx = i
                            break

                    for row in data_rows:
                        if len(row) <= id_idx:
                            continue
                        pid = row[id_idx].strip()
                        if not pid:
                            continue
                        status_val = None
                        if status_idx is not None and len(row) > status_idx:
                            status_val = normalize_digits(row[status_idx])
                        key = status_val or "(empty)"
                        status_counts[key] = status_counts.get(key, 0) + 1
                        m = re.search(r'(\d+)', status_val or "")
                        if m and int(m.group(1)) == 2:
                            product_ids.append(pid)

                else:
                    id_field = guess_id_field(fieldnames)
                    status_field = guess_status_field(fieldnames)

                    print(f"[debug] guessed id_field={id_field}, status_field={status_field}")

                    if not id_field:
                        id_field = fieldnames[0]

                    if not status_field:
                        print("CSV にステータス列が見つかりませんでした。処理対象なしとします。")
                        return []

                    for row in reader:
                        pid = (row.get(id_field) or "").strip()
                        if not pid:
                            continue
                        raw_status = row.get(status_field)
                        status_val = normalize_digits(raw_status)
                        key = status_val or "(empty)"
                        status_counts[key] = status_counts.get(key, 0) + 1
                        m = re.search(r'(\d+)', status_val)
                        if m:
                            try:
                                if int(m.group(1)) == 2:
                                    product_ids.append(pid)
                            except Exception:
                                pass

                print(f"[debug] encoding={enc} status_counts (sample up to 20 keys) = {dict(list(status_counts.items())[:20])}")
                if product_ids:
                    print(f"CSV 読み込み成功: encoding={enc}, 対象 product_id 数={len(product_ids)}")
                else:
                    print(f"CSV 読み込み: encoding={enc} で成功したが対象 product_id は見つかりませんでした")
                return list(dict.fromkeys(product_ids))

        except Exception as e:
            last_exc = e
            continue

    print(f"CSV 読み込みエラー: {last_exc}")
    return []

def get_downloaded_product_ids():
    """IMAGE_DIR 内のファイル名からダウンロード済みの product_id のセットを返す"""
    downloaded_ids = set()
    try:
        for filename in os.listdir(IMAGE_DIR):
            # ファイル名が "product_id-*" の形式であると仮定
            match = re.match(r'^(.*?)-', filename)
            if match:
                downloaded_ids.add(match.group(1))
    except FileNotFoundError:
        print(f"Warning: Image directory not found: {IMAGE_DIR}")
    return downloaded_ids

def process_product_pages(product_ids, downloaded_ids):
    if not product_ids:
        print("処理対象の product_id がありません。")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for product_id in product_ids:
            if not product_id:
                continue
            if product_id in downloaded_ids:
                print(f"\n▶ {product_id} は既に画像保存済みのためスキップします。")
                continue

            product_url = f"https://jp.mercari.com/shops/product/{product_id}"
            print(f"\n▶ {product_id} を処理中... ({product_url})")

            try:
                detail_page = browser.new_page()
                detail_page.goto(product_url, timeout=60000)
                # 必要ならスクロール（画像が遅延読み込みされる場合に備え）
                prev_height = 0
                for _ in range(SCROLL_TIMES):
                    detail_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    detail_page.wait_for_timeout(1000)
                    height = detail_page.evaluate("document.body.scrollHeight")
                    if height == prev_height:
                        break
                    prev_height = height

                # 画像URL抽出
                img_elements = detail_page.query_selector_all('div[data-testid="carousel-item"] picture img')
                if not img_elements:
                    # 別セレクタの可能性にも対応
                    img_elements = detail_page.query_selector_all('img')
                if not img_elements:
                    print("  ⚠️ 画像が見つかりませんでした。")
                else:
                    print(f"  🖼️ {len(img_elements)}枚の画像が見つかりました。")
                    for i, img_element in enumerate(img_elements):
                        img_url = img_element.get_attribute('src')
                        if img_url:
                            # 拡張子は .jpg 固定にせず元URLから取得する
                            fname = safe_filename(img_url)
                            # URLに'@'が含まれる場合を考慮して、'@'以降を削除してから拡張子を取得
                            fname_main = fname.split('@')[0]
                            ext = os.path.splitext(fname_main)[1] or ".jpg"
                            file_name = f"{product_id}-{i+1}{ext}"
                            file_path = os.path.join(IMAGE_DIR, file_name)
                            download_image(img_url, file_path)
                        else:
                            print("  ❌ 画像URLの取得に失敗しました。")
                detail_page.close()
            except Exception as e:
                print(f"  ❌ ページ処理失敗 ({product_id}): {e}")

        browser.close()

def main():
    latest_csv = find_latest_product_csv()
    if not latest_csv:
        print(f"product_data_*.csv が見つかりません。検索パターン: {PRODUCT_DATA_GLOB}")
        return
    print(f"最新の CSV: {latest_csv}")
    product_ids = read_product_ids_from_csv(latest_csv)
    print(f"CSV から取得した処理対象の product_id 数: {len(product_ids)}")
    downloaded_ids = get_downloaded_product_ids()
    print(f"ダウンロード済みの product_id 数: {len(downloaded_ids)}")
    process_product_pages(product_ids, downloaded_ids)
    print("\n✅ 処理完了")

if __name__ == "__main__":
    main()
