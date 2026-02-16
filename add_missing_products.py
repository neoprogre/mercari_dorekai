"""
CSVファイルを比較して、ベースファイルに無い商品をソースファイルから追加するスクリプト
"""
import pandas as pd
import os
import glob
import re
from datetime import datetime

# ファイルパターン
BASE_FILE_PATTERN = r"C:\Users\progr\Desktop\Python\mercari_dorekai\downloads\dorekai-base-shop-*.csv"
SOURCE_FILE_PATTERN = r"C:\Users\progr\Desktop\Python\mercari_dorekai\downloads\product_data_*.csv"
IMAGE_BASE_PATH = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images"

def extract_number_from_text(text):
    """テキストから最初の数字を抽出（先頭の0を除く）"""
    if pd.isna(text):
        return ""
    text = str(text)
    # 最初の数字パターンを検索
    match = re.search(r'\d+', text)
    if match:
        # 先頭の0を除去
        return str(int(match.group()))
    return ""

def find_product_images(product_code, max_images=20):
    """商品コードに基づいて画像ファイルを検索"""
    images = []
    if not product_code or product_code == "":
        return images
    
    for i in range(1, max_images + 1):
        image_path = os.path.join(IMAGE_BASE_PATH, f"{product_code}-{i}.jpg")
        if os.path.exists(image_path):
            images.append(image_path)
        else:
            # 連続していない可能性もあるが、効率のため最初の欠番で終了
            break
    return images

def get_latest_file(pattern):
    """指定されたパターンに一致する最新のファイルを取得"""
    files = glob.glob(pattern)
    if not files:
        return None
    # 最新のファイルを取得（変更日時でソート）
    latest_file = max(files, key=os.path.getmtime)
    return latest_file

