"""2v2 match engine – same physics as the original env, extended to four robots."""

from __future__ import annotations

import random
from typing import Any

import numpy as np
import pygame
from pygame.math import Vector2

from robocup_sim import env as sim_env
from robocup_sim.env import Ball, Robot, KICK_COOLDOWN_SECONDS, KICK_POWER

# ---------------------------------------------------------------------------
# Kickoff formations – chosen randomly at every kickoff/goal restart.
#
# Each entry is ((dx0, dy0), (dx1, dy1)) – offsets from the field centre.
# Team 1 (attacks right):  r0 → (cx+dx0, cy+dy0),  r1 → (cx+dx1, cy+dy1)
# Team 2 (attacks left):   r0 → (cx-dx0, cy-dy0),  r1 → (cx-dx1, cy-dy1)
#
# This 180° rotational symmetry guarantees perfect fairness – swapping the
# teams gives the exactly mirrored arrangement.
# ---------------------------------------------------------------------------
_KICKOFF_FORMATIONS: list[tuple[tuple[int, int], tuple[int, int]]] = [
    # Расстояние от мяча всегда >= 100px. dy != 0 чтобы избежать
    # коллинеарности (мяч не зажимается между двумя роботами).
    # Симметрия: team2 ставится в (-dx, -dy) – зеркало на 180°.

    # 1. Стандарт – оба у центра, разнесены по вертикали
    ((-120, -70), (-250,  70)),
    # 2. Оба в защите – широко по вертикали
    ((-380, -90), (-380,  90)),
    # 3. Страйкер слегка смещён + вратарь на воротах
    ((-120,  80), (-430, -70)),
    # 4. Широкая расстановка по флангам
    ((-200, -170), (-200, 170)),
    # 5. Диагональная схема
    ((-150, -140), (-320, 150)),
    # 6. Компактно у центра сзади
    ((-170, -55), (-300,  55)),
    # 7. Один вперёд-фланг, один полузащита
    ((-130, 140), (-310, -80)),
    # 8. Оба на одном фланге, стагированы
    ((-160, -190), (-370, -110)),
]


TEAM1_BODY_COLOR = (242, 177, 52)
TEAM1_HEAD_COLOR = (38, 38, 38)
TEAM2_BODY_COLOR = (68, 156, 232)
TEAM2_HEAD_COLOR = (18, 48, 90)


def _mirror_angle(angle: float) -> float:
    mirrored = 180.0 - angle
    while mirrored <= -180.0:
        mirrored += 360.0
    while mirrored > 180.0:
        mirrored -= 360.0
    return mirrored


