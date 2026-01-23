"""
CSVファイルから1商品を読み込んでヤフオクに自動出品するスクリプト
"""
import os
import sys
import csv
from pathlib import Path

try:
    from yahooku_dorekai import setup_driver, list_item_on_yahoo_auction
except Exception as e:
    print(f"yahooku_dorekai をインポートできませんでした: {e}")
    sys.exit(1)

# CSVファイルパス
csv_path = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\product_data_2026-01-05.csv"

print("\n" + "="*60)
print("【CSVからヤフオク自動出品】")
print("="*60)
print(f"\nCSVファイル: {csv_path}")

# CSVファイルが存在するか確認
if not os.path.exists(csv_path):
    print(f"❌ ファイルが見つかりません: {csv_path}")
    sys.exit(1)

print("✅ CSVファイルを読み込み中...")

try:
    # CSVを読み込む（CP932エンコーディング使用）
    items = []
    with open(csv_path, 'r', encoding='cp932') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            items.append(row)
            if i == 0:  # 最初の行をプリント
                print(f"\n📋 最初の商品情報:")
                print(f"  商品名: {row.get('商品名', 'N/A')[:50]}")
                print(f"  説明: {row.get('商品説明', 'N/A')[:100]}")
                print(f"  価格: {row.get('販売価格', 'N/A')}")
                print(f"  カテゴリID: {row.get('カテゴリID', 'N/A')}")
    
    if not items:
        print("❌ CSVファイルにデータが見つかりません")
        sys.exit(1)
    
    print(f"\n✅ 合計 {len(items)} 件の商品が見つかりました")
    print(f"📌 最初の1商品を使用します")
    
    # 最初の商品を取得
    item_row = items[0]
    
    # 画像ファイルを探す
    images = []
    script_dir = Path(__file__).parent
    
    # CSVからイメージ名を取得してパスを構築
    for i in range(1, 21):  # 最大20個の画像
        img_col = f'商品画像名_{i}'
        if img_col in item_row and item_row[img_col]:
            img_name = item_row[img_col]
            # ネットワークドライブの画像フォルダを想定
            img_path = rf"\\LS210DNBD82\share\平良\Python\mercari_dorekai\images\{img_name}"
            if os.path.exists(img_path):
                images.append(img_path)
                print(f"  ✅ 画像見つかり: {img_name}")
            else:
                print(f"  ⚠️ 画像が見つかりません: {img_name}")
    
    # 画像がない場合はサンプル画像を使用
    if not images:
        sample_img = script_dir / 'sample_image.jpg'
        if sample_img.exists():
            images = [str(sample_img)]
            print(f"  📸 サンプル画像を使用: {sample_img}")
        else:
            print("  ❌ 画像が見つかりません")
    
    # item_data を構築
    title = item_row.get('商品名', 'テスト出品').strip()
    description = item_row.get('商品説明', '説明なし').strip()
    price_str = item_row.get('販売価格', '1000')
    
    # 価格をint型に変換
    try:
        price = int(float(price_str)) if price_str else 1000
    except (ValueError, TypeError):
        price = 1000
    
    item_data = {
        'title': title[:100],  # タイトルは最大100文字
        'description': description[:5000],  # 説明は最大5000文字
        'price': price,
        'images': images,
    }
    
    print("\n📝 出品データ:")
    print(f"  タイトル: {item_data['title']}")
    print(f"  説明: {item_data['description'][:100]}...")
    print(f"  価格: {item_data['price']}円")
    print(f"  画像数: {len(item_data['images'])}")
    
    # ユーザーに確認
    print("\n")
    response = input("この商品で出品を開始しますか？ (y/n) [y]: ").strip().lower()
    if response == 'n':
        print("❌ キャンセルしました")
        sys.exit(0)
    
    # ドライバーをセットアップ
    print("\n🚀 ブラウザを起動しています...")
    driver = setup_driver()
    
    print("📄 ヤフオク出品ページにアクセスしています...")
    print("\n【手動操作が必要】")
    print("  1. ブラウザでヤフオクにログインしてください")
    print("  2. カテゴリを選択して『このカテゴリに出品』をクリックしてください")
    print("  3. 完了したら、このターミナルで Enterキーを押してください")
    print("\n")
    
    input("👉 準備完了後、Enterキーを押してください: ")
    
    print("\n🔄 自動出品処理を開始します...")
    list_item_on_yahoo_auction(driver, item_data)
    
    print("\n" + "="*60)
    print("✅ テスト完了しました！")
    print("="*60)
    print("\n🎉 ヤフオクへの出品処理が完了しました！")
    print("   ブラウザで確認画面を確認してください。")
    print("\n⏳ ブラウザを閉じずに開いたままにします...")
    
except Exception as e:
    print(f"\n❌ エラーが発生しました: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
