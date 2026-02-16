"""
指定した品番の画像を re フォルダに移動し、1枚目の明るさを調整するスクリプト
毎日5品番程度を処理する想定
"""
import os
import re
from PIL import Image, ImageEnhance
import argparse
import shutil

# 設定
IMAGE_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images"
RE_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images\re"
BACKUP_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images\バックアップ_明るさ調整前"

def find_all_images(product_number, search_dir=IMAGE_DIR):
    """
    指定した品番の全ての画像を探す
    
    Args:
        product_number: 品番（例: "1001"）
        search_dir: 検索するディレクトリ
    
    Returns:
        画像ファイルパスのリスト（連番順）
    """
    if not os.path.exists(search_dir):
        return []
    
    images = []
    for filename in os.listdir(search_dir):
        # 品番-連番.拡張子 の形式をチェック
        match = re.match(rf'^{re.escape(product_number)}-(\d+)(\.\w+)$', filename, re.I)
        if match:
            filepath = os.path.join(search_dir, filename)
            seq_num = int(match.group(1))
            images.append((seq_num, filepath))
    
    # 連番順にソート
    images.sort(key=lambda x: x[0])
    return [filepath for _, filepath in images]

def move_images_to_re(product_number, copy_mode=True, dry_run=False):
    """
    指定した品番の全画像をreフォルダに移動（またはコピー）
    
    Args:
        product_number: 品番
        copy_mode: True=コピー（元を残す）, False=移動（元を削除）
        dry_run: ドライランモード
    
    Returns:
        (moved_files, first_image_path) - 移動したファイル数と1枚目のパス
    """
    # 元フォルダから画像を探す
    images = find_all_images(product_number, IMAGE_DIR)
    
    if not images:
        return 0, None
    
    os.makedirs(RE_DIR, exist_ok=True)
    
    moved_count = 0
    first_image_in_re = None
    
    action = "コピー" if copy_mode else "移動"
    
    for image_path in images:
        filename = os.path.basename(image_path)
        dest_path = os.path.join(RE_DIR, filename)
        
        if dry_run:
            print(f"    [予定] {action}: {filename}")
            moved_count += 1
            if filename.endswith(('-1.jpg', '-1.jpeg', '-1.png', '-1.gif', '-1.webp')):
                first_image_in_re = dest_path
        else:
            try:
                if copy_mode:
                    shutil.copy2(image_path, dest_path)
                else:
                    shutil.move(image_path, dest_path)
                print(f"    ✅ {action}: {filename}")
                moved_count += 1
                
                # 1枚目の画像パスを記録
                if filename.endswith(('-1.jpg', '-1.jpeg', '-1.png', '-1.gif', '-1.webp')):
                    first_image_in_re = dest_path
            except Exception as e:
                print(f"    ❌ {action}失敗: {filename} - {e}")
    
    return moved_count, first_image_in_re

def brighten_image(image_path, brightness_factor=1.5, backup=True, dry_run=False):
    """
    画像の明るさを調整
    
    Args:
        image_path: 画像ファイルのパス
        brightness_factor: 明るさの係数（1.0=元のまま、1.5=1.5倍明るく、2.0=2倍明るく）
        backup: バックアップを取るかどうか
        dry_run: ドライランモード
    """
    if dry_run:
        print(f"    [予定] 明るさ調整: {os.path.basename(image_path)} (係数: {brightness_factor})")
        if backup:
            print(f"    [予定] バックアップ作成")
        return True
    
    try:
        # 画像を開く
        img = Image.open(image_path)
        filename = os.path.basename(image_path)
        
        # バックアップを作成（各ファイルごとに個別チェック）
        if backup:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            backup_path = os.path.join(BACKUP_DIR, filename)
            # 該当ファイルのバックアップが存在しない場合のみ保存
            if not os.path.exists(backup_path):
                shutil.copy2(image_path, backup_path)
                print(f"    💾 バックアップ保存: {filename}")
            else:
                print(f"    ℹ️ バックアップスキップ（既に存在: {filename}）")
        
        # 明るさを調整
        enhancer = ImageEnhance.Brightness(img)
        brightened_img = enhancer.enhance(brightness_factor)
        
        # reフォルダの画像に上書き保存
        brightened_img.save(image_path, quality=95)
        print(f"    ✅ 明るさ調整完了 (re): {filename} (係数: {brightness_factor})")
        
        # 元のmercari_imagesフォルダにも保存（上書き）
        original_path = os.path.join(IMAGE_DIR, filename)
        brightened_img.save(original_path, quality=95)
        print(f"    ✅ 元フォルダにも保存: {filename}")
        
        return True
    except Exception as e:
        print(f"    ❌ エラー: {os.path.basename(image_path)} - {e}")
        return False

