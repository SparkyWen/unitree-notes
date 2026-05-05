"""Standalone E-stop listener process.

Run as:
    python -m g1_brain.safety.estop_listener [--config configs/g1_brain.yaml]

While running:
  * Listens for ESC on the keyboard (via pynput).
  * On press, touches the shared flag file (so the main process supervisor
    sees the trip on its next ``validate``) and pushes ``N`` zero-torque
    LowCmd messages onto ``rt/lowcmd`` to override anything the main
    process may still be commanding.
  * Status messages go to stderr so the operator can see it's alive.

For ``--release``: just deletes the flag file and exits without engaging
or initialising DDS.

This module intentionally has only soft imports of DDS / pynput so unit
tests can import the file (e.g. for argparse coverage) without those
dependencies installed.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml  # type: ignore[import-untyped]

from .estop_client import EstopClient

log = logging.getLogger("g1_brain.safety.estop_listener")


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "g1_brain.yaml"


# ----------------------------------------------------------------------- utils

def _load_cfg(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _expand(path: str) -> str:
    return os.path.expanduser(os.path.expandvars(path))


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ------------------------------------------------------------------- main flow

class EstopListener:
    """Encapsulates DDS init, key listener, and zero-torque publishing."""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg
        safety_cfg = (cfg.get("safety") or {}).get("estop") or {}
        flag_path = _expand(str(safety_cfg.get("flag_path", "/tmp/g1_brain_estop")))
        self.client = EstopClient(flag_path)
        self.zero_torque_count = int(safety_cfg.get("publish_zero_torque_count", 30))

        robot_cfg = cfg.get("robot") or {}
        self.domain_id = int(robot_cfg.get("domain_id", 1))
        self.interface = str(robot_cfg.get("interface", "lo"))

        self._engaged = threading.Event()
        self._dds_ready = threading.Event()
        self._latest_q: Optional[List[float]] = None
        self._publisher = None
        self._cmd_msg = None
        self._crc = None

    # ----- DDS init ---------------------------------------------------------

    def init_dds(self) -> None:
        from unitree_sdk2py.core.channel import (  # type: ignore[import-not-found]
            ChannelFactoryInitialize,
            ChannelPublisher,
            ChannelSubscriber,
        )
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import (  # type: ignore[import-not-found]
            LowCmd_,
            LowState_,
        )
        from unitree_sdk2py.idl.default import (  # type: ignore[import-not-found]
            unitree_hg_msg_dds__LowCmd_,
        )
        from unitree_sdk2py.utils.crc import CRC  # type: ignore[import-not-found]

        ChannelFactoryInitialize(self.domain_id, self.interface)
        self._publisher = ChannelPublisher("rt/lowcmd", LowCmd_)
        self._publisher.Init()
        self._cmd_msg = unitree_hg_msg_dds__LowCmd_()
        self._crc = CRC()

        sub = ChannelSubscriber("rt/lowstate", LowState_)
        sub.Init(self._on_state, 10)
        self._sub = sub
        _stderr(f"[estop] DDS up on domain={self.domain_id} iface={self.interface}")

    def _on_state(self, msg) -> None:
        try:
            self._latest_q = [m.q for m in msg.motor_state]
            self._dds_ready.set()
        except Exception:  # noqa: BLE001
            log.exception("estop: lowstate parse failed")

    # ----- E-stop action ----------------------------------------------------

    def engage(self, reason: str) -> None:
        if self._engaged.is_set():
            return
        self._engaged.set()
        _stderr(f"[estop] *** ENGAGING: {reason} ***")
        try:
            self.client.engage(reason)
        except Exception:  # noqa: BLE001
            log.exception("estop: failed to write flag file")

        # Wait briefly for at least one lowstate so we can mirror q.
        if not self._dds_ready.wait(timeout=0.5):
            _stderr("[estop] WARN: no lowstate yet; publishing zero q instead")

        n_motors = len(self._latest_q) if self._latest_q else 29
        for i in range(self.zero_torque_count):
            self._publish_zero_torque(n_motors)
            time.sleep(0.005)
        _stderr(
            f"[estop] sent {self.zero_torque_count} zero-torque frames "
            f"({n_motors} motors)"
        )

    def _publish_zero_torque(self, n_motors: int) -> None:
        if self._publisher is None or self._cmd_msg is None:
            return
        try:
            self._cmd_msg.mode_pr = 0
            for i in range(n_motors):
                m = self._cmd_msg.motor_cmd[i]
                m.mode = 1
                m.q = float(self._latest_q[i]) if self._latest_q else 0.0
                m.dq = 0.0
                m.tau = 0.0
                m.kp = 0.0
                m.kd = 0.0
            if self._crc is not None:
                self._cmd_msg.crc = self._crc.Crc(self._cmd_msg)
            self._publisher.Write(self._cmd_msg)
        except Exception:  # noqa: BLE001
            log.exception("estop: publish failed")

    # ----- key listener -----------------------------------------------------

    def run_key_loop(self) -> None:
        try:
            from pynput import keyboard  # type: ignore[import-not-found]
        except ImportError:
            _stderr("[estop] FATAL: pynput not installed — `pip install pynput`")
            sys.exit(2)

        _stderr("[estop] press ESC to engage; Ctrl-C to exit listener")

        def _on_press(key) -> Optional[bool]:
            try:
                if key == keyboard.Key.esc:
                    self.engage("keyboard:ESC")
                    return False  # stop listener
            except Exception:  # noqa: BLE001
                log.exception("estop: key handler raised")
            return None

        with keyboard.Listener(on_press=_on_press) as ll:
            ll.join()


# ---------------------------------------------------------------- entry point

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="g1_brain.safety.estop_listener")
    p.add_argument(
        "--config",
        type=str,
        default=str(DEFAULT_CONFIG),
        help=f"Path to g1_brain.yaml (default: {DEFAULT_CONFIG})",
    )
    p.add_argument(
        "--release",
        action="store_true",
        help="Delete the e-stop flag file and exit (do not engage / connect DDS).",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _build_arg_parser().parse_args(argv)

    cfg_path = Path(_expand(args.config))
    cfg = _load_cfg(cfg_path)

    flag_path = _expand(
        str(((cfg.get("safety") or {}).get("estop") or {}).get(
            "flag_path", "/tmp/g1_brain_estop"
        ))
    )
    client = EstopClient(flag_path)

    if args.release:
        client.release()
        _stderr(f"[estop] released flag at {flag_path}")
        return 0

    listener = EstopListener(cfg)
    try:
        listener.init_dds()
    except Exception:  # noqa: BLE001
        _stderr(
            "[estop] WARN: DDS init failed; key listener will still touch the "
            "flag file but cannot publish zero-torque LowCmd."
        )
        log.exception("estop: init_dds failed")

    try:
        listener.run_key_loop()
    except KeyboardInterrupt:
        _stderr("[estop] interrupted; exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
