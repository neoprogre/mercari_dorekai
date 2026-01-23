"""
CSVファイルから商品データを読み込み、商品IDを使って画像を自動マッピングし、
ヤフオクに自動出品するスクリプト
"""
import os
import sys
import csv
import glob
import time
from pathlib import Path

try:
    from yahooku_dorekai import setup_driver, list_item_on_yahoo_auction
except Exception as e:
    print(f"yahooku_dorekai をインポートできませんでした: {e}")
    sys.exit(1)

# ネットワークドライブパス
NETWORK_BASE = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai"
IMAGES_DIR = os.path.join(NETWORK_BASE, "mercari_images")

# ヤフオクの出品数制限（現在の段階では100商品まで）
MAX_ITEMS_LIMIT = 100

print("\n" + "="*60)
print("【CSVからヤフオク自動出品】商品ID連携版")
print("="*60)

# 最新のproduct_data_*.csvを探す
csv_files = sorted(
    glob.glob(os.path.join(NETWORK_BASE, "product_data_*.csv")),
    key=os.path.getmtime,
    reverse=True
)

if not csv_files:
    print(f"❌ product_data_*.csv ファイルが見つかりません: {NETWORK_BASE}")
    sys.exit(1)

csv_path = csv_files[0]
print(f"\n✅ 最新のCSV: {os.path.basename(csv_path)}")

# CSVを読み込む
print("📂 CSVを読み込み中...")
items = []
try:
    with open(csv_path, 'r', encoding='cp932', newline='') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            items.append(row)
            if i == 0:
                print(f"\n📋 最初の商品情報:")
                print(f"  商品ID: {row.get('商品ID', 'N/A')}")
                print(f"  商品名: {row.get('商品名', 'N/A')[:60]}")
                print(f"  価格: {row.get('販売価格', 'N/A')}")
except Exception as e:
    print(f"❌ CSVファイルの読み込み失敗: {e}")
    sys.exit(1)

if not items:
    print("❌ CSVにデータが見つかりません")
    sys.exit(1)

# 出品数制限の適用
if len(items) > MAX_ITEMS_LIMIT:
    print(f"⚠️ ヤフオクの出品制限により、先頭 {MAX_ITEMS_LIMIT} 件のみを処理対象とします。")
    items = items[:MAX_ITEMS_LIMIT]

print(f"\n✅ 合計 {len(items)} 件の商品が見つかりました")

# ドライバーをセットアップ
print("\n🚀 ブラウザを起動しています...")
driver = setup_driver()

print("📄 ヤフオク出品ページにアクセスしています...")

logged_in = False

print("\n 自動出品処理を開始します...")

for i, item_row in enumerate(items):
    print(f"\n" + "="*60)
    print(f"📦 商品 {i+1}/{len(items)} 処理中...")
    print("="*60)

    if not logged_in:
        print("\n【初回手動操作】")
        print("  1. ブラウザでヤフオクにログインしてください。")
        print("  2. ログインが完了したら、このターミナルに戻ってEnterキーを押してください。")
        input("👉 ログイン完了後、Enterキーを押してください: ")
        logged_in = True

    product_id = item_row.get('商品ID', '')
    print(f"  商品ID: {product_id}")
    print(f"  商品名: {item_row.get('商品名', 'N/A')[:60]}")

    # 画像検索
    images = []
    if product_id:
        for j in range(1, 11):
            img_path = os.path.join(IMAGES_DIR, f"{product_id}-{j}.jpg")
            if os.path.exists(img_path):
                images.append(img_path)
    
    if not images:
        print(f"  ⚠️ 画像が見つかりません。この商品をスキップします。")
        continue

    # データ構築
    title = item_row.get('商品名', 'テスト出品').strip()
    description = item_row.get('商品説明', '説明なし').strip()
    price_str = item_row.get('販売価格', '1000')
    try:
        price = int(float(price_str)) if price_str else 1000
    except (ValueError, TypeError):
        price = 1000

    # 商品の状態マッピング
    condition_map = {
        '1': 'new',      # 未使用
        '2': 'used10',   # 未使用に近い
        '3': 'used20',   # 目立った傷や汚れなし
        '4': 'used40',   # やや傷や汚れあり
        '5': 'used60',   # 傷や汚れあり
        '6': 'used80'    # 全体的に状態が悪い
    }
    condition_val = condition_map.get(item_row.get('商品の状態', ''), 'used40') # デフォルトは「やや傷や汚れあり」

    # カテゴリパスの自動判定
    category_path = "ファッション > レディースファッション > フォーマル > カラードレス > その他"
    if "ロング" in title:
        category_path = "ファッション > レディースファッション > フォーマル > カラードレス > ロング"
    elif "ミニ" in title:
        category_path = "ファッション > レディースファッション > フォーマル > カラードレス > ミニ"
    elif "スーツ" in title:
        category_path = "ファッション > レディースファッション > フォーマル > スーツ、アンサンブル"

    item_data = {
        'title': title[:100],
        'description': description[:5000],
        'price': price,
        'images': images,
        'category_path': category_path,
        'condition': condition_val,
        'shipping': 'compact', # 宅急便コンパクト（EAZY）を指定
    }

    try:
        list_item_on_yahoo_auction(driver, item_data)
        print(f"  ✅ 商品 {i+1} の出品処理が完了しました。")
    except Exception as e:
        print(f"  ❌ 商品 {i+1} の出品中にエラーが発生しました: {e}")
    
    # 待機
    print("   ...次の商品まで5秒待機...")
    time.sleep(5)

print("\n" + "="*60)
print("✅ 全商品の出品処理が完了しました！")
print("="*60)
print("\n⏳ ブラウザを閉じずに開いたままにします...")
