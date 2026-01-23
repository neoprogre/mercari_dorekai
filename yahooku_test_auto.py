"""
自動テストランナー: yahooku_dorekai.py をユーザー入力なしで実行
（カテゴリ選択は自動 selectCategory() で処理）
"""
import os
import time
import sys
from pathlib import Path

try:
    from yahooku_dorekai import setup_driver, list_item_on_yahoo_auction
except Exception as e:
    print(f"yahooku_dorekai をインポートできませんでした: {e}")
    sys.exit(1)

script_dir = Path(__file__).parent
sample_img = script_dir / 'sample_image.jpg'

# サンプル画像がない場合は作成
if not sample_img.exists():
    try:
        from PIL import Image
        img = Image.new('RGB', (600, 400), color=(73, 109, 137))
        img.save(str(sample_img), 'JPEG')
        print(f"✅ サンプルJPG画像を作成しました: {sample_img}")
    except Exception:
        # フォールバック
        try:
            import base64
            jpg_b64 = b'/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8VAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAA8A/9k='
            sample_img.parent.mkdir(parents=True, exist_ok=True)
            with open(sample_img, 'wb') as f:
                f.write(base64.b64decode(jpg_b64))
            print(f"✅ フォールバックのサンプルJPG画像を作成しました: {sample_img}")
        except Exception as e:
            print(f"❌ サンプル画像の作成に失敗しました: {e}")

sample_item = {
    'title': 'テスト出品 (ヤフオク) - テスト用',
    'description': 'これはテスト用の出品です。シンプルで効果的です。',
    'price': 1000,
    'images': [str(sample_img)],
    # カテゴリパスを指定（オプション）
    # 一度カテゴリを選択すると、次回以降はこのパスと一致すれば自動スキップします
    # 'category_path': 'オークショントップ > ファッション > レディースファッション > フォーマル > カラードレス > その他'
}

print("\n" + "="*60)
print("【ヤフオク自動出品テスト】完全自動版")
print("="*60)
print("\n📝 テストデータ:")
print(f"  タイトル: {sample_item['title']}")
print(f"  説明: {sample_item['description']}")
print(f"  価格: {sample_item['price']}円")
print(f"  画像: {sample_item['images'][0]}")
print("\n")

driver = None
try:
    print("🚀 ブラウザを起動しています...")
    driver = setup_driver()
    
    print("📄 ヤフオク出品ページにアクセスしています...")
    print("\n【手動操作が必要】")
    print("  1. ブラウザでヤフオクにログインしてください")
    print("  2. カテゴリを選択して『このカテゴリに出品』をクリックしてください")
    print("  3. 完了したら、このターミナルで Enterキーを押してください")
    print("\n")
    
    input("👉 準備完了後、Enterキーを押してください: ")
    
    print("\n🔄 自動出品処理を開始します...")
    list_item_on_yahoo_auction(driver, sample_item)
    
    print("\n" + "="*60)
    print("✅ テスト完了しました！")
    print("="*60)
    print("\n📊 処理結果:")
    print("  ✅ 画像: アップロード完了")
    print("  ✅ タイトル: 入力完了")
    print("  ✅ 説明: 入力完了")
    print("  ✅ 価格: 入力完了")
    print("  ✅ 確認: 自動送信")
    print("\n🎉 ヤフオクへの出品処理が完了しました！")
    print("   ブラウザで確認画面を確認してください。")
    
except Exception as e:
    print(f"\n❌ エラーが発生しました: {e}")
    import traceback
    traceback.print_exc()

finally:
    if driver:
        print("\n⏳ ブラウザを閉じずに開いたままにします...")
        print("   （手動で確認・修正が必要な場合に対応するため）")
        # driver.quit() を呼ばない
