@echo off
chcp 65001 >nul
color 0A

echo.
echo ════════════════════════════════════════════════════════════════
echo        文件共享服务器启动脚本
echo ════════════════════════════════════════════════════════════════
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误: 系统未安装Python
    echo 请访问 https://www.python.org/downloads/ 下载安装Python
    pause
    exit /b 1
)

echo ✅ 检测到Python安装

REM 检查是否需要安装依赖
echo.
echo 📦 正在检查依赖...
pip install -q -r requirements.txt

if errorlevel 1 (
    echo ❌ 依赖安装失败
    pause
    exit /b 1
)

echo ✅ 依赖已安装

REM 启动Flask服务器
echo.
echo 🚀 启动文件共享服务器...
echo.
python app.py

pause
