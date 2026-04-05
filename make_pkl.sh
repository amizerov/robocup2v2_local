#!/usr/bin/env bash
# -----------------------------------------------------------------------
# make_pkl.sh — создаёт .pkl файл модели в нужном Python-окружении.
#
# Использование:
#   ./make_pkl.sh путь/к/my_model.py
#
# Результат: рядом с .py файлом появится .pkl с тем же именем.
# Пример:
#   ./make_pkl.sh models/my_model.py  ->  models/my_model.pkl
# -----------------------------------------------------------------------
set -e
cd "$(dirname "$0")"

if [ -z "$1" ]; then
    echo ""
    echo "  Использование: ./make_pkl.sh путь/к/my_model.py"
    echo ""
    echo "  Скрипт создаст .pkl файл рядом с исходником, используя"
    echo "  Python 3.14.x — ту же версию, что и на боевом сервере."
    echo ""
    exit 1
fi

MODEL_PY="$(realpath "$1")"

if [ ! -f "$MODEL_PY" ]; then
    echo "[ОШИБКА] Файл не найден: $MODEL_PY"
    exit 1
fi

# Check venv
if [ ! -f ".venv/bin/python" ]; then
    echo "[ОШИБКА] Виртуальное окружение не найдено."
    echo "         Сначала запустите ./start.sh, чтобы создать окружение."
    exit 1
fi

# Check Python version in venv
VENV_VER="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
VENV_MINOR="${VENV_VER%.*}"   # e.g. "3.14"
VENV_MAJ_MIN="${VENV_VER:0:4}"  # first 4 chars: "3.14"

if [ "${VENV_VER:0:4}" != "3.14" ]; then
    echo "[ОШИБКА] Окружение .venv использует Python $VENV_VER, а не 3.14.x."
    echo "         Запустите ./start.sh — он пересоздаст окружение на нужной версии."
    exit 1
fi

echo ""
echo " =============================="
echo "  RoboCup — сборка модели"
echo " =============================="
echo ""
echo "[OK] Python $VENV_VER в окружении .venv"
echo "[*]  Исходник: $MODEL_PY"
echo ""

.venv/bin/python _make_pkl_helper.py "$MODEL_PY"
BUILD_RC=$?

if [ $BUILD_RC -ne 0 ]; then
    echo ""
    echo "[ОШИБКА] Не удалось создать .pkl — см. сообщение выше."
    exit $BUILD_RC
fi

echo ""
echo "  Файл готов! Загрузите его на сайт через кнопку «Загрузить модель»."
echo ""
