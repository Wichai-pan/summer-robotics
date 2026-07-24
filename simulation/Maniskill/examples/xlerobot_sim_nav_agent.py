#!/usr/bin/env python3
"""Minimal camera/tool/agent navigation pipeline for XLeRobot in ManiSkill.

This mirrors the RoboCrew-style real-robot pipeline at a small scale:

    camera frame -> agent chooses a tool -> tool calls controller -> env.step()

The agent here is deliberately rule-based so the example runs without API keys.
Replace SimpleNavAgent.choose_tool(...) with an LLM call later if desired.
"""

import argparse
import base64
import io
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np


DEFAULT_TABLE_Z = 0.65
DEFAULT_TABLE_SIZE_X = 0.70
DEFAULT_TABLE_SIZE_Y = 0.45
DEFAULT_TABLE_THICKNESS = 0.05
DEFAULT_TABLE_MODEL_HEIGHT = 0.65
DEFAULT_TABLE_STYLE = "scaled"
DEFAULT_TABLE_X = 0.08
DEFAULT_TABLE_Y = 0.0
DEFAULT_CAMERA_UIDS = ("fetch_head", "fetch_right_arm_camera", "fetch_left_arm_camera")
MANISKILL_TABLE_HEIGHT = 0.9196429
MANISKILL_TABLE_SIZE_X = 1.2090764
MANISKILL_TABLE_SIZE_Y = 2.4178784
MANISKILL_TABLE_VISUAL_SCALE = 1.75
Tool = Callable[[], str]


def to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def extract_image(value: Any) -> np.ndarray | None:
    """Find the first image-like array inside ManiSkill render outputs."""
    if value is None:
        return None
    if isinstance(value, dict):
        for item in value.values():
            image = extract_image(item)
            if image is not None:
                return image
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            image = extract_image(item)
            if image is not None:
                return image
        return None

    arr = to_numpy(value)
    if arr.ndim >= 3 and arr.shape[-1] in (3, 4):
        return arr
    return None


def set_actor_xyz(actor: Any, xyz: np.ndarray, sapien_module: Any) -> None:
    if actor is None:
        return
    pose = getattr(actor, "pose", None)
    if pose is None:
        return
    q = to_numpy(pose.q)
    if q.ndim > 1:
        q = q[0]
    actor.set_pose(
        sapien_module.Pose(
            p=np.asarray(xyz, dtype=np.float32),
            q=np.asarray(q, dtype=np.float32),
        )
    )


def place_small_table(env: Any, args: argparse.Namespace, sapien_module: Any) -> None:
    """Place a table for navigation.

    The original ManiSkill table can be moved but not resized after it is built.
    For custom dimensions, build a new table using the same table.glb visual asset.
    """
    table_scene = getattr(env.unwrapped, "table_scene", None)
    original_table = getattr(table_scene, "table", None)
    if original_table is not None and args.table_style == "original":
        pose = getattr(original_table, "pose", None)
        if pose is not None:
            xyz = to_numpy(pose.p)
            if xyz.ndim > 1:
                xyz = xyz[0]
            xyz = np.asarray(xyz, dtype=np.float32)
            table_height = getattr(table_scene, "table_height", MANISKILL_TABLE_HEIGHT)
            xyz[:] = [args.table_x, args.table_y, args.table_z - table_height]
            set_actor_xyz(original_table, xyz, sapien_module)
        env.unwrapped.xlerobot_nav_table = original_table
        return
    if original_table is not None:
        set_actor_xyz(original_table, np.asarray([4.0, 0.0, -2.0], dtype=np.float32), sapien_module)

    scene = getattr(env.unwrapped, "scene", None)
    if scene is None:
        return

    if args.table_style == "scaled":
        build_scaled_table(env, args, sapien_module)
        return

    build_box_table(env, args, sapien_module)


