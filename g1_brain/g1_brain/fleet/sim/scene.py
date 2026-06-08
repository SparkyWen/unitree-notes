"""Declarative arena registry: one source of truth for the command center's
static world geometry and named landmarks.

Consumed by SharedG1World (build geoms), nl_position (resolve names), the codex
snapshot, and the web map. PERFORMANCE: geoms are static primitives only
(box/cylinder) added to the worldbody with no body/joint -> zero new DOFs and
no extra render passes on WSL2/llvmpipe. No heightfield/mesh/lights."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Geom:
    """One static primitive. ``size`` is MuJoCo-native HALF-extents
    (box: hx,hy,hz; cylinder: radius,half_len). ``avoid_r`` is the circular
    footprint radius the navigator steers around (0 = scenery/terrain, walked
    over, not avoided)."""
    gtype: str                       # "box" | "cylinder"
    pos: Tuple[float, float, float]
    size: Tuple[float, ...]
    rgba: Tuple[float, float, float, float] = (0.6, 0.6, 0.6, 1.0)
    quat: Tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    name: str = ""
    avoid_r: float = 0.0


@dataclass
class Scene:
    geoms: List[Geom] = field(default_factory=list)
    landmarks: Dict[str, Tuple[float, float]] = field(default_factory=dict)


def pitch_quat(deg: float) -> Tuple[float, float, float, float]:
    """Quaternion for a rotation about +Y (pitch) — used to tilt a thin box
    into a ramp."""
    th = math.radians(deg) / 2.0
    return (math.cos(th), 0.0, math.sin(th), 0.0)


# alias substring (lowercased) -> canonical landmark name (must exist in scene)
LANDMARK_ALIASES: Dict[str, str] = {
    "center": "集合点", "centre": "集合点", "middle": "集合点",
    "中间": "集合点", "中心": "集合点", "会合": "集合点", "集合": "集合点",
    "top left": "左上角", "top-left": "左上角", "upper left": "左上角",
    "top right": "右上角", "top-right": "右上角", "upper right": "右上角",
    "bottom left": "左下角", "bottom-left": "左下角", "lower left": "左下角",
    "bottom right": "右下角", "bottom-right": "右下角", "lower right": "右下角",
    "terrain": "地形测试区", "ramp": "地形测试区",
}


def resolve_landmark(landmarks: Dict[str, Tuple[float, float]],
                     text: str) -> Optional[Tuple[float, float]]:
    """Return (x,y) if any landmark name or alias appears in ``text``."""
    low = text.lower()
    for name in sorted(landmarks, key=len, reverse=True):
        if name.lower() in low:
            xy = landmarks[name]
            return (float(xy[0]), float(xy[1]))
    for alias, canon in LANDMARK_ALIASES.items():
        if alias in low and canon in landmarks:
            xy = landmarks[canon]
            return (float(xy[0]), float(xy[1]))
    return None


def _demo_scene() -> Scene:
    R, B, G, Y, O, W = (
        (0.86, 0.20, 0.20, 1), (0.20, 0.42, 0.95, 1), (0.20, 0.75, 0.35, 1),
        (0.95, 0.78, 0.20, 1), (0.95, 0.55, 0.15, 1), (0.55, 0.57, 0.60, 1))
    geoms: List[Geom] = [
        Geom("cylinder", (-2.5, 1.8, 0.40), (0.15, 0.40), R, name="红色柱子", avoid_r=0.45),
        Geom("box",      (2.5, 1.8, 0.40),  (0.25, 0.25, 0.40), B, name="蓝色箱子", avoid_r=0.50),
        Geom("cylinder", (-2.5, -1.8, 0.40), (0.15, 0.40), G, name="绿色柱子", avoid_r=0.45),
        Geom("box",      (2.5, -1.8, 0.30), (0.25, 0.25, 0.30), Y, name="黄色箱子", avoid_r=0.50),
        Geom("cylinder", (0.0, 1.30, 0.35), (0.18, 0.35), O, name="路障", avoid_r=0.50),
        Geom("box",      (0.0, 3.0, 0.30),  (1.5, 0.10, 0.30), W, name="矮墙", avoid_r=0.0),
        Geom("box", (3.5, 0.0, 0.129), (0.60, 0.50, 0.025), W, quat=pitch_quat(10.0), name="斜坡"),
        Geom("box", (4.2, 0.30, 0.03), (0.20, 0.20, 0.03), W, name="起伏1"),
        Geom("box", (4.2, -0.30, 0.025), (0.20, 0.20, 0.025), W, name="起伏2"),
        Geom("box", (4.8, 0.0, 0.025), (0.50, 0.60, 0.025), W, name="矮台阶"),
    ]
    landmarks: Dict[str, Tuple[float, float]] = {
        "集合点": (0.0, 0.0),
        "左上角": (-3.5, 2.5), "右上角": (3.5, 2.5),
        "左下角": (-3.5, -2.5), "右下角": (3.5, -2.5),
        "红色柱子": (-2.5, 1.8), "蓝色箱子": (2.5, 1.8),
        "绿色柱子": (-2.5, -1.8), "黄色箱子": (2.5, -1.8),
        "路障": (0.0, 1.3), "地形测试区": (4.0, 0.0),
    }
    return Scene(geoms=geoms, landmarks=landmarks)


SCENES: Dict[str, Scene] = {"bare": Scene()}
SCENES["demo"] = _demo_scene()
SCENES["solo"] = SCENES["demo"]


def get_scene(name: str) -> Scene:
    return SCENES[name]
