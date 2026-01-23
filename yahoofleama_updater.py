import pyautogui
import time
import logging
import sys
import os

# ログ設定
logging.basicConfig(
    filename="relist.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def click_button(image_path, timeout=10, confidence=0.7):
    """
    指定した画像を画面上から探してクリックする関数
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            location = pyautogui.locateCenterOnScreen(image_path, confidence=confidence)
        except Exception as e:
            debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_exception_screen.png")
            pyautogui.screenshot(debug_path)
            logging.error(f"Exception while locating {image_path}: {e}. Screenshot saved to {debug_path}")
            return False

        if location:
            pyautogui.moveTo(location)
            pyautogui.click()
            logging.info(f"Clicked {image_path} at {location}")
            return True

        time.sleep(0.5)

    # 見つからなかった場合はスクリーンショット保存
    debug_path = os.path.join(os.path.dirname(__file__), "debug_screen.png")
    pyautogui.screenshot(debug_path)
    logging.warning(f"Timeout: {image_path} not found. Screenshot saved to {debug_path}")
    return False

def relist_one_item():
    # スクリプトの場所を基準に画像へのパスを組み立てる
    script_dir = os.path.dirname(os.path.abspath(__file__))
    relist_button_path = os.path.join(script_dir, "relist_button.png")
    confirm_button_path = os.path.join(script_dir, "confirm_button.png")

    # 1. 「再出品」ボタンをクリック
    if not click_button(relist_button_path, timeout=15, confidence=0.6):
        return False

    time.sleep(2)

    # 2. 「出品する」ボタンをクリック
    if not click_button(confirm_button_path, timeout=15, confidence=0.6):
        return False

    logging.info("Relist completed successfully")
    return True

if __name__ == "__main__":
    try:
        success = relist_one_item()
        if success:
            print("✅ 再出品完了")
        else:
            print("⚠️ 再出品失敗（ログとdebug_screen.pngを確認してください）")
    except KeyboardInterrupt:
        print("⏹ 中断されました")
        sys.exit(0)