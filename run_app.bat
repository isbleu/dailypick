@chcp 65001 >nul
@echo off
title DailyPick Web Platform

echo ==================================================
echo Starting DailyPick Web Platform...
echo ==================================================

cd /d "%~dp0"

if not exist "frontend\node_modules\" (
    echo [INFO] Installing Node modules...
    cd frontend
    call npm install
    cd ..
)

echo [INFO] Opening Browser: http://localhost:3000
start "" "http://localhost:3000"

node frontend\server.js
pause
