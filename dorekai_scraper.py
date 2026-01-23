import os
import glob
import json
import sys
import pandas as pd
import re
import time
import requests
from bs4 import BeautifulSoup

def load_brand_name_list_from_master(file_path="brand_master_sjis.csv"):
    """ブランドマスターファイルからブランド名のリストを読み込む（商品名からの抽出用）"""
    brands = []
    try:
        df = pd.read_csv(file_path, encoding='cp932', header=None, usecols=[1])
        brands = df[1].dropna().astype(str).tolist()
        brands.sort(key=len, reverse=True)
        print(f"📚 ブランドマスターから {len(brands)} 件のブランドを読み込みました。")
    except FileNotFoundError:
        print(f"⚠️ ブランドマスターファイルが見つかりません: {file_path}。商品名からのブランド抽出は行われません。")
    return brands

def load_brand_master_map(file_path="brand_master_sjis.csv"):
    """ブランドマスターファイルから {ブランドID: {各名称}} の辞書を作成する"""
    brand_map = {}
    try:
        # Shift_JISで読み込み、ヘッダーがないことを想定
        df = pd.read_csv(file_path, encoding='cp932', header=None, dtype=str)
        # 列名を定義
        df.columns = ['ブランドID', 'ブランド名', 'ブランド名（カナ）', 'ブランド名（英語）']
        df.dropna(subset=['ブランドID'], inplace=True)
        # ブランドIDをインデックスにして辞書化
        brand_map = df.set_index('ブランドID').to_dict('index')
        print(f"📚 ブランドマスター辞書を {len(brand_map)} 件読み込みました。")
    except FileNotFoundError:
        print(f"⚠️ ブランドマスターファイルが見つかりません: {file_path}。IDからのブランド名解決は行われません。")
    except Exception as e:
        print(f"❌ ブランドマスターファイルの読み込み中にエラーが発生しました: {e}")
    return brand_map

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
    # --- [設定] スクレイピング対象ページ ---
    # Trueにするとショップの全ページをスクレイピングします。
    # Falseにすると1ページ目のみを対象にします。
    SCRAPE_ALL_PAGES = True
    # ------------------------------------
    # --- データマッピング（逆引き用） ---
    CONDITION_MAP_INV = {'新品、未使用': '1', '未使用に近い': '2', '目立った傷や汚れなし': '3', 'やや傷や汚れあり': '4', '傷や汚れあり': '5', '全体的に状態が悪い': '6'}
    SHIPPING_PAYER_MAP_INV = {'送料込み(出品者負担)': '1', '着払い(購入者負担)': '2', '送料込': '1'}
    DAYS_TO_SHIP_MAP_INV = {'1-2日で発送': '1', '2-3日で発送': '2', '4-7日で発送': '3', '支払い後、1～2日で発送': '1', '支払い後、2～3日で発送': '2', '支払い後、4～7日で発送': '3'}
    # PREFECTURE_MAPは数が多いため、必要に応じて追加

    """指定されたURLからラクマのデータを抽出し、ページネーションを処理して整形する"""
    print("Processing Rakuma data from web...")
    base_url = 'https://fril.jp/shop/3c65d78bc0e1eadbe2a3528b344d8311'
    page = 1
    all_products = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    product_links = []
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
            link_tag = item.find('a', class_='link_shop_image')
            if link_tag and 'href' in link_tag.attrs:
                product_links.append(link_tag['href'])
        
        # 1ページのみを対象とする場合、ここでループを抜ける
        if not SCRAPE_ALL_PAGES:
            print("1ページ目のみをスクレイピングしました。")
            break

        page += 1
        time.sleep(1)  # サーバーへの負荷を軽減するための待機

    print(f"Found {len(product_links)} product links. Now scraping details for each product...")

    for item_url in product_links:
        print(f"  Scraping details from: {item_url}")
        try:
            response = requests.get(item_url, headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # 基本情報の取得
            name = soup.find('h1', class_='item__name').text.strip() if soup.find('h1', class_='item__name') else 'N/A'
            # [再修正] 価格取得ロジックをさらに強化
            price = 'N/A'
            price_selectors = [
                'span[data-price]', # 属性から直接取得 (最も確実)
                'p.item__price',    # 以前の構造
                'div.item__price',  # divタグの可能性
                'span.item__price', # spanタグの可能性
            ]
            for selector in price_selectors:
                price_tag = soup.select_one(selector)
                if price_tag:
                    if 'data-price' in price_tag.attrs:
                        price = price_tag['data-price']
                        break
                    price_text = price_tag.get_text(strip=True)
                    price_match = re.search(r'[\d,]+', price_text)
                    if price_match:
                        price = price_match.group(0).replace(',', '')
                        break

            is_sold_out = soup.find('div', class_='item-box__soldout_ribbon') is not None

            # 商品説明の取得
            description = 'N/A'
            desc_tag = soup.find('div', class_='item__description__line-limited')
            if desc_tag:
                # <br>タグを改行に変換
                for br in desc_tag.find_all("br"):
                    br.replace_with("\n")
                description = desc_tag.text.strip()

            # 商品情報の取得
            product_info = {}
            details_table = soup.find('table', class_='item__details')
            if details_table:
                for row in details_table.find_all('tr'):
                    th = row.find('th')
                    td = row.find('td')
                    if th and td:
                        key = th.text.strip()
                        # カテゴリはリンクを辿ってテキストを結合
                        if key == 'カテゴリ':
                            value = ' > '.join([a.text.strip() for a in td.find_all('a')])
                        # ブランド名は<a>タグの中にある場合と、td直下にある場合の両方に対応
                        elif key == 'ブランド':
                            brand_link = td.find('a')
                            if brand_link:
                                value = brand_link.text.strip()
                            else:
                                value = td.text.strip()
                        else:
                            value = td.text.strip()
                        product_info[key] = value
            
            # 取得した情報をまとめる
            product_data = {
                '商品名': name,
                '価格': price,
                'URL': item_url,
                'is_sold_out': is_sold_out,
                '商品説明': description,
                'ブランド': product_info.get('ブランド', ''), # [修正] ラクマページから取得したブランドのみを設定
                'カテゴリ': product_info.get('カテゴリ', ''),
                'サイズ': product_info.get('サイズ', ''),
                '商品の状態': product_info.get('商品の状態', ''),
                '配送料の負担': product_info.get('配送料の負担', ''),
                '配送方法': product_info.get('配送方法', ''),
                '発送日の目安': product_info.get('発送日の目安', ''),
                '発送元の地域': product_info.get('発送元の地域', ''),
            }
            all_products.append(product_data)

        except requests.exceptions.RequestException as e:
            print(f"  Error fetching item page {item_url}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"  Error parsing item page {item_url}: {e}", file=sys.stderr)
        
        time.sleep(1)

    if not all_products:
        print("No products found in Rakuma data.")
        return pd.DataFrame()

    df = pd.DataFrame(all_products)
    df['品番'] = df['商品名'].apply(extract_product_number)

    # データマッピングを適用してコードに変換
    df['商品の状態コード'] = df['商品の状態'].map(CONDITION_MAP_INV)
    df['配送料負担コード'] = df['配送料の負担'].map(SHIPPING_PAYER_MAP_INV)
    df['発送日の目安コード'] = df['発送日の目安'].map(DAYS_TO_SHIP_MAP_INV)

    df = add_duplicate_column(df)
    
    # 出力する列を定義
    output_cols = [
        '品番', '重複', '商品名', '価格', 'URL', 'is_sold_out', '商品説明', 'ブランド',
        'カテゴリ', 'サイズ', '商品の状態', '配送料の負担', '配送方法',
        '発送日の目安', '発送元の地域', '商品の状態コード', '配送料負担コード', '発送日の目安コード'
    ]
    # 存在しない列があれば空文字で埋める
    for col in output_cols:
        if col not in df.columns:
            df[col] = ''

    df = df[output_cols]
    print(f"Found {len(df)} products in Rakuma data.")
    return df

def process_mercari_data():
    """ネットワーク上の最新のMercari CSVからデータを抽出し、整形する"""
    print("Processing Mercari data...")
    try:
        mercari_path = r'\\LS210DNBD82\share\平良\Python\mercari_dorekai'
        search_pattern = os.path.join(mercari_path, 'product_data_*.csv') # [修正] ユーザーの要求に合わせてパスを修正
        
        files = glob.glob(search_pattern)
        if not files:
            print(f"No Mercari CSV files found at: {search_pattern}")
            return pd.DataFrame(), {} # [修正] 空の辞書も返す
        
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
        
        # [追加] ブランドIDと品番のマップを作成
        hinban_to_brandid_map = {}
        if '品番' in df.columns and 'ブランドID' in df.columns:
            df_map = df[['品番', 'ブランドID']].copy()
            df_map.dropna(subset=['品番', 'ブランドID'], inplace=True)
            df_map['品番'] = df_map['品番'].astype(str)
            hinban_to_brandid_map = pd.Series(df_map['ブランドID'].values, index=df_map['品番']).to_dict()
            print(f"📚 品番->ブランドID辞書を {len(hinban_to_brandid_map)} 件読み込みました。")

        final_cols = ['品番', '重複', '商品名', '価格', 'URL', '商品ステータス', '商品ID', 'ブランドID']
        for col in final_cols:
            if col not in df.columns:
                df[col] = ''
        
        print(f"Found {len(df)} products in Mercari data.")
        return df[final_cols].copy(), hinban_to_brandid_map

    except Exception as e:
        print(f"An error occurred while processing Mercari data: {e}")
        return pd.DataFrame(), {}

def main():
    """メイン処理"""
    rakuma_df = process_rakuma_data()
    mercari_df, hinban_to_brandid_map = process_mercari_data()
    brand_master_map = load_brand_master_map()

    # --- [新規] ラクマデータにブランドマスターから引いたブランド名を設定 ---
    if not rakuma_df.empty and hinban_to_brandid_map and brand_master_map:
        rakuma_df['ブランドID'] = rakuma_df['品番'].astype(str).map(hinban_to_brandid_map)

        # ブランドIDに基づいて各ブランド名を設定する関数
        def get_brand_details(brand_id, column_name):
            if pd.isna(brand_id):
                return None
            return brand_master_map.get(str(brand_id), {}).get(column_name, None)

        # 新しい列を追加
        rakuma_df['ブランド名'] = rakuma_df['ブランドID'].apply(lambda x: get_brand_details(x, 'ブランド名'))
        rakuma_df['ブランド名（カナ）'] = rakuma_df['ブランドID'].apply(lambda x: get_brand_details(x, 'ブランド名（カナ）'))
        rakuma_df['ブランド名（英語）'] = rakuma_df['ブランドID'].apply(lambda x: get_brand_details(x, 'ブランド名（英語）'))
        # [削除] 既存のブランド列の更新ロジックを削除

    # --- ラクマデータにメルカリの商品IDを紐付ける処理を追加 ---
    print("ラクマデータにメルカリの商品IDを紐付けます...")
    if not mercari_df.empty and '品番' in mercari_df.columns and '商品ID' in mercari_df.columns:
        # メルカリデータから品番と商品IDのみを抽出（重複は最初のものを採用）
        mercari_id_map = mercari_df.drop_duplicates(subset=['品番'])[['品番', '商品ID']].copy()
        # 品番を文字列に統一してマージエラーを防ぐ
        mercari_id_map['品番'] = mercari_id_map['品番'].astype(str)
        rakuma_df['品番'] = rakuma_df['品番'].astype(str)

        # ラクマのデータフレームにメルカリの情報をマージする
        rakuma_df = pd.merge(rakuma_df, mercari_id_map, on='品番', how='left')
        # マージによって '商品ID_x', '商品ID_y' ができるのを防ぐため、元の '商品ID' を優先
        rakuma_df.rename(columns={'商品ID_x': '商品ID'}, inplace=True)
        print("メルカリ商品IDの紐付けが完了しました。")
    # ---------------------------------------------------------
    
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

        # ステータスが '1' (売切れ) の場合
        if str(mercari_status) == '1': # 条件2: Mercariでのステータスが'1'
            return '削除'
            
        return ''

    # '品番'列が存在する場合のみ削除列を追加
    if '品番' in rakuma_df.columns:
        # is_sold_out列を先に処理
        if 'is_sold_out' not in rakuma_df.columns:
            rakuma_df['is_sold_out'] = False
        else:
            rakuma_df['is_sold_out'] = rakuma_df['is_sold_out'].fillna(False)

        rakuma_df['削除'] = rakuma_df.apply(get_delete_status, axis=1)
        # is_sold_out列を削除
        if 'is_sold_out' in rakuma_df.columns:
            rakuma_df = rakuma_df.drop(columns=['is_sold_out'])

        # --- 列の順序を最終調整 ---
        # 基本となる列の順序を定義
        final_cols_order = [
            '品番', '重複', '商品ID', '削除', '商品名', '価格', 'URL', '商品説明', 'ブランド', 'ブランド名', 'ブランド名（カナ）', 'ブランド名（英語）',
            'カテゴリ', 'サイズ', '商品の状態', '配送料の負担', '配送方法', 'ブランドID',
            '発送日の目安', '発送元の地域', '商品の状態コード', '配送料負担コード', '発送日の目安コード'
        ]
        
        # 実際に存在する列のみで順序を再構築
        current_cols = rakuma_df.columns.tolist()
        ordered_cols = [col for col in final_cols_order if col in current_cols]
        
        # 順序定義に含まれないが、万が一存在する列があれば末尾に追加
        ordered_cols.extend([col for col in current_cols if col not in ordered_cols])
        
        rakuma_df = rakuma_df[ordered_cols]
    else:
        rakuma_df['削除'] = ''
        print("⚠️ Rakumaデータに'品番'列がないため、削除ロジックをスキップします。")

    print("削除列の処理完了。")

    # スクリプトが置かれているディレクトリを取得
    script_dir = os.path.dirname(os.path.abspath(__file__))

    output_rakuma_file = os.path.join(script_dir, 'products_rakuma.csv')
    output_mercari_file = os.path.join(script_dir, 'products_mercari.csv')
    
    print(f"Writing Rakuma data to '{output_rakuma_file}'...")
    rakuma_df.to_csv(output_rakuma_file, index=False, encoding='utf-8-sig')
    
    print(f"Writing Mercari data to '{output_mercari_file}'...")
    mercari_df.to_csv(output_mercari_file, index=False, encoding='utf-8-sig')
        
    print("Script finished successfully.")

if __name__ == '__main__':
    main()
