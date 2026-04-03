from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import gymnasium as gym
import numpy as np
import pygame
from gymnasium import spaces
from pygame.math import Vector2


WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 760
FPS = 60
SIM_DT = 1.0 / FPS

FIELD_MARGIN = 60
FIELD_WIDTH = WINDOW_WIDTH - FIELD_MARGIN * 2
FIELD_HEIGHT = WINDOW_HEIGHT - FIELD_MARGIN * 2
FIELD_RECT = pygame.Rect(FIELD_MARGIN, FIELD_MARGIN, FIELD_WIDTH, FIELD_HEIGHT)

GOAL_HEIGHT = 220
GOAL_DEPTH = 34
GOAL_TOP = FIELD_RECT.centery - GOAL_HEIGHT // 2
GOAL_BOTTOM = FIELD_RECT.centery + GOAL_HEIGHT // 2
LEFT_GOAL_RECT = pygame.Rect(FIELD_RECT.left - GOAL_DEPTH, GOAL_TOP, GOAL_DEPTH, GOAL_HEIGHT)
RIGHT_GOAL_RECT = pygame.Rect(FIELD_RECT.right, GOAL_TOP, GOAL_DEPTH, GOAL_HEIGHT)
RIGHT_GOAL_CENTER = Vector2(FIELD_RECT.right, FIELD_RECT.centery)
FIELD_CENTER = Vector2(FIELD_RECT.centerx, FIELD_RECT.centery)
MAX_DISTANCE = float(np.hypot(FIELD_WIDTH, FIELD_HEIGHT))
BALL_SPEED_SCALE = 900.0

BACKGROUND_COLOR = (22, 31, 25)
FIELD_COLOR = (52, 138, 78)
LINE_COLOR = (238, 245, 239)
BALL_COLOR = (220, 50, 50)
ROBOT_COLOR = (242, 177, 52)
ROBOT_HEAD_COLOR = (38, 38, 38)
TEXT_COLOR = (235, 240, 236)
GOAL_COLOR = (225, 233, 228)
AUTO_COLOR = (240, 225, 124)

GOAL_REWARD = 10.0
OWN_GOAL_PENALTY = -10.0
STEP_PENALTY = -0.002
CONTACT_REWARD = 0.03
STANDING_PENALTY = -0.003
JITTER_PENALTY_SCALE = 0.0025
KICK_COOLDOWN_SECONDS = 3.0
KICK_POWER = 900.0


@dataclass
class Ball:
    position: Vector2
    velocity: Vector2
    radius: float = 14.0
    damping: float = 0.992

    def update(self, dt: float) -> None:
        self.position += self.velocity * dt
        self.velocity *= self.damping
        if self.velocity.length_squared() < 1.5:
            self.velocity.update(0.0, 0.0)


@dataclass
class Robot:
    position: Vector2
    velocity: Vector2
    angle: float = 0.0
    radius: float = 28.0
    acceleration: float = 900.0
    max_speed: float = 360.0
    drag: float = 0.90
    kick_cooldown: float = 0.0  # seconds

    def update(self, dt: float, action: Vector2) -> None:
        if action.length_squared() > 0:
            direction = action.normalize()
            self.velocity += direction * self.acceleration * dt
            self.angle = Vector2(1, 0).angle_to(direction)

        if self.velocity.length() > self.max_speed:
            self.velocity.scale_to_length(self.max_speed)

        self.position += self.velocity * dt
        self.velocity *= self.drag

        if self.velocity.length_squared() < 4.0:
            self.velocity.update(0.0, 0.0)

    def keep_in_bounds(self, rect: pygame.Rect) -> None:
        if self.position.x - self.radius < rect.left:
            self.position.x = rect.left + self.radius
            self.velocity.x = 0.0
        elif self.position.x + self.radius > rect.right:
            self.position.x = rect.right - self.radius
            self.velocity.x = 0.0

        if self.position.y - self.radius < rect.top:
            self.position.y = rect.top + self.radius
            self.velocity.y = 0.0
        elif self.position.y + self.radius > rect.bottom:
            self.position.y = rect.bottom - self.radius
            self.velocity.y = 0.0


