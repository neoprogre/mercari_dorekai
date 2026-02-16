"""
商品説明からサイズを抽出し、商品名をクリーンアップするスクリプト
"""
import pandas as pd
import re
import os
import glob

CSV_DIR = r"C:\Users\progr\Desktop\Python\mercari_dorekai\downloads"

def extract_size_from_description(description):
    """
    商品説明からサイズを抽出
    - 数字の場合はF
    - 何も書いてない場合もF
    - 有効なサイズ値のみ抽出
    """
    if not description or not isinstance(description, str):
        return 'F'
    
    # 有効なサイズ値のリスト
    valid_sizes = [
        'XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', '2XL', '3XL',
        'F', 'FREE', 'フリー', 'フリーサイズ',
        'S-M', 'M-L', 'L-XL',
        # EU・UK・US サイズ
        'EU32', 'EU34', 'EU36', 'EU38', 'EU40', 'EU42',
        'UK4', 'UK6', 'UK8', 'UK10', 'UK12', 'UK14',
        'US0', 'US2', 'US4', 'US6', 'US8', 'US10',
        # その他
        '0', '00', '2', '4', '6', '8', '9', '10', '11', '12', '13', '15',
        '0サイズ', '2サイズ', '4サイズ', '6サイズ', '7サイズ', '9サイズ', '11サイズ', '13サイズ', '15サイズ', '16サイズ', '36サイズ', '38サイズ', '40サイズ',
        '7号', '9号', '11号', '13号', '15号',
        # キッズサイズ
        '4y', '5y', '6y', '7y', '8y', '9y', '10y', '11y', '12y', '13y', '14y', '15y', '16y'
    ]
    
    # ＊サイズの後の行を探す
    match = re.search(r'＊サイズ\s*\n+\s*(\S+)', description)
    if not match:
        return 'F'
    
    size_value = match.group(1).strip()
    
    # 肩幅や身幅などの採寸が来た場合は空と判断
    if '幅' in size_value or 'cm' in size_value or '約' in size_value or '着丈' in size_value:
        return 'F'
    
    # 長すぎる場合はF（説明文など）
    if len(size_value) > 20:
        return 'F'
    
    # 数字のみ（サイズ表記なし）の場合
    if size_value.isdigit():
        # 1桁または2桁の数字の場合はF
        if len(size_value) <= 2:
            return 'F'
    
    # 有効なサイズリストにあればそのまま返す
    size_upper = size_value.upper()
    for valid_size in valid_sizes:
        if valid_size.upper() == size_upper:
            return size_value
    
    # 「表記」「タグ」などはF
    if '表記' in size_value or 'タグ' in size_value or '画像' in size_value:
        return 'F'
    
    # それ以外はF
    return 'F'

def clean_product_name(name):
    """
    商品名をクリーンアップ
    - スペース区切り
    - 始部分の数字を削除
    - キャバクラ、ドレス、ロングドレス、キャバドレスを削除（単語として独立している場合のみ）
    """
    if not name or not isinstance(name, str):
        return ''
    
    # 先頭の数字を削除
    name = re.sub(r'^\d+\s*', '', name)
    
    # キーワードを削除（前後にスペースまたは文字列の開始/終了がある場合のみ）
    # 長い順に削除（ロングドレスがドレスより先、キャバドレスがドレスより先）
    replacements = [
        (r'(?:^|\s)ロングドレス(?:\s|$)', ' '),
        (r'(?:^|\s)キャバドレス(?:\s|$)', ' '),
        (r'(?:^|\s)キャバクラ(?:\s|$)', ' '),
        (r'(?:^|\s)ドレス(?:\s|$)', ' '),  # キャミドレス、チャイナドレスは残る
    ]
    
    for pattern, replacement in replacements:
        name = re.sub(pattern, replacement, name)
    
    # 複数の空白を1つに
    name = re.sub(r'\s+', ' ', name)
    
    # 前後の空白を削除
    name = name.strip()
    
    return name

