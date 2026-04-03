@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ==============================
echo   RoboCup Local Gamemaster
echo  ==============================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден.
    echo          Установите Python 3.10+ с https://python.org
    echo          Не забудьте поставить галочку "Add Python to PATH"
    pause
    exit /b 1
)

:: Create venv if needed
if not exist ".venv\Scripts\activate.bat" (
    echo [*] Создаём виртуальное окружение...
    python -m venv .venv
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать venv.
        pause
        exit /b 1
    )
)

:: Activate venv
call .venv\Scripts\activate.bat

:: Clear Python bytecode cache so latest code is always used
if exist "robocup_sim\__pycache__" rmdir /s /q "robocup_sim\__pycache__"
if exist "__pycache__" rmdir /s /q "__pycache__"

:: Install / update dependencies
echo [*] Устанавливаем зависимости...
pip install -r requirements.txt -q --disable-pip-version-check
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    pause
    exit /b 1
)

echo.
echo [OK] Сервер запускается на http://127.0.0.1:8080
echo      Браузер откроется автоматически.
echo      Нажмите Ctrl+C для остановки.
echo.

python server.py

pause