def process_product_numbers(product_numbers, brightness_factor, backup, copy_mode, dry_run):
    """
    複数の品番を処理
    1. 全画像をreフォルダに移動（またはコピー）
    2. 1枚目のみ明るさ調整
    
    Args:
        product_numbers: 品番のリスト
        brightness_factor: 明るさの係数
        backup: バックアップを取るかどうか
        copy_mode: True=コピー（元を残す）, False=移動
        dry_run: ドライランモードかどうか
    """
    if not os.path.exists(IMAGE_DIR):
        print(f"❌ 画像フォルダが見つかりません: {IMAGE_DIR}")
        return
    
    os.makedirs(RE_DIR, exist_ok=True)
    
    success_count = 0
    not_found_count = 0
    error_count = 0
    total_moved = 0
    skipped_count = 0
    
    print(f"\n{'='*60}")
    if dry_run:
        print("🔍 ドライランモード（プレビューのみ、実際の変更なし）")
    print(f"処理対象: {len(product_numbers)}件")
    print(f"明るさ係数: {brightness_factor} (1.0=元のまま)")
    print(f"移動モード: {'コピー（元を残す）' if copy_mode else '移動（元を削除）'}")
    print(f"バックアップ: {'あり' if backup else 'なし'}")
    print(f"移動先: {RE_DIR}")
    print(f"{'='*60}\n")
    
    for product_number in product_numbers:
        product_number = str(product_number).strip()
        if not product_number:
            continue
        
        print(f"▶ 品番: {product_number}")
        
        # reフォルダに既に画像が存在するかチェック
        re_images = glob.glob(os.path.join(RE_DIR, f"{product_number}-*.jpg"))
        if re_images:
            print(f"    ℹ️ reフォルダに既に画像が存在（{len(re_images)}枚）- スキップ")
            skipped_count += 1
            continue
        
        # 1. 全画像をreフォルダに移動/コピー
        moved_count, first_image_path = move_images_to_re(product_number, copy_mode, dry_run)
        
        if moved_count == 0:
            print(f"    ⚠️ 画像が見つかりません")
            not_found_count += 1
            continue
        
        total_moved += moved_count
        
        # 2. 1枚目のみ明るさ調整
        if first_image_path:
            if brighten_image(first_image_path, brightness_factor, backup, dry_run):
                success_count += 1
            else:
                error_count += 1
        else:
            print(f"    ⚠️ 1枚目の画像が見つかりません")
            not_found_count += 1
    
    # 結果表示
    print(f"\n{'='*60}")
    if dry_run:
        print(f"🔍 ドライラン完了（実際の変更なし）")
        print(f"  移動/コピー予定: {total_moved}枚")
        print(f"  明るさ調整予定: {success_count}枚")
        print(f"  見つからない: {not_found_count}件")
        if skipped_count > 0:
            print(f"  スキップ: {skipped_count}件（reフォルダに既存）")
        print(f"\n💡 実際に実行する場合は --dry-run オプションなしで実行してください")
    else:
        print(f"✅ 処理完了")
        print(f"  移動/コピー成功: {total_moved}枚")
        print(f"  明るさ調整成功: {success_count}枚")
        print(f"  見つからない: {not_found_count}件")
        if skipped_count > 0:
            print(f"  スキップ: {skipped_count}件（reフォルダに既存）")
        print(f"  エラー: {error_count}枚")
        if backup and success_count > 0:
            print(f"\n💾 バックアップ保存先:")
            print(f"   {BACKUP_DIR}")
            print(f"   ※各ファイルのバックアップが存在しない場合のみ保存されます")
        print(f"\n📁 調整後の画像保存先:")
        print(f"   ・reフォルダ: {RE_DIR}")
        print(f"   ・元フォルダ: {IMAGE_DIR} (上書き)")
        if not copy_mode:
            print(f"\n⚠️ 元フォルダから画像を移動しました")
    print(f"{'='*60}")

