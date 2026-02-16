import pandas as pd
from collections import Counter

# CSVファイルを読み込む
csv_file = r"C:\Users\progr\Desktop\Python\mercari_dorekai\ブランド分析.csv"
df = pd.read_csv(csv_file)

# ブランド抽出列のデータを取得（空白や欠損値を除外）
brand_column = df['ブランド抽出'].dropna()
brand_column = brand_column[brand_column.astype(str).str.strip() != '']

# 各ブランドの出現回数をカウント
brand_counts = Counter(brand_column)

# 多い順に並び替え
sorted_brands = brand_counts.most_common()

# 結果を表示
print(f"総ブランド数: {len(brand_column)}")
print(f"ユニークなブランド数: {len(brand_counts)}")
print("\n" + "="*80)
print(f"{'順位':<6} {'ブランド名':<50} {'出現回数':<10}")
print("="*80)

for idx, (brand, count) in enumerate(sorted_brands, 1):
    print(f"{idx:<6} {brand:<50} {count:<10}")

# 結果をCSVファイルに保存
result_df = pd.DataFrame(sorted_brands, columns=['ブランド名', '出現回数'])
result_df.insert(0, '順位', range(1, len(result_df) + 1))
output_file = r"C:\Users\progr\Desktop\Python\mercari_dorekai\ブランド分析_集計結果.csv"
result_df.to_csv(output_file, index=False, encoding='utf-8-sig')

print("\n" + "="*80)
print(f"結果を保存しました: {output_file}")
