@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python main.py > error_log.txt 2>&1
if errorlevel 1 (
    echo 오류 발생! error_log.txt 확인하세요.
    notepad error_log.txt
) else (
    echo 정상 종료
)
pause
