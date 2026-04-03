"""RoboCup Local Gamemaster – local-only FastAPI server.

Run:  python server.py
Or:   uvicorn server:app --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

import importlib.util
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from robocup_sim.match_2v2 import Match2v2
from robocup_sim import env as sim_env

BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(exist_ok=True)
WEB_DIR = BASE_DIR / "web"
DB_PATH = BASE_DIR / "leaderboard.db"

ALLOWED_EXTENSIONS = {".pkl", ".py"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                team1       TEXT    NOT NULL,
                team2       TEXT    NOT NULL,
                score1      INTEGER NOT NULL,
                score2      INTEGER NOT NULL,
                duration    REAL    NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


_init_db()


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def _load_model(path: Path):
    """Load a model from .pkl (cloudpickle object with get_actions) or .py file."""
    if path.suffix == ".pkl":
        try:
            import cloudpickle
        except ImportError:
            raise ImportError("cloudpickle is not installed. Run: pip install cloudpickle")
        with open(path, "rb") as f:
            obj = cloudpickle.load(f)
        if callable(getattr(obj, "get_actions", None)):
            return obj
        # Maybe the pkl is a plain function
        if callable(obj):
            class _FnWrapper:
                def get_actions(self_, observation):  # noqa
                    return obj(observation)
            return _FnWrapper()
        raise ImportError(f"{path.name}: loaded object has no callable 'get_actions' method")

    # .py file
    spec = importlib.util.spec_from_file_location("user_model", str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path.name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    if not hasattr(mod, "get_actions"):
        raise ImportError(f"{path.name}: module must define a 'get_actions(observation)' function")
    return mod


def _safe_get_actions(model: Any, obs: dict) -> list:
    """Call model.get_actions(obs); return zeroes on any failure."""
    try:
        result = model.get_actions(obs)
        if not isinstance(result, (list, tuple)) or len(result) < 2:
            return [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
        actions = []
        for action in result[:2]:
            if not isinstance(action, (list, tuple)) or len(action) < 2:
                actions.append([0.0, 0.0, 0.0])
            elif len(action) >= 3:
                actions.append([float(action[0]), float(action[1]), float(action[2])])
            else:
                actions.append([float(action[0]), float(action[1]), 0.0])
        return actions
    except Exception:
        return [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]


# ---------------------------------------------------------------------------
# Match state (global, thread-safe)
# ---------------------------------------------------------------------------

_match_lock = threading.Lock()
_match_state: dict[str, Any] = {
    "running": False,
    "team1": "",
    "team2": "",
    "state": None,
    "stop_requested": False,
    "error": None,
}


def _run_match(team1: str, team2: str, period: float, speed: float) -> None:
    """Match loop – runs in a daemon thread."""
    global _match_state

    try:
        m1 = _load_model(MODELS_DIR / team1)
        m2 = _load_model(MODELS_DIR / team2)
    except Exception as exc:
        with _match_lock:
            _match_state["running"] = False
            _match_state["error"] = str(exc)
        return

    engine = Match2v2(period_seconds=period)
    engine.reset()

    sleep_per_step = (sim_env.SIM_DT / speed) if speed > 0 else 0.0

    while not engine.truncated:
        with _match_lock:
            if _match_state["stop_requested"]:
                _match_state["running"] = False
                _match_state["stop_requested"] = False
                return

        obs1 = engine.get_observation("team1")
        obs2 = engine.get_observation("team2")
        a1 = _safe_get_actions(m1, obs1)
        a2 = _safe_get_actions(m2, obs2)
        engine.step(a1, a2)

        st = engine.get_state()
        st["team1_name"] = team1
        st["team2_name"] = team2
        with _match_lock:
            _match_state["state"] = st

        if sleep_per_step > 0:
            time.sleep(sleep_per_step)
        else:
            # Yield to other threads every ~100 steps even at max speed
            if engine.step_count % 100 == 0:
                time.sleep(0)

    # Match completed – save to DB
    final = engine.get_state()
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO matches (team1, team2, score1, score2, duration) VALUES (?,?,?,?,?)",
            (team1, team2, final["team1_score"], final["team2_score"], final["elapsed_time"]),
        )

    final["team1_name"] = team1
    final["team2_name"] = team2
    with _match_lock:
        _match_state["running"] = False
        _match_state["state"] = final
        _match_state["error"] = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="RoboCup Local Gamemaster")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class _NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/web/") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(_NoCacheMiddleware)
app.mount("/web", StaticFiles(directory=WEB_DIR, html=True), name="web")


# ---------------------------------------------------------------------------
# Static pages
# ---------------------------------------------------------------------------

@app.get("/")
def root() -> FileResponse:
    return FileResponse(
        WEB_DIR / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ---------------------------------------------------------------------------
# Config (field geometry for canvas renderer)
# ---------------------------------------------------------------------------

@app.get("/api/config")
def config():
    return {
        "window_width": sim_env.WINDOW_WIDTH,
        "window_height": sim_env.WINDOW_HEIGHT,
        "field_margin": sim_env.FIELD_MARGIN,
        "field_width": sim_env.FIELD_WIDTH,
        "field_height": sim_env.FIELD_HEIGHT,
        "goal_height": sim_env.GOAL_HEIGHT,
        "goal_depth": sim_env.GOAL_DEPTH,
        "goal_top": sim_env.GOAL_TOP,
        "goal_bottom": sim_env.GOAL_BOTTOM,
        "field_center_x": sim_env.FIELD_RECT.centerx,
        "field_center_y": sim_env.FIELD_RECT.centery,
        "colors": {
            "background": [22, 31, 25],
            "field": [52, 138, 78],
            "line": [238, 245, 239],
            "ball": [220, 50, 50],
            "team1_body": [242, 177, 52],
            "team1_head": [38, 38, 38],
            "team2_body": [68, 156, 232],
            "team2_head": [18, 48, 90],
            "goal": [225, 233, 228],
        },
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@app.get("/api/models")
def list_models() -> list[str]:
    files = sorted(
        f.name
        for f in MODELS_DIR.iterdir()
        if f.is_file() and f.suffix in ALLOWED_EXTENSIONS
    )
    return files


@app.post("/api/models/upload")
async def upload_model(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "No filename provided")
    path = Path(file.filename)
    if path.suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Only {sorted(ALLOWED_EXTENSIONS)} files are allowed")
    # Security: strip any directory traversal
    safe_name = path.name
    if not safe_name or safe_name.startswith("."):
        raise HTTPException(400, "Invalid filename")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File too large (max 50 MB)")
    dest = MODELS_DIR / safe_name
    dest.write_bytes(content)
    return {"name": safe_name, "size": len(content)}


@app.delete("/api/models/{name}")
def delete_model(name: str) -> dict:
    # Security: prevent path traversal
    safe_name = Path(name).name
    path = MODELS_DIR / safe_name
    if not path.exists() or path.suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(404, "Model not found")
    path.unlink()
    return {"deleted": safe_name}


# ---------------------------------------------------------------------------
# Match
# ---------------------------------------------------------------------------

class StartMatchRequest(BaseModel):
    team1: str
    team2: str
    period: float = 60.0   # seconds
    speed: float = 10.0    # simulation speed multiplier (0 = max speed)


@app.post("/api/match/start")
def start_match(body: StartMatchRequest, background_tasks: BackgroundTasks):
    if not (1.0 <= body.period <= 600.0):
        raise HTTPException(400, "period must be between 1 and 600 seconds")
    if body.speed < 0:
        raise HTTPException(400, "speed must be >= 0")

    # Validate model names (no path traversal)
    t1_name = Path(body.team1).name
    t2_name = Path(body.team2).name

    with _match_lock:
        if _match_state["running"]:
            raise HTTPException(409, "A match is already running. Stop it first.")

    if not (MODELS_DIR / t1_name).exists():
        raise HTTPException(404, f"Model not found: {t1_name}")
    if not (MODELS_DIR / t2_name).exists():
        raise HTTPException(404, f"Model not found: {t2_name}")

    with _match_lock:
        _match_state["running"] = True
        _match_state["team1"] = t1_name
        _match_state["team2"] = t2_name
        _match_state["state"] = None
        _match_state["stop_requested"] = False
        _match_state["error"] = None

    thread = threading.Thread(
        target=_run_match,
        args=(t1_name, t2_name, body.period, body.speed),
        daemon=True,
    )
    thread.start()
    return {"status": "started", "team1": t1_name, "team2": t2_name}


@app.get("/api/match/state")
def match_state() -> dict:
    with _match_lock:
        return {
            "running": _match_state["running"],
            "team1": _match_state["team1"],
            "team2": _match_state["team2"],
            "state": _match_state["state"],
            "error": _match_state["error"],
        }


@app.post("/api/match/stop")
def stop_match() -> dict:
    with _match_lock:
        if not _match_state["running"]:
            return {"status": "not_running"}
        _match_state["stop_requested"] = True
    return {"status": "stopping"}


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

@app.get("/api/leaderboard")
def leaderboard() -> list[dict]:
    """Raw match history, newest first."""
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM matches ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/leaderboard/stats")
def leaderboard_stats() -> list[dict]:
    """Aggregated stats per model, sorted by points."""
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT team1, team2, score1, score2 FROM matches"
        ).fetchall()

    stats: dict[str, dict] = {}

    for t1, t2, s1, s2 in rows:
        for name, my_score, opp_score in ((t1, s1, s2), (t2, s2, s1)):
            if name not in stats:
                stats[name] = {"m": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0}
            entry = stats[name]
            entry["m"] += 1
            entry["gf"] += my_score
            entry["ga"] += opp_score
            if my_score > opp_score:
                entry["w"] += 1
            elif my_score == opp_score:
                entry["d"] += 1
            else:
                entry["l"] += 1

    result = [
        {"name": name, **s, "pts": s["w"] * 3 + s["d"]}
        for name, s in stats.items()
    ]
    result.sort(key=lambda x: (-x["pts"], -(x["gf"] - x["ga"]), -x["gf"]))
    return result


@app.delete("/api/leaderboard")
def reset_leaderboard() -> dict:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM matches")
    return {"status": "reset"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import webbrowser
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8080")).start()
    uvicorn.run("server:app", host="127.0.0.1", port=8080, reload=False)
