@echo off
chcp 65001 > nul
cd /d "C:\Users\progr\Desktop\Python\mercari_dorekai"
"C:\Users\progr\Desktop\Python\.venv\Scripts\python.exe" weekend_csv_scheduler.py >> scheduler_log.txt 2>&1
