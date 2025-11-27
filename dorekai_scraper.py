import os
import glob
import pandas as pd
import re
import time
import requests
from bs4 import BeautifulSoup

def extract_product_number(name):
    """商品名から品番（先頭の3-5桁の数字）を抽出する"""
    if not isinstance(name, str):
        return None
    match = re.match(r'^(\d{3,5})\s', name)
    return match.group(1) if match else None

def add_duplicate_column(df, subset_col='品番'):
    """データフレームに重複チェック列を追加する"""
    df['重複'] = ''
    if not df.empty and subset_col in df.columns:
        # keep=Falseは重複するすべての行をTrueにする
        duplicates = df.duplicated(subset=[subset_col], keep=False) & df[subset_col].notna()
        df.loc[duplicates, '重複'] = '重複'
    return df

def process_rakuma_data():
    """指定されたURLからラクマのデータを抽出し、ページネーションを処理して整形する"""
    print("Processing Rakuma data from web...")
    base_url = 'https://fril.jp/shop/3c65d78bc0e1eadbe2a3528b344d8311'
    page = 1
    all_products = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    while True:
        url = f"{base_url}?page={page}"
        print(f"Scraping Rakuma page: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()  # エラーがあれば例外を発生させる
        except requests.exceptions.RequestException as e:
            print(f"Error fetching Rakuma page: {e}")
            break

        soup = BeautifulSoup(response.content, 'html.parser')
        items = soup.find_all('div', class_='item', attrs={'data-test': 'item'})

        if not items:
            print(f"No more items found on page {page}. Stopping.")
            break

        for item in items:
            name_tag = item.find('span', attrs={'data-test': 'item_name'})
            price_tag = item.find('span', attrs={'data-test': 'item_price'})
            link_tag = item.find('a', class_='link_shop_image')

            name = name_tag.text.strip() if name_tag else 'N/A'
            price = price_tag['data-content'] if price_tag and 'data-content' in price_tag.attrs else 'N/A'
            # URLのドメインを補完
            item_url = link_tag['href'] if link_tag and 'href' in link_tag.attrs else 'N/A'
            
            # SOLD OUTのチェックを追加
            is_sold_out = item.find('div', class_='item-box__soldout_ribbon') is not None

            all_products.append({'商品名': name, '価格': price, 'URL': item_url, 'is_sold_out': is_sold_out})
        
        page += 1
        time.sleep(1)  # サーバーへの負荷を軽減するための待機

    if not all_products:
        print("No products found in Rakuma data.")
        return pd.DataFrame()

    df = pd.DataFrame(all_products)
    df['品番'] = df['商品名'].apply(extract_product_number)
    df = add_duplicate_column(df)
    
    df = df[['品番', '重複', '商品名', '価格', 'URL', 'is_sold_out']]
    print(f"Found {len(df)} products in Rakuma data.")
    return df

def process_mercari_data():
    """ネットワーク上の最新のMercari CSVからデータを抽出し、整形する"""
    print("Processing Mercari data...")
    try:
        mercari_path = r'\\LS210DNBD82\share\平良\Python\mercari_dorekai'
        search_pattern = os.path.join(mercari_path, 'product_data_*.csv')
        
        files = glob.glob(search_pattern)
        if not files:
            print(f"No Mercari CSV files found at: {search_pattern}")
            return pd.DataFrame()
        
        latest_file = max(files, key=os.path.getmtime)
        print(f"Processing latest Mercari file: {latest_file}")
        
        df = pd.read_csv(latest_file, encoding='cp932')
        
        df = df.rename(columns={'販売価格': '価格'})
        
        if '商品ID' in df.columns:
            df['URL'] = 'https://jp.mercari.com/shops/product/' + df['商品ID'].astype(str)
        else:
            print("Warning: '商品ID' column not found in Mercari CSV. URL will be empty.")
            df['URL'] = ''

        df['品番'] = df['商品名'].apply(extract_product_number)
        df = add_duplicate_column(df)

        # 商品ステータス列を追加（存在しない場合）
        if '商品ステータス' not in df.columns:
            df['商品ステータス'] = '0'  # デフォルト値として '0' (販売中) を設定
        
        final_cols = ['品番', '重複', '商品名', '価格', 'URL', '商品ステータス']
        for col in final_cols:
            if col not in df.columns:
                df[col] = ''
        
        print(f"Found {len(df)} products in Mercari data.")
        return df[final_cols]

    except Exception as e:
        print(f"An error occurred while processing Mercari data: {e}")
        return pd.DataFrame()

def main():
    """メイン処理"""
    rakuma_df = process_rakuma_data()
    mercari_df = process_mercari_data()
    
    print("ラクマデータに削除列を追加する処理を開始...")
    
    # Mercariの品番をキー、商品ステータスを値とする辞書を作成
    if '品番' in mercari_df.columns and '商品ステータス' in mercari_df.columns:
        # NaNを考慮し、dropna()を追加。ステータスは文字列として扱う
        mercari_status_map = pd.Series(mercari_df['商品ステータス'].astype(str).values, index=mercari_df['品番']).dropna().to_dict()
    else:
        print("⚠️ Mercariデータに'品番'または'商品ステータス'列がないため、削除ロジックをスキップします。")
        mercari_status_map = {}

    def get_delete_status(row):
        # ラクマでSOLD OUTの場合は削除しない
        if row.get('is_sold_out', False):
            return ''

        hinban = row['品番']
        # 品番がNaNやNoneの場合はチェックしない
        if pd.isna(hinban):
            return ''
        
        mercari_status = mercari_status_map.get(str(hinban))
        
        if mercari_status is None: # 条件1: Mercariに品番が存在しない
            return '削除'
        
        if mercari_status == '1': # 条件2: Mercariでのステータスが'1'
            return '削除'
            
        return ''

    # '品番'列が存在する場合のみ削除列を追加
    if '品番' in rakuma_df.columns:
        rakuma_df['削除'] = rakuma_df.apply(get_delete_status, axis=1)
        # is_sold_out列を削除
        if 'is_sold_out' in rakuma_df.columns:
            rakuma_df = rakuma_df.drop(columns=['is_sold_out'])

        # 列の順序を調整
        cols = rakuma_df.columns.tolist()
        # '削除'列を'品番'の隣に移動
        if '削除' in cols:
            cols.insert(cols.index('品番') + 1, cols.pop(cols.index('削除')))
            rakuma_df = rakuma_df[cols]
    else:
        rakuma_df['削除'] = ''
        print("⚠️ Rakumaデータに'品番'列がないため、削除ロジックをスキップします。")

    print("削除列の処理完了。")

    output_rakuma_file = 'products_rakuma.csv'
    output_mercari_file = 'products_mercari.csv'
    
    print(f"Writing Rakuma data to '{output_rakuma_file}'...")
    rakuma_df.to_csv(output_rakuma_file, index=False, encoding='utf-8-sig')
    
    print(f"Writing Mercari data to '{output_mercari_file}'...")
    mercari_df.to_csv(output_mercari_file, index=False, encoding='utf-8-sig')
        
    print("Script finished successfully.")

if __name__ == '__main__':
    main()