class Match2v2:
    """Physics engine for a 2v2 robot soccer match.

    Team 1 attacks RIGHT, team 2 attacks LEFT (in world coords).
    Observations for team 2 are mirrored so models always see
    "my goal is on the left, I attack right".
    """

    def __init__(
        self,
        period_seconds: float = 180.0,
        kickoff_pause_seconds: float = 1.5,
    ) -> None:
        self.period_seconds = float(period_seconds)
        self.kickoff_pause_seconds = float(kickoff_pause_seconds)
        self.kickoff_pause_steps = max(1, int(self.kickoff_pause_seconds * sim_env.FPS))

        self.team1_robots = [
            Robot(position=Vector2(), velocity=Vector2()),
            Robot(position=Vector2(), velocity=Vector2()),
        ]
        self.team2_robots = [
            Robot(position=Vector2(), velocity=Vector2()),
            Robot(position=Vector2(), velocity=Vector2()),
        ]
        self.ball = Ball(position=Vector2(), velocity=Vector2())

        self.team1_score = 0
        self.team2_score = 0
        self.elapsed_time = 0.0
        self.step_count = 0
        self.truncated = False
        self.goal_scored: str | None = None
        self.match_phase = "kickoff"
        self.kickoff_team = "team1"
        self.goal_pause_steps_remaining = 0
        self.last_scoring_team: str | None = None
        self._reset_kick_cooldowns()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def time_remaining(self) -> float:
        return max(0.0, self.period_seconds - self.elapsed_time)

    @property
    def all_robots(self) -> list[Robot]:
        return self.team1_robots + self.team2_robots

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self.team1_score = 0
        self.team2_score = 0
        self.elapsed_time = 0.0
        self.step_count = 0
        self.truncated = False
        self.goal_scored = None
        self.match_phase = "kickoff"
        self.kickoff_team = "team1"
        self.goal_pause_steps_remaining = 0
        self.last_scoring_team = None
        self._setup_kickoff("team1")

    def get_observation(self, team: str) -> dict[str, Any]:
        """Get observation dict for *team* (always as-if attacking right)."""
        mirror = team == "team2"

        if team == "team1":
            my_robots = self.team1_robots
            opp_robots = self.team2_robots
            my_score = self.team1_score
            opp_score = self.team2_score
        else:
            my_robots = self.team2_robots
            opp_robots = self.team1_robots
            my_score = self.team2_score
            opp_score = self.team1_score

        def _robot_obs(robot: Robot) -> dict[str, float]:
            x = float(robot.position.x - sim_env.FIELD_RECT.left)
            y = float(robot.position.y - sim_env.FIELD_RECT.top)
            vx = float(robot.velocity.x)
            vy = float(robot.velocity.y)
            angle = float(robot.angle)
            kick_ready = 1.0 if robot.kick_cooldown == 0.0 else 0.0
            if mirror:
                x = float(sim_env.FIELD_WIDTH) - x
                vx = -vx
                angle = _mirror_angle(angle)
            return {"x": x, "y": y, "vx": vx, "vy": vy, "angle": angle, "kick_ready": kick_ready}

        bx = float(self.ball.position.x - sim_env.FIELD_RECT.left)
        by = float(self.ball.position.y - sim_env.FIELD_RECT.top)
        bvx = float(self.ball.velocity.x)
        bvy = float(self.ball.velocity.y)
        if mirror:
            bx = float(sim_env.FIELD_WIDTH) - bx
            bvx = -bvx

        return {
            "my_robots": [_robot_obs(r) for r in my_robots],
            "opponent_robots": [_robot_obs(r) for r in opp_robots],
            "ball": {"x": bx, "y": by, "vx": bvx, "vy": bvy},
            "score": {"my": my_score, "opponent": opp_score},
            "time_remaining": self.time_remaining,
            "period_seconds": self.period_seconds,
            "field": {
                "x": 0.0,
                "y": 0.0,
                "width": float(sim_env.FIELD_WIDTH),
                "height": float(sim_env.FIELD_HEIGHT),
                "goal_y_top": float(sim_env.GOAL_TOP - sim_env.FIELD_RECT.top),
                "goal_y_bottom": float(sim_env.GOAL_BOTTOM - sim_env.FIELD_RECT.top),
            },
        }

    def step(self, team1_actions: list, team2_actions: list) -> None:
        """Advance one physics step with actions from both teams."""
        if self.truncated:
            return

        self.elapsed_time += sim_env.SIM_DT
        self.step_count += 1

        if self.elapsed_time >= self.period_seconds:
            self.truncated = True
            self.match_phase = "full_time"
            self.goal_scored = None
            return

        if self.goal_pause_steps_remaining > 0:
            self.goal_pause_steps_remaining -= 1
            if self.goal_pause_steps_remaining == 0:
                self._setup_kickoff(self.kickoff_team)
                self.match_phase = "live"
            return

        if self.match_phase == "kickoff":
            self.match_phase = "live"

        # --- Team 1 actions (no mirror) ---
        for i, robot in enumerate(self.team1_robots):
            if i < len(team1_actions):
                act = team1_actions[i]
                ax = float(np.clip(act[0], -1.0, 1.0))
                ay = float(np.clip(act[1], -1.0, 1.0))
                robot.update(sim_env.SIM_DT, Vector2(ax, ay))
            robot.keep_in_bounds(sim_env.FIELD_RECT)

        # --- Team 2 actions (mirror x back to world coords) ---
        for i, robot in enumerate(self.team2_robots):
            if i < len(team2_actions):
                act = team2_actions[i]
                ax = float(np.clip(act[0], -1.0, 1.0))
                ay = float(np.clip(act[1], -1.0, 1.0))
                robot.update(sim_env.SIM_DT, Vector2(-ax, ay))
            robot.keep_in_bounds(sim_env.FIELD_RECT)

        # --- Robot-robot collisions (all pairs) ---
        robots = self.all_robots
        for i in range(len(robots)):
            for j in range(i + 1, len(robots)):
                self._resolve_robot_robot_collision(robots[i], robots[j])

        # --- Kick cooldown update + kick application ---
        for robot in robots:
            if robot.kick_cooldown > 0.0:
                robot.kick_cooldown = max(0.0, robot.kick_cooldown - sim_env.SIM_DT)

        for i, robot in enumerate(self.team1_robots):
            if i < len(team1_actions) and len(team1_actions[i]) > 2:
                if float(team1_actions[i][2]) > 0.5 and robot.kick_cooldown == 0.0:
                    delta = self.ball.position - robot.position
                    if delta.length_squared() > 0 and delta.length() <= robot.radius + self.ball.radius + 2.0:
                        self.ball.velocity += delta.normalize() * KICK_POWER
                        robot.kick_cooldown = KICK_COOLDOWN_SECONDS

        for i, robot in enumerate(self.team2_robots):
            if i < len(team2_actions) and len(team2_actions[i]) > 2:
                if float(team2_actions[i][2]) > 0.5 and robot.kick_cooldown == 0.0:
                    delta = self.ball.position - robot.position
                    if delta.length_squared() > 0 and delta.length() <= robot.radius + self.ball.radius + 2.0:
                        self.ball.velocity += delta.normalize() * KICK_POWER
                        robot.kick_cooldown = KICK_COOLDOWN_SECONDS

        # --- Ball physics ---
        self.ball.update(sim_env.SIM_DT)
        # Resolve ball-robot collisions iteratively to prevent sticking
        for _ in range(3):
            for robot in robots:
                self._resolve_robot_ball_collision(robot)
        self._resolve_ball_walls()

        # --- Goal detection ---
        goal_side = self._detect_goal()
        self.goal_scored = goal_side
        if goal_side is not None:
            self._handle_goal(goal_side)

    def get_state(self) -> dict[str, Any]:
        """Serializable match state for API / frontend."""

        def _robot_dict(robot: Robot) -> dict[str, float]:
            return {
                "x": float(robot.position.x),
                "y": float(robot.position.y),
                "vx": float(robot.velocity.x),
                "vy": float(robot.velocity.y),
                "angle": float(robot.angle),
                "radius": float(robot.radius),
            }

        return {
            "team1_robots": [_robot_dict(r) for r in self.team1_robots],
            "team2_robots": [_robot_dict(r) for r in self.team2_robots],
            "ball": {
                "x": float(self.ball.position.x),
                "y": float(self.ball.position.y),
                "vx": float(self.ball.velocity.x),
                "vy": float(self.ball.velocity.y),
                "radius": float(self.ball.radius),
            },
            "team1_score": self.team1_score,
            "team2_score": self.team2_score,
            "elapsed_time": self.elapsed_time,
            "time_remaining": self.time_remaining,
            "period_seconds": self.period_seconds,
            "step_count": self.step_count,
            "truncated": self.truncated,
            "goal_scored": self.goal_scored,
            "match_phase": self.match_phase,
            "kickoff_team": self.kickoff_team,
            "goal_pause_steps_remaining": self.goal_pause_steps_remaining,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _setup_kickoff(self, kickoff_team: str) -> None:
        cx = float(sim_env.FIELD_RECT.centerx)
        cy = float(sim_env.FIELD_RECT.centery)

        self.ball.position = Vector2(cx, cy)
        self.ball.velocity.update(0.0, 0.0)
        self.kickoff_team = kickoff_team
        self.goal_scored = None
        self._reset_kick_cooldowns()

        # Pick a random formation – perfectly symmetric around the centre.
        (dx0, dy0), (dx1, dy1) = random.choice(_KICKOFF_FORMATIONS)

        # Team 1 (left side, attacks right)
        self.team1_robots[0].position = Vector2(cx + dx0, cy + dy0)
        self.team1_robots[1].position = Vector2(cx + dx1, cy + dy1)
        for r in self.team1_robots:
            r.velocity.update(0.0, 0.0)
            r.angle = 0.0

        # Team 2 (right side, attacks left) – 180° mirror of team 1
        self.team2_robots[0].position = Vector2(cx - dx0, cy - dy0)
        self.team2_robots[1].position = Vector2(cx - dx1, cy - dy1)
        for r in self.team2_robots:
            r.velocity.update(0.0, 0.0)
            r.angle = 180.0

        # Enforce ball-robot separation: push any robot that overlaps the ball
        for robot in self.all_robots:
            safe = robot.radius + self.ball.radius + 5.0
            delta = self.ball.position - robot.position
            dist = delta.length()
            if dist < safe:
                normal = delta.normalize() if dist > 0.01 else Vector2(1.0, 0.0)
                robot.position = self.ball.position - normal * safe
                robot.keep_in_bounds(sim_env.FIELD_RECT)

    def _handle_goal(self, goal_side: str) -> None:
        if goal_side == "right":
            self.team1_score += 1
            self.last_scoring_team = "team1"
            self.kickoff_team = "team2"
        else:
            self.team2_score += 1
            self.last_scoring_team = "team2"
            self.kickoff_team = "team1"

        self.match_phase = "goal_pause"
        self.goal_pause_steps_remaining = self.kickoff_pause_steps
        self.ball.velocity.update(0.0, 0.0)
        for r in self.all_robots:
            r.velocity.update(0.0, 0.0)

    def _reset_kick_cooldowns(self) -> None:
        for r in self.all_robots:
            r.kick_cooldown = 0.0

    def _resolve_robot_ball_collision(self, robot: Robot) -> bool:
        delta = self.ball.position - robot.position
        distance = delta.length()
        min_dist = robot.radius + self.ball.radius
        if distance >= min_dist:
            return False
        normal = delta / distance if distance > 0.01 else Vector2(1.0, 0.0)
        # Snap ball to exact boundary so it never stays inside the robot
        self.ball.position = robot.position + normal * min_dist
        relative = robot.velocity - self.ball.velocity
        impulse = max(0.0, relative.dot(normal))
        self.ball.velocity += normal * (impulse * 1.35 + 150.0)
        robot.velocity *= 0.80
        return True

    def _resolve_robot_robot_collision(self, a: Robot, b: Robot) -> None:
        delta = b.position - a.position
        distance = delta.length()
        min_dist = a.radius + b.radius
        if distance >= min_dist:
            return
        normal = delta / distance if distance > 0 else Vector2(1.0, 0.0)
        correction = normal * ((min_dist - distance) * 0.5)
        a.position -= correction
        b.position += correction
        a_n = a.velocity.dot(normal)
        b_n = b.velocity.dot(normal)
        a.velocity += normal * (b_n - a_n) * 0.5
        b.velocity += normal * (a_n - b_n) * 0.5
        a.keep_in_bounds(sim_env.FIELD_RECT)
        b.keep_in_bounds(sim_env.FIELD_RECT)

    def _resolve_ball_walls(self) -> None:
        if self.ball.position.y - self.ball.radius < sim_env.FIELD_RECT.top:
            self.ball.position.y = sim_env.FIELD_RECT.top + self.ball.radius
            self.ball.velocity.y *= -0.85
        elif self.ball.position.y + self.ball.radius > sim_env.FIELD_RECT.bottom:
            self.ball.position.y = sim_env.FIELD_RECT.bottom - self.ball.radius
            self.ball.velocity.y *= -0.85

        if not self._ball_in_goal_opening():
            if self.ball.position.x - self.ball.radius < sim_env.FIELD_RECT.left:
                self.ball.position.x = sim_env.FIELD_RECT.left + self.ball.radius
                self.ball.velocity.x *= -0.85
            elif self.ball.position.x + self.ball.radius > sim_env.FIELD_RECT.right:
                self.ball.position.x = sim_env.FIELD_RECT.right - self.ball.radius
                self.ball.velocity.x *= -0.85

    def _ball_in_goal_opening(self) -> bool:
        return sim_env.GOAL_TOP <= self.ball.position.y <= sim_env.GOAL_BOTTOM

    def _detect_goal(self) -> str | None:
        if not self._ball_in_goal_opening():
            return None
        if self.ball.position.x - self.ball.radius <= sim_env.LEFT_GOAL_RECT.left:
            return "left"
        if self.ball.position.x + self.ball.radius >= sim_env.RIGHT_GOAL_RECT.right:
            return "right"
        return None
