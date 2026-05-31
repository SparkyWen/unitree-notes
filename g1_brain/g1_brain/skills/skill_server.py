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
import json
import logging
import math
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
    """Make `import g1_sim_rl_combo` resolve. Mirrors va_demo.skills.

    Anchored on ``__file__`` so it works whether the workspace is at
    ``~/unitree-notes`` or nested under ``~/unitree/unitree-notes``.
    """
    p = Path(__file__).resolve().parents[3] / "g1_sim_demo"
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
#
# Pre-fix had ``_TURN_DURATION_PER_DEG = 1/25`` paired with wz=0.25 rad/s
# (≈ 14.32 °/s). At that math, asking for ``turn(yaw_deg=25)`` ran wz=0.25
# rad/s for 1.0 s and rotated only ≈ 14° — i.e. the robot turned ~57 % of
# the requested angle. Combined with ``_TURN_MAX_DURATION_S = 1.5`` it
# meant a 'turn 180°' request became 7+ chained tool calls, *each* costing
# the operator a y/N in confirm-mode. The geometry is now correct: degrees
# requested == degrees actually turned (modulo policy tracking error and
# any reactive abort). 180° at 0.25 rad/s = π/0.25 ≈ 12.57 s; we cap at
# 14 s to leave a small margin and bound any single confirm.
_TURN_YAW_RATE_RAD_S = 0.25
_TURN_DURATION_PER_DEG = math.pi / (180.0 * _TURN_YAW_RATE_RAD_S)  # ≈ 0.0698 s/deg
_TURN_MAX_DURATION_S = 14.0


