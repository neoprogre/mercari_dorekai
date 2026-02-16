import pandas as pd
import glob
import os
import re

# ファイルパス
downloads_dir = r"C:\Users\progr\Desktop\Python\mercari_dorekai\downloads"
brand_master_csv = r"C:\Users\progr\Desktop\Python\mercari_dorekai\brand_master_sjis.csv"
output_csv = r"C:\Users\progr\Desktop\Python\mercari_dorekai\ブランド抽出.csv"
output_analysis_csv = r"C:\Users\progr\Desktop\Python\mercari_dorekai\ブランド分析.csv"

try:
    # 最新のproduct_data_*.csvを取得
    print("📂 最新のproduct_data_*.csvを検索中...")
    product_data_files = glob.glob(os.path.join(downloads_dir, "product_data_*.csv"))
    
    if not product_data_files:
        print("❌ product_data_*.csvが見つかりません")
        exit()
    
    # 最新のファイルを取得（更新日時順）
    latest_file = max(product_data_files, key=os.path.getmtime)
    print(f"✅ 最新ファイル: {os.path.basename(latest_file)}")
    
    # product_data_*.csvを読み込む
    print("📂 product_data_*.csvを読み込み中...")
    for encoding in ['utf-8', 'shift_jis', 'cp932']:
        try:
            df_product = pd.read_csv(latest_file, encoding=encoding)
            print(f"✅ 読み込み成功: {encoding}")
            break
        except Exception:
            continue
    else:
        print("❌ ファイル読み込み失敗")
        exit()
    
    print(f"📊 product_data: {len(df_product)} 行")
    print(f"📋 全列: {list(df_product.columns)}")
    
    # ブランド抽出列を追加：商品名から前半の数字とスペースを削除
    if '商品名' in df_product.columns:
        print(f"\n🎯 ブランド抽出列を作成中...")
        
        def extract_brand_name(text):
            """ブランド名を抽出する
            1. 先頭の数字とスペースを削除
            2. 英文の後の最初の日本語の後の最初のスペース前まで
            """
            if pd.isna(text):
                return text
            
            text = str(text)
            
            # 1. 先頭の数字とスペースを削除
            text = re.sub(r'^\d+\s+', '', text)
            
            # 2. 英文部分 + 日本語部分（最初のスペースまで）を抽出
            # 正規表現：英数字記号の後に日本語が来て、その後のスペース（全角・半角）まで
            match = re.match(r'^([A-Za-z0-9&.\-\s]+?)([ぁ-んァ-ヶー一-龯]+?)[\s　]', text)
            if match:
                # 英文 + 日本語部分を取得
                result = (match.group(1) + match.group(2)).strip()
                return result
            
            # マッチしない場合は最初のスペース（全角・半角）まで
            for i, char in enumerate(text):
                if char in [' ', '　', '\t']:
                    return text[:i].strip()
            
            # スペースがない場合は全体を返す
            return text.strip()
        
        df_product['ブランド抽出'] = df_product['商品名'].apply(extract_brand_name)
        print(f"✅ ブランド抽出列を追加しました")
        print(f"\n📝 抽出例:")
        print(df_product[['商品名', 'ブランド抽出']].head(5).to_string())
    
    # 元のDataFrameをそのまま使用（全列を保持）
    df_extraction = df_product.copy()
    print(f"\n✅ 全列を保持: {len(df_extraction.columns)} 列")
    
    # brand_master_sjis.csvを読み込む
    print("\n📂 brand_master_sjis.csvを読み込み中...")
    for encoding in ['shift_jis', 'cp932', 'utf-8']:
        try:
            df_master = pd.read_csv(brand_master_csv, encoding=encoding)
            print(f"✅ brand_master_sjis.csv読み込み成功: {encoding}")
            break
        except Exception:
            continue
    else:
        print("❌ brand_master_sjis.csv読み込み失敗")
        exit()
    
    print(f"📊 brand_master: {len(df_master)} 行")
    print(f"📋 列: {list(df_master.columns)}")
    
    # brand_master_sjis.csvの列名を取得
    master_cols = df_master.columns.tolist()
    brand_id_col = master_cols[0]  # 最初の列がブランドID
    brand_name_col = master_cols[1]  # 2番目の列がブランド名
    brand_kana_col = master_cols[2]  # 3番目の列がブランド名（カナ）
    
    print(f"   マスタ列: {brand_id_col}, {brand_name_col}, {brand_kana_col}")
    
    # ブランドIDでマージ（left join）
    print(f"\n🔗 ブランドIDで結合中...")
    df_merged = df_extraction.merge(
        df_master[[brand_id_col, brand_name_col, brand_kana_col]],
        left_on='ブランドID',
        right_on=brand_id_col,
        how='left'
    )
    
    # 列名を整理
    df_merged = df_merged.rename(columns={
        brand_name_col: 'ブランド名',
        brand_kana_col: 'ブランド名（カナ）'
    })
    
    # 不要な列を削除（重複したブランドID列）
    if brand_id_col != 'ブランドID' and brand_id_col in df_merged.columns:
        df_merged = df_merged.drop(columns=[brand_id_col])
    
    # 元のCSVの列順を維持しつつ、ブランド抽出・ブランド名・ブランド名（カナ）を末尾に配置
    original_cols = [col for col in df_product.columns if col in df_merged.columns]
    new_cols = ['ブランド抽出', 'ブランド名', 'ブランド名（カナ）']
    cols_order = original_cols + [col for col in new_cols if col in df_merged.columns and col not in original_cols]
    df_merged = df_merged[cols_order]
    
    # 結果を表示
    print(f"\n✅ マージ完了: {len(df_merged)} 行")
    print(f"📋 最終列: {list(df_merged.columns)}")
    print(f"\n📝 サンプルデータ:")
    print(df_merged.head(10).to_string())
    
    # マッチ率を表示
    matched = df_merged['ブランド名'].notna().sum()
    total = len(df_merged)
    print(f"\n📊 マッチ率: {matched}/{total} ({matched/total*100:.1f}%)")
    
    # 空のブランドIDがある行を表示
    empty_brand = df_merged[df_merged['ブランドID'].isna() | (df_merged['ブランドID'] == '')]
    if len(empty_brand) > 0:
        print(f"\n⚠️ ブランドIDが空の商品: {len(empty_brand)} 件")
    
    # 2つのファイルを保存
    
    # 1. メルカリアップロード用：元の列構成のみ（ブランド名・カナを更新）
    df_upload = df_merged[df_product.columns].copy()
    # ブランド名とブランド名（カナ）が元のCSVにあれば更新
    if 'ブランド名' in df_product.columns and 'ブランド名' in df_merged.columns:
        df_upload['ブランド名'] = df_merged['ブランド名']
    if 'ブランド名（カナ）' in df_product.columns and 'ブランド名（カナ）' in df_merged.columns:
        df_upload['ブランド名（カナ）'] = df_merged['ブランド名（カナ）']
    
    df_upload.to_csv(output_csv, index=False, encoding='utf-8-sig')
    print(f"\n✅ メルカリアップロード用ファイルを保存: {output_csv}")
    print(f"   列数: {len(df_upload.columns)} (元のCSVと同じ)")
    
    # 2. 分析用：ブランド抽出列を追加 + ソート
    df_analysis = df_merged.copy()
    
    # ブランドIDの有無で分ける
    if 'ブランドID' in df_analysis.columns:
        # ブランドIDがある商品
        df_with_brand = df_analysis[df_analysis['ブランドID'].notna() & (df_analysis['ブランドID'] != '')].copy()
        # ブランドIDがない商品
        df_without_brand = df_analysis[df_analysis['ブランドID'].isna() | (df_analysis['ブランドID'] == '')].copy()
        
        # 1. ブランドIDがある商品：ブランドID出現回数（降順） + ブランド抽出（昇順）
        if len(df_with_brand) > 0:
            brand_counts = df_with_brand['ブランドID'].value_counts()
            df_with_brand['_temp_count'] = df_with_brand['ブランドID'].map(brand_counts)
            
            if 'ブランド抽出' in df_with_brand.columns:
                df_with_brand['_temp_brand_lower'] = df_with_brand['ブランド抽出'].str.lower()
                df_with_brand = df_with_brand.sort_values(['_temp_count', '_temp_brand_lower'], ascending=[False, True])
                df_with_brand = df_with_brand.drop(columns=['_temp_count', '_temp_brand_lower'])
            else:
                df_with_brand = df_with_brand.sort_values('_temp_count', ascending=False)
                df_with_brand = df_with_brand.drop(columns=['_temp_count'])
        
        # 2. ブランドIDがない商品：ブランド抽出の出現回数（降順）
        if len(df_without_brand) > 0 and 'ブランド抽出' in df_without_brand.columns:
            brand_extract_counts = df_without_brand['ブランド抽出'].value_counts()
            df_without_brand['_temp_extract_count'] = df_without_brand['ブランド抽出'].map(brand_extract_counts)
            df_without_brand['_temp_brand_lower'] = df_without_brand['ブランド抽出'].str.lower()
            df_without_brand = df_without_brand.sort_values(['_temp_extract_count', '_temp_brand_lower'], ascending=[False, True])
            df_without_brand = df_without_brand.drop(columns=['_temp_extract_count', '_temp_brand_lower'])
        
        # 結合：ブランドIDあり + ブランドIDなし
        df_analysis = pd.concat([df_with_brand, df_without_brand], ignore_index=True)
        
        print(f"\n📊 ソート完了:")
        print(f"   - ブランドIDあり: {len(df_with_brand)} 件（ブランドID出現回数→ブランド抽出順）")
        print(f"   - ブランドIDなし: {len(df_without_brand)} 件（ブランド抽出出現回数順）")
    
    df_analysis.to_csv(output_analysis_csv, index=False, encoding='utf-8-sig')
    print(f"\n✅ 分析用ファイルを保存: {output_analysis_csv}")
    print(f"   列数: {len(df_analysis.columns)} (ブランド抽出・ブランド名・カナ含む)")
    
except Exception as e:
    print(f"❌ エラー: {e}")
    import traceback
    traceback.print_exc()
