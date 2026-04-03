"""
goalkeeper_striker.py — стратегия: вратарь + нападающий.

Система координат observation:
  (0, 0) — левый верхний угол поля.
  Команда всегда атакует вправо: свои ворота при x=0, чужие при x=field["width"].

Сигнатура функции:
  get_actions(observation) -> [[ax0, ay0, kick0], [ax1, ay1, kick1]]

Ключи observation:
  my_robots       — [{x, y, vx, vy, angle, kick_ready}, ...]  (ваши роботы)
  opponent_robots — [{x, y, vx, vy, angle, kick_ready}, ...]  (соперники)
  ball            — {x, y, vx, vy}                            (позиция и скорость мяча)
  score           — {my: int, opponent: int}                  (текущий счёт)
  time_remaining  — float                                      (секунды до конца тайма)
  field           — {width, height, goal_y_top, goal_y_bottom}

Робот 0 — НАПАДАЮЩИЙ:
  - Встаёт за мячом так, чтобы прямая робот→мяч вела в центр чужих ворот.
  - Когда выстроился — разгоняется к мячу и бьёт.
  - При проигрыше в концовке: бьёт из более широких позиций.

Робот 1 — ВРАТАРЬ:
  - Стоит на линии ворот и выходит на перехват по предсказанной траектории мяча.
  - При победе в концовке (< 30 с): строго держит линию ворот.
  - При проигрыше: выдвигается чуть дальше за мячом.
"""

import math


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _norm(dx, dy):
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 1e-6 else (0.0, 0.0)


def _steer(rx, ry, tx, ty, gain=4.0):
    nx, ny = _norm(tx - rx, ty - ry)
    return _clamp(nx * gain, -1.0, 1.0), _clamp(ny * gain, -1.0, 1.0)


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

GK_LINE    = 28.0    # goalkeeper x (robot radius ~28, flush to goal line)
GK_FORWARD = 90.0    # max forward standoff from goal line
GK_KICK_D  = 75.0    # kick distance for goalkeeper

APPROACH_DIST = 130.0
SHOOT_DIST    = 58.0
ALIGN_COS     = math.cos(math.radians(22.0))


# ---------------------------------------------------------------------------
# Goalkeeper
# ---------------------------------------------------------------------------

def _goalkeeper(robot, ball, field, score, time_remaining):
    fh = field["height"]
    goal_top    = field.get("goal_y_top",    fh * 0.328)
    goal_bottom = field.get("goal_y_bottom", fh * 0.672)
    goal_cy     = (goal_top + goal_bottom) / 2.0

    bx  = ball["x"]
    by  = ball["y"]
    bvx = ball.get("vx", 0.0)
    bvy = ball.get("vy", 0.0)

    # Adjust standoff limit based on score and time
    diff = score["my"] - score["opponent"]
    if diff > 0 and time_remaining < 30.0:
        # Winning in dying seconds: hug the goal line, no risks
        max_fwd = 0.0
        standoff_factor = 0.0
    elif diff < 0 and time_remaining < 90.0:
        # Losing: advance a bit more to give striker room to score
        max_fwd = GK_FORWARD * 1.4
        standoff_factor = 0.24
    else:
        max_fwd = GK_FORWARD
        standoff_factor = 0.18

    # Predict y when ball reaches goal line
    if bvx < -5.0:
        t = (GK_LINE - bx) / bvx
        pred_y = _clamp(by + bvy * t, goal_top, goal_bottom)
    else:
        pred_y = _clamp(by, goal_top, goal_bottom)

    # Standoff: advance toward ball along goal-center->ball direction
    dist_to_ball = math.hypot(bx - GK_LINE, by - goal_cy)
    standoff     = _clamp(dist_to_ball * standoff_factor, 0.0, max_fwd)
    dx_dir, dy_dir = _norm(bx - GK_LINE, by - goal_cy)
    intercept_x  = _clamp(GK_LINE + dx_dir * standoff, GK_LINE, GK_LINE + max_fwd)
    intercept_y  = _clamp(goal_cy + dy_dir * standoff, goal_top, goal_bottom)

    # Ball racing toward goal -> snap to goal line at predicted y
    if bvx < -30.0:
        target_x = GK_LINE
        target_y = pred_y
    else:
        target_x = intercept_x
        target_y = intercept_y

    ax, ay = _steer(robot["x"], robot["y"], target_x, target_y, gain=6.0)
    dist   = math.hypot(robot["x"] - bx, robot["y"] - by)
    kick   = 1.0 if dist < GK_KICK_D and robot.get("kick_ready", 1) > 0.5 else 0.0

    return [ax, ay, kick]


# ---------------------------------------------------------------------------
# Striker
# ---------------------------------------------------------------------------

