@echo off
title MeituEcomAgent
cd /d "%~dp0"

echo.
echo ============================================================
echo   MeituEcomAgent - Startup Script
echo ============================================================
echo.

echo [*] Stopping old containers...
docker compose down 2>nul
if %errorlevel% neq 0 docker-compose down 2>nul

echo [*] Building image (first time may take 5-10 min)...
docker compose build 2>nul
if %errorlevel% neq 0 docker-compose build
if %errorlevel% neq 0 (
    echo.
    echo [X] Build failed! Please check network and retry.
    pause
    exit /b 1
)

echo [*] Starting services...
docker compose up -d 2>nul
if %errorlevel% neq 0 docker-compose up -d
if %errorlevel% neq 0 (
    echo [X] Startup failed!
    docker compose logs --tail 20 2>nul
    docker-compose logs --tail 20 2>nul
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   [OK] Startup successful!
echo ============================================================
echo.
echo   Web UI  : http://localhost:8002
echo   API Docs: http://localhost:8002/docs
echo   Health  : http://localhost:8002/api/v1/health
echo.
echo   Logs    : docker compose logs -f api
echo   Stop    : docker compose down
echo ============================================================
echo.

start http://localhost:8002

pause
