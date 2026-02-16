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

# ネットワークドライブパスとローカルパス
NETWORK_BASE = r"C:\Users\progr\Desktop\Python\mercari_dorekai\downloads"
LOCAL_BASE = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(r"\\LS210DNBD82\share\平良\Python\mercari_dorekai", "mercari_images")

print("\n" + "="*60)
print("【CSVからヤフオク自動出品】商品ID連携版")
print("="*60)

# 最新のproduct_data_*.csvを探す（ローカル優先）
csv_files = []
for base_path in [LOCAL_BASE, NETWORK_BASE]:
    try:
        found = glob.glob(os.path.join(base_path, "product_data_*.csv"))
        if found:
            csv_files = sorted(found, key=os.path.getmtime, reverse=True)
            print(f"📂 CSVファイルを検索中: {base_path}")
            break
    except Exception as e:
        print(f"⚠️ パス {base_path} にアクセスできません: {e}")
        continue

if not csv_files:
    print(f"❌ product_data_*.csv ファイルが見つかりません")
    print(f"   検索パス1: {LOCAL_BASE}")
    print(f"   検索パス2: {NETWORK_BASE}")
    sys.exit(1)

csv_path = csv_files[0]
print(f"\n✅ 最新のCSV: {os.path.basename(csv_path)}")

# 出品済み商品IDを記録するファイル
PROCESSED_FILE = os.path.join(LOCAL_BASE, "yahooku_processed_ids.txt")

# 既に出品済みの商品IDを読み込む
processed_ids = set()
if os.path.exists(PROCESSED_FILE):
    try:
        with open(PROCESSED_FILE, 'r', encoding='utf-8') as f:
            processed_ids = set(line.strip() for line in f if line.strip())
        print(f"📋 既に出品済み: {len(processed_ids)} 件")
    except Exception as e:
        print(f"⚠️ 出品済みリスト読み込み失敗: {e}")

# CSVを読み込む
print("📂 CSVを読み込み中...")
items = []
try:
    with open(csv_path, 'r', encoding='cp932') as f:
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

print(f"\n✅ 合計 {len(items)} 件の商品が見つかりました")

# 未出品の商品を古い順から最大15件取得
unprocessed_items = []
for item in items:
    product_id = item.get('商品ID', '')
    if product_id and product_id not in processed_ids:
        unprocessed_items.append(item)
        if len(unprocessed_items) >= 15:
            break

if not unprocessed_items:
    print("❌ 未出品の商品がありません（全て出品済み）")
    sys.exit(0)

print(f"\n📌 未出品の商品を {len(unprocessed_items)} 件見つけました")
print(f"   これから順番に出品を開始します...\n")

# ドライバーをセットアップ
print("🚀 ブラウザを起動しています...")
driver = setup_driver()

print("📄 ヤフオク出品ページにアクセスしています...")
print("\n【手動操作が必要】")
print("  1. ブラウザでヤフオクにログインしてください")
print("  2. 完了したら、このターミナルで Enterキーを押してください")
print("\n")

input("👉 準備完了後、Enterキーを押してください: ")

# 15件の商品を順番に処理
success_count = 0
error_count = 0

for idx, item_row in enumerate(unprocessed_items, 1):
    product_id = item_row.get('商品ID', '')
    
    print(f"\n{'='*60}")
    print(f"📦 [{idx}/{len(unprocessed_items)}] 商品を処理中...")
    print(f"{'='*60}")
    print(f"  商品ID: {product_id}")
    print(f"  商品名: {item_row.get('商品名', 'N/A')[:60]}")
    
    # 商品IDを使ってすべての画像を検索
    print(f"\n🖼️  商品ID '{product_id}' の画像を検索中...")
    images = []
    if product_id:
        # パターン: {商品ID}-1.jpg から {商品ID}-10.jpg まで（ヤフオクは最大10枚）
        for i in range(1, 11):
            img_path = os.path.join(IMAGES_DIR, f"{product_id}-{i}.jpg")
            if os.path.exists(img_path):
                images.append(img_path)
                print(f"  ✅ 見つかり: {product_id}-{i}.jpg")
            else:
                # 存在しない場合は検索を終了（連番なので）
                if i == 1:
                    print(f"  ⚠️ 画像が見つかりません")
                break

    if not images:
        print(f"  ⚠️ 画像が見つかりませんでした。この商品をスキップします。")
        error_count += 1
        continue

    print(f"\n✅ 合計 {len(images)} 件の画像を取得しました")

    # item_dataを構築
    title = item_row.get('商品名', 'テスト出品').strip()
    description = item_row.get('商品説明', '説明なし').strip()
    price_str = item_row.get('販売価格', '1000')

    try:
        price = int(float(price_str)) if price_str else 1000
    except (ValueError, TypeError):
        price = 1000

    item_data = {
        'title': title[:100],
        'description': description[:5000],
        'price': price,
        'images': images,
        'category_path': 'オークション > ファッション > レディースファッション > フォーマル > カラードレス > その他'
    }

    print("\n📝 出品データ:")
    print(f"  タイトル: {item_data['title']}")
    print(f"  説明: {item_data['description'][:80]}...")
    print(f"  価格: {item_data['price']}円")
    print(f"  画像数: {len(item_data['images'])}")

    # 出品処理を実行
    try:
        print("\n🔄 自動出品処理を開始します...")
        list_item_on_yahoo_auction(driver, item_data)
        
        # 成功したら商品IDを記録
        with open(PROCESSED_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{product_id}\n")
        processed_ids.add(product_id)
        
        success_count += 1
        print(f"\n✅ [{idx}/{len(unprocessed_items)}] 出品成功: {product_id}")
        
        # 次の商品まで少し待機
        if idx < len(unprocessed_items):
            print("\n⏳ 次の商品まで5秒待機...")
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("\n⚠️ ユーザーによる中断")
        break
    except Exception as e:
        print(f"\n❌ 出品エラー: {e}")
        error_count += 1
        continue

# 最終結果を表示
print(f"\n{'='*60}")
print(f"📊 出品結果")
print(f"{'='*60}")
print(f"  成功: {success_count} 件")
print(f"  失敗: {error_count} 件")
print(f"  合計: {len(unprocessed_items)} 件")
print(f"\n✅ 処理が完了しました")

# ブラウザを閉じる
try:
    driver.quit()
    print("\n🔒 ブラウザを閉じました")
except Exception:
    pass

print("\n🔄 自動出品処理を開始します...")
list_item_on_yahoo_auction(driver, item_data)

print("\n" + "="*60)
print("✅ 出品完了しました！")
print("="*60)
print("\n🎉 ヤフオクへの出品処理が完了しました！")
print("   ブラウザで確認画面を確認してください。")
print("\n⏳ ブラウザを閉じずに開いたままにします...")