def _striker(robot, ball, field, score, time_remaining):
    fw = field["width"]
    fh = field["height"]
    goal_top    = field.get("goal_y_top",    fh * 0.328)
    goal_bottom = field.get("goal_y_bottom", fh * 0.672)

    bx, by = ball["x"], ball["y"]
    rx, ry = robot["x"], robot["y"]

    goal_cx = fw
    goal_cy = (goal_top + goal_bottom) / 2.0

    # Adjust aggressiveness based on score and time
    diff = score["my"] - score["opponent"]
    if diff < 0 and time_remaining < 90.0:
        # Losing in second half: attack even from imperfect angles
        approach = APPROACH_DIST * 0.75
        align_cos = math.cos(math.radians(35.0))
        gain_rush = 6.0
    elif diff > 0 and time_remaining < 30.0:
        # Winning at the end: stay safe, don't over-commit forward
        approach = APPROACH_DIST * 1.1
        align_cos = ALIGN_COS
        gain_rush = 4.0
    else:
        approach  = APPROACH_DIST
        align_cos = ALIGN_COS
        gain_rush = 5.0

    tgx, tgy = _norm(goal_cx - bx, goal_cy - by)

    ap_x = _clamp(bx - tgx * approach, 0.0, fw)
    ap_y = _clamp(by - tgy * approach, 0.0, fh)

    tbx, tby  = _norm(bx - rx, by - ry)
    dot       = tbx * tgx + tby * tgy
    dist_ball = math.hypot(bx - rx, by - ry)

    if dot >= align_cos and dist_ball < approach * 2.5:
        ax, ay = _steer(rx, ry, bx, by, gain=gain_rush)
        kick   = 1.0 if dist_ball < SHOOT_DIST and robot.get("kick_ready", 1) > 0.5 else 0.0
    else:
        ax, ay = _steer(rx, ry, ap_x, ap_y, gain=4.5)
        kick   = 0.0

    return [ax, ay, kick]


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def get_actions(observation):
    """
    Робот 0 → нападающий  (старт ближе к центру)
    Робот 1 → вратарь     (старт ближе к своим воротам)
    """
    r0    = observation["my_robots"][0]
    r1    = observation["my_robots"][1]
    ball  = observation["ball"]
    field = observation["field"]
    score = observation.get("score", {"my": 0, "opponent": 0})
    time_remaining = observation.get("time_remaining", 180.0)

    return [
        _striker(r0, ball, field, score, time_remaining),
        _goalkeeper(r1, ball, field, score, time_remaining),
    ]


# ---------------------------------------------------------------------------
# Wrapper class for .pkl serialization
# ---------------------------------------------------------------------------

class GoalkeeperStriker:
    """Picklable strategy wrapper.

    The pkl is created with standard pickle (protocol 2) so it contains only
    a class reference — no compiled bytecode.  Any Python 3.x can load it
    as long as goalkeeper_striker.py is importable (server puts models/ on
    sys.path automatically).
    """

    def get_actions(self, observation):
        return get_actions(observation)

    def __reduce__(self):
        # Reconstruct by calling GoalkeeperStriker() with no args.
        # Standard pickle stores ("goalkeeper_striker", "GoalkeeperStriker")
        # and imports the class from sys.path at load-time.
        return (GoalkeeperStriker, ())


# ---------------------------------------------------------------------------
# Generate .pkl  (run: python goalkeeper_striker.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pickle
    import importlib.util
    import sys as _sys

    # Re-load THIS file as the 'goalkeeper_striker' module so that
    # standard pickle can find the class by import path.
    _spec = importlib.util.spec_from_file_location("goalkeeper_striker", __file__)
    _mod  = importlib.util.module_from_spec(_spec)
    _sys.modules["goalkeeper_striker"] = _mod
    _spec.loader.exec_module(_mod)  # type: ignore

    model = _mod.GoalkeeperStriker()

    obs = {
        "my_robots": [
            {"x": 450, "y": 260, "vx": 0, "vy": 0, "angle": 0, "kick_ready": 1.0},
            {"x": 330, "y": 380, "vx": 0, "vy": 0, "angle": 0, "kick_ready": 1.0},
        ],
        "ball": {"x": 540, "y": 320, "vx": -200, "vy": 30},
        "score": {"my": 0, "opponent": 0},
        "time_remaining": 120.0,
        "field": {
            "width": 1080.0, "height": 640.0,
            "goal_y_top": 210.0, "goal_y_bottom": 430.0,
        },
        "opponent_robots": [],
    }
    r = model.get_actions(obs)
    assert len(r) == 2, r
    print("Striker  action:", r[0])
    print("Goalkeeper action:", r[1])

    out = "goalkeeper_striker.pkl"
    # Protocol 2 = compatible with Python 3.x (no bytecode, just class ref)
    with open(out, "wb") as f:
        pickle.dump(model, f, protocol=2)
    print(f"\nFile {out} created! (standard pickle, cross-platform)")