def get_latest_csv():
    """
    最新のproduct_data_*.csvまたはパッド直し*.csvを取得（ただし_サイズ商品名や_処理済を含むファイルは除外）
    """
    patterns = [
        os.path.join(CSV_DIR, "product_data_*.csv"),
        os.path.join(CSV_DIR, "パッド直し", "*.csv")
    ]
    
    all_files = []
    for pattern in patterns:
        files = glob.glob(pattern)
        # _サイズ商品名や_処理済を含むファイルは除外（処理後のファイル）
        files = [f for f in files if '_サイズ商品名' not in f and '_処理済' not in f]
        all_files.extend(files)
    
    if not all_files:
        return None
    
    return max(all_files, key=os.path.getmtime)

def main():
    # CSVファイルを取得
    csv_file = get_latest_csv()
    if not csv_file:
        print("❌ CSVファイルが見つかりません")
        return
    
    print(f"📄 CSVファイル: {os.path.basename(csv_file)}")
    
    # CSVを読み込む
    try:
        df = pd.read_csv(csv_file, encoding='shift-jis')
        print(f"✅ CSV読み込み完了: {len(df)}行")
    except Exception as e:
        print(f"❌ CSV読み込みエラー: {e}")
        return
    
    # 列の確認
    print(f"\n📋 現在の列: {', '.join(df.columns.tolist())}")
    
    # 商品説明列が存在するか確認
    desc_col = None
    for col in ['商品説明', 'description', 'desc']:
        if col in df.columns:
            desc_col = col
            break
    
    if not desc_col:
        print("❌ 商品説明列が見つかりません")
        return
    
    # 商品名列が存在するか確認
    name_col = None
    for col in ['商品名', 'name', 'product_name']:
        if col in df.columns:
            name_col = col
            break
    
    if not name_col:
        print("❌ 商品名列が見つかりません")
        return
    
    print(f"\n🔍 処理対象:")
    print(f"  商品説明列: {desc_col}")
    print(f"  商品名列: {name_col}")
    
    # サイズを抽出
    print(f"\n⏳ サイズ抽出中...")
    df['サイズ'] = df[desc_col].apply(extract_size_from_description)
    size_count = df['サイズ'].notna().sum()
    print(f"✅ サイズ抽出完了: {size_count}件")
    
    # サイズの分布を表示（上位10件）
    size_distribution = df['サイズ'].value_counts().head(10)
    print(f"\n📊 サイズ分布（上位10件）:")
    for size, count in size_distribution.items():
        print(f"  {size}: {count}件")
    
    # 商品名をクリーンアップ
    print(f"\n⏳ 商品名クリーンアップ中...")
    df['商品名1'] = df[name_col].apply(clean_product_name)
    cleaned_count = (df['商品名1'] != df[name_col]).sum()
    print(f"✅ 商品名クリーンアップ完了: {cleaned_count}件変更")
    
    # サンプルを表示
    print(f"\n📝 処理結果サンプル（最初の3件）:")
    for idx in range(min(3, len(df))):
        print(f"\n{idx + 1}件目:")
        print(f"  商品名: {df.loc[idx, name_col][:60]}...")
        print(f"  サイズ: {df.loc[idx, 'サイズ']}")
        print(f"  商品名1: {df.loc[idx, '商品名1'][:60]}...")
    
    # 列の順序を整理（サイズと商品名1を見やすい位置に）
    cols = df.columns.tolist()
    # サイズと商品名1を削除
    if 'サイズ' in cols:
        cols.remove('サイズ')
    if '商品名1' in cols:
        cols.remove('商品名1')
    
    # 商品名の直後にサイズと商品名1を挿入
    if name_col in cols:
        name_idx = cols.index(name_col)
        cols.insert(name_idx + 1, 'サイズ')
        cols.insert(name_idx + 2, '商品名1')
    else:
        cols.extend(['サイズ', '商品名1'])
    
    df = df[cols]
    
    # 保存
    # ファイル名を決定（元のファイル名に_処理済を追加）
    base_name = os.path.splitext(os.path.basename(csv_file))[0]
    # 既に_処理済が含まれていたら追加しない
    if '_処理済' not in base_name:
        output_name = f"{base_name}_処理済.csv"
    else:
        output_name = f"{base_name}.csv"
    
    output_file = os.path.join(os.path.dirname(csv_file), output_name)
    try:
        df.to_csv(output_file, index=False, encoding='shift-jis')
        print(f"\n✅ 保存完了: {output_name}")
        print(f"   場所: {os.path.dirname(output_file)}")
    except Exception as e:
        print(f"❌ 保存エラー: {e}")

if __name__ == '__main__':
    main()
