"""MuJoCo offscreen head-camera renderer.

The unitree_mujoco simulator owns the physics; we are a passive renderer
running our own private MjModel/MjData clone, syncing it to live joint
positions (from `rt/lowstate`) and the floating-base pose (from
`rt/sportmodestate` when available, fallback to identity), then offscreen-
rendering RGB + depth.

We never write motor commands — only the bridge / skill server does.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional, Sequence, Tuple

import numpy as np

# WSLg's GLX bridge crashes (BadAccess on glXMakeCurrent) when MuJoCo's GLFW
# backend juggles two renderer contexts from a worker thread. EGL goes through
# Mesa directly without GLX, which is the WSL-safe choice. User can still
# override by exporting MUJOCO_GL=glfw|osmesa before launch.
os.environ.setdefault("MUJOCO_GL", "egl")

log = logging.getLogger(__name__)

# Default head-camera mount when the MJCF doesn't ship one. G1's "head" is a
# static mesh hanging off torso_link at offset (0.004, 0, -0.054); the eyes sit
# roughly at +X 0.08, +Z 0.45 in torso_link's frame. xyaxes rotates the camera's
# default -Z look direction onto the robot's +X (forward) axis: cam-X = world-Y
# (left), cam-Y = world-Z (up), so cam-Z = -X (looking backwards along -X means
# the camera looks forward along +X).
DEFAULT_ATTACH_BODY = "torso_link"
DEFAULT_ATTACH_POS: Tuple[float, float, float] = (0.08, 0.0, 0.45)
DEFAULT_ATTACH_XYAXES: Tuple[float, float, float, float, float, float] = (
    0.0, -1.0, 0.0, 0.0, 0.0, 1.0,
)
DEFAULT_ATTACH_FOVY = 60.0

# G1 has 29 actuated joints in g1_29dof.xml; the floating base adds 7 qpos
# (xyz + quat). We don't hardcode this — we read mj_model.nu / nq instead.


class MuJoCoHeadCamera:
    """Background-rendered RGB + depth from a head-mounted MJCF camera."""

    def __init__(
        self,
        mjcf_path: str,
        camera_name: str = "head_camera",
        width: int = 640,
        height: int = 480,
        poll_hz: float = 20.0,
        jpeg_quality: int = 85,
        subscribe_dds: bool = True,
        attach_body: str = DEFAULT_ATTACH_BODY,
        attach_pos: Sequence[float] = DEFAULT_ATTACH_POS,
        attach_xyaxes: Sequence[float] = DEFAULT_ATTACH_XYAXES,
        attach_fovy: float = DEFAULT_ATTACH_FOVY,
    ):
        # Heavy import is intentionally inside __init__ so derivation tests
        # never need MuJoCo on the path.
        import mujoco

        self._mujoco = mujoco

        self._model = self._load_or_synthesize_model(
            mjcf_path,
            camera_name=camera_name,
            attach_body=attach_body,
            attach_pos=attach_pos,
            attach_xyaxes=attach_xyaxes,
            attach_fovy=attach_fovy,
        )
        self._data = mujoco.MjData(self._model)
        # Renderers are NOT built here. EGL/GLFW GL contexts are owned by the
        # thread that creates them — making them current from another thread
        # errors with EGL_BAD_ACCESS / GLX BadAccess. We lazy-build inside the
        # render thread instead.
        self._renderer: Optional["mujoco.Renderer"] = None
        self._depth_renderer: Optional["mujoco.Renderer"] = None
        self._width = width
        self._height = height
        self._jpeg_quality = jpeg_quality

        self._cam_id = self._resolve_camera(camera_name)
        self._hfov_deg, self._vfov_deg = self._compute_fov()

        self._lock = threading.Lock()
        self._last_bgr: Optional[np.ndarray] = None
        self._last_depth_m: Optional[np.ndarray] = None
        self._last_t: float = 0.0

        self._stop = threading.Event()
        self._poll_interval_s = 1.0 / poll_hz if poll_hz > 0 else 0.05

        # Live state from DDS
        self._state_lock = threading.Lock()
        self._latest_motor_q: Optional[np.ndarray] = None
        self._latest_base_quat: Optional[np.ndarray] = None  # (w, x, y, z)
        self._latest_base_pos: Optional[np.ndarray] = None   # (x, y, z)

        self._subs = []
        if subscribe_dds:
            self._init_dds_subscribers()

        self._render_thread = threading.Thread(
            target=self._render_loop, name="g1-brain-head-render", daemon=True
        )
        self._render_thread.start()

    # ---------------- model loading ----------------

    def _load_or_synthesize_model(
        self,
        mjcf_path: str,
        *,
        camera_name: str,
        attach_body: str,
        attach_pos: Sequence[float],
        attach_xyaxes: Sequence[float],
        attach_fovy: float,
    ):
        """Compile the MJCF; if no usable camera exists, splice one onto
        ``attach_body`` via MjSpec so we don't render from world origin."""
        mujoco = self._mujoco
        spec = mujoco.MjSpec.from_file(mjcf_path)

        # Walk the spec to see if the requested camera is already defined.
        # MjSpec.cameras returns every <camera> in the model.
        existing = {c.name for c in spec.cameras}
        if camera_name in existing:
            return spec.compile()

        body = spec.body(attach_body)
        if body is None:
            log.warning(
                "attach_body %r not found in MJCF; falling back to free "
                "camera at origin (renders will be useless until you set "
                "cameras.head.attach_body to a real body name)",
                attach_body,
            )
            return spec.compile()

        body.add_camera(
            name=camera_name,
            pos=list(attach_pos),
            xyaxes=list(attach_xyaxes),
            fovy=float(attach_fovy),
        )
        log.info(
            "synthesized head camera %r on body %r at pos=%s fovy=%.1f°",
            camera_name, attach_body, tuple(attach_pos), float(attach_fovy),
        )
        return spec.compile()

    # ---------------- camera resolution ----------------

    def _resolve_camera(self, name: str) -> int:
        """Find a named camera in the compiled model. After
        _load_or_synthesize_model the requested name should exist; fall
        through to first camera or free-cam only as a last resort."""
        cam_id = self._mujoco.mj_name2id(
            self._model, self._mujoco.mjtObj.mjOBJ_CAMERA, name
        )
        if cam_id >= 0:
            return cam_id
        if self._model.ncam > 0:
            log.warning(
                "head camera %r missing after compile; using camera idx=0", name
            )
            return 0
        log.warning(
            "no <camera> available; falling back to free camera at origin"
        )
        return -1

    def _compute_fov(self) -> Tuple[float, float]:
        """Pull the camera's vertical FoV from MJCF and derive horizontal FoV
        from aspect. Defaults to 60° horizontal if no camera is defined."""
        if self._cam_id < 0:
            return 60.0, 60.0 * self._height / max(self._width, 1)
        # mjModel.cam_fovy is in degrees (vertical)
        vfov = float(self._model.cam_fovy[self._cam_id])
        # horizontal FoV: 2 * atan( tan(vfov/2) * W/H )
        import math

        hfov = math.degrees(
            2.0 * math.atan(math.tan(math.radians(vfov) * 0.5) * (self._width / self._height))
        )
        return hfov, vfov

    @property
    def hfov_deg(self) -> float:
        return self._hfov_deg

    @property
    def vfov_deg(self) -> float:
        return self._vfov_deg

    # ---------------- DDS subscribers ----------------

    def _init_dds_subscribers(self) -> None:
        try:
            from unitree_sdk2py.core.channel import ChannelSubscriber
            from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
            from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
        except Exception as e:
            log.warning(
                "cannot import unitree_sdk2py for head cam DDS: %s; rendering "
                "from default qpos only",
                e,
            )
            return
        try:
            sub_low = ChannelSubscriber("rt/lowstate", LowState_)
            sub_low.Init(self._on_lowstate, 10)
            self._subs.append(sub_low)
        except Exception as e:
            log.warning("failed to subscribe rt/lowstate: %s", e)
        try:
            sub_high = ChannelSubscriber("rt/sportmodestate", SportModeState_)
            sub_high.Init(self._on_sportmode, 10)
            self._subs.append(sub_high)
        except Exception as e:
            log.warning("failed to subscribe rt/sportmodestate: %s", e)

    def _on_lowstate(self, msg) -> None:
        try:
            n = self._model.nu
            q = np.array([msg.motor_state[i].q for i in range(n)], dtype=np.float64)
            quat = np.array(msg.imu_state.quaternion[:4], dtype=np.float64)
            with self._state_lock:
                self._latest_motor_q = q
                self._latest_base_quat = quat
        except Exception as e:
            log.debug("lowstate decode error: %s", e)

    def _on_sportmode(self, msg) -> None:
        try:
            pos = np.array(msg.position[:3], dtype=np.float64)
            with self._state_lock:
                self._latest_base_pos = pos
        except Exception as e:
            log.debug("sportmode decode error: %s", e)

    # ---------------- rendering ----------------

    def _sync_qpos(self) -> None:
        """Push the latest live state into our private mjData. We only set
        qpos slices; we don't run forward dynamics, just kinematics."""
        with self._state_lock:
            q = self._latest_motor_q
            quat = self._latest_base_quat
            pos = self._latest_base_pos
        # Floating base is the first 7 entries of qpos when present.
        free_joint = self._model.nq - self._model.nu == 7
        if free_joint:
            if pos is not None:
                self._data.qpos[0:3] = pos
            if quat is not None:
                # MuJoCo quat order is (w, x, y, z), same as Unitree IMU
                self._data.qpos[3:7] = quat
            if q is not None and q.shape[0] == self._model.nu:
                self._data.qpos[7 : 7 + self._model.nu] = q
        else:
            if q is not None and q.shape[0] <= self._model.nq:
                self._data.qpos[: q.shape[0]] = q
        self._mujoco.mj_forward(self._model, self._data)

    def _render_once(self) -> None:
        try:
            self._sync_qpos()
        except Exception as e:
            log.debug("qpos sync error: %s", e)
            return
        try:
            cam_arg = self._cam_id if self._cam_id >= 0 else None
            if cam_arg is None:
                self._renderer.update_scene(self._data)
                self._depth_renderer.update_scene(self._data)
            else:
                self._renderer.update_scene(self._data, camera=cam_arg)
                self._depth_renderer.update_scene(self._data, camera=cam_arg)
            rgb = self._renderer.render()       # (H, W, 3) uint8
            depth = self._depth_renderer.render()  # (H, W) float32, meters
            bgr = rgb[..., ::-1].copy()
            now = time.monotonic()
            with self._lock:
                self._last_bgr = bgr
                self._last_depth_m = np.asarray(depth, dtype=np.float32)
                self._last_t = now
        except Exception as e:
            log.debug("render error: %s", e)

    def _render_loop(self) -> None:
        # Build the GL-backed renderers here so their EGL/GLFW contexts are
        # owned by this thread (see __init__).
        try:
            self._renderer = self._mujoco.Renderer(
                self._model, height=self._height, width=self._width
            )
            self._depth_renderer = self._mujoco.Renderer(
                self._model, height=self._height, width=self._width
            )
            self._depth_renderer.enable_depth_rendering()
        except Exception as e:  # noqa: BLE001
            log.error("head cam renderer init failed: %s", e)
            return
        try:
            while not self._stop.is_set():
                self._render_once()
                self._stop.wait(self._poll_interval_s)
        finally:
            for r in (self._renderer, self._depth_renderer):
                try:
                    if r is not None:
                        r.close()
                except Exception:  # noqa: BLE001
                    pass
            self._renderer = None
            self._depth_renderer = None

    # ---------------- public API ----------------

    def latest_bgr(self) -> Optional[np.ndarray]:
        with self._lock:
            return None if self._last_bgr is None else self._last_bgr.copy()

    def latest_depth_meters(self) -> Optional[np.ndarray]:
        with self._lock:
            return None if self._last_depth_m is None else self._last_depth_m.copy()

    def latest_jpeg_b64(self, width: int = 1024, jpeg_quality: int = 85) -> Optional[str]:
        import base64

        import cv2

        bgr = self.latest_bgr()
        if bgr is None:
            return None
        h, w = bgr.shape[:2]
        if w > width:
            new_h = int(h * width / w)
            bgr = cv2.resize(bgr, (width, new_h), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode("ascii")

    def frame_age_seconds(self) -> float:
        with self._lock:
            if self._last_t <= 0:
                return float("inf")
            return time.monotonic() - self._last_t

    def close(self) -> None:
        # Signal the render thread; it owns the GL contexts and frees them
        # in its own finally block. Closing them from this thread would error
        # with EGL_BAD_ACCESS for the same reason renderer construction had to
        # be moved into the worker.
        self._stop.set()
        try:
            self._render_thread.join(timeout=2.0)
        except Exception:
            pass
        for s in self._subs:
            try:
                # unitree_sdk2py subscribers don't have a public Close in all
                # versions; best-effort cleanup.
                close = getattr(s, "Close", None)
                if callable(close):
                    close()
            except Exception:
                pass
