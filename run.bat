@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python -m pip install -q -r requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python app.py
pause
exit /b
:fail
echo 启动失败，请检查 Python 3.10+ 和网络连接。
pause
exit /b 1
