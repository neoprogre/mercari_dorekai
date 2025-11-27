
import pandas as pd
import os
import glob

# --- 設定 ---
# ネットワーク上の最新の製品データCSVが置かれているフォルダ
MERCARI_DATA_PATH = r'\\LS210DNBD82\share\平良\Python\mercari_dorekai'
# 在庫のマスターデータとなるExcelファイル
MASTER_INVENTORY_FILE = 'products.xlsx'
# 生成されるアップロード用CSVファイル
OUTPUT_UPLOAD_FILE = 'mercari_upload.csv'


def get_latest_mercari_template():
    """ネットワークフォルダから最新のproduct_data_*.csvファイルパスを取得する"""
    print(f"Searching for template CSV in: {MERCARI_DATA_PATH}")
    search_pattern = os.path.join(MERCARI_DATA_PATH, 'product_data_*.csv')
    files = glob.glob(search_pattern)
    if not files:
        raise FileNotFoundError(f"No Mercari CSV files found at: {search_pattern}")
    
    latest_file = max(files, key=os.path.getmtime)
    print(f"Found latest template file: {latest_file}")
    return latest_file

def main():
    """メイン処理"""
    try:
        # 1. 在庫マスターファイル(products.xlsx)を読み込む
        print(f"Reading master inventory file: {MASTER_INVENTORY_FILE}")
        # ここでは仮に在庫を「1」として扱います。本来はExcelに在庫数の列が必要です。
        # TODO: products.xlsxに実際の在庫数列を追加する
        master_df = pd.read_excel(MASTER_INVENTORY_FILE, sheet_name='mercari_products')
        if '品番' not in master_df.columns:
            raise ValueError("Master file 'mercari_products' sheet must contain '品番' column.")
        
        # サンプルとして、マスターファイルにある商品の在庫はすべて「1」に設定する
        master_df['在庫数'] = 1 
        stock_map = master_df.set_index('品番')['在庫数'].to_dict()
        print(f"Loaded {len(stock_map)} items from master file.")

        # 2. アップロード用のテンプレートとなる最新のCSVを読み込む
        template_file = get_latest_mercari_template()
        template_df = pd.read_csv(template_file, encoding='cp932')
        print("Template CSV loaded successfully.")

        # 3. 在庫数を更新する
        update_count = 0
        # SKU1_商品管理コードが存在するか確認
        if 'SKU1_商品管理コード' in template_df.columns and 'SKU1_現在の在庫数' in template_df.columns:
            for index, row in template_df.iterrows():
                # .ilocを使って値を取得し、NoneやNaNでないことを確認
                product_code = row.get('SKU1_商品管理コード')
                if pd.notna(product_code) and product_code in stock_map:
                    # 在庫数をマスターファイルの内容で上書き
                    template_df.at[index, 'SKU1_現在の在庫数'] = stock_map[product_code]
                    update_count += 1
            print(f"Updated stock for {update_count} items based on master file.")
        else:
            print("Warning: 'SKU1_商品管理コード' or 'SKU1_現在の在庫数' not found in template CSV.")

        # 4. アップロード用CSVファイルとして保存
        template_df.to_csv(OUTPUT_UPLOAD_FILE, encoding='cp932', index=False)
        print(f"Successfully created upload file: {OUTPUT_UPLOAD_FILE}")

    except FileNotFoundError as e:
        print(f"Error: {e}")
    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    main()