def build_scaled_table(env: Any, args: argparse.Namespace, sapien_module: Any) -> None:
    from pathlib import Path
    import mani_skill

    scene = getattr(env.unwrapped, "scene", None)
    if scene is None:
        return

    maniskill_root = Path(mani_skill.__file__).parent
    table_model_file = (
        maniskill_root
        / "utils"
        / "scene_builder"
        / "table"
        / "assets"
        / "table.glb"
    )
    table_yaw_quat = np.asarray([0.70710678, 0.0, 0.0, 0.70710678], dtype=np.float32)
    table_height = max(args.table_model_height, 1e-3)
    local_size_x = args.table_size_y
    local_size_y = args.table_size_x
    visual_scale = [
        MANISKILL_TABLE_VISUAL_SCALE * (args.table_size_y / MANISKILL_TABLE_SIZE_Y),
        MANISKILL_TABLE_VISUAL_SCALE * (args.table_size_x / MANISKILL_TABLE_SIZE_X),
        MANISKILL_TABLE_VISUAL_SCALE * (table_height / MANISKILL_TABLE_HEIGHT),
    ]

    builder = scene.create_actor_builder()
    builder.add_box_collision(
        pose=sapien_module.Pose(p=np.asarray([0.0, 0.0, table_height / 2.0], dtype=np.float32)),
        half_size=[local_size_x / 2.0, local_size_y / 2.0, table_height / 2.0],
    )
    builder.add_visual_from_file(
        filename=str(table_model_file),
        scale=visual_scale,
        pose=sapien_module.Pose(q=table_yaw_quat),
    )
    builder.initial_pose = sapien_module.Pose(
        p=np.asarray(
            [args.table_x, args.table_y, args.table_z - table_height],
            dtype=np.float32,
        ),
        q=table_yaw_quat,
    )
    env.unwrapped.xlerobot_nav_table = builder.build_kinematic(name="xlerobot-nav-scaled-table")


def build_box_table(env: Any, args: argparse.Namespace, sapien_module: Any) -> None:
    scene = getattr(env.unwrapped, "scene", None)
    if scene is None:
        return

    builder = scene.create_actor_builder()
    half_size = [
        args.table_size_x / 2.0,
        args.table_size_y / 2.0,
        args.table_thickness / 2.0,
    ]
    builder.add_box_collision(pose=sapien_module.Pose(), half_size=half_size)
    builder.add_box_visual(
        pose=sapien_module.Pose(),
        half_size=half_size,
        material=[0.45, 0.43, 0.38, 1.0],
    )
    builder.initial_pose = sapien_module.Pose(
        p=np.asarray(
            [
                args.table_x,
                args.table_y,
                args.table_z - args.table_thickness / 2.0,
            ],
            dtype=np.float32,
        )
    )
    env.unwrapped.xlerobot_nav_table = builder.build_kinematic(name="xlerobot-nav-table")


def pose_to_config_list(pose: Any) -> list[float]:
    p = to_numpy(pose.p)
    q = to_numpy(pose.q)
    if p.ndim > 1:
        p = p[0]
    if q.ndim > 1:
        q = q[0]
    return [*p.astype(float).tolist(), *q.astype(float).tolist()]


