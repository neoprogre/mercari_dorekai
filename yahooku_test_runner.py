r"""
簡単なテストランナー: yahooku_dorekai.py の出品関数を単独で試すためのスクリプト
使い方:
  - venv を有効化した上で:
      C:\Users\progr\Desktop\Python\.venv\Scripts\python.exe c:\Users\progr\Desktop\Python\mercari_dorekai\yahooku_test_runner.py
  - 実際のアップロードを行いたくない場合は環境変数 DRY_RUN=1 をセットするか、実行中に "dry" と入力してください。

注意:
  - yahooku_dorekai.py が同ディレクトリにあり、Chrome プロファイルの準備 (yahoo_user_data) を推奨します。
  - ログインが必要な場合はブラウザでログインしてください。スクリプトは Enter を待ちます。
"""
import os
import time
import sys
from pathlib import Path

DRY_RUN = os.environ.get('DRY_RUN') == '1'

try:
    from yahooku_dorekai import setup_driver, list_item_on_yahoo_auction
except Exception as e:
    print(f"yahooku_dorekai をインポートできませんでした: {e}")
    sys.exit(1)

script_dir = Path(__file__).parent
sample_img = script_dir / 'sample_image.jpg'  # ヤフオクはJPG/GIFのみ対応

if not sample_img.exists():
    # Pillowで適切なJPGを作成（あれば）、なければBase64フォールバック
    try:
        from PIL import Image
        img = Image.new('RGB', (600, 400), color=(73, 109, 137))
        img.save(str(sample_img), 'JPEG')
        print(f"サンプルJPG画像を作成しました: {sample_img}")
    except Exception:
        # Pillow不可なら組み込みJPGを書き出す（1x1の最小限JPG）
        try:
            import base64
            # 最小限のJPG（1x1ピクセル）
            jpg_b64 = b'/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8VAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAA8A/9k='
            sample_img.parent.mkdir(parents=True, exist_ok=True)
            with open(sample_img, 'wb') as f:
                f.write(base64.b64decode(jpg_b64))
            print(f"フォールバックのサンプルJPG画像を作成しました: {sample_img}")
        except Exception as e:
            print(f"サンプル画像の作成に失敗しました: {e}")

sample_item = {
    'title': 'テスト出品 (ヤフオク) - テスト用',
    'description': 'これはテスト用の出品です。',
    'price': 1000,
    'images': [str(sample_img)]
}

print("--- Yahoo テストランナー ---")
print("DRY_RUN=" + str(DRY_RUN))
print("このスクリプトはブラウザを起動します。ヤフオクにログインしていない場合は、ブラウザでログインしてください。")
if not DRY_RUN:
    resp = input("実際に出品処理を実行しますか？ (y/n/dry) [y]: ").strip().lower() or 'y'
    if resp == 'dry' or resp == 'n':
        DRY_RUN = True

if DRY_RUN:
    print("ドライランモード: 出力内容のみ表示します。")
    print(sample_item)
    sys.exit(0)

# 実行: Selenium ドライバを起動して関数を呼ぶ
driver = None
try:
    driver = setup_driver()
    print("ブラウザを起動しました。")
    print("\n【ステップ1】ヤフオク出品ページにアクセスしてください:")
    print("  1. ヤフオクにログインしてください（まだの場合）")
    print("  2. 出品ページ (https://auctions.yahoo.co.jp/sell/jp/show/submit) にアクセスしてください")
    print("  3. カテゴリを選択して「このカテゴリに出品」をクリックしてください")
    print("  4. 完了したら Enterキーを押してください")
    input("\n準備完了: ")
    
    print("\n出品フローを開始します...")
    list_item_on_yahoo_auction(driver, sample_item)
    print("テスト実行が完了しました。ブラウザは開いたままにします。")
except Exception as e:
    print(f"テスト実行中に例外が発生しました: {e}")
finally:
    # すぐ閉じない: ユーザーが確認できるように少し待つ
    try:
        time.sleep(1)
    except Exception:
        pass
    