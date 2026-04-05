"""
_make_pkl_helper.py — внутренний скрипт сборки модели.
Вызывается из make_pkl.bat и make_pkl.sh.
Не запускайте напрямую.
"""
import sys
import importlib.util
import pathlib
import cloudpickle

if len(sys.argv) < 2:
    print("Usage: python _make_pkl_helper.py <model.py>")
    sys.exit(1)

model_path = pathlib.Path(sys.argv[1]).resolve()
out_path = model_path.with_suffix('.pkl')

if not model_path.exists():
    print(f"ОШИБКА: файл не найден: {model_path}")
    sys.exit(1)

# Load the module
spec = importlib.util.spec_from_file_location("_user_model", model_path)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except Exception as e:
    print(f"ОШИБКА при импорте модуля: {e}")
    sys.exit(1)

# Find object to pickle:
# 1. Class with get_actions method (instantiate it)
# 2. Module-level get_actions function (wrap it)
obj = None
for attr in dir(mod):
    if attr.startswith('_'):
        continue
    candidate = getattr(mod, attr)
    if isinstance(candidate, type) and hasattr(candidate, 'get_actions'):
        try:
            obj = candidate()
        except Exception as e:
            print(f"ОШИБКА при создании экземпляра {attr}: {e}")
            sys.exit(1)
        print(f"[*] Используется класс: {attr}")
        break

if obj is None and callable(getattr(mod, 'get_actions', None)):
    class _Wrapper:
        def get_actions(self, obs):
            return mod.get_actions(obs)
    obj = _Wrapper()
    print("[*] Используется функция get_actions на уровне модуля")

if obj is None:
    print("ОШИБКА: не найден класс с методом get_actions или функция get_actions")
    print("        Убедитесь, что в файле есть класс с методом get_actions(self, observation)")
    sys.exit(1)

# Test run
test_obs = {
    "my_robots": [
        {"x": 200, "y": 320, "vx": 0, "vy": 0, "angle": 0, "kick_ready": 1.0},
        {"x": 200, "y": 170, "vx": 0, "vy": 0, "angle": 0, "kick_ready": 1.0},
    ],
    "opponent_robots": [
        {"x": 880, "y": 320, "vx": 0, "vy": 0, "angle": 3.14159, "kick_ready": 1.0},
        {"x": 880, "y": 170, "vx": 0, "vy": 0, "angle": 3.14159, "kick_ready": 1.0},
    ],
    "ball": {"x": 540, "y": 320, "vx": 0, "vy": 0},
    "score": {"my": 0, "opponent": 0},
    "time_remaining": 120.0,
    "period_seconds": 120.0,
    "field": {
        "x": 0.0, "y": 0.0,
        "width": 1080.0, "height": 640.0,
        "goal_y_top": 150.0, "goal_y_bottom": 370.0,
    },
}
try:
    result = obj.get_actions(test_obs)
    assert isinstance(result, (list, tuple)) and len(result) >= 2, \
        f"get_actions должен вернуть список из 2 действий, получено: {result!r}"
    print("[*] Тестовый запуск: OK")
except Exception as e:
    print(f"ОШИБКА при тестовом запуске get_actions: {e}")
    sys.exit(1)

# Save
with open(out_path, 'wb') as f:
    cloudpickle.dump(obj, f)

py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
print(f"[OK] Сохранено: {out_path}")
print(f"[OK] Python {py_ver} — совместим с боевым сервером")
