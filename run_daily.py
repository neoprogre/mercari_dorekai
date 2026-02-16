from datetime import datetime

import csv_exhibitor
import weekend_csv_scheduler as scheduler


def main() -> None:
    now = datetime.now()
    if scheduler.is_target_day(now):
        scheduler.run_once()
        return

    csv_path = scheduler.get_csv_path(now)
    csv_exhibitor.main(csv_path)


if __name__ == "__main__":
    main()
