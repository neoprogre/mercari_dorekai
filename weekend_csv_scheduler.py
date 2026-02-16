import json
import os
import time
import urllib.request
from datetime import datetime, time as dt_time
from pathlib import Path

import csv_exhibitor
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
CSV_DIR = Path(os.getenv("CSV_DIR", str(BASE_DIR / "downloads")))
CSV_PREFIX = "生成_"
CSV_EXT = ".csv"
RUN_TIME = "20:00"  # 実行時刻（24時間形式）

# 平日の祝日を設定（土日は自動判定）
HOLIDAY_1 = "20260216"
HOLIDAY_2 = ""
HOLIDAY_3 = ""
HOLIDAY_4 = ""

STATE_FILE = Path(__file__).with_name("weekend_csv_scheduler_state.json")


def log(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def send_slack_message(message: str) -> bool:
    load_dotenv(csv_exhibitor.ENV_PATH)
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        log("SLACK_WEBHOOK_URL not set. Skipping Slack notification.")
        return False

    payload = json.dumps({"text": message}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except Exception as exc:
        log(f"Slack notification failed: {exc}")
        return False


def format_result_message(now: datetime, result: dict) -> str:
    csv_name = os.path.basename(result.get("csv_path", ""))
    status = "成功" if result.get("upload_success") else "失敗"
    rows = result.get("rows", 0)
    private_processed = result.get("private_processed", 0)
    private_skipped = result.get("private_skipped", 0)
    size_processed = result.get("size_processed", 0)
    size_skipped = result.get("size_skipped", 0)

    return (
        f"メルカリ出品結果 ({now.strftime('%Y-%m-%d %H:%M')})\n"
        f"CSV: {csv_name}\n"
        f"登録: {status}\n"
        f"非公開設定: processed={private_processed}, skipped={private_skipped}\n"
        f"サイズ設定: processed={size_processed}, skipped={size_skipped}\n"
        f"CSV行数: {rows}"
    )


def parse_run_time(value: str) -> dt_time:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("RUN_TIME must be HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    return dt_time(hour=hour, minute=minute)


def load_last_run_date() -> str:
    if not STATE_FILE.exists():
        return ""
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return str(data.get("last_run", ""))
    except Exception:
        return ""


def save_last_run_date(yyyymmdd: str) -> None:
    data = {"last_run": yyyymmdd}
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")


def is_weekend(date_value: datetime) -> bool:
    return date_value.weekday() in (5, 6)


def is_holiday(date_value: datetime) -> bool:
    yyyymmdd = date_value.strftime("%Y%m%d")
    holiday_list = [HOLIDAY_1, HOLIDAY_2, HOLIDAY_3, HOLIDAY_4]
    holiday_list = [item for item in holiday_list if item]
    return yyyymmdd in holiday_list


def is_target_day(date_value: datetime) -> bool:
    return is_weekend(date_value) or is_holiday(date_value)


def get_csv_path(date_value: datetime) -> str:
    filename = f"{CSV_PREFIX}{date_value.strftime('%Y%m%d')}{CSV_EXT}"
    return str(CSV_DIR / filename)


def should_run_today(now: datetime, run_time: dt_time, last_run: str) -> bool:
    today = now.strftime("%Y%m%d")
    if today == last_run:
        return False
    if not is_target_day(now):
        return False
    return now.time() >= run_time


def run_once() -> None:
    run_time = parse_run_time(RUN_TIME)
    last_run = load_last_run_date()
    now = datetime.now()
    
    log(f"Checking... now={now.strftime('%Y-%m-%d %H:%M')}, last_run={last_run}, is_weekend={is_weekend(now)}, is_holiday={is_holiday(now)}")

    if not should_run_today(now, run_time, last_run):
        return

    csv_path = get_csv_path(now)
    log(f"CSV path: {csv_path}")
    
    if not os.path.exists(csv_path):
        log(f"CSV not found for today: {csv_path}")
        save_last_run_date(now.strftime("%Y%m%d"))
        return

    log(f"Start processing: {csv_path}")
    try:
        result = csv_exhibitor.main(csv_path)
        message = format_result_message(now, result)
        send_slack_message(message)
    except Exception as exc:
        log(f"Execution failed: {exc}")
        send_slack_message(
            f"メルカリ出品結果 ({now.strftime('%Y-%m-%d %H:%M')})\n"
            f"CSV: {os.path.basename(csv_path)}\n"
            f"登録: 失敗\n"
            f"エラー: {exc}"
        )
    save_last_run_date(now.strftime("%Y%m%d"))


def run_forever(poll_seconds: int = 60) -> None:
    log("Scheduler started.")
    while True:
        run_once()
        time.sleep(poll_seconds)


if __name__ == "__main__":
    run_forever()
