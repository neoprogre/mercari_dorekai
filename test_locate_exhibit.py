# テスト用: exhibit_button の検出テスト
import os, traceback
from PIL import Image
import pyautogui

IMG = r"C:\Users\progr\Desktop\Python\mercari_dorekai\images\exhibit_button1.png"

print("exists:", os.path.exists(IMG))
try:
    img = Image.open(IMG)
    print("image size/mode:", img.size, img.mode)
except Exception as e:
    print("image open error:", e)
    img = None

for conf in (0.85, 0.75, 0.65, 0.6):
    try:
        res = pyautogui.locateCenterOnScreen(IMG, confidence=conf)
        print(f"locate(conf={conf}):", res)
    except Exception as e:
        print(f"locate(conf={conf}) exception:", repr(e))
        traceback.print_exc()

    try:
        resg = pyautogui.locateCenterOnScreen(IMG, confidence=conf, grayscale=True)
        print(f"locate(grayscale, conf={conf}):", resg)
    except Exception as e:
        print(f"locate(grayscale, conf={conf}) exception:", repr(e))
        traceback.print_exc()

# OpenCV フォールバック（インストールされていれば実行）
try:
    import cv2
    import numpy as np
    print("cv2 version:", cv2.__version__)
    ss = pyautogui.screenshot()
    ss_np = cv2.cvtColor(np.array(ss), cv2.COLOR_RGB2BGR)
    tpl = cv2.imread(IMG)
    if tpl is None:
        print("cv2: template load failed")
    else:
        res = cv2.matchTemplate(ss_np, tpl, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        print("cv2 matchTemplate max_val:", max_val, "max_loc:", max_loc)
except Exception as e:
    print("OpenCV test skipped/failed:", e)