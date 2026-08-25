@echo off
chcp 65001 >nul
title 湖滨四季 Web 可视化看板平台

echo ==================================================
echo 🚀 正在启动 湖滨四季 Web 可视化看板平台...
echo ==================================================

cd /d "%~dp0"

if not exist "frontend\node_modules" (
    echo [提示] 首次运行检测到依赖未安装，正在安装 Node 依赖...
    cd frontend
    call npm install
    cd ..
)

echo [提示] 正在自动打开浏览器访问看板: http://localhost:3000
start "" "http://localhost:3000"

node frontend\server.js
pause
