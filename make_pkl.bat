@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: -----------------------------------------------------------------------
:: make_pkl.bat — создаёт .pkl файл модели в нужном Python-окружении.
::
:: Использование:
::   make_pkl.bat путь\к\my_model.py
::
:: Результат: рядом с .py файлом появится .pkl с тем же именем.
:: Пример:
::   make_pkl.bat models\my_model.py  ->  models\my_model.pkl
:: -----------------------------------------------------------------------

if "%~1" == "" (
    echo.
    echo  Использование: make_pkl.bat путь\к\my_model.py
    echo.
    echo  Скрипт создаст .pkl файл рядом с исходником, используя
    echo  Python 3.14.x — ту же версию, что и на боевом сервере.
    echo.
    pause
    exit /b 1
)

set MODEL_PY=%~f1

if not exist "%MODEL_PY%" (
    echo [ОШИБКА] Файл не найден: %MODEL_PY%
    pause
    exit /b 1
)

:: Check venv exists
if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Виртуальное окружение не найдено.
    echo          Сначала запустите start.bat, чтобы создать окружение.
    pause
    exit /b 1
)

:: Check venv Python version is 3.14
for /f "tokens=2" %%V in ('".venv\Scripts\python.exe" --version 2^>^&1') do set VENV_VER=%%V
if not "!VENV_VER:~0,4!" == "3.14" (
    echo [ОШИБКА] Окружение .venv использует Python !VENV_VER!, а не 3.14.x.
    echo          Запустите start.bat — он пересоздаст окружение на нужной версии.
    pause
    exit /b 1
)

echo.
echo  ==============================
echo   RoboCup — сборка модели
echo  ==============================
echo.
echo [OK] Python !VENV_VER! в окружении .venv
echo [*]  Исходник: %MODEL_PY%
echo.

".venv\Scripts\python.exe" _make_pkl_helper.py "%MODEL_PY%"
set BUILD_RC=%ERRORLEVEL%

if %BUILD_RC% neq 0 (
    echo.
    echo [ОШИБКА] Не удалось создать .pkl — см. сообщение выше.
    pause
    exit /b %BUILD_RC%
)

echo.
echo  Файл готов! Загрузите его на сайт через кнопку "Загрузить модель".
echo.
pause
exit /b 0