def main():
    parser = argparse.ArgumentParser(
        description='指定した品番の画像をreフォルダに移動・コピーし、1枚目の明るさを調整',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 品番を直接指定（5品番を一度に処理）
  python brighten_images.py 1001 1002 1003 1004 1005
  
  # 標準入力から品番を入力（複数行で貼り付け可能）
  python brighten_images.py --input
  (品番を入力して Ctrl+Z → Enter で終了)
  
  # 明るさ係数を指定（デフォルト: 1.5）
  python brighten_images.py --input --brightness 2.0
  
  # 移動モード（元フォルダから削除）
  python brighten_images.py 1001 1002 --move
  
  # バックアップなし
  python brighten_images.py 1001 1002 --no-backup
  
  # ドライラン（プレビューのみ）
  python brighten_images.py 1001 1002 --dry-run
  
  # ファイルから品番リストを読み込み
  python brighten_images.py --file product_numbers.txt

処理フロー:
  1. 指定した品番の全画像をreフォルダに移動/コピー
  2. reフォルダ内の1枚目のみ明るさ調整
  3. バックアップは明るさ調整前に別フォルダに保存

バックアップの仕組み:
  - デフォルト：コピーモード（元フォルダに画像が残る）
  - 明るさ調整前の画像は「バックアップ_明るさ調整前」フォルダに保存
  - --move オプション：元フォルダから削除（移動）

明るさ係数の目安:
  1.0 = 元のまま
  1.3 = 少し明るく
  1.5 = 明るく（デフォルト）
  2.0 = かなり明るく
  0.8 = 少し暗く
        """
    )
    
    parser.add_argument('product_numbers', nargs='*', 
                        help='品番（スペース区切りで複数指定可能、毎日5品番程度推奨）')
    parser.add_argument('-f', '--file', 
                        help='品番リストが記載されたテキストファイル（1行1品番）')
    parser.add_argument('-i', '--input', action='store_true',
                        help='標準入力から品番を読み込む（1行1品番、Ctrl+Zで終了）')
    parser.add_argument('-b', '--brightness', type=float, default=1.5,
                        help='明るさの係数（デフォルト: 1.5）')
    parser.add_argument('--move', action='store_true',
                        help='移動モード（元フォルダから削除、デフォルトはコピー）')
    parser.add_argument('--no-backup', action='store_true',
                        help='バックアップを作成しない')
    parser.add_argument('--dry-run', action='store_true',
                        help='ドライランモード（プレビューのみ、実際の変更なし）')
    
    args = parser.parse_args()
    
    # 品番リストを取得
    product_numbers = []
    
    # 標準入力から
    if args.input:
        print("品番を入力してください（1行1品番、Ctrl+Z → Enterで終了）:")
        import sys
        for line in sys.stdin:
            line = line.strip()
            if line and not line.startswith('#'):
                product_numbers.append(line)
    
    # コマンドライン引数から
    if args.product_numbers:
        product_numbers.extend(args.product_numbers)
    
    # ファイルから
    if args.file:
        if not os.path.exists(args.file):
            print(f"❌ ファイルが見つかりません: {args.file}")
            return
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        product_numbers.append(line)
        except Exception as e:
            print(f"❌ ファイル読み込みエラー: {e}")
            return
    
    if not product_numbers:
        parser.print_help()
        print("\n❌ エラー: 品番を指定してください")
        return
    
    # 重複を削除
    product_numbers = list(dict.fromkeys(product_numbers))
    
    # 処理実行
    process_product_numbers(
        product_numbers=product_numbers,
        brightness_factor=args.brightness,
        backup=not args.no_backup,
        copy_mode=not args.move,  # moveフラグがFalseならコピーモード
        dry_run=args.dry_run
    )

if __name__ == "__main__":
    main()
