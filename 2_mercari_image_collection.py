from playwright.sync_api import sync_playwright
from urllib.parse import urlparse
import os, time, requests, json, glob, csv, re, shutil

# === 設定 =========================
# SHOP_URL はもう使いません（個別商品ページにアクセスします。）
IMAGE_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images"
BROKEN_IMAGE_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images\破損"
# product_data_*.csv を探すディレクトリ
DATA_DIR = r"C:\Users\progr\Desktop\Python\mercari_dorekai\downloads"
PRODUCT_DATA_GLOB = os.path.join(DATA_DIR, "product_data_*.csv")
SCROLL_TIMES = 10  # 下までスクロール回数（商品ページ内の画像取得のため）
WAIT_BETWEEN_IMAGES = 0.3  # 秒
# =================================

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(BROKEN_IMAGE_DIR, exist_ok=True)

# 在庫なし用フォルダ（画像を移動する先）
NO_STOCK_DIR = os.path.join(IMAGE_DIR, '在庫なし')
os.makedirs(NO_STOCK_DIR, exist_ok=True)

# 履歴ファイル（削除処理済みの識別子を記録）
PROCESSED_DELETIONS_FILE = os.path.join(os.path.dirname(__file__), 'processed_deleted_images.txt')

def load_processed_deleted_ids():
    ids = set()
    try:
        with open(PROCESSED_DELETIONS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                v = line.strip()
                if v:
                    ids.add(v)
    except FileNotFoundError:
        pass
    return ids

def append_processed_deleted_ids(ids):
    try:
        with open(PROCESSED_DELETIONS_FILE, 'a', encoding='utf-8') as f:
            for v in ids:
                if v:
                    f.write(v + '\n')
    except Exception as e:
        print(f"⚠️ 履歴ファイルへの書き込みに失敗しました: {e}")

def check_broken_images():
    """破損フォルダから品番を抽出し、既存画像を削除"""
    broken_product_ids = set()
    
    if not os.path.exists(BROKEN_IMAGE_DIR):
        print(f"⚠️ 破損フォルダが見つかりません: {BROKEN_IMAGE_DIR}")
        return broken_product_ids
    
    try:
        files = os.listdir(BROKEN_IMAGE_DIR)
        if not files:
            print(f"✅ 破損フォルダは空です")
            return broken_product_ids
        
        print(f"\n🔍 破損フォルダをチェック中: {len(files)} ファイル")
        
        for filename in files:
            # ファイル名から品番を抽出（product_id-*.jpg 形式を想定）
            match = re.match(r'^(.*?)-', filename)
            if match:
                product_id = match.group(1)
                broken_product_ids.add(product_id)
        
        if broken_product_ids:
            print(f"🔧 破損画像検出: {len(broken_product_ids)} 品番")
            
            # 既存画像を削除
            for product_id in broken_product_ids:
                print(f"\n  🗑️ 品番 {product_id} の既存画像を削除中...")
                deleted_count = delete_product_images(product_id)
                if deleted_count > 0:
                    print(f"    削除完了: {deleted_count} ファイル")
        
        return broken_product_ids
        
    except Exception as e:
        print(f"❌ 破損フォルダチェックエラー: {e}")
        return broken_product_ids

def cleanup_broken_folder(product_id):
    """再取得成功後、破損フォルダの該当画像を削除"""
    try:
        deleted_count = 0
        for filename in os.listdir(BROKEN_IMAGE_DIR):
            if filename.startswith(f"{product_id}-"):
                file_path = os.path.join(BROKEN_IMAGE_DIR, filename)
                try:
                    os.remove(file_path)
                    print(f"  🧹 破損フォルダから削除: {filename}")
                    deleted_count += 1
                except Exception as e:
                    print(f"  ⚠️ 削除失敗: {filename} - {e}")
        return deleted_count
    except Exception as e:
        print(f"  ⚠️ 破損フォルダクリーンアップエラー: {e}")
        return 0

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
    CSV から product_id を読み、商品ステータス列が '1' または '2' の行を返す。
    - ステータス '2': ダウンロード対象のID
    - ステータス '1': 画像削除対象のID
    - ヘッダ名をログ出力して検出状況を確認
    - ステータス値は全角数字や小数表記等を正規化して判定
    - 複数エンコーディングを試行
    - 商品名と商品説明の最初の数字が一致する場合のみ、その数字も返す
    戻り値: (status_2_data, status_1_ids) のタプル
              status_2_data は (product_id, matched_number) のタプルのリスト
    """
    product_data_status_2 = []  # (product_id, matched_number) のリスト
    product_ids_status_1 = []
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

                def guess_name_field(fns):
                    for fn in fns:
                        if re.search(r'商品名|product.*name|product_name|^name$|^商品$', fn or '', re.I):
                            return fn
                    return None

                def guess_description_field(fns):
                    for fn in fns:
                        if re.search(r'商品説明|product.*description|description|説明', fn or '', re.I):
                            return fn
                    return None

                def guess_sku1_field(fns):
                    # SKU1 や在庫数を表す列名を優先的に探す
                    patterns = [r'SKU1_現在の在庫数', r'SKU1', r'sku1', r'SKU1在庫', r'SKU1.*在庫', r'SKU.*在庫', r'現在の在庫数', r'在庫数', r'在庫']
                    for pat in patterns:
                        for fn in fns:
                            if re.search(pat, fn or '', re.I):
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
                        if m:
                            status_num = int(m.group(1))
                            if status_num == 2:
                                product_data_status_2.append((pid, None))
                            elif status_num == 1:
                                product_ids_status_1.append((pid, None))

                else:
                    id_field = guess_id_field(fieldnames)
                    status_field = guess_status_field(fieldnames)
                    name_field = guess_name_field(fieldnames)
                    desc_field = guess_description_field(fieldnames)

                    print(f"[debug] guessed id_field={id_field}, status_field={status_field}, name_field={name_field}, desc_field={desc_field}")

                    if not id_field:
                        id_field = fieldnames[0]

                    if not status_field:
                        print("CSV にステータス列が見つかりませんでした。処理対象なしとします。")
                        return ([], [])

                    sku1_field = guess_sku1_field(fieldnames)

                    for row in reader:
                        pid = (row.get(id_field) or "").strip()
                        if not pid:
                            continue

                        raw_status = row.get(status_field)
                        status_val = normalize_digits(raw_status)
                        key = status_val or "(empty)"
                        status_counts[key] = status_counts.get(key, 0) + 1

                        # ステータス数値を取り出す（無ければ None）
                        status_num = None
                        m = re.search(r'(\d+)', status_val)
                        if m:
                            try:
                                status_num = int(m.group(1))
                            except Exception:
                                status_num = None

                        # SKU1 の在庫数を確認（見つからなければ None と扱う）
                        stock_num = None
                        if sku1_field:
                            raw_stock = row.get(sku1_field)
                            stock_val = normalize_digits(raw_stock)
                            sm = re.search(r'(\d+)', stock_val)
                            if sm:
                                try:
                                    stock_num = int(sm.group(1))
                                except Exception:
                                    stock_num = None

                        # 判定: ステータスが2かつ SKU1 在庫が 0 でない場合のみダウンロード対象
                        is_active = (status_num == 2)
                        is_sold_or_deleted = (not is_active) or (stock_num == 0)

                        matched_number = None
                        if name_field and desc_field:
                            product_name = (row.get(name_field) or "").strip()
                            product_desc = (row.get(desc_field) or "").strip()
                            name_match = re.search(r'^(\d+)', product_name)
                            desc_match = re.search(r'^(\d+)', product_desc)
                            if name_match and desc_match:
                                name_number = name_match.group(1)
                                desc_number = desc_match.group(1)
                                if name_number == desc_number:
                                    matched_number = name_number
                                    print(f"  ✓ 品番一致: {pid} -> {matched_number}")

                        if is_sold_or_deleted:
                            product_ids_status_1.append((pid, matched_number))
                            continue

                        # ここまで来たらステータス2かつ在庫が存在する（ダウンロード対象）
                        product_data_status_2.append((pid, matched_number))

                print(f"[debug] encoding={enc} status_counts (sample up to 20 keys) = {dict(list(status_counts.items())[:20])}")
                print(f"CSV 読み込み成功: encoding={enc}, ステータス2={len(product_data_status_2)}, ステータス1={len(product_ids_status_1)}")
                # 重複を削除（最初の出現を保持）
                seen_ids = set()
                unique_status_2 = []
                for pid, num in product_data_status_2:
                    if pid not in seen_ids:
                        seen_ids.add(pid)
                        unique_status_2.append((pid, num))

                seen_ids_1 = set()
                unique_status_1 = []
                for pid, num in product_ids_status_1:
                    if pid not in seen_ids_1:
                        seen_ids_1.add(pid)
                        unique_status_1.append((pid, num))

                return (unique_status_2, unique_status_1)

        except Exception as e:
            last_exc = e
            continue

    print(f"CSV 読み込みエラー: {last_exc}")
    return ([], [])

def get_downloaded_product_ids():
    """IMAGE_DIR 内のファイル名からダウンロード済みの product_id または matched_number のセットを返す"""
    downloaded_ids = set()
    try:
        for filename in os.listdir(IMAGE_DIR):
            # ファイル名が "number-*" の形式であると仮定
            match = re.match(r'^(.*?)-', filename)
            if match:
                downloaded_ids.add(match.group(1))
    except FileNotFoundError:
        print(f"Warning: Image directory not found: {IMAGE_DIR}")
    return downloaded_ids

def delete_product_images(identifier):
    """指定されたidentifier（product_idまたはmatched_number）の画像を全て削除する"""
    deleted_count = 0
    try:
        for filename in os.listdir(IMAGE_DIR):
            # ファイル名が "identifier-*" の形式であるか確認
            if filename.startswith(f"{identifier}-"):
                file_path = os.path.join(IMAGE_DIR, filename)
                try:
                    os.remove(file_path)
                    print(f"  🗑️ 削除: {filename}")
                    deleted_count += 1
                except Exception as e:
                    print(f"  ❌ 削除失敗: {filename} - {e}")
    except FileNotFoundError:
        pass
    return deleted_count

def move_product_images(identifier):
    """指定されたidentifier（product_idまたはmatched_number）の画像を在庫なしフォルダへ移動する"""
    moved_count = 0
    try:
        for filename in os.listdir(IMAGE_DIR):
            if filename.startswith(f"{identifier}-"):
                src = os.path.join(IMAGE_DIR, filename)
                dst = os.path.join(NO_STOCK_DIR, filename)
                try:
                    shutil.move(src, dst)
                    print(f"  📦 移動: {filename} -> 在庫なしフォルダ")
                    moved_count += 1
                except Exception as e:
                    print(f"  ❌ 移動失敗: {filename} - {e}")
    except FileNotFoundError:
        pass
    return moved_count

def process_product_pages(product_data, downloaded_ids, is_broken_retry=False):
    """
    product_data: (product_id, matched_number) のタプルのリスト
                  matched_number が None の場合は処理をスキップ
    """
    if not product_data:
        print("処理対象のデータがありません。")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for product_id, matched_number in product_data:
            if not product_id:
                continue
            
            # matched_number が None の場合はスキップ（商品名と商品説明の数字が一致しない）
            if matched_number is None and not is_broken_retry:
                print(f"\n▶ {product_id} は品番不一致のためスキップします。")
                continue
            
            # ファイル名に使用する識別子を決定
            file_identifier = matched_number if matched_number else product_id
            
            # 破損画像の再取得でない場合はスキップチェック
            if not is_broken_retry and file_identifier in downloaded_ids:
                print(f"\n▶ {file_identifier} は既に画像保存済みのためスキップします。")
                continue

            product_url = f"https://jp.mercari.com/shops/product/{product_id}"
            print(f"\n▶ {product_id} (保存名: {file_identifier}) を処理中... ({product_url})")

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
                    download_success = False
                    for i, img_element in enumerate(img_elements):
                        img_url = img_element.get_attribute('src')
                        if img_url:
                            # 拡張子は .jpg 固定にせず元URLから取得する
                            fname = safe_filename(img_url)
                            # URLに'@'が含まれる場合を考慮して、'@'以降を削除してから拡張子を取得
                            fname_main = fname.split('@')[0]
                            ext = os.path.splitext(fname_main)[1] or ".jpg"
                            # file_identifierを使用してファイル名を作成
                            file_name = f"{file_identifier}-{i+1}{ext}"
                            file_path = os.path.join(IMAGE_DIR, file_name)
                            download_image(img_url, file_path)
                            download_success = True
                        else:
                            print("  ❌ 画像URLの取得に失敗しました。")
                    
                    # 破損画像の再取得で成功した場合、破損フォルダをクリーンアップ
                    if is_broken_retry and download_success:
                        cleanup_broken_folder(file_identifier)
                        
                detail_page.close()
            except Exception as e:
                print(f"  ❌ ページ処理失敗 ({product_id}): {e}")

        browser.close()

def main():
    # 1. 破損フォルダをチェック（優先処理）
    broken_product_ids = check_broken_images()
    
    # 2. CSVを読み込み
    latest_csv = find_latest_product_csv()
    if not latest_csv:
        print(f"product_data_*.csv が見つかりません。検索パターン: {PRODUCT_DATA_GLOB}")
        return
    print(f"最新の CSV: {latest_csv}")
    product_data_status_2, product_ids_status_1 = read_product_ids_from_csv(latest_csv)
    print(f"CSV から取得した処理対象 (ステータス2): {len(product_data_status_2)} 件")
    print(f"CSV から取得した削除対象 (ステータス1): {len(product_ids_status_1)} 件")
    
    # 品番一致した件数をカウント
    matched_count = sum(1 for _, num in product_data_status_2 if num is not None)
    print(f"  うち品番一致: {matched_count} 件")
    
    # 3. 破損画像の再取得（優先）
    if broken_product_ids:
        print(f"\n🔧 破損画像の再取得を優先的に実行: {len(broken_product_ids)} 品番")
        # 破損画像の再取得は product_id をそのまま使用
        broken_data = [(pid, None) for pid in broken_product_ids]
        process_product_pages(broken_data, set(), is_broken_retry=True)
    
    # 4. ステータス1の商品画像を削除（履歴参照して2度削除しない）
    if product_ids_status_1:
        print("\n▶ ステータス1の商品画像を削除中... (履歴を参照します)")
        total_deleted = 0
        processed_deleted = load_processed_deleted_ids()
        print(f"  履歴登録済み識別子: {len(processed_deleted)} 件")
        for product_id, matched_number in product_ids_status_1:
            if not product_id:
                continue

            # 履歴に登録済みならスキップ
            if product_id in processed_deleted or (matched_number and matched_number in processed_deleted):
                print(f"\n▶ {product_id} は履歴によりスキップします。")
                continue

            print(f"\n▶ {product_id} の画像を在庫なしフォルダへ移動中...")
            deleted_cnt = 0
            d1 = move_product_images(product_id)
            deleted_cnt += d1
            # matched_number がある場合はそれも移動を試みる
            d2 = 0
            if matched_number:
                d2 = move_product_images(matched_number)
                deleted_cnt += d2

            if deleted_cnt > 0:
                print(f"  ✅ {deleted_cnt}枚の画像を削除しました")
            else:
                print(f"  ℹ️ 削除対象の画像はありませんでした")

            total_deleted += deleted_cnt

            # 履歴に追記（削除が無くても処理済みとして記録して次回はスキップする）
            ids_to_append = [product_id]
            if matched_number:
                ids_to_append.append(matched_number)
            append_processed_deleted_ids(ids_to_append)
            processed_deleted.update(ids_to_append)

        print(f"\n✅ 合計 {total_deleted}枚の画像を削除しました\n")
    
    # 5. ステータス2の商品画像をダウンロード
    downloaded_ids = get_downloaded_product_ids()
    print(f"ダウンロード済みのファイル識別子数: {len(downloaded_ids)}")
    process_product_pages(product_data_status_2, downloaded_ids, is_broken_retry=False)
    print("\n✅ 処理完了")

if __name__ == "__main__":
    main()
