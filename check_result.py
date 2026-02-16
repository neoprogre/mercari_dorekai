import pandas as pd

# CSVを読み込み
df = pd.read_csv(r'C:\Users\progr\Desktop\Python\mercari_dorekai\downloads\dorekai-base-shop-updated_20260204_200124.csv', encoding='shift-jis')

print(f'合計行数: {len(df)}')
print(f'カラム数: {len(df.columns)}')

print('\n=== 追加された最初の行 (row 1) ===')
row = df.iloc[1]
print(f'商品ID: {row["商品ID"]}')
print(f'商品名: {row["商品名"][:80]}...')
print(f'説明: {str(row["説明"])[:100]}')
print(f'価格: {row["価格"]}')
print(f'税率: {row["税率"]}')
print(f'在庫数: {row["在庫数"]}')
print(f'公開状態: {row["公開状態"]}')
print(f'表示順: {row["表示順"]}')
print(f'商品コード: {row["商品コード"]}')
print(f'画像1: {str(row["画像1"])[:80]}')
print(f'画像2: {str(row["画像2"])[:80]}')
print(f'画像3: {str(row["画像3"])[:80]}')

print('\n=== 追加された2行目 (row 2) ===')
row2 = df.iloc[2]
print(f'商品ID: {row2["商品ID"]}')
print(f'商品名: {row2["商品名"][:80]}...')
print(f'説明: {str(row2["説明"])[:100]}')
print(f'価格: {row2["価格"]}')
print(f'在庫数: {row2["在庫数"]}')
print(f'商品コード: {row2["商品コード"]}')
print(f'画像1: {str(row2["画像1"])[:80]}')