@dataclass
class SimXLeRobotController:
    env: Any
    render_every: int
    ignore_render_errors: bool
    hz: float
    camera_source: str
    camera_uid: str
    allow_render_fallback: bool

    def __post_init__(self) -> None:
        self.action = np.zeros(self.env.action_space.shape, dtype=np.float32)
        self.step_count = 0
        self.render_enabled = self.env.render_mode is not None
        self.last_obs = None

    def camera_frame(self) -> np.ndarray | None:
        """Return robot-mounted camera by default, or render camera as fallback."""
        if self.camera_source == "robot":
            frame = self.robot_camera_frame()
            if frame is not None:
                return frame
            if not self.allow_render_fallback:
                print(f"Robot camera '{self.camera_uid}' not available; no frame saved.")
                return None
            print(f"Robot camera '{self.camera_uid}' not available; falling back to render camera.")

        return self.render_camera_frame()

    def robot_camera_frame(self) -> np.ndarray | None:
        frames = self.robot_camera_frames()
        if not frames:
            return None
        if self.camera_uid == "all":
            return make_camera_mosaic(frames)
        return frames.get(self.camera_uid)

    def robot_camera_frames(self) -> dict[str, np.ndarray]:
        try:
            sensor_images = self.env.unwrapped.get_sensor_images()
        except Exception as exc:
            print(f"Could not read robot sensor images: {exc}")
            return {}

        camera_uids = DEFAULT_CAMERA_UIDS if self.camera_uid == "all" else (self.camera_uid,)
        frames: dict[str, np.ndarray] = {}
        for camera_uid in camera_uids:
            camera_data = sensor_images.get(camera_uid)
            if camera_data is None:
                print(f"Camera '{camera_uid}' unavailable. Available robot cameras: {list(sensor_images.keys())}")
                continue
            for key in ("rgb", "Color"):
                if key in camera_data:
                    frame = extract_image(camera_data[key])
                    if frame is not None:
                        frames[camera_uid] = frame
                    break
            if camera_uid not in frames:
                print(f"Camera '{camera_uid}' has no rgb/Color image; keys={list(camera_data.keys())}")
        return frames

    def render_camera_frame(self) -> np.ndarray | None:
        if not self.render_enabled:
            return None
        try:
            render_result = self.env.render()
        except RuntimeError as exc:
            if self.ignore_render_errors:
                print(f"Render/camera failed; continuing without frame: {exc}")
                self.render_enabled = False
                return None
            raise
        frame = extract_image(render_result)
        if frame is None:
            print(f"Render returned no image frame; result type={type(render_result).__name__}")
        return frame

    def step_base(self, forward: float = 0.0, turn: float = 0.0, steps: int = 15) -> None:
        dt = 1.0 / self.hz
        for _ in range(steps):
            self.action[:] = 0.0
            self.action[0] = forward
            if self.action.size > 1:
                self.action[1] = turn

            self.last_obs, _reward, terminated, truncated, _info = self.env.step(self.action)
            self.step_count += 1
            if self.step_count % self.render_every == 0:
                self.camera_frame()
            if (terminated | truncated).any():
                break
            time.sleep(dt)

    def move_forward(self, speed: float = 0.14, steps: int = 18) -> str:
        self.step_base(forward=speed, turn=0.0, steps=steps)
        return f"Moved forward for {steps} sim steps."

    def turn_left(self, speed: float = 0.35, steps: int = 14) -> str:
        self.step_base(forward=0.0, turn=speed, steps=steps)
        return f"Turned left for {steps} sim steps."

    def turn_right(self, speed: float = 0.35, steps: int = 14) -> str:
        self.step_base(forward=0.0, turn=-speed, steps=steps)
        return f"Turned right for {steps} sim steps."


def create_move_forward(controller: SimXLeRobotController) -> Tool:
    def move_forward() -> str:
        return controller.move_forward()

    move_forward.__name__ = "move_forward"
    move_forward.description = "Drive the XLeRobot base forward a short distance."
    return move_forward


def create_turn_left(controller: SimXLeRobotController) -> Tool:
    def turn_left() -> str:
        return controller.turn_left()

    turn_left.__name__ = "turn_left"
    turn_left.description = "Rotate the XLeRobot base left a small amount."
    return turn_left


def create_turn_right(controller: SimXLeRobotController) -> Tool:
    def turn_right() -> str:
        return controller.turn_right()

    turn_right.__name__ = "turn_right"
    turn_right.description = "Rotate the XLeRobot base right a small amount."
    return turn_right


class SimpleNavAgent:
    """Tiny stand-in for an LLM agent that chooses from named tools."""

    def __init__(self, tools: list[Tool], task: str, save_camera_dir: str | None = None):
        self.tools = {tool.__name__: tool for tool in tools}
        self.task = task
        self.decision_count = 0
        self.save_camera_dir = save_camera_dir
        self.needs_camera = True
        if self.save_camera_dir:
            os.makedirs(self.save_camera_dir, exist_ok=True)

    def choose_tool(self, frame: np.ndarray | None) -> str:
        # This is where an LLM would inspect the image and choose a tool.
        # The scripted sequence keeps the example deterministic and API-free.
        sequence = [
            "move_forward",
            "move_forward",
            "turn_left",
            "move_forward",
            "turn_right",
            "move_forward",
        ]
        if self.decision_count >= len(sequence):
            return "finish_task"
        return sequence[self.decision_count]

    def go(self, controller: SimXLeRobotController, max_decisions: int) -> None:
        print(f"Agent task: {self.task}")
        for _ in range(max_decisions):
            frame = controller.camera_frame() if self.needs_camera or self.save_camera_dir else None
            if frame is not None and self.save_camera_dir:
                save_camera_frame(frame, self.save_camera_dir, self.decision_count)
            frame_info = "none" if frame is None else f"{frame.shape}"
            tool_name = self.choose_tool(frame)
            print(f"decision={self.decision_count:02d} camera={frame_info} selected_tool={tool_name}")

            if tool_name == "finish_task":
                print("Agent finished task.")
                break

            tool = self.tools[tool_name]
            result = tool()
            print(f"tool_result={result}")
            self.decision_count += 1


