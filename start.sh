#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo ""
echo " =============================="
echo "  RoboCup Local Gamemaster"
echo " =============================="
echo ""

# Find Python 3.10+
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" > /dev/null 2>&1; then
        VER=$("$cmd" -c "import sys; print(sys.version_info >= (3,10))" 2>/dev/null || echo "False")
        if [ "$VER" = "True" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ОШИБКА] Python 3.10+ не найден."
    echo "         Установите Python: https://python.org"
    exit 1
fi

echo "[*] Используем: $($PYTHON --version)"

# Create venv if needed
if [ ! -f ".venv/bin/activate" ]; then
    echo "[*] Создаём виртуальное окружение..."
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
