"""SkillServer: single async entry point for every tool the LLM can call.

This is the convergence point of the brain (LLM tool calls in) and the
sim/real backends (motion primitives out). Every call goes through:

    safety.validate(tool, args)  -> sanitized_args
        -> _skill_<tool>(**sanitized_args)
            -> {"ok": bool, ...}    (with scene snapshot attached on success)

If the safety layer rejects the call we never invoke the skill. If the
skill itself raises, we run a defensive ``stop`` and return ok=false.
The FSM transitions ENGAGED→ACTING on motion start and back on end.

The combo controller (`g1_sim_rl_combo.ComboController`) is imported via a
small wrapper helper so tests can monkey-patch the loader and avoid pulling
in onnxruntime / DDS / mujoco at import time.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from . import compound_skills
from .keyframe_extras import build_extra_arm_actions
from .tool_schemas import (
    GESTURE_NAMES,
    LOOK_AT_TARGETS,
    MIRRORABLE_GESTURES,
    STATIC_POSE_NAMES,
)

log = logging.getLogger(__name__)


# ---- ComboController loader (test-monkey-patchable) ------------------------

def _ensure_g1_sim_demo_on_path() -> None:
    """Make `import g1_sim_rl_combo` resolve. Mirrors va_demo.skills."""
    p = Path.home() / "unitree" / "unitree-notes" / "g1_sim_demo"
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _load_combo_module():
    """Import and return the g1_sim_rl_combo module. Tests monkey-patch
    *this function* (not the path helper) to inject a fake combo with the
    minimal surface we use: ``ArmAction`` and ``build_arm_actions``.
    """
    _ensure_g1_sim_demo_on_path()
    import g1_sim_rl_combo as combo  # noqa: WPS433 (deliberate late import)
    return combo


# ---- Walk reactive-interrupt knobs ----------------------------------------

# How often we re-check SceneState mid-walk. Spec §4.3 calls for 0.2 s.
_WALK_SCENE_CHECK_INTERVAL_S = 0.2

# Mid-walk obstacle threshold. We intentionally use a tighter floor than
# the SafetySupervisor pre-check (0.6m) — once we're already moving the
# 0.5m line is the "abort *now*" trigger; below it the policy won't have
# time to finish a step cleanly.
_WALK_ABORT_OBSTACLE_M = 0.5

# turn(yaw_deg) parameters.
_TURN_YAW_RATE_RAD_S = 0.25
_TURN_DURATION_PER_DEG = 1.0 / 25.0   # min(|yaw|/25, 1.5)
_TURN_MAX_DURATION_S = 1.5


class SkillServer:
    """Validate-then-dispatch wrapper around the motion / vision / TTS layer.

    All public methods are coroutines. The combo controller's own thread
    safety (50 Hz tick + cmd_lock + arm_lock) means concurrent calls to
    ``execute`` are safe; we don't add an extra outer lock.
    """

    def __init__(
        self,
        *,
        combo_ctl,
        safety,
        tts,
        vision,
        camera_hub,
        scene_bus,
        fsm,
        sim: bool = True,
    ) -> None:
        self.combo = combo_ctl
        self.safety = safety
        self.tts = tts
        self.vision = vision
        self.cam = camera_hub
        self.scene = scene_bus
        self.fsm = fsm
        self.sim = sim

        # Pre-build the gesture lookup table:
        #   name (str)  ->  ArmAction (with .keyframes)
        # Combined sources: combo's 8 RL-tolerant gestures + our 2 keyframe
        # extras (salute, hug). We tolerate the combo module being absent
        # (e.g. real-robot-only deployment) — methods that need the table
        # raise a clean error at call time instead.
        self._gesture_table: Dict[str, Any] = {}
        self._extras_by_name: Dict[str, Any] = {}
        try:
            self._gesture_table = self._build_gesture_table()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "[skill_server] gesture table not built (%s); "
                "gesture/static_pose calls will fail until combo is wired.",
                e,
            )

    # ----- gesture / static_pose tables -----------------------------------

    # Map gesture name -> the combo "key" that build_arm_actions assigns.
    # This mirrors va_demo.skills.GESTURE_KEY_MAP exactly.
    _COMBO_KEY_FOR_NAME: Dict[str, str] = {
        "wave_right":  "1",
        "wave_left":   "2",
        "hands_up":    "3",
        "t_pose":      "4",
        "salute":      "5",
        "clap":        "6",
        "guard":       "7",
        "punch_combo": "8",
    }

    def _build_gesture_table(self) -> Dict[str, Any]:
        """Pre-build the {gesture_name -> ArmAction} lookup once at init.

        Pulls 8 from combo.build_arm_actions and 2 from keyframe_extras.
        The combo module is loaded lazily via ``_load_combo_module`` so
        tests can stub it.
        """
        combo_mod = _load_combo_module()
        combo_actions = combo_mod.build_arm_actions(
            self.combo.arm_rest, self.combo.arm_scale
        )
        actions_by_key = {a.key: a for a in combo_actions}

        table: Dict[str, Any] = {}
        for name, key in self._COMBO_KEY_FOR_NAME.items():
            if key in actions_by_key:
                table[name] = actions_by_key[key]

        extras = build_extra_arm_actions(
            self.combo.arm_rest, self.combo.arm_scale, self.combo.arm_offset,
        )
        self._extras_by_name = {a.name: a for a in extras}
        for a in extras:
            # Extras keyed by name; expose under both gesture and static_pose
            # by adding into the unified table. static_pose shares this
            # storage but its dispatcher (_skill_static_pose) restricts the
            # name set to STATIC_POSE_NAMES.
            table[a.name] = a
        return table

    # ----- Public single entry point --------------------------------------

    async def execute(self, tool: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Validate `tool(args)` via safety then dispatch.

        Always returns a dict; never raises. ``ok=True`` results from
        motion skills get a ``scene_after`` field with a fresh snapshot
        summary so the brain has post-action context.
        """
        args = dict(args or {})
        try:
            ok, reason, sanitized = await self.safety.validate(tool, args)
        except Exception as e:  # noqa: BLE001
            log.exception("safety.validate raised; rejecting %s", tool)
            return {"ok": False, "skill": tool, "reason": f"safety exception: {e!s}"}

        if not ok:
            return {"ok": False, "skill": tool, "reason": reason}

        sanitized = dict(sanitized or {})
        method = getattr(self, f"_skill_{tool}", None)
        if method is None:
            return {"ok": False, "skill": tool, "reason": f"unknown tool: {tool!r}"}

        is_motion = tool in _MOTION_TOOLS
        if is_motion:
            self._fsm_safe_transition_to_acting(tool)

        try:
            result = await method(**sanitized)
        except Exception as e:  # noqa: BLE001
            log.exception("skill %s raised; running defensive stop", tool)
            try:
                await self._skill_stop()
            except Exception:  # noqa: BLE001
                log.exception("defensive stop also failed")
            result = {"ok": False, "skill": tool, "reason": f"exception: {e!s}"}
        finally:
            if is_motion:
                self._fsm_safe_transition_to_engaged(tool)

        # Normalize result envelope.
        if not isinstance(result, dict):
            result = {"ok": True, "skill": tool, "value": result}
        result.setdefault("ok", True)
        result.setdefault("skill", tool)

        # Attach post-action scene snapshot for motion skills that succeeded.
        if is_motion and result.get("ok", False):
            try:
                result["scene_after"] = self.scene.snapshot().summary_for_llm()
            except Exception:  # noqa: BLE001
                log.exception("scene snapshot for tool result failed; omitting")

        return result

    # ----- FSM helpers (never raise to caller) ----------------------------

    def _fsm_safe_transition_to_acting(self, tool: str) -> None:
        try:
            from ..safety.state_machine import RobotFsmState
            current = self.fsm.state
            if current == RobotFsmState.ACTING:
                return
            if current == RobotFsmState.ENGAGED:
                self.fsm.transition(RobotFsmState.ACTING, reason=f"skill {tool}")
        except Exception:  # noqa: BLE001
            log.debug("fsm transition to ACTING skipped", exc_info=True)

    def _fsm_safe_transition_to_engaged(self, tool: str) -> None:
        try:
            from ..safety.state_machine import RobotFsmState
            if self.fsm.state == RobotFsmState.ACTING:
                self.fsm.transition(RobotFsmState.ENGAGED, reason=f"skill {tool} done")
        except Exception:  # noqa: BLE001
            log.debug("fsm transition to ENGAGED skipped", exc_info=True)

    # ===== individual skill implementations ===============================

    # ---- L1: speech & vision ---------------------------------------------

    async def _skill_say(self, text: str) -> Dict[str, Any]:
        await self.tts.speak(text)
        return {"ok": True, "skill": "say", "spoken": text}

    async def _skill_describe_scene(
        self, question: str = "", detail: str = "medium",
    ) -> Dict[str, Any]:
        jpeg_b64 = self._latest_jpeg_b64_preferring_head()
        if jpeg_b64 is None:
            return {"ok": False, "skill": "describe_scene", "reason": "no frame available"}
        prompt = (
            "Describe what the robot's first-person camera sees. "
            "Be concise (1-2 short sentences). Mention people, obstacles, "
            "and whether the path forward looks clear."
        )
        if question:
            prompt = prompt + f"\nUser question: {question}"
        text = await self.vision.describe(
            image_jpeg_b64=jpeg_b64, prompt=prompt, detail=detail,
        )
        return {"ok": True, "skill": "describe_scene", "description": text}

    async def _skill_query_scene_state(self) -> Dict[str, Any]:
        return {
            "ok": True, "skill": "query_scene_state",
            "scene": self.scene.snapshot().summary_for_llm(),
        }

    # ---- L1: compound skills (delegate) ----------------------------------

    async def _skill_look_at(self, target: str) -> Dict[str, Any]:
        return await compound_skills.look_at(self, {"target": target})

    async def _skill_approach(self, target_distance_m: float) -> Dict[str, Any]:
        return await compound_skills.approach(
            self, {"target_distance_m": target_distance_m},
        )

    async def _skill_mock_imitate(self, gesture: str) -> Dict[str, Any]:
        return await compound_skills.mock_imitate(self, {"gesture": gesture})

    async def _skill_ask_human(self, question: str) -> Dict[str, Any]:
        return await compound_skills.ask_human(self, {"question": question})

    # ---- L2: motion primitives -------------------------------------------

    async def _skill_walk(
        self,
        vx: float = 0.0,
        vy: float = 0.0,
        wz: float = 0.0,
        duration_s: float = 0.5,
    ) -> Dict[str, Any]:
        """Send a velocity command for `duration_s`, re-checking the scene
        every 0.2s and aborting early if the path becomes unsafe.

        Always issues a zero-command in finally so a raise here can't leave
        the robot walking.
        """
        log.info(
            "walk vx=%+0.2f vy=%+0.2f wz=%+0.2f dur=%.2f",
            vx, vy, wz, duration_s,
        )
        self.combo.set_command(vx, vy, wz)
        t0 = time.monotonic()
        abort_reason: Optional[str] = None
        try:
            while True:
                elapsed = time.monotonic() - t0
                if elapsed >= duration_s:
                    break
                await asyncio.sleep(min(_WALK_SCENE_CHECK_INTERVAL_S, duration_s - elapsed))
                scene = self.scene.snapshot()
                ground = getattr(scene, "ground", None)
                if ground is None:
                    continue
                if not ground.clear_path:
                    abort_reason = "path blocked"
                    log.warning("walk aborted: path blocked at t=%.2f", elapsed)
                    break
                if ground.nearest_obstacle_m < _WALK_ABORT_OBSTACLE_M:
                    abort_reason = (
                        f"obstacle {ground.nearest_obstacle_m:.2f}m within "
                        f"{_WALK_ABORT_OBSTACLE_M:.2f}m"
                    )
                    log.warning("walk aborted: %s", abort_reason)
                    break
        finally:
            self.combo.set_command(0.0, 0.0, 0.0)

        return {
            "ok": True,
            "skill": "walk",
            "actual_duration_s": round(time.monotonic() - t0, 3),
            "aborted": abort_reason is not None,
            **({"abort_reason": abort_reason} if abort_reason else {}),
        }

    async def _skill_turn(self, yaw_deg: float) -> Dict[str, Any]:
        """Rotate in place. Translates yaw_deg → (wz, duration) then routes
        through `_skill_walk` so we get the same reactive-interrupt loop.
        """
        if abs(yaw_deg) < 0.5:
            return {"ok": True, "skill": "turn", "yaw_deg": yaw_deg, "actual_duration_s": 0.0}
        sign = 1.0 if yaw_deg >= 0 else -1.0
        wz = sign * _TURN_YAW_RATE_RAD_S
        duration_s = min(abs(yaw_deg) * _TURN_DURATION_PER_DEG, _TURN_MAX_DURATION_S)
        # Bypass safety re-validate here: we're already inside an execute()
        # call that validated `turn(yaw_deg)`; calling _skill_walk directly
        # avoids re-prompting the operator in confirm-mode.
        result = await self._skill_walk(vx=0.0, vy=0.0, wz=wz, duration_s=duration_s)
        result["skill"] = "turn"
        result["yaw_deg"] = yaw_deg
        return result

    async def _skill_gesture(self, name: str) -> Dict[str, Any]:
        action = self._gesture_table.get(name)
        if action is None:
            return {
                "ok": False, "skill": "gesture",
                "reason": f"unknown gesture: {name!r}; "
                          f"allowed: {sorted(self._gesture_table.keys())}",
            }
        log.info("gesture %s", name)
        self.combo.push_arm_action(action.keyframes)
        # Don't await the full keyframe duration; combo plays it async and
        # releases arms back to the policy when the last keyframe finishes.
        return {"ok": True, "skill": "gesture", "name": name}

    async def _skill_static_pose(self, name: str) -> Dict[str, Any]:
        if name not in STATIC_POSE_NAMES:
            return {
                "ok": False, "skill": "static_pose",
                "reason": f"static_pose only supports {STATIC_POSE_NAMES}; got {name!r}",
            }
        action = self._extras_by_name.get(name) or self._gesture_table.get(name)
        if action is None:
            return {
                "ok": False, "skill": "static_pose",
                "reason": f"static pose {name!r} not registered",
            }
        log.info("static_pose %s", name)
        self.combo.push_arm_action(action.keyframes)
        return {"ok": True, "skill": "static_pose", "name": name}

    async def _skill_stop(self) -> Dict[str, Any]:
        log.info("stop")
        self.combo.set_command(0.0, 0.0, 0.0)
        self.combo.release_arms()
        return {"ok": True, "skill": "stop"}

    async def _skill_release_arms(self) -> Dict[str, Any]:
        log.info("release_arms")
        self.combo.release_arms()
        return {"ok": True, "skill": "release_arms"}

    # ---- Real-robot-only (always reject in sim) --------------------------

    async def _skill_loco_high(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"ok": False, "skill": "loco_high", "reason": "real-robot only"}

    async def _skill_arm_action_high(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"ok": False, "skill": "arm_action_high", "reason": "real-robot only"}

    async def _skill_audio_tts_robot(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"ok": False, "skill": "audio_tts_robot", "reason": "real-robot only"}

    # ----- Helpers ---------------------------------------------------------

    def _latest_jpeg_b64_preferring_head(self) -> Optional[str]:
        """Pick the head camera JPEG when available (robot's first-person
        view); fall back to USB. The CameraHub interface is still in flux
        — we probe a few likely method names so we don't break when it
        lands."""
        cam = self.cam
        if cam is None:
            return None
        # Hub-style: explicit per-source getters.
        for getter in (
            "latest_head_jpeg_b64",
            "latest_jpeg_b64_head",
        ):
            fn = getattr(cam, getter, None)
            if callable(fn):
                try:
                    out = fn()
                    if out:
                        return out
                except Exception:  # noqa: BLE001
                    log.debug("camera_hub.%s raised", getter, exc_info=True)
        # Generic: latest_jpeg_b64(source="head")
        generic = getattr(cam, "latest_jpeg_b64", None)
        if callable(generic):
            try:
                try:
                    out = generic(source="head")
                except TypeError:
                    out = generic()
                if out:
                    return out
            except Exception:  # noqa: BLE001
                log.debug("camera_hub.latest_jpeg_b64 raised", exc_info=True)
        # USB fallback (sim with no head camera attached).
        for getter in ("latest_usb_jpeg_b64", "latest_jpeg_b64_usb"):
            fn = getattr(cam, getter, None)
            if callable(fn):
                try:
                    out = fn()
                    if out:
                        return out
                except Exception:  # noqa: BLE001
                    log.debug("camera_hub.%s raised", getter, exc_info=True)
        return None


# Tools that drive motors. Used to gate FSM transitions and to decide
# whether to attach a post-action scene snapshot.
_MOTION_TOOLS: frozenset = frozenset({
    "walk", "turn", "gesture", "static_pose", "stop", "release_arms",
    "look_at", "approach", "mock_imitate",
    "loco_high", "arm_action_high",
})


__all__ = [
    "SkillServer",
    "_load_combo_module",
    "_ensure_g1_sim_demo_on_path",
]
