"""Deterministic anomaly detector — the coordinator's autonomous "perception".

Edge-triggered with hysteresis: an anomaly is emitted only when a robot first
crosses into the bad condition, and re-arms once it recovers past a margin. This
keeps the dispatch loop from flapping while a robot stays hot/down/stale.

It reads only the north-bound RobotState (battery/health/IMU + g1_sim ext) and
the registry status; it never reaches into the robot. Classifying raw telemetry
into anomalies lives here (policy), not in the robot's ThermalModel (sensing).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Set, Tuple


def _iso_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


@dataclass
class Anomaly:
    robot_id: str
    kind: str          # battery_overheat | motor_overheat | fall | low_soc | stale
    severity: str      # warning | critical
    evidence: Dict
    ts: str = field(default_factory=_iso_now)


class AnomalyDetector:
    def __init__(self, *, battery_hot_c: float = 70.0, motor_hot_c: float = 80.0,
                 soc_min: float = 0.15, fall_gz: float = -0.85, margin: float = 3.0,
                 now: Callable[[], str] = _iso_now):
        self._battery_hot = battery_hot_c
        self._motor_hot = motor_hot_c
        self._soc_min = soc_min
        self._fall_gz = fall_gz
        self._margin = margin
        self._now = now
        self._tripped: Set[Tuple[str, str]] = set()

    def _edge(self, out: List[Anomaly], rid: str, kind: str, cond: bool,
              rearm: bool, evidence: Dict, severity: str) -> None:
        key = (rid, kind)
        if cond and key not in self._tripped:
            self._tripped.add(key)
            out.append(Anomaly(robot_id=rid, kind=kind, severity=severity,
                               evidence=evidence, ts=self._now()))
        elif rearm and key in self._tripped:
            self._tripped.discard(key)

    def scan(self, registry) -> List[Anomaly]:
        out: List[Anomaly] = []
        for r in registry.list_robots():
            rid = r["robot_id"]
            status = r["status"]
            st = r.get("state")
            self._edge(out, rid, "stale", status in ("stale", "offline"),
                       status == "online", {"status": status}, "warning")
            if not st:
                continue
            core = st.get("core") or {}
            batt = core.get("battery") or {}
            safety = core.get("safety_state") or {}
            ext = (st.get("extensions") or {}).get("g1_sim", {})

            temp = batt.get("temperature_c")
            if temp is not None:
                self._edge(out, rid, "battery_overheat", temp >= self._battery_hot,
                           temp < self._battery_hot - self._margin,
                           {"temperature_c": temp}, "critical")
            soc = batt.get("soc")
            if soc is not None:
                self._edge(out, rid, "low_soc", soc <= self._soc_min,
                           soc > self._soc_min + 0.05, {"soc": soc}, "warning")
            motor = ext.get("hottest_motor_c")
            if motor is not None:
                self._edge(out, rid, "motor_overheat", motor >= self._motor_hot,
                           motor < self._motor_hot - self._margin,
                           {"hottest_motor_c": motor}, "critical")
            gz = safety.get("gravity_proj_z")
            if gz is not None:
                self._edge(out, rid, "fall", gz > self._fall_gz,
                           gz <= self._fall_gz, {"gravity_proj_z": gz}, "critical")
        return out
