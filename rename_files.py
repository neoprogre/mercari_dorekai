import os

IMAGE_DIR = r"\\LS210DNBD82\share\平良\Python\mercari_dorekai\mercari_images"

def rename_files():
    """
    IMAGE_DIR 内のファイル名末尾にある '@jpg' を削除します。
    """
    if not os.path.isdir(IMAGE_DIR):
        print(f"エラー: ディレクトリが見つかりません: {IMAGE_DIR}")
        return

    renamed_count = 0
    print(f"ディレクトリ '{IMAGE_DIR}' をスキャンしています...")
    try:
        for filename in os.listdir(IMAGE_DIR):
            if filename.endswith('@jpg'):
                old_path = os.path.join(IMAGE_DIR, filename)
                # 末尾の '@jpg' を削除
                new_filename = filename[:-4]
                new_path = os.path.join(IMAGE_DIR, new_filename)

                # 新しいファイル名が既に存在するかチェック
                if os.path.exists(new_path):
                    print(f"スキップ: '{new_filename}' は既に存在するため、古いファイル '{filename}' を削除します。")
                    try:
                        os.remove(old_path)
                    except OSError as e:
                        print(f"エラー: 古いファイル '{filename}' の削除に失敗しました: {e}")
                    continue

                try:
                    os.rename(old_path, new_path)
                    print(f"リネーム: '{filename}' -> '{new_filename}'")
                    renamed_count += 1
                except OSError as e:
                    print(f"エラー: '{filename}' のリネームに失敗しました: {e}")
    except FileNotFoundError:
        print(f"エラー: ディレクトリにアクセスできません: {IMAGE_DIR}")
        print("ネットワークドライブが接続されているか確認してください。")
        return
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")
        return


    if renamed_count == 0:
        print("\n'@jpg' で終わるファイルは見つかりませんでした。")
    else:
        print(f"\n合計 {renamed_count} 個のファイルをリネームしました。")

if __name__ == "__main__":
    rename_files()
