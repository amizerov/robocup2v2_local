#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo ""
echo " =============================="
echo "  RoboCup Local Gamemaster"
echo " =============================="
echo ""

# -----------------------------------------------------------------------
# Require Python 3.14.x — same minor version as the production server.
# Models (.pkl) saved with a different Python version will not work on
# the server (cloudpickle serialises bytecode which is version-specific).
# -----------------------------------------------------------------------
PYTHON=""
for cmd in python3.14 python3 python; do
    if command -v "$cmd" > /dev/null 2>&1; then
        VER=$("$cmd" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>/dev/null || echo "")
        if [ "$VER" = "3.14" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ОШИБКА] Python 3.14.x не найден."
    echo ""
    echo "  Боевой сервер работает на Python 3.14."
    echo "  Чтобы модель работала одинаково локально и на сайте,"
    echo "  установите Python 3.14 с https://python.org/downloads/"
    echo ""
    echo "  Текущие Python в системе:"
    for cmd in python3 python; do
        command -v "$cmd" > /dev/null 2>&1 && "$cmd" --version 2>&1 || true
    done
    exit 1
fi

PY_VER=$("$PYTHON" --version 2>&1 | awk '{print $2}')
echo "[OK] Найден $PYTHON $PY_VER — соответствует боевому серверу."
echo ""

# Create venv if needed, or recreate if wrong Python version
if [ -f ".venv/bin/python" ]; then
    VENV_VER=$(.venv/bin/python -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>/dev/null || echo "")
    if [ "$VENV_VER" != "3.14" ]; then
        echo "[!] Существующий venv на Python $VENV_VER — пересоздаём на $PY_VER..."
        rm -rf .venv
    fi
fi
if [ ! -f ".venv/bin/activate" ]; then
    echo "[*] Создаём виртуальное окружение на $PYTHON $PY_VER..."
    "$PYTHON" -m venv .venv
fi

source .venv/bin/activate

echo "[*] Устанавливаем зависимости..."
pip install -r requirements.txt -q

# Open browser after short delay (background)
(sleep 2 && (
    xdg-open  http://127.0.0.1:8080 2>/dev/null ||
    open       http://127.0.0.1:8080 2>/dev/null ||
    true
)) &

echo ""
echo "[OK] Сервер запускается на http://127.0.0.1:8080"
echo "     Браузер откроется автоматически."
echo "     Нажмите Ctrl+C для остановки."
echo ""

python server.py