class OpenAIVisionNavAgent(SimpleNavAgent):
    """Vision agent that asks a model to choose one tool from the tool list."""

    def __init__(
        self,
        tools: list[Tool],
        task: str,
        model: str,
        save_camera_dir: str | None = None,
    ):
        super().__init__(tools=tools, task=task, save_camera_dir=save_camera_dir)
        from openai import OpenAI

        self.client = OpenAI()
        self.model = model

    def choose_tool(self, frame: np.ndarray | None) -> str:
        if frame is None:
            return "move_forward"

        tool_names = [*self.tools.keys(), "finish_task"]
        prompt = (
            "You are controlling a simulated XLeRobot base using only these tools: "
            f"{tool_names}. The input image is a horizontal mosaic of the robot's "
            "head camera, right wrist camera, and left wrist camera. Choose exactly "
            "one next tool. Prefer small cautious moves. Return only JSON like "
            '{"tool":"move_forward"} with no extra text.\n'
            f"Task: {self.task}"
        )
        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": frame_to_data_url(frame)},
                    ],
                }
            ],
        )
        text = getattr(response, "output_text", "") or ""
        try:
            data = json.loads(text)
            tool_name = data.get("tool", "")
        except json.JSONDecodeError:
            tool_name = text.strip().strip("`")

        if tool_name not in tool_names:
            print(f"Model returned invalid tool '{tool_name}', using finish_task.")
            return "finish_task"
        return tool_name


class GeminiVisionNavAgent(SimpleNavAgent):
    """Vision agent that asks Gemini to choose one tool from the tool list."""

    def __init__(
        self,
        tools: list[Tool],
        task: str,
        model: str,
        save_camera_dir: str | None = None,
    ):
        super().__init__(tools=tools, task=task, save_camera_dir=save_camera_dir)
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ImportError(
                "Gemini agent requires the official Google GenAI SDK. "
                "Install it with: pip install google-genai"
            ) from exc

        self.client = genai.Client()
        self.types = types
        self.model = model

    def choose_tool(self, frame: np.ndarray | None) -> str:
        if frame is None:
            return "move_forward"

        tool_names = [*self.tools.keys(), "finish_task"]
        prompt = (
            "You are controlling a simulated XLeRobot base using only these tools: "
            f"{tool_names}. The input image is a horizontal mosaic of the robot's "
            "head camera, right wrist camera, and left wrist camera. Choose exactly "
            "one next tool. Prefer small cautious moves. Return only JSON like "
            '{"tool":"move_forward"} with no extra text.\n'
            f"Task: {self.task}"
        )
        image_part = self.types.Part.from_bytes(
            data=frame_to_png_bytes(frame),
            mime_type="image/png",
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=[image_part, prompt],
        )
        text = getattr(response, "text", "") or ""
        try:
            data = json.loads(text)
            tool_name = data.get("tool", "")
        except json.JSONDecodeError:
            tool_name = text.strip().strip("`")

        if tool_name not in tool_names:
            print(f"Model returned invalid tool '{tool_name}', using finish_task.")
            return "finish_task"
        return tool_name


class DeepSeekNavAgent(SimpleNavAgent):
    """Text-only DeepSeek agent that chooses one tool from the tool list."""

    def __init__(
        self,
        tools: list[Tool],
        task: str,
        model: str,
        save_camera_dir: str | None = None,
    ):
        super().__init__(tools=tools, task=task, save_camera_dir=save_camera_dir)
        from openai import OpenAI

        self.client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )
        self.model = model
        self.needs_camera = False

    def choose_tool(self, frame: np.ndarray | None) -> str:
        tool_names = [*self.tools.keys(), "finish_task"]
        frame_info = "none" if frame is None else f"{frame.shape}"
        prompt = (
            "You are controlling a simulated XLeRobot base using only these tools: "
            f"{tool_names}. You cannot inspect raw camera pixels in this DeepSeek "
            "mode, so make a cautious navigation decision from the task, the decision "
            "index, and any camera metadata. Return only valid JSON like "
            '{"tool":"move_forward"} with no extra text.\n'
            f"Task: {self.task}\n"
            f"Decision index: {self.decision_count}\n"
            f"Camera mosaic shape: {frame_info}"
        )
        print(f"Calling DeepSeek model={self.model} decision={self.decision_count}...")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You choose one robot control tool and return JSON only."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=64,
            extra_body={"thinking": {"type": "disabled"}},
        )
        text = response.choices[0].message.content or ""
        print(f"DeepSeek raw response: {text}")
        try:
            data = json.loads(text)
            tool_name = data.get("tool", "")
        except json.JSONDecodeError:
            tool_name = text.strip().strip("`")

        if tool_name not in tool_names:
            print(f"Model returned invalid tool '{tool_name}', using finish_task.")
            return "finish_task"
        return tool_name


