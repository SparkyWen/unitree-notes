"""Standalone perception debug entry point.

Starts only the CameraHub + PerceptionRunner (no DDS, no Realtime). Loops
at 2 Hz printing ``SceneStateBus.snapshot().summary_for_llm()``. With
``--show`` you also get cv2 windows for the USB and head streams with
detection / pose overlays.

This is the fastest way to verify perception works without booting the
whole agent (no MuJoCo, no DDS, no OpenAI key needed if you only want
USB+pose; head cam still requires MuJoCo running for live qpos).
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import yaml


log = logging.getLogger("g1_brain.perception_debug")


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_CONFIG = REPO_ROOT / "g1_brain" / "configs" / "g1_brain.yaml"


def _ensure_sibling_repos_on_path() -> None:
    home = Path.home()
    for p in (
        home / "unitree" / "unitree-notes" / "va-demo",
        home / "unitree" / "unitree-notes" / "g1_sim_demo",
    ):
        sp = str(p)
        if p.exists() and sp not in sys.path:
            sys.path.insert(0, sp)


def _load_config(path: Path) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    # Lightweight ${HOME} expansion (mirrors agent_main, but local to keep
    # this file standalone-runnable).
    def _expand(o):
        if isinstance(o, str):
            return os.path.expandvars(o)
        if isinstance(o, list):
            return [_expand(v) for v in o]
        if isinstance(o, dict):
            return {k: _expand(v) for k, v in o.items()}
        return o
    return _expand(cfg)


def _draw_overlays(bgr, dets, pose=None):
    import cv2
    out = bgr.copy()
    for d in dets or ():
        x1, y1, x2, y2 = (int(v) for v in d.bbox_xyxy)
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{d.class_name} {d.score:.2f}"
        if d.distance_m is not None:
            label += f" {d.distance_m:.2f}m"
        cv2.putText(out, label, (x1, max(15, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    if pose is not None:
        h, w = out.shape[:2]
        for (x, y), v in zip(pose.landmarks_xy, pose.visibility):
            if float(v) < 0.3:
                continue
            cv2.circle(out, (int(x * w), int(y * h)), 3, (0, 200, 255), -1)
        if pose.gesture:
            cv2.putText(
                out, f"{pose.gesture} {pose.gesture_confidence:.2f}",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2,
            )
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="g1_brain perception debug")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--show", action="store_true",
                   help="open cv2 windows showing USB + head frames with overlays")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _ensure_sibling_repos_on_path()

    cfg = _load_config(args.config)

    from ..scene_state.fusion import RobotStateBus, SceneStateBus

    scene_bus = SceneStateBus()
    robot_bus = RobotStateBus()

    try:
        from ..perception.cameras import CameraHub
    except Exception as e:  # noqa: BLE001
        log.error("could not import CameraHub: %s", e)
        return 2
    try:
        from ..perception.runner import PerceptionRunner
    except Exception as e:  # noqa: BLE001
        log.error("could not import PerceptionRunner: %s", e)
        return 2

    camera_hub: Optional[CameraHub] = None
    runner: Optional[PerceptionRunner] = None
    try:
        camera_hub = CameraHub(cfg)
    except Exception as e:  # noqa: BLE001
        log.warning("CameraHub init failed: %s", e)

    try:
        runner = PerceptionRunner(cfg, scene_bus, robot_bus)
        runner.start()
    except Exception as e:  # noqa: BLE001
        log.error("PerceptionRunner failed: %s", e)
        if camera_hub is not None:
            camera_hub.close()
        return 3

    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    log.info("perception running; Ctrl-C to exit")
    try:
        if args.show:
            import cv2
            cv2.namedWindow("usb", cv2.WINDOW_NORMAL)
            cv2.namedWindow("head", cv2.WINDOW_NORMAL)
        while not stop:
            snap = scene_bus.snapshot()
            print(snap.summary_for_llm(), flush=True)
            if args.show and camera_hub is not None:
                import cv2
                usb = getattr(camera_hub, "latest_usb_bgr", lambda: None)()
                if usb is not None:
                    cv2.imshow("usb",
                               _draw_overlays(usb, snap.user_detections,
                                              pose=snap.user_pose))
                head = getattr(camera_hub, "latest_head_bgr", lambda: None)()
                if head is not None:
                    cv2.imshow("head",
                               _draw_overlays(head, snap.head_detections))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            time.sleep(0.5)
    finally:
        log.info("stopping perception ...")
        try:
            runner.stop()
        except Exception:  # noqa: BLE001
            log.exception("runner.stop failed")
        if camera_hub is not None:
            try:
                camera_hub.close()
            except Exception:  # noqa: BLE001
                log.exception("camera_hub.close failed")
        if args.show:
            try:
                import cv2
                cv2.destroyAllWindows()
            except Exception:  # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
