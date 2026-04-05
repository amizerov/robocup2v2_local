@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ==============================
echo   RoboCup Local Gamemaster
echo  ==============================
echo.

:: -----------------------------------------------------------------------
:: Require Python 3.14.x — same minor version as the production server.
:: Models (.pkl) saved with a different Python version will not work on
:: the server (cloudpickle serialises bytecode which is version-specific).
:: -----------------------------------------------------------------------

:: Try python3.14 first, then fall back to python / py
set PYTHON_CMD=
for %%C in (python3.14 python3 python py) do (
    if not defined PYTHON_CMD (
        %%C --version >nul 2>&1
        if not errorlevel 1 (
            for /f "tokens=2" %%V in ('%%C --version 2^>^&1') do (
                set PY_VER=%%V
                if "!PY_VER:~0,4!" == "3.14" set PYTHON_CMD=%%C
            )
        )
    )
)

if not defined PYTHON_CMD (
    echo [ОШИБКА] Python 3.14.x не найден.
    echo.
    echo  Боевой сервер работает на Python 3.14.
    echo  Чтобы модель работала одинаково локально и на сайте,
    echo  установите Python 3.14 с https://python.org/downloads/
    echo  и добавьте его в PATH.
    echo.
    echo  Текущие версии Python в системе:
    for %%C in (python3 python py) do (
        %%C --version 2>nul
    )
    echo.
    pause
    exit /b 1
)

echo [OK] Найден %PYTHON_CMD% !PY_VER! — соответствует боевому серверу.
echo.

:: Create venv if needed (or recreate if it's on the wrong Python version)
if exist ".venv\Scripts\activate.bat" (
    for /f "tokens=2" %%V in ('".venv\Scripts\python.exe" --version 2^>^&1') do set VENV_VER=%%V
    if not "!VENV_VER:~0,4!" == "3.14" (
        echo [!] Существующий venv на Python !VENV_VER! — пересоздаём на !PY_VER!...
        rmdir /s /q .venv
    )
)
if not exist ".venv\Scripts\activate.bat" (
    echo [*] Создаём виртуальное окружение на %PYTHON_CMD% !PY_VER!...
    %PYTHON_CMD% -m venv .venv
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

:: Open browser after 2s delay (background)
start /b cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8080"

:: venv already activated — python in PATH is now the venv python
python server.py

pause