def save_camera_frame(frame: np.ndarray, out_dir: str, index: int) -> None:
    from PIL import Image

    image = prepare_image(frame)

    path = os.path.join(out_dir, f"camera_{index:03d}_mosaic.png")
    Image.fromarray(image).save(path)
    print(f"saved_camera={path}")


def frame_to_data_url(frame: np.ndarray) -> str:
    encoded = base64.b64encode(frame_to_png_bytes(frame)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def frame_to_png_bytes(frame: np.ndarray) -> bytes:
    from PIL import Image

    image = prepare_image(frame)
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="PNG")
    return buffer.getvalue()


def prepare_image(frame: np.ndarray) -> np.ndarray:
    image = frame
    if image.ndim == 4:
        image = image[0]
    if image.ndim == 3 and image.shape[0] in (3, 4) and image.shape[-1] not in (3, 4):
        image = np.moveaxis(image, 0, -1)
    if image.dtype != np.uint8:
        if np.nanmax(image) <= 1.0:
            image = image * 255.0
        image = np.clip(image, 0, 255).astype(np.uint8)
    if image.shape[-1] == 4:
        image = image[..., :3]
    return image


def make_camera_mosaic(frames: dict[str, np.ndarray]) -> np.ndarray:
    images = [prepare_image(frames[name]) for name in DEFAULT_CAMERA_UIDS if name in frames]
    if not images:
        return None
    min_h = min(image.shape[0] for image in images)
    resized = []
    for image in images:
        if image.shape[0] != min_h:
            scale = min_h / image.shape[0]
            new_w = max(1, int(image.shape[1] * scale))
            image = nearest_resize(image, min_h, new_w)
        resized.append(image)
    return np.concatenate(resized, axis=1)