def main():
    print("=" * 80)
    print("商品追加スクリプト開始")
    print("=" * 80)
    
    # 最新のファイルを取得
    print("\n[*] 最新のファイルを検索中...")
    BASE_FILE = get_latest_file(BASE_FILE_PATTERN)
    SOURCE_FILE = get_latest_file(SOURCE_FILE_PATTERN)
    
    # ファイルの存在確認
    if not BASE_FILE:
        print(f"[X] ベースファイルが見つかりません: {BASE_FILE_PATTERN}")
        return
    
    if not SOURCE_FILE:
        print(f"[X] ソースファイルが見つかりません: {SOURCE_FILE_PATTERN}")
        return
    
    print(f"\n[+] ベースファイル: {os.path.basename(BASE_FILE)}")
    print(f"    パス: {BASE_FILE}")
    print(f"[+] ソースファイル: {os.path.basename(SOURCE_FILE)}")
    print(f"    パス: {SOURCE_FILE}")
    
    try:
        # CSVファイルを読み込み (Shift-JIS エンコーディング)
        print("\n[*] ベースファイルを読み込み中...")
        base_df = pd.read_csv(BASE_FILE, encoding='shift-jis', low_memory=False)
        print(f"    [OK] {len(base_df)} 件の商品を読み込みました")
        
        print("\n[*] ソースファイルを読み込み中...")
        source_df = pd.read_csv(SOURCE_FILE, encoding='shift-jis', low_memory=False)
        print(f"    [OK] {len(source_df)} 件の商品を読み込みました")
        
        # カラム名を表示
        print(f"\n[*] ベースファイルのカラム: {list(base_df.columns[:5])}...")
        print(f"[*] ソースファイルのカラム: {list(source_df.columns[:10])}...")
        
        # 商品IDカラムを特定
        base_id_col = base_df.columns[0]  # 最初のカラムを商品IDとして使用
        source_id_col = source_df.columns[0]
        
        print(f"\n[*] 比較キー:")
        print(f"    ベース: {base_id_col}")
        print(f"    ソース: {source_id_col}")
        
        # ベースファイルの商品IDセット
        base_ids = set(base_df[base_id_col].dropna().astype(str))
        print(f"\n[*] ベースファイルのユニーク商品ID数: {len(base_ids)}")
        
        # ソースファイルの商品IDセット
        source_ids = set(source_df[source_id_col].dropna().astype(str))
        print(f"[*] ソースファイルのユニーク商品ID数: {len(source_ids)}")
        
        # ベースに無い商品IDを特定
        missing_ids = source_ids - base_ids
        print(f"\n[*] ベースファイルに無い商品: {len(missing_ids)} 件")
        
        if len(missing_ids) == 0:
            print("\n[OK] すべての商品が既にベースファイルに存在します。")
            return
        
        # 無い商品のデータを抽出
        missing_products = source_df[source_df[source_id_col].astype(str).isin(missing_ids)].copy()
        
        # フィルタリング条件を適用
        print(f"\n[*] フィルタリング前: {len(missing_products)} 件")
        
        # 商品ステータスが1の場合は除外
        if '商品ステータス' in missing_products.columns:
            before_count = len(missing_products)
            missing_products = missing_products[missing_products['商品ステータス'] != 1]
            filtered_count = before_count - len(missing_products)
            if filtered_count > 0:
                print(f"    [*] 商品ステータス=1 の商品を除外: {filtered_count} 件")
        
        # SKU1_現在の在庫数が0の場合は除外
        if 'SKU1_現在の在庫数' in missing_products.columns:
            before_count = len(missing_products)
            missing_products = missing_products[missing_products['SKU1_現在の在庫数'] != 0]
            filtered_count = before_count - len(missing_products)
            if filtered_count > 0:
                print(f"    [*] SKU1_現在の在庫数=0 の商品を除外: {filtered_count} 件")
        
        # ベースファイルの既存商品コードをチェック（商品IDが存在する行のみ）
        product_code_col = None
        for col in ['商品コード', '品番ID']:
            if col in base_df.columns:
                product_code_col = col
                break
        
        if product_code_col and product_code_col in base_df.columns:
            # 商品ID列が空でない（既存商品）の商品コードを取得
            existing_base_products = base_df[base_df[base_id_col].notna() & (base_df[base_id_col].astype(str).str.strip() != '')]
            existing_product_codes = set(existing_base_products[product_code_col].dropna().astype(str).str.strip())
            existing_product_codes.discard('')  # 空文字を除外
            
            if len(existing_product_codes) > 0:
                print(f"    [*] ベースファイルの既存商品コード数: {len(existing_product_codes)} 件")
                
                # 追加予定商品から商品名を使って商品コードを抽出し、重複チェック
                before_count = len(missing_products)
                duplicate_mask = []
                
                for idx, row in missing_products.iterrows():
                    product_name = str(row.get('商品名', ''))
                    extracted_code = extract_number_from_text(product_name)
                    
                    # 商品コードが既存商品と重複しているかチェック
                    is_duplicate = extracted_code in existing_product_codes if extracted_code else False
                    duplicate_mask.append(not is_duplicate)  # 重複していないものをTrue
                
                missing_products = missing_products[duplicate_mask]
                filtered_count = before_count - len(missing_products)
                if filtered_count > 0:
                    print(f"    [*] 商品コード重複の商品を除外: {filtered_count} 件")
        
        print(f"[*] フィルタリング後: {len(missing_products)} 件")
        
        if len(missing_products) == 0:
            print("\n[OK] フィルタリング後、追加する商品がありません。")
            return
        
        print(f"\n[*] 追加する商品の最初の5件:")
        for idx, row in missing_products.head().iterrows():
            product_id = row[source_id_col]
            # 商品名を取得（商品名カラムが存在する場合）
            product_name = ""
            if '商品名' in row:
                product_name = row['商品名']
            elif len(row) > 1:
                product_name = str(row[1])[:50]  # 2番目のカラムの最初の50文字
            print(f"   - {product_id}: {product_name}")
        
        # 商品を追加（データ変換処理）
        print(f"\n[*] {len(missing_products)} 件の商品をベースファイルに追加します...")
        print("[*] 商品データを変換中...")
        
        # デバッグ: 最初の商品で画像パス確認
        first_row = missing_products.iloc[0]
        first_name = str(first_row.get('商品名', ''))
        first_code = extract_number_from_text(first_name)
        print(f"\n[DEBUG] 最初の商品:")
        print(f"  商品名: {first_name[:50]}...")
        print(f"  抽出した商品コード: {first_code}")
        if first_code:
            test_path = os.path.join(IMAGE_BASE_PATH, f"{first_code}-1.jpg")
            print(f"  画像1パス: {test_path}")
            print(f"  画像1存在: {os.path.exists(test_path)}")
        
        # ベースファイルのフォーマットに合わせて変換
        converted_products = []
        
        for idx, row in missing_products.iterrows():
            new_row = {}
            
            # 先に商品コードを計算
            product_name = str(row.get('商品名', ''))
            product_desc = str(row.get('商品説明', ''))
            name_number = extract_number_from_text(product_name)
            desc_number = extract_number_from_text(product_desc)
            
            if name_number and name_number == desc_number:
                product_code = name_number
            elif name_number:
                product_code = name_number
            else:
                product_code = ""
            
            # ベースファイルの各カラムに対応
            for col in base_df.columns:
                if col == base_id_col or col == '商品ID':
                    # 商品IDは空白
                    new_row[col] = ""
                elif col == '商品名':
                    # 商品名はそのまま
                    new_row[col] = row.get('商品名', '')
                elif col in ['商品説明', '説明']:
                    # 説明は「商品説明」カラムから取得
                    new_row[col] = row.get('商品説明', '')
                elif col in ['価格', '販売価格']:
                    # 価格は「販売価格」カラムから取得
                    new_row[col] = row.get('販売価格', '')
                elif col == '税率':
                    new_row[col] = 1
                elif col == '公開状態':
                    new_row[col] = 1
                elif col == '表示順':
                    new_row[col] = 1
                elif col in ['在庫数', '在庫']:
                    # 在庫数はSKU1_現在の在庫数
                    new_row[col] = row.get('SKU1_現在の在庫数', '')
                elif col in ['商品コード', '品番ID']:
                    # 事前に計算した商品コードを使用
                    new_row[col] = product_code
                elif col.startswith('画像'):
                    # 画像ファイルのパスを設定
                    # カラム名から番号を抽出（例: 画像1 -> 1）
                    img_match = re.search(r'画像(\d+)', col)
                    if img_match:
                        img_num = int(img_match.group(1))
                        # 事前に計算した商品コードを使用
                        if product_code and product_code != "":
                            # ファイル名を構築
                            image_filename = f"{product_code}-{img_num}.jpg"
                            # フルパスで存在確認
                            image_path = os.path.join(IMAGE_BASE_PATH, image_filename)
                            if os.path.exists(image_path):
                                # ファイル名のみを保存
                                new_row[col] = image_filename
                            else:
                                new_row[col] = ""
                        else:
                            new_row[col] = ""
                    else:
                        new_row[col] = ""
                else:
                    # その他のカラムは空白または元のデータを保持
                    if col in source_df.columns:
                        new_row[col] = row.get(col, '')
                    else:
                        new_row[col] = ""
            
            converted_products.append(new_row)
        
        # DataFrameに変換
        converted_df = pd.DataFrame(converted_products)
        
        print(f"    [OK] {len(converted_df)} 件の商品を変換しました")
        
        # ベースファイルと結合
        combined_df = pd.concat([base_df, converted_df], ignore_index=True)
        
        print(f"    [OK] 結合完了: {len(combined_df)} 件")
        
        # 新しいファイル名を生成
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.dirname(BASE_FILE)
        output_file = os.path.join(output_dir, f"dorekai-base-updated_{timestamp}.csv")
        
        # ファイルに保存
        print(f"\n[*] ファイルを保存中: {os.path.basename(output_file)}")
        combined_df.to_csv(output_file, index=False, encoding='shift-jis')
        
        print("\n" + "=" * 80)
        print("[OK] 処理完了!")
        print("=" * 80)
        print(f"[*] 統計:")
        print(f"    元のベースファイル: {len(base_df)} 件")
        print(f"    追加された商品: {len(converted_df)} 件")
        print(f"    新しいファイル: {len(combined_df)} 件")
        print(f"\n[*] 保存先: {output_file}")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n[ERROR] エラーが発生しました: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
