"""Cross-process proxy for ComboController.

Runs ``g1_sim_rl_combo.ComboController`` in a dedicated subprocess so its
50 Hz control loop has its own Python GIL, isolated from agent_main's
perception (YOLO + MediaPipe + MuJoCo head render), AI (OpenAI realtime
websocket + TTS), and audio (sounddevice capture + playback) threads.

Why this matters
----------------
The trained velocity policy is rock-solid in isolation: headless verify
(`docs/verify/g1_stand_policy.py`, `g1_combo_integration.py`) holds
``gravity_z = -1.000`` for 60 s of idle and through walk-then-stop. But in
production with the full agent stack the policy visibly destabilizes:

  - idle arm flailing (the policy emits ±0.3 raw_action on arms; under
    timing jitter those amplitudes become time-varying instead of
    static-offset);
  - falls 12 s after a single ``walk(vx=0.2, dur=1.0)``;
  - many ``ALSA underrun`` lines in the log (audio's 50 ms buffer can't
    be kept full).

When the operator launches with ``--no-perception``, all three symptoms
vanish: the robot is "完全不乱晃, 非常稳定" (rock-solid, doesn't shake
at all). That is the proof that perception's GIL pressure on the 50 Hz
control thread is the root cause — disable perception, contention
disappears, controller hits its deadlines, policy stays in distribution.

This module re-creates the ``--no-perception`` isolation while keeping
perception running: combo lives in its own process, perception lives in
agent_main, and neither touches the other's GIL.

API surface
-----------
``ComboProxy`` exposes the same methods + attributes ``skill_server`` and
``watchdogs`` rely on, dispatched across the process boundary:

  - constants (read-once at startup): ``arm_rest``, ``arm_scale``,
    ``arm_offset``, ``mode_machine``;
  - liveness flags (shared memory, atomic): ``policy_active``,
    ``first_state_received``, ``last_state_time``;
  - commands (Pipe, fire-and-forget): ``set_command(vx, vy, wz)``,
    ``push_arm_action(keyframes)``, ``release_arms()``,
    ``set_safe_hold(active)``;
  - lifecycle: ``start()``, ``stop_and_settle()``.

Things deliberately NOT proxied:
  - ``low_state`` always returns ``None``. Anything that needed the live
    LowState message must subscribe to ``rt/lowstate`` directly; see
    ``_LowStateMirror`` in ``apps/agent_main.py`` for the brain-side
    subscriber that replaces ``combo.low_state`` reads.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import time
from typing import Any, List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subprocess entry. Re-imports combo, runs the controller, services the
# command pipe. Keep the body tight — every import here happens *after*
# fork/spawn, so it must not assume parent-side state.
# ---------------------------------------------------------------------------
def _combo_main(
    cmd_pipe,
    policy_active_v,        # mp.Value('b')
    mode_machine_v,         # mp.Value('i')
    last_state_time_v,      # mp.Value('d')
    first_state_v,          # mp.Value('b')
    constants_pipe,         # one-shot send of arm_rest/arm_scale/arm_offset
    domain_id: int,
    interface: str,
) -> None:
    # Reduce log spam from re-imported modules.
    logging.basicConfig(level=logging.INFO)
    sub_log = logging.getLogger("combo_subproc")
    sub_log.info("combo subprocess starting (domain=%s iface=%s)", domain_id, interface)

    # DDS must be (re-)initialized in this process.
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    ChannelFactoryInitialize(int(domain_id), str(interface))

    # Late import: g1_sim_rl_combo pulls in onnxruntime + DDS bindings; we
    # don't want any of that loaded in the parent process.
    import g1_sim_rl_combo as combo_mod  # noqa: WPS433

    cfg = combo_mod.DeployCfg(combo_mod.POLICY_YAML)
    policy = combo_mod.Policy(combo_mod.POLICY_ONNX)
    ctl = combo_mod.ComboController(cfg, policy)
    ctl.init_dds()

    # Block until the simulator is publishing rt/lowstate, exactly like the
    # in-process version did. This keeps the parent's "waiting for
    # /rt/lowstate" UX intact.
    sub_log.info("waiting for first rt/lowstate ...")
    while not ctl.first_state_received:
        time.sleep(0.05)
    sub_log.info("rt/lowstate received; starting control thread")

    # Publish constants exactly once. We use a Pipe for this rather than a
    # Manager dict because Manager.dict requires a manager proxy server
    # (slow + extra subprocess), and the constants are 14-D arrays we only
    # need to deliver once.
    constants_pipe.send({
        "arm_rest": np.asarray(ctl.arm_rest, dtype=np.float64),
        "arm_scale": np.asarray(ctl.arm_scale, dtype=np.float64),
        "arm_offset": np.asarray(ctl.arm_offset, dtype=np.float64),
        "mode_machine": int(ctl.mode_machine),
    })
    constants_pipe.close()

    ctl.start()

    # Status updater: one cheap thread inside the combo process that pushes
    # liveness flags into shared memory the parent can read at native speed
    # (no IPC per read, no GIL crossing).
    import threading
    stop_status = threading.Event()

    def _status_loop():
        while not stop_status.is_set():
            with policy_active_v.get_lock():
                policy_active_v.value = bool(ctl.policy_active)
            with mode_machine_v.get_lock():
                mode_machine_v.value = int(ctl.mode_machine)
            with last_state_time_v.get_lock():
                last_state_time_v.value = float(ctl.last_state_time)
            with first_state_v.get_lock():
                first_state_v.value = bool(ctl.first_state_received)
            time.sleep(0.05)

    status_thread = threading.Thread(
        target=_status_loop, name="combo-status", daemon=True
    )
    status_thread.start()

    # Command listener: blocks on the parent's Pipe and dispatches to the
    # in-process combo. Critically, this thread holds the GIL only for the
    # short time it takes to dispatch — combo's 50 Hz control thread runs
    # uninterrupted because it is in the same process and there are no
    # heavy CPU consumers here (perception lives in the parent).
    try:
        while True:
            try:
                msg = cmd_pipe.recv()
            except EOFError:
                break
            if msg is None:
                break
            op = msg[0]
            try:
                if op == "set_command":
                    ctl.set_command(*msg[1:])
                elif op == "push_arm_action":
                    # msg[1] is List[Tuple[float, np.ndarray]] — pickle handles ndarrays
                    ctl.push_arm_action(msg[1])
                elif op == "release_arms":
                    ctl.release_arms()
                elif op == "set_safe_hold":
                    ctl.set_safe_hold(bool(msg[1]))
                elif op == "soften":
                    ctl.soften(*msg[1:])
                elif op == "stop":
                    ctl.stop_and_settle()
                    break
                else:
                    sub_log.warning("unknown combo op: %s", op)
            except Exception:  # noqa: BLE001 — never crash the worker on a single bad cmd
                sub_log.exception("combo op %s raised", op)
    finally:
        stop_status.set()
        try:
            ctl.stop_and_settle()
        except Exception:  # noqa: BLE001
            pass
        sub_log.info("combo subprocess exiting")


# ---------------------------------------------------------------------------
# Parent-side proxy. Drop-in replacement for ComboController everywhere
# skill_server / watchdogs / agent_main read its public API.
# ---------------------------------------------------------------------------
class ComboProxy:
    """Cross-process proxy for :class:`g1_sim_rl_combo.ComboController`.

    Lifecycle:
      1. ``__init__`` allocates shared-memory mirrors for liveness flags.
      2. ``start()`` spawns the subprocess, blocks until it has signalled
         constants ready (so ``arm_rest`` / ``arm_scale`` / ``arm_offset`` /
         ``mode_machine`` are populated before any caller reads them).
      3. ``set_command`` / ``push_arm_action`` / ``release_arms`` /
         ``set_safe_hold`` send Pipe messages; combo applies them on its
         own tick.
      4. ``stop_and_settle()`` requests a clean shutdown, joins the
         subprocess with a timeout, and falls back to ``terminate()`` if
         the worker hangs.

    Threading: parent-side methods are safe to call from any thread; mp.Pipe
    sends are atomic per message. Reads of ``policy_active`` etc. are
    lock-protected via ``mp.Value.get_lock``.
    """

    # Spawn vs fork: fork is fastest on Linux but inherits the parent's
    # imported state (DDS, onnxruntime, audio threads — all bad). We force
    # ``spawn`` so the child starts from a clean Python interpreter and
    # only loads what _combo_main imports. Slightly slower startup
    # (~2 s extra) for full process isolation.
    _CTX = mp.get_context("spawn")

    def __init__(self, *, domain_id: int, interface: str) -> None:
        self._domain_id = int(domain_id)
        self._interface = str(interface)

        # Shared-memory liveness mirrors. ctype 'b' = signed char (acts as
        # bool); 'i' = int; 'd' = double.
        self._policy_active_v = self._CTX.Value("b", False, lock=True)
        self._mode_machine_v = self._CTX.Value("i", 0, lock=True)
        self._last_state_time_v = self._CTX.Value("d", 0.0, lock=True)
        self._first_state_v = self._CTX.Value("b", False, lock=True)

        # Command pipe (parent -> child). Pickled tuples.
        self._cmd_parent, self._cmd_child = self._CTX.Pipe(duplex=False)
        # Constants pipe (child -> parent). One-shot.
        self._const_parent, self._const_child = self._CTX.Pipe(duplex=False)

        self._proc: Optional[mp.process.BaseProcess] = None

        # Filled by start() once the child publishes constants.
        self.arm_rest: np.ndarray = np.zeros(14, dtype=np.float64)
        self.arm_scale: np.ndarray = np.zeros(14, dtype=np.float64)
        self.arm_offset: np.ndarray = np.zeros(14, dtype=np.float64)
        self.mode_machine: int = 0

    # ----- lifecycle --------------------------------------------------------

    def start(self, *, ready_timeout_s: float = 30.0) -> None:
        if self._proc is not None and self._proc.is_alive():
            return
        self._proc = self._CTX.Process(
            target=_combo_main,
            name="g1-combo-proc",
            args=(
                self._cmd_child,
                self._policy_active_v,
                self._mode_machine_v,
                self._last_state_time_v,
                self._first_state_v,
                self._const_child,
                self._domain_id,
                self._interface,
            ),
            daemon=False,
        )
        self._proc.start()
        # Close our copies of the child-side pipe ends so EOF propagates
        # cleanly when the subprocess exits.
        self._cmd_child.close()
        self._const_child.close()

        # Block until constants arrive. The subprocess only sends after
        # it has received its first rt/lowstate, which means by the time
        # this returns the controller is publishing lowcmd.
        if not self._const_parent.poll(ready_timeout_s):
            self.stop_and_settle()
            raise TimeoutError(
                f"combo subprocess did not signal ready within "
                f"{ready_timeout_s:.1f}s (no rt/lowstate?)"
            )
        const = self._const_parent.recv()
        self._const_parent.close()

        self.arm_rest = np.asarray(const["arm_rest"], dtype=np.float64)
        self.arm_scale = np.asarray(const["arm_scale"], dtype=np.float64)
        self.arm_offset = np.asarray(const["arm_offset"], dtype=np.float64)
        self.mode_machine = int(const["mode_machine"])

    def stop_and_settle(self) -> None:
        if self._proc is None:
            return
        try:
            self._cmd_parent.send(("stop",))
        except (BrokenPipeError, EOFError, OSError):
            pass
        try:
            self._cmd_parent.close()
        except Exception:  # noqa: BLE001
            pass
        if self._proc.is_alive():
            self._proc.join(timeout=5.0)
        if self._proc.is_alive():
            log.warning("combo subprocess did not stop in 5s; terminating")
            try:
                self._proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            self._proc.join(timeout=2.0)

    # ----- liveness flags (shared memory) ----------------------------------

    @property
    def policy_active(self) -> bool:
        with self._policy_active_v.get_lock():
            return bool(self._policy_active_v.value)

    @property
    def first_state_received(self) -> bool:
        with self._first_state_v.get_lock():
            return bool(self._first_state_v.value)

    @property
    def last_state_time(self) -> float:
        with self._last_state_time_v.get_lock():
            return float(self._last_state_time_v.value)

    @property
    def low_state(self) -> Any:
        # Cross-process LowState_ would mean either pickling a 100+-field
        # ROS message at 500 Hz (untenable) or maintaining a synchronized
        # copy through shared memory. Neither is justified: the only
        # in-tree consumer (`_RobotStateProducer`) can subscribe to
        # rt/lowstate directly. Returning None forces that path.
        return None

    # ----- commands (Pipe) -------------------------------------------------

    def set_command(self, vx: float, vy: float, wz: float) -> None:
        self._send(("set_command", float(vx), float(vy), float(wz)))

    def push_arm_action(
        self,
        keyframes: List[Tuple[float, np.ndarray]],
    ) -> None:
        self._send(("push_arm_action", list(keyframes)))

    def release_arms(self) -> None:
        self._send(("release_arms",))

    def set_safe_hold(self, active: bool) -> None:
        self._send(("set_safe_hold", bool(active)))

    def soften(self, target_scale: float = 0.0, duration: float = 1.0) -> None:
        self._send(("soften", float(target_scale), float(duration)))

    def _send(self, msg: tuple) -> None:
        if self._proc is None or not self._proc.is_alive():
            log.warning("combo subprocess not running; dropping %s", msg[0])
            return
        try:
            self._cmd_parent.send(msg)
        except (BrokenPipeError, EOFError, OSError) as e:
            log.warning("combo cmd pipe error on %s: %s", msg[0], e)


__all__ = ["ComboProxy"]