def nearest_resize(image: np.ndarray, height: int, width: int) -> np.ndarray:
    y_idx = np.linspace(0, image.shape[0] - 1, height).astype(np.int64)
    x_idx = np.linspace(0, image.shape[1] - 1, width).astype(np.int64)
    return image[y_idx][:, x_idx]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-id", default="PushCube-v1")
    parser.add_argument("--robot", default="xlerobot")
    parser.add_argument("--control-mode", default="pd_joint_delta_pos_dual_arm")
    parser.add_argument("--obs-mode", default="sensor_data")
    parser.add_argument("--render-mode", default="rgb_array")
    parser.add_argument("--shader", default="default")
    parser.add_argument("--seed", type=int, default=2022)
    parser.add_argument("--max-episode-steps", type=int, default=500)
    parser.add_argument("--max-decisions", type=int, default=8)
    parser.add_argument("--save-camera-dir", default=None)
    parser.add_argument("--agent", choices=("auto", "scripted", "openai", "gemini", "deepseek"), default="auto")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"))
    parser.add_argument("--gemini-model", default=os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"))
    parser.add_argument("--deepseek-model", default=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    parser.add_argument("--camera-source", choices=("robot", "render"), default="robot")
    parser.add_argument("--camera-uid", default="all")
    parser.add_argument("--allow-render-fallback", action="store_true")
    parser.add_argument("--hz", type=float, default=30.0)
    parser.add_argument("--render-every", type=int, default=4)
    parser.add_argument("--ignore-render-errors", action="store_true")

    parser.add_argument("--table-x", type=float, default=DEFAULT_TABLE_X)
    parser.add_argument("--table-y", type=float, default=DEFAULT_TABLE_Y)
    parser.add_argument("--table-z", type=float, default=DEFAULT_TABLE_Z)
    parser.add_argument("--table-size-x", type=float, default=DEFAULT_TABLE_SIZE_X)
    parser.add_argument("--table-size-y", type=float, default=DEFAULT_TABLE_SIZE_Y)
    parser.add_argument("--table-thickness", type=float, default=DEFAULT_TABLE_THICKNESS)
    parser.add_argument("--table-model-height", type=float, default=DEFAULT_TABLE_MODEL_HEIGHT)
    parser.add_argument("--table-style", choices=("original", "scaled", "box"), default=DEFAULT_TABLE_STYLE)
    return parser.parse_args()


def main() -> None:
    import gymnasium as gym
    import sapien
    from mani_skill.utils import sapien_utils

    maniskill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, maniskill_dir)
    from agents.xlerobot import xlerobot  # noqa: F401

    render_mode = None if args.render_mode.lower() == "none" else args.render_mode
    render_camera_pose = sapien_utils.look_at(
        eye=[0.55, -0.65, 1.25],
        target=[args.table_x, args.table_y, args.table_z],
    )
    render_camera_overrides = {
        "render_camera": {
            "pose": pose_to_config_list(render_camera_pose),
            "width": 512,
            "height": 512,
            "fov": 1.0,
            "near": 0.01,
            "far": 100,
            "shader_pack": args.shader,
        }
    }
    viewer_camera_overrides = {
        "viewer": {
            "pose": pose_to_config_list(render_camera_pose),
            "width": 1280,
            "height": 720,
            "fov": 1.0,
            "near": 0.01,
            "far": 100,
            "shader_pack": args.shader,
        }
    }
    env = gym.make(
        args.env_id,
        obs_mode=args.obs_mode,
        control_mode=args.control_mode,
        render_mode=render_mode,
        robot_uids=args.robot,
        sensor_configs=dict(shader_pack=args.shader),
        human_render_camera_configs=render_camera_overrides,
        viewer_camera_configs=viewer_camera_overrides,
        num_envs=1,
        sim_backend="auto",
        max_episode_steps=args.max_episode_steps,
    )

    try:
        print("Observation space:", env.observation_space)
        print("Action space:", env.action_space)
        env.reset(seed=args.seed, options=dict(reconfigure=True))
        place_small_table(env, args, sapien)

        controller = SimXLeRobotController(
            env=env,
            render_every=args.render_every,
            ignore_render_errors=args.ignore_render_errors,
            hz=args.hz,
            camera_source=args.camera_source,
            camera_uid=args.camera_uid,
            allow_render_fallback=args.allow_render_fallback,
        )
        tools = [
            create_move_forward(controller),
            create_turn_left(controller),
            create_turn_right(controller),
        ]
        task = "Move forward slowly and turn right"
        use_openai_agent = args.agent == "openai" or (
            args.agent == "auto" and bool(os.environ.get("OPENAI_API_KEY"))
        )
        use_gemini_agent = args.agent == "gemini" or (
            args.agent == "auto"
            and not use_openai_agent
            and bool(os.environ.get("GEMINI_API_KEY"))
        )
        use_deepseek_agent = args.agent == "deepseek" or (
            args.agent == "auto"
            and not use_openai_agent
            and not use_gemini_agent
            and bool(os.environ.get("DEEPSEEK_API_KEY"))
        )
        if use_openai_agent:
            agent = OpenAIVisionNavAgent(
                tools=tools,
                task=task,
                model=args.model,
                save_camera_dir=args.save_camera_dir,
            )
            print(f"Using OpenAI vision agent with model={args.model}")
        elif use_gemini_agent:
            agent = GeminiVisionNavAgent(
                tools=tools,
                task=task,
                model=args.gemini_model,
                save_camera_dir=args.save_camera_dir,
            )
            print(f"Using Gemini vision agent with model={args.gemini_model}")
        elif use_deepseek_agent:
            agent = DeepSeekNavAgent(
                tools=tools,
                task=task,
                model=args.deepseek_model,
                save_camera_dir=args.save_camera_dir,
            )
            print(
                f"Using DeepSeek text-only agent with model={args.deepseek_model}. "
                "Camera mosaic is saved locally but not sent to DeepSeek."
            )
        else:
            agent = SimpleNavAgent(
                tools=tools,
                task=task,
                save_camera_dir=args.save_camera_dir,
            )
            print(
                "Using scripted fallback agent. Set OPENAI_API_KEY/GEMINI_API_KEY/DEEPSEEK_API_KEY "
                "or pass --agent openai/--agent gemini/--agent deepseek to use a model."
            )
        agent.go(controller=controller, max_decisions=args.max_decisions)
    finally:
        env.close()


if __name__ == "__main__":
    args = parse_args()
    main()