def _normalize_e164(number: str) -> str:
    """Best-effort canonicalise a phone number to bare E.164 (``+`` + digits).

    The Realtime model often passes a spoken number with separators it heard
    ("+61 411 706 848", "+61-411-706-848") or with the international call
    prefix instead of ``+`` ("0061411706848"). All of those denote the SAME
    destination as the whitelisted "+61411706848", so we strip separators and
    fold a leading "00" to "+" before comparing against the allowlist. We do
    NOT invent a missing country code or a missing "+": a genuinely different
    digit must still fail the whitelist check (the misheard-digit safety gate).
    """
    if not number:
        return ""
    s = "".join(ch for ch in number if ch.isdigit() or ch == "+")
    if s.startswith("00"):
        s = "+" + s[2:]
    return s


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
        conversation_logger=None,
        memory=None,
        dialer=None,
        default_phone_to: Optional[str] = None,
    ) -> None:
        self.combo = combo_ctl
        self.safety = safety
        self.tts = tts
        self.vision = vision
        self.cam = camera_hub
        self.scene = scene_bus
        self.fsm = fsm
        self.sim = sim
        # Optional persistent conversation log; recall_history reads it so
        # past tool calls / user turns can be retrieved verbatim instead of
        # relying on the Realtime model's lossy in-context memory. None when
        # the operator launched with audio_control.transcript.enabled: false.
        self.conv_logger = conversation_logger
        # Optional memory subsystem (Codex-style long-term recall + ask_slow_brain).
        # None when memory.enabled is false in config or the subsystem failed
        # to start. Every new tool checks for None and returns memory_disabled.
        self.memory = memory
        # Tracks in-flight ask_slow_brain calls keyed by tool call_id, so
        # on_response_canceled (fired on barge-in) can set the cancel events.
        self._ask_cancel_events: Dict[str, Any] = {}
        # Optional Twilio dialer. None = phone bridge not enabled.
        self._dialer = dialer
        self._default_phone_to = default_phone_to
        # Whitelist of E.164 numbers the LLM may dial via start_phone_call.
        # Defends against wake-word ASR misheard digits (a real-world incident
        # 2026-05-24: model heard +6848 as +6888 and rang a stranger for 3min).
        # Empty list => only the default operator number is allowed.
        self._allowed_phone_callers: List[str] = []

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

    async def execute(
        self,
        tool: str,
        args: Optional[Dict[str, Any]] = None,
        *,
        call_id: str = "",
    ) -> Dict[str, Any]:
        """Validate `tool(args)` via safety then dispatch.

        Always returns a dict; never raises. ``ok=True`` results from
        motion skills get a ``scene_after`` field with a fresh snapshot
        summary so the brain has post-action context.

        When the memory subsystem is wired, also emits scene_snapshot
        (pre/post motion) and action_result meta events for every call.
        """
        args = dict(args or {})
        try:
            ok, reason, sanitized = await self.safety.validate(tool, args)
        except Exception as e:  # noqa: BLE001
            log.exception("safety.validate raised; rejecting %s", tool)
            return {"ok": False, "skill": tool, "reason": f"safety exception: {e!s}"}

        if not ok:
            log.warning("safety rejected %s(%s): %s", tool, args, reason)
            # Memory: log action_result + safety_event for rejection
            self._log_action_result_safe(
                call_id=call_id, tool_name=tool, args=args,
                status="blocked_by_safety", blocked_reason=str(reason),
                outcome_metrics=None, result_payload_brief="",
            )
            self._log_safety_event_safe(
                kind="tool_rejected",
                rule=(reason.split(":")[0] if isinstance(reason, str) and ":" in reason else None),
                details=str(reason),
                associated_tool_use_id=call_id,
            )
            return {"ok": False, "skill": tool, "reason": reason}

        sanitized = dict(sanitized or {})
        method = getattr(self, f"_skill_{tool}", None)
        if method is None:
            self._log_action_result_safe(
                call_id=call_id, tool_name=tool, args=args,
                status="exec_error",
                blocked_reason=None,
                outcome_metrics=None,
                result_payload_brief=f"unknown tool: {tool!r}",
            )
            return {"ok": False, "skill": tool, "reason": f"unknown tool: {tool!r}"}

        is_motion = tool in _MOTION_TOOLS
        if is_motion:
            # Pre-motion scene snapshot (memory pipeline keyframe)
            self._log_scene_snapshot_safe(trigger="pre_motion")
            self._fsm_safe_transition_to_acting(tool)

        exec_status = "ok"
        # Expose call_id to _skill_ask_slow_brain for cancel-token registration
        self._current_call_id_value = call_id
        try:
            result = await method(**sanitized)
        except Exception as e:  # noqa: BLE001
            log.exception("skill %s raised; running defensive stop", tool)
            try:
                await self._skill_stop()
            except Exception:  # noqa: BLE001
                log.exception("defensive stop also failed")
            result = {"ok": False, "skill": tool, "reason": f"exception: {e!s}"}
            exec_status = "exec_error"
        finally:
            if is_motion:
                self._fsm_safe_transition_to_engaged(tool)
                # Post-motion scene snapshot
                self._log_scene_snapshot_safe(trigger="post_motion")

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

        # Action_result: physical-world view of the outcome
        if exec_status == "ok" and not result.get("ok", True):
            exec_status = "exec_error"
        outcome_metrics = self._extract_outcome_metrics(tool, result) if is_motion else None
        try:
            brief = json.dumps(result, ensure_ascii=False)[:256]
        except (TypeError, ValueError):
            brief = repr(result)[:256]
        self._log_action_result_safe(
            call_id=call_id, tool_name=tool, args=args,
            status=exec_status,
            blocked_reason=None,
            outcome_metrics=outcome_metrics,
            result_payload_brief=brief,
        )
        return result

    # ----- conv_logger helpers (best-effort, never raise) -----------------

    def _log_action_result_safe(
        self, *, call_id: str, tool_name: str, args: Dict[str, Any],
        status: str, blocked_reason: Optional[str],
        outcome_metrics: Optional[Dict[str, Any]],
        result_payload_brief: str,
    ) -> None:
        if self.conv_logger is None:
            return
        try:
            self.conv_logger.log_action_result(
                tool_use_id=call_id or "",
                tool_name=tool_name,
                args=args,
                status=status,
                blocked_reason=blocked_reason,
                outcome_metrics=outcome_metrics,
                result_payload_brief=result_payload_brief,
            )
        except Exception:  # noqa: BLE001
            log.exception("log_action_result failed; ignoring")

    def _log_safety_event_safe(
        self, *, kind: str, rule: Optional[str] = None,
        from_state: Optional[str] = None, to_state: Optional[str] = None,
        details: str = "", associated_tool_use_id: Optional[str] = None,
    ) -> None:
        if self.conv_logger is None:
            return
        try:
            self.conv_logger.log_safety_event(
                kind=kind, rule=rule, from_state=from_state, to_state=to_state,
                details=details,
                associated_tool_use_id=associated_tool_use_id,
            )
        except Exception:  # noqa: BLE001
            log.exception("log_safety_event failed; ignoring")

    def _log_scene_snapshot_safe(self, *, trigger: str) -> None:
        if self.conv_logger is None or self.scene is None:
            return
        try:
            snap = self.scene.snapshot()
        except Exception:  # noqa: BLE001
            return
        try:
            self.conv_logger.log_scene_snapshot(
                trigger=trigger, scene_state=snap, frame_paths=None,
            )
        except Exception:  # noqa: BLE001
            log.exception("log_scene_snapshot failed; ignoring")

    def _extract_outcome_metrics(self, tool: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """Best-effort outcome metrics for memory's action_result event.

        sim only: combo controller returns displacement / duration; real
        robot returns nothing useful yet. Both cases collapse to a small
        dict; missing fields stay missing.
        """
        out: Dict[str, Any] = {}
        for key in ("displacement_m", "duration_actual_s", "end_pose_z",
                    "end_safety_state"):
            if key in result:
                out[key] = result[key]
        # Sometimes result has nested 'metrics' dict
        m = result.get("metrics")
        if isinstance(m, dict):
            for key in ("displacement_m", "duration_actual_s"):
                if key in m and key not in out:
                    out[key] = m[key]
        return out or None

    # ----- barge-in cancellation propagation ------------------------------

    def on_response_canceled(self, response_id: Optional[str] = None) -> None:
        """Called when BrainRealtimeAgent fires on_response_canceled.

        Sets every pending ask_slow_brain cancel_event so daemon can send
        MCP notifications/cancelled and return partial text fast.
        """
        if self.memory is not None:
            try:
                n = self.memory.cancel_all_in_flight()
                if n:
                    log.info("on_response_canceled: cancelled %d in-flight ask(s)", n)
            except Exception:  # noqa: BLE001
                log.exception("memory.cancel_all_in_flight failed")

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
        self, question: str = "", detail: str = "auto",
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

    async def _skill_recall_history(
        self,
        kind: str = "actions",
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Query the persistent conversation jsonl for past events.

        ``kind`` controls what is returned:

          - ``"actions"`` — every motion/skill the robot executed (tool_use of
            walk/turn/gesture/static_pose/look_at/approach/mock_imitate/stop).
            This is the canonical answer to "what did I do" / "what was my
            first motion" — Realtime context truncation can lose old turns,
            but the jsonl always has every call.
          - ``"user_turns"`` — every user utterance.
          - ``"all"`` — interleaved user + assistant + tool_use entries.

        Returns the OLDEST-first slice (so the first entry is the actual
        first action), capped at ``limit``. The list is empty when there is
        no transcript logger or the file has no matching events yet.
        """
        if self.conv_logger is None or self.conv_logger.path is None:
            return {
                "ok": False,
                "skill": "recall_history",
                "reason": "conversation transcript disabled",
            }
        path = self.conv_logger.path
        kinds = {"actions", "user_turns", "all"}
        if kind not in kinds:
            return {
                "ok": False, "skill": "recall_history",
                "reason": f"kind must be one of {sorted(kinds)}; got {kind!r}",
            }
        try:
            limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            limit = 20

        action_tools = {
            "walk", "turn", "gesture", "static_pose", "look_at",
            "approach", "mock_imitate", "stop", "release_arms",
        }

        items: List[Dict[str, Any]] = []
        try:
            import json as _json
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = _json.loads(raw)
                    except ValueError:
                        continue
                    rec_type = rec.get("type")
                    msg = rec.get("message") or {}
                    blocks = msg.get("content") or []
                    first = blocks[0] if blocks else {}

                    if kind == "user_turns":
                        if rec_type != "user":
                            continue
                        items.append({
                            "turn_id": rec.get("turn_id"),
                            "timestamp": rec.get("timestamp"),
                            "text": first.get("text", ""),
                        })
                    elif kind == "actions":
                        if rec_type != "tool_use":
                            continue
                        if first.get("type") != "tool_use":
                            continue
                        if first.get("name") not in action_tools:
                            continue
                        items.append({
                            "turn_id": rec.get("turn_id"),
                            "timestamp": rec.get("timestamp"),
                            "name": first.get("name"),
                            "input": first.get("input"),
                        })
                    else:  # "all"
                        if rec_type == "user":
                            items.append({
                                "turn_id": rec.get("turn_id"),
                                "timestamp": rec.get("timestamp"),
                                "type": "user",
                                "text": first.get("text", ""),
                            })
                        elif rec_type == "assistant":
                            items.append({
                                "turn_id": rec.get("turn_id"),
                                "timestamp": rec.get("timestamp"),
                                "type": "assistant",
                                "text": first.get("text", ""),
                            })
                        elif rec_type == "tool_use" and first.get("type") == "tool_use":
                            items.append({
                                "turn_id": rec.get("turn_id"),
                                "timestamp": rec.get("timestamp"),
                                "type": "tool_use",
                                "name": first.get("name"),
                                "input": first.get("input"),
                            })
        except OSError as e:
            return {
                "ok": False, "skill": "recall_history",
                "reason": f"read failed: {e!s}",
            }

        return {
            "ok": True,
            "skill": "recall_history",
            "kind": kind,
            "session_id": self.conv_logger.session_id,
            "total_matched": len(items),
            "returned": min(len(items), limit),
            # Oldest-first; the model needs the first entry for "first action"
            # questions. Truncate from the tail so we always keep the start.
            "events": items[:limit],
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

    async def _skill_start_phone_call(
        self, *, to: Optional[str] = None, **_: object,
    ) -> Dict[str, Any]:
        if self._dialer is None:
            return {"ok": False, "skill": "start_phone_call",
                    "reason": "phone bridge not enabled"}
        # When the operator just says "call me" / "call my number", the model
        # should omit `to` so we dial the configured operator number — that
        # path can never be derailed by ASR mishearing a digit.
        dest_raw = to or self._default_phone_to
        if not dest_raw:
            return {"ok": False, "skill": "start_phone_call",
                    "reason": "no destination configured"}
        dest = _normalize_e164(dest_raw)
        # Whitelist-enforce dest. Wake-word ASR can mishear a single digit and
        # without this gate the LLM happily dials whoever it heard. We compare
        # on the NORMALIZED form so harmless formatting variance ("+61 411 706
        # 848", "+61-411-706-848", "0061411706848") still matches a whitelisted
        # number, while a genuine wrong digit is still rejected.
        allowed = {_normalize_e164(n) for n in (self._allowed_phone_callers or [])}
        if self._default_phone_to:
            allowed.add(_normalize_e164(self._default_phone_to))
        if allowed and dest not in allowed:
            return {"ok": False, "skill": "start_phone_call",
                    "reason": f"refusing dial: {dest_raw} is not a saved number. "
                              f"To call the operator's own phone, call "
                              f"start_phone_call with no arguments (it dials the "
                              f"configured operator number)."}
        try:
            sid = await self._dialer.dial(dest)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "skill": "start_phone_call",
                    "reason": f"dial failed: {e!s}"}
        return {"ok": True, "skill": "start_phone_call",
                "summary": f"calling {dest}", "call_sid": sid}

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

    # ----- memory skills (recall + ask_slow_brain) -----------------------

    async def _skill_recall_grep(
        self,
        pattern: str,
        scope: str = "registry",
        session_id: Optional[str] = None,
        max_lines: int = 50,
    ) -> Dict[str, Any]:
        if self.memory is None:
            return {"ok": False, "skill": "recall_grep",
                    "status": "memory_disabled"}
        try:
            r = await self.memory.recall.grep(
                pattern=pattern, scope=scope,
                session_id=session_id, max_lines=max_lines,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("recall_grep failed")
            return {"ok": False, "skill": "recall_grep",
                    "status": "tool_unavailable", "reason": str(e)}
        r.setdefault("ok", r.get("status") == "ok")
        r.setdefault("skill", "recall_grep")
        return r

    async def _skill_recall_read(
        self,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> Dict[str, Any]:
        if self.memory is None:
            return {"ok": False, "skill": "recall_read",
                    "status": "memory_disabled"}
        try:
            r = await self.memory.recall.read(
                path=path, start_line=start_line, end_line=end_line,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("recall_read failed")
            return {"ok": False, "skill": "recall_read",
                    "status": "tool_unavailable", "reason": str(e)}
        r.setdefault("ok", r.get("status") == "ok")
        r.setdefault("skill", "recall_read")
        return r

    async def _skill_recall_glob(
        self,
        pattern: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        if self.memory is None:
            return {"ok": False, "skill": "recall_glob",
                    "status": "memory_disabled"}
        try:
            r = await self.memory.recall.glob(pattern=pattern, limit=limit)
        except Exception as e:  # noqa: BLE001
            log.exception("recall_glob failed")
            return {"ok": False, "skill": "recall_glob",
                    "status": "tool_unavailable", "reason": str(e)}
        r.setdefault("ok", r.get("status") == "ok")
        r.setdefault("skill", "recall_glob")
        return r

    async def _skill_ask_slow_brain(
        self,
        query: str,
        timeout_s: float = 90.0,
    ) -> Dict[str, Any]:
        if self.memory is None:
            return {"ok": False, "skill": "ask_slow_brain",
                    "status": "memory_disabled"}
        call_id = self._current_call_id() or ""
        cancel_evt = self.memory.register_cancel_token(call_id)
        try:
            ask = await self.memory.daemon.ask_slow_brain(
                query=query,
                timeout_s=float(timeout_s),
                cancel_event=cancel_evt,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("ask_slow_brain raised")
            return {"ok": False, "skill": "ask_slow_brain",
                    "status": "tool_unavailable", "reason": str(e)}
        finally:
            self.memory.unregister_cancel_token(call_id)
        return {
            "ok": ask.status == "ok",
            "skill": "ask_slow_brain",
            "status": ask.status,
            "text": ask.text,
            "latency_ms": ask.latency_ms,
            "partial": ask.partial,
        }

    def _current_call_id(self) -> Optional[str]:
        # The wrapping execute() sets self._current_tool_call_id_var via
        # a context-local before dispatching skills; if absent, return None.
        return getattr(self, "_current_call_id_value", None)


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
