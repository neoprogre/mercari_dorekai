from openpyxl import load_workbook

wb = load_workbook(r'C:\Users\progr\Desktop\Python\mercari_dorekai\downloads\ドレ買い.xlsx')
sheet = wb['再出品']

# ヘッダー行を取得
print('ヘッダー行:')
headers = []
for cell in sheet[1]:
    headers.append(cell.value)
print(headers)

# 販売単価列を探す
price_col = None
for idx, h in enumerate(headers, 1):
    if h and ('販売単価' in str(h) or '単価' in str(h) or '価格' in str(h)):
        price_col = idx
        print(f'\n販売単価列: 列{idx} ({h})')
        break

if not price_col:
    print('\n❌ 販売単価列が見つかりません')
else:
    # 最初の5行のデータを表示
    print('\n最初の5行の販売単価:')
    for i in range(2, 7):
        row = sheet[i]
        price_val = row[price_col - 1].value if len(row) >= price_col else None
        print(f'行{i}: {price_val}')
