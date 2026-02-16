@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
set ERROR_FLAG=0
set START_TIME=%time%

REM バッチファイルのディレクトリに移動
cd /d "%~dp0"

echo ========================================
echo   自動実行バッチ開始
echo ========================================
echo 開始時刻: %date% %time%
echo.

echo [1/6] メルカリCSVダウンロード...
call 1_mercari_csv_download.bat
set STEP1_ERROR=%errorlevel%
echo   終了コード: %STEP1_ERROR%
if %STEP1_ERROR% neq 0 (
    echo   ❌ エラーが発生しました。処理を中止します。
    set ERROR_FLAG=1
    pause
    goto :error_exit
)

echo.
echo [2/6] メルカリ画像収集...
call 2_mercari_image_collection.bat
set STEP2_ERROR=%errorlevel%
echo   終了コード: %STEP2_ERROR%
if %STEP2_ERROR% neq 0 (
    echo   ❌ エラーが発生しました。処理を中止します。
    set ERROR_FLAG=1
    pause
    goto :error_exit
)

echo.
echo [3/6] ラクマ・メルカリスクレイピング...
call 3_rakuma_mercari_scraper.bat
set STEP3_ERROR=%errorlevel%
echo   終了コード: %STEP3_ERROR%
if %STEP3_ERROR% neq 0 (
    echo   ❌ エラーが発生しました。処理を中止します。
    set ERROR_FLAG=1
    pause
    goto :error_exit
)

echo.
echo [4/6] ラクマ下書き移動...
call 4_rakuma_draft_mover.bat
if %errorlevel% neq 0 (
    echo   ❌ エラーが発生しました。処理を中止します。
    set ERROR_FLAG=1
    goto :error_exit
)

echo.
echo [5/6] ラクマ新規出品...
call 5_rakuma_new_items.bat
if %errorlevel% neq 0 (
    echo   ⚠️ 警告: エラーが発生しましたが続行します
)

echo.
echo [6/6] ヤフオク出品（スキップ可）...
call 6_yahoo_auction_post.bat
if %errorlevel% neq 0 (
    echo   ⚠️ 警告: ヤフオク出品でエラーが発生しました（想定内）
)

:success_exit
echo.
echo ========================================
echo   全処理完了
echo ========================================
set END_TIME=%time%
echo 終了時刻: %date% %time%
echo.

REM Slack通知（成功）
..\\.venv\\Scripts\\python.exe send_slack_notification.py "自動実行バッチが正常に完了しました。 開始: %START_TIME% 終了: %END_TIME%" "success"
goto :end

:error_exit
echo.
echo ========================================
echo   エラーにより処理を中止しました
echo ========================================
set END_TIME=%time%
echo 終了時刻: %date% %time%
echo.
pause

REM Slack通知（失敗）
..\\.venv\\Scripts\\python.exe send_slack_notification.py "自動実行バッチでエラーが発生しました。 開始: %START_TIME% 終了: %END_TIME% 出品作業は実行されませんでした。" "error"
goto :end

:end
endlocal