class RobotSoccerEnv(gym.Env[np.ndarray, np.ndarray]):
    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": FPS}

    def __init__(
        self,
        render_mode: str | None = None,
        episode_seconds: float = 20.0,
        difficulty: str = "medium",
    ) -> None:
        super().__init__()
        if render_mode is not None and render_mode not in self.metadata["render_modes"]:
            raise ValueError(f"Unsupported render_mode: {render_mode}")
        if difficulty not in {"easy", "medium", "hard"}:
            raise ValueError(f"Unsupported difficulty: {difficulty}")

        self.render_mode = render_mode
        self.episode_seconds = float(episode_seconds)
        self.difficulty = difficulty
        self.max_episode_steps = int(self.episode_seconds / SIM_DT)

        # action: [ax, ay, kick]  kick > 0.5 triggers kick if ball touching and cooldown=0
        self.action_space = spaces.Box(
            low=np.array([-1.0, -1.0, 0.0]),
            high=np.array([1.0, 1.0, 1.0]),
            shape=(3,),
            dtype=np.float32,
        )
        # observation: 17 original + kick_ready = 18
        self.observation_space = spaces.Box(low=-1.0, high=1.0, shape=(18,), dtype=np.float32)

        self.robot = Robot(position=Vector2(), velocity=Vector2())
        self.ball = Ball(position=Vector2(), velocity=Vector2())

        self.reward = 0.0
        self.terminated = False
        self.truncated = False
        self.goal_scored: str | None = None
        self.elapsed_time = 0.0
        self.step_count = 0
        self.ball_touches = 0
        self.shots_toward_goal = 0
        self.episode_return = 0.0
        self.last_action = np.zeros(3, dtype=np.float32)
        self.last_reward_components: dict[str, float] = {}
        self.autopilot_mode = False
        self.control_mode = "manual"
        self._was_ball_contacting_robot = False
        self._shot_in_progress = False

        self._screen: pygame.Surface | None = None
        self._font: pygame.font.Font | None = None
        self._render_clock: pygame.time.Clock | None = None

    def reset(
        self,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)

        if options and "autopilot_mode" in options:
            self.autopilot_mode = bool(options["autopilot_mode"])

        robot_pos, ball_pos = self._sample_start_positions()
        self.robot.position = robot_pos
        self.robot.velocity.update(0.0, 0.0)
        self.robot.angle = float(self.np_random.uniform(-180.0, 180.0))

        self.ball.position = ball_pos
        self.ball.velocity.update(0.0, 0.0)

        self.reward = 0.0
        self.terminated = False
        self.truncated = False
        self.goal_scored = None
        self.elapsed_time = 0.0
        self.step_count = 0
        self.ball_touches = 0
        self.shots_toward_goal = 0
        self.episode_return = 0.0
        self.robot.kick_cooldown = 0.0
        self.last_action = np.zeros(3, dtype=np.float32)
        self.last_reward_components = {}
        self._was_ball_contacting_robot = self._is_ball_contacting_robot()
        self._shot_in_progress = False

        return self.get_observation(), self._build_info()

    def step(
        self,
        action: np.ndarray | list[float] | tuple[float, float],
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self.terminated or self.truncated:
            return self.get_observation(), self.reward, self.terminated, self.truncated, self._build_info()

        action_array = np.asarray(action, dtype=np.float32).reshape(self.action_space.shape)
        action_array = np.clip(action_array, self.action_space.low, self.action_space.high)
        move_action = action_array[:2]
        kick_action = bool(action_array[2] > 0.5)

        previous_robot_to_ball = self.robot.position.distance_to(self.ball.position)
        previous_ball_to_goal = self.ball.position.distance_to(RIGHT_GOAL_CENTER)

        # Decrement kick cooldown
        if self.robot.kick_cooldown > 0.0:
            self.robot.kick_cooldown = max(0.0, self.robot.kick_cooldown - SIM_DT)

        self.robot.update(SIM_DT, Vector2(float(move_action[0]), float(move_action[1])))
        self.robot.keep_in_bounds(FIELD_RECT)

        self.ball.update(SIM_DT)
        contact_happened = self._resolve_robot_ball_collision()

        # Apply kick: strong impulse when touching, cooldown ready, and kick requested
        if kick_action and self._is_ball_contacting_robot() and self.robot.kick_cooldown == 0.0:
            direction = self.ball.position - self.robot.position
            if direction.length_squared() > 0:
                self.ball.velocity += direction.normalize() * KICK_POWER
            self.robot.kick_cooldown = KICK_COOLDOWN_SECONDS

        self._resolve_ball_walls()

        current_contact = self._is_ball_contacting_robot()
        if current_contact and not self._was_ball_contacting_robot:
            self.ball_touches += 1
        self._was_ball_contacting_robot = current_contact

        shot_now = self._is_shot_toward_goal()
        if shot_now and not self._shot_in_progress:
            self.shots_toward_goal += 1
        self._shot_in_progress = shot_now

        self.elapsed_time += SIM_DT
        self.step_count += 1
        self.goal_scored = self._detect_goal()
        self.terminated = self.goal_scored is not None
        self.truncated = self.elapsed_time >= self.episode_seconds and not self.terminated

        reward_value, reward_components = self._compute_reward(
            action_array=action_array,
            previous_robot_to_ball=previous_robot_to_ball,
            previous_ball_to_goal=previous_ball_to_goal,
            contact_happened=contact_happened,
        )
        self.reward = float(reward_value)
        self.episode_return += self.reward
        self.last_reward_components = reward_components
        self.last_action = action_array

        return self.get_observation(), self.reward, self.terminated, self.truncated, self._build_info()

    def get_observation(self) -> np.ndarray:
        robot_to_ball = self.ball.position - self.robot.position
        ball_to_goal = RIGHT_GOAL_CENTER - self.ball.position
        robot_angle_rad = np.deg2rad(self.robot.angle)
        robot_to_ball_distance = self.robot.position.distance_to(self.ball.position)
        ball_to_goal_distance = self.ball.position.distance_to(RIGHT_GOAL_CENTER)
        contact_flag = 1.0 if self._is_ball_contacting_robot() else 0.0
        kick_ready = 1.0 if self.robot.kick_cooldown == 0.0 else 0.0

        observation = np.array(
            [
                self._normalize_position_x(self.robot.position.x),
                self._normalize_position_y(self.robot.position.y),
                self._normalize_robot_velocity(self.robot.velocity.x),
                self._normalize_robot_velocity(self.robot.velocity.y),
                np.float32(np.sin(robot_angle_rad)),
                np.float32(np.cos(robot_angle_rad)),
                self._normalize_position_x(self.ball.position.x),
                self._normalize_position_y(self.ball.position.y),
                self._normalize_ball_velocity(self.ball.velocity.x),
                self._normalize_ball_velocity(self.ball.velocity.y),
                self._normalize_vector_x(robot_to_ball.x),
                self._normalize_vector_y(robot_to_ball.y),
                self._normalize_vector_x(ball_to_goal.x),
                self._normalize_vector_y(ball_to_goal.y),
                self._normalize_distance(robot_to_ball_distance),
                self._normalize_distance(ball_to_goal_distance),
                np.float32(contact_flag),
                np.float32(kick_ready),
            ],
            dtype=np.float32,
        )
        return np.clip(observation, -1.0, 1.0)

    def render(self) -> np.ndarray | None:
        if self.render_mode is None:
            return None

        from robocup_sim.viewer import render_env

        return render_env(self)

    def close(self) -> None:
        from robocup_sim.viewer import close_viewer

        close_viewer(self)

    def scripted_autopilot_action(self) -> np.ndarray:
        desired_ball_direction = self._get_autopilot_ball_direction()
        approach_offset = self.robot.radius + self.ball.radius + 20.0
        if FIELD_RECT.right - self.ball.position.x < 90.0:
            approach_offset += 26.0

        recovery_point = self._get_right_wall_recovery_point()
        if recovery_point is not None and self.robot.position.distance_to(recovery_point) > 18.0:
            target = recovery_point
        else:
            staging_point = self.ball.position - desired_ball_direction * approach_offset
            staging_point = self._clamp_robot_target(staging_point)

            robot_to_ball = self.ball.position - self.robot.position
            robot_to_stage = staging_point - self.robot.position

            aligned_for_shot = (
                robot_to_stage.length() < 24.0
                or robot_to_ball.dot(desired_ball_direction) > approach_offset * 0.35
            )

            if aligned_for_shot:
                push_target = self.ball.position + desired_ball_direction * 28.0
                target = self._clamp_robot_target(push_target)
            else:
                target = staging_point

        desired = target - self.robot.position
        if desired.length_squared() == 0:
            return np.zeros(2, dtype=np.float32)

        if desired.length() > 1.0:
            desired.scale_to_length(1.0)

        return np.array([desired.x, desired.y], dtype=np.float32)

    def _get_autopilot_ball_direction(self) -> Vector2:
        top_clearance = self.ball.position.y - FIELD_RECT.top
        bottom_clearance = FIELD_RECT.bottom - self.ball.position.y
        right_clearance = FIELD_RECT.right - self.ball.position.x

        if right_clearance < 40.0 and self.ball.position.y < GOAL_TOP:
            return Vector2(-0.55, 1.0).normalize()
        if right_clearance < 40.0 and self.ball.position.y > GOAL_BOTTOM:
            return Vector2(-0.55, -1.0).normalize()
        if top_clearance < 34.0:
            return Vector2(0.45, 1.0).normalize()
        if bottom_clearance < 34.0:
            return Vector2(0.45, -1.0).normalize()

        goal_entry_y = float(np.clip(self.ball.position.y, GOAL_TOP + 18.0, GOAL_BOTTOM - 18.0))
        goal_entry_target = Vector2(FIELD_RECT.right - 6.0, goal_entry_y)
        goal_vector = goal_entry_target - self.ball.position
        if goal_vector.length_squared() == 0:
            return Vector2(1.0, 0.0)
        return goal_vector.normalize()

    def _clamp_robot_target(self, target: Vector2) -> Vector2:
        clamped_x = float(
            np.clip(
                target.x,
                FIELD_RECT.left + self.robot.radius,
                FIELD_RECT.right - self.robot.radius,
            )
        )
        clamped_y = float(
            np.clip(
                target.y,
                FIELD_RECT.top + self.robot.radius,
                FIELD_RECT.bottom - self.robot.radius,
            )
        )
        return Vector2(clamped_x, clamped_y)

    def _get_right_wall_recovery_point(self) -> Vector2 | None:
        right_clearance = FIELD_RECT.right - self.ball.position.x
        if right_clearance >= 85.0:
            return None

        recovery_x = self.ball.position.x - (self.robot.radius + self.ball.radius + 34.0)
        if self.ball.position.y < GOAL_TOP:
            recovery_y = min(self.ball.position.y + 70.0, GOAL_TOP + 36.0)
        elif self.ball.position.y > GOAL_BOTTOM:
            recovery_y = max(self.ball.position.y - 70.0, GOAL_BOTTOM - 36.0)
        else:
            recovery_y = self.ball.position.y

        return self._clamp_robot_target(Vector2(recovery_x, recovery_y))

    def _sample_start_positions(self) -> tuple[Vector2, Vector2]:
        if self.difficulty == "easy":
            robot_min_x = FIELD_RECT.left + FIELD_WIDTH * 0.18
            robot_max_x = FIELD_RECT.left + FIELD_WIDTH * 0.34
            robot_min_y = FIELD_RECT.centery - FIELD_HEIGHT * 0.12
            robot_max_y = FIELD_RECT.centery + FIELD_HEIGHT * 0.12

            ball_min_x = FIELD_RECT.left + FIELD_WIDTH * 0.34
            ball_max_x = FIELD_RECT.left + FIELD_WIDTH * 0.48
            ball_min_y = FIELD_RECT.centery - FIELD_HEIGHT * 0.10
            ball_max_y = FIELD_RECT.centery + FIELD_HEIGHT * 0.10
        elif self.difficulty == "hard":
            robot_min_x = FIELD_RECT.left + self.robot.radius + 12.0
            robot_max_x = FIELD_RECT.centerx - self.robot.radius - 12.0
            robot_min_y = FIELD_RECT.top + self.robot.radius + 12.0
            robot_max_y = FIELD_RECT.bottom - self.robot.radius - 12.0

            ball_min_x = FIELD_RECT.left + self.ball.radius + 24.0
            ball_max_x = FIELD_RECT.right - self.ball.radius - 24.0
            ball_min_y = FIELD_RECT.top + self.ball.radius + 24.0
            ball_max_y = FIELD_RECT.bottom - self.ball.radius - 24.0
        else:
            robot_min_x = FIELD_RECT.left + self.robot.radius + 12.0
            robot_max_x = FIELD_RECT.centerx - self.robot.radius - 24.0
            robot_min_y = FIELD_RECT.top + self.robot.radius + 12.0
            robot_max_y = FIELD_RECT.bottom - self.robot.radius - 12.0

            ball_half_width = FIELD_WIDTH * 0.16
            ball_half_height = FIELD_HEIGHT * 0.22
            ball_min_x = FIELD_RECT.centerx - ball_half_width
            ball_max_x = FIELD_RECT.centerx + ball_half_width
            ball_min_y = FIELD_RECT.centery - ball_half_height
            ball_max_y = FIELD_RECT.centery + ball_half_height

        min_separation = self.robot.radius + self.ball.radius + 24.0
        for _ in range(256):
            robot_position = Vector2(
                float(self.np_random.uniform(robot_min_x, robot_max_x)),
                float(self.np_random.uniform(robot_min_y, robot_max_y)),
            )
            ball_position = Vector2(
                float(self.np_random.uniform(ball_min_x, ball_max_x)),
                float(self.np_random.uniform(ball_min_y, ball_max_y)),
            )
            if robot_position.distance_to(ball_position) >= min_separation:
                return robot_position, ball_position

        return Vector2(FIELD_RECT.left + 170.0, FIELD_RECT.centery), Vector2(FIELD_RECT.centerx, FIELD_RECT.centery)

    def _resolve_robot_ball_collision(self) -> bool:
        delta = self.ball.position - self.robot.position
        distance = delta.length()
        min_distance = self.robot.radius + self.ball.radius

        if distance == 0:
            normal = Vector2(1, 0)
        else:
            normal = delta / distance

        if distance < min_distance:
            overlap = min_distance - distance
            self.ball.position += normal * overlap

            relative_speed = self.robot.velocity - self.ball.velocity
            impulse_strength = max(0.0, relative_speed.dot(normal))
            self.ball.velocity += normal * (impulse_strength * 1.35 + 110.0)
            self.robot.velocity *= 0.82
            return True

        return False

    def _resolve_ball_walls(self) -> None:
        if self.ball.position.y - self.ball.radius < FIELD_RECT.top:
            self.ball.position.y = FIELD_RECT.top + self.ball.radius
            self.ball.velocity.y *= -0.85
        elif self.ball.position.y + self.ball.radius > FIELD_RECT.bottom:
            self.ball.position.y = FIELD_RECT.bottom - self.ball.radius
            self.ball.velocity.y *= -0.85

        if not self._ball_within_goal_opening():
            if self.ball.position.x - self.ball.radius < FIELD_RECT.left:
                self.ball.position.x = FIELD_RECT.left + self.ball.radius
                self.ball.velocity.x *= -0.85
            elif self.ball.position.x + self.ball.radius > FIELD_RECT.right:
                self.ball.position.x = FIELD_RECT.right - self.ball.radius
                self.ball.velocity.x *= -0.85

    def _ball_within_goal_opening(self) -> bool:
        return GOAL_TOP <= self.ball.position.y <= GOAL_BOTTOM

    def _detect_goal(self) -> str | None:
        if not self._ball_within_goal_opening():
            return None
        if self.ball.position.x - self.ball.radius <= LEFT_GOAL_RECT.left:
            return "left"
        if self.ball.position.x + self.ball.radius >= RIGHT_GOAL_RECT.right:
            return "right"
        return None

    def _compute_reward(
        self,
        action_array: np.ndarray,
        previous_robot_to_ball: float,
        previous_ball_to_goal: float,
        contact_happened: bool,
    ) -> tuple[float, dict[str, float]]:
        current_robot_to_ball = self.robot.position.distance_to(self.ball.position)
        current_ball_to_goal = self.ball.position.distance_to(RIGHT_GOAL_CENTER)
        robot_speed = self.robot.velocity.length()
        ball_speed = self.ball.velocity.length()

        robot_progress = float((previous_robot_to_ball - current_robot_to_ball) / MAX_DISTANCE)
        ball_progress = float((previous_ball_to_goal - current_ball_to_goal) / MAX_DISTANCE)

        reward = STEP_PENALTY
        reward += robot_progress * 1.0
        reward += ball_progress * 2.5

        contact_bonus = CONTACT_REWARD if contact_happened else 0.0
        reward += contact_bonus

        if ball_speed > 1e-6:
            goal_direction = RIGHT_GOAL_CENTER - self.ball.position
            if goal_direction.length_squared() > 0:
                goal_direction = goal_direction.normalize()
                velocity_direction = self.ball.velocity.normalize()
                toward_goal_bonus = max(0.0, velocity_direction.dot(goal_direction))
                toward_goal_bonus *= min(ball_speed / BALL_SPEED_SCALE, 1.0) * 0.05
            else:
                toward_goal_bonus = 0.0
        else:
            toward_goal_bonus = 0.0
        reward += toward_goal_bonus

        standing_penalty = STANDING_PENALTY if robot_speed < 10.0 else 0.0
        reward += standing_penalty

        action_delta = float(np.linalg.norm(action_array - self.last_action))
        jitter_penalty = action_delta * JITTER_PENALTY_SCALE
        reward -= jitter_penalty

        goal_reward = 0.0
        if self.goal_scored == "right":
            goal_reward = GOAL_REWARD
        elif self.goal_scored == "left":
            goal_reward = OWN_GOAL_PENALTY
        reward += goal_reward

        reward_components = {
            "step_penalty": STEP_PENALTY,
            "robot_progress": robot_progress * 1.0,
            "ball_progress": ball_progress * 2.5,
            "contact_bonus": contact_bonus,
            "toward_goal_bonus": toward_goal_bonus,
            "standing_penalty": standing_penalty,
            "jitter_penalty": -jitter_penalty,
            "goal_reward": goal_reward,
        }
        return reward, reward_components

    def _build_info(self) -> dict[str, Any]:
        info = {
            "goal_scored": self.goal_scored,
            "difficulty": self.difficulty,
            "elapsed_time": self.elapsed_time,
            "step_count": self.step_count,
            "ball_touches": self.ball_touches,
            "shots_toward_goal": self.shots_toward_goal,
            "episode_return": self.episode_return,
            "robot_pos": (self.robot.position.x, self.robot.position.y),
            "ball_pos": (self.ball.position.x, self.ball.position.y),
            "reward_components": self.last_reward_components,
            "is_success": self.goal_scored == "right",
        }
        if self.terminated or self.truncated:
            info["episode"] = {
                "r": self.episode_return,
                "l": self.step_count,
                "ball_touches": self.ball_touches,
                "shots_toward_goal": self.shots_toward_goal,
                "goal_scored": self.goal_scored,
            }
        return info

    def _is_ball_contacting_robot(self) -> bool:
        return self.robot.position.distance_to(self.ball.position) <= self.robot.radius + self.ball.radius + 1e-6

    def _is_shot_toward_goal(self) -> bool:
        if self.ball.velocity.length() < 120.0:
            return False

        goal_vector = RIGHT_GOAL_CENTER - self.ball.position
        if goal_vector.length_squared() == 0:
            return False

        velocity_direction = self.ball.velocity.normalize()
        goal_direction = goal_vector.normalize()
        return velocity_direction.dot(goal_direction) > 0.7

    def _normalize_position_x(self, x_value: float) -> np.float32:
        return np.float32((x_value - FIELD_CENTER.x) / (FIELD_WIDTH / 2.0))

    def _normalize_position_y(self, y_value: float) -> np.float32:
        return np.float32((y_value - FIELD_CENTER.y) / (FIELD_HEIGHT / 2.0))

    def _normalize_robot_velocity(self, velocity_value: float) -> np.float32:
        return np.float32(np.clip(velocity_value / self.robot.max_speed, -1.0, 1.0))

    def _normalize_ball_velocity(self, velocity_value: float) -> np.float32:
        return np.float32(np.clip(velocity_value / BALL_SPEED_SCALE, -1.0, 1.0))

    def _normalize_vector_x(self, x_value: float) -> np.float32:
        return np.float32(np.clip(x_value / FIELD_WIDTH, -1.0, 1.0))

    def _normalize_vector_y(self, y_value: float) -> np.float32:
        return np.float32(np.clip(y_value / FIELD_HEIGHT, -1.0, 1.0))

    def _normalize_distance(self, distance_value: float) -> np.float32:
        return np.float32(np.clip(distance_value / MAX_DISTANCE, 0.0, 1.0))
