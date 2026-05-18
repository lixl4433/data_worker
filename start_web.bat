@echo off
chcp 65001 >nul
title 量化选股系统 - Web 服务

echo ============================================================
echo  量化选股系统 - Web 服务启动脚本 (Windows)
echo ============================================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 检查依赖是否安装
echo [检查] 验证依赖...
python -c "import fastapi" >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 首次运行需要安装依赖，正在安装...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败，请手动执行: pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo [完成] 依赖安装成功
)

:: 初始化数据库
echo [检查] 初始化数据库...
python -c "from core.db_manager import init_db; init_db(); print('数据库初始化成功')"

:: 启动 Web 服务
echo.
echo ============================================================
echo  启动 Web 服务...
echo  访问地址: http://localhost:7654
echo  按 Ctrl+C 停止服务
echo ============================================================
echo.

python main.py

pause
