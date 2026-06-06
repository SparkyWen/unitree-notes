"""Synthesized thermal/battery telemetry for the G1 sim harness.

MuJoCo models no battery or motor temperature, so the harness derives them from
the *real* joint efforts (``tau_est`` from LowState): each joint heats with
load and cools toward ambient; battery temperature tracks the aggregate motor
excess; SOC drains with time and load. An ``inject()`` hook lets the
coordinator/test force a deterministic overheat for verification.

The model only *reports* raw values + injected faults. Classifying them as an
anomaly (e.g. "battery_hot") is the coordinator's job (AnomalyDetector), keeping
sensing and policy separate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set


@dataclass
class ThermalSnapshot:
    hottest_motor_c: float
    hottest_motor_idx: int
    mean_motor_c: float
    battery_temperature_c: float
    soc: float
    charging: bool
    faults: List[str] = field(default_factory=list)


class ThermalModel:
    def __init__(self, *, n_joints: int = 29, ambient_c: float = 25.0,
                 k: float = 0.02, cooling: float = 0.15,
                 battery_alpha: float = 0.6, base_drain: float = 0.0008,
                 load_drain: float = 0.00006, soc0: float = 1.0,
                 tau_clip: Optional[float] = None):
        self._n = max(1, n_joints)
        self._ambient = ambient_c
        self._k = k
        self._cooling = cooling
        self._tau_clip = tau_clip
        self._battery_alpha = battery_alpha
        self._base_drain = base_drain
        self._load_drain = load_drain
        self._temps: List[float] = [ambient_c] * self._n
        self._soc = soc0
        self._charging = False
        # Sticky injection overrides (None = use model value).
        self._inj_batt_c: Optional[float] = None
        self._inj_soc: Optional[float] = None
        self._inj_motor_c: Optional[float] = None
        self._inj_faults: Set[str] = set()

    def update(self, *, tau: List[float], dt: float) -> None:
        n = min(self._n, len(tau))
        clip = self._tau_clip
        for i in range(n):
            ti = abs(tau[i])
            if clip is not None and ti > clip:
                ti = clip
            t = self._temps[i]
            heat = self._k * (ti ** 2) * dt
            cool = self._cooling * (t - self._ambient) * dt
            self._temps[i] = t + heat - cool
        if tau:
            mean_abs = sum(min(abs(x), clip) if clip is not None else abs(x)
                           for x in tau[:n]) / max(1, n)
        else:
            mean_abs = 0.0
        self._soc = max(0.0, self._soc - (self._base_drain + self._load_drain * mean_abs) * dt)

    def inject(self, *, battery_temperature_c: Optional[float] = None,
               soc: Optional[float] = None, motor_temperature_c: Optional[float] = None,
               fault: Optional[str] = None, charging: Optional[bool] = None) -> None:
        if battery_temperature_c is not None:
            self._inj_batt_c = float(battery_temperature_c)
        if soc is not None:
            self._inj_soc = float(soc)
        if motor_temperature_c is not None:
            self._inj_motor_c = float(motor_temperature_c)
        if fault:
            self._inj_faults.add(fault)
        if charging is not None:
            self._charging = bool(charging)

    def clear_injection(self) -> None:
        self._inj_batt_c = None
        self._inj_soc = None
        self._inj_motor_c = None
        self._inj_faults.clear()

    def snapshot(self) -> ThermalSnapshot:
        hottest_idx = max(range(self._n), key=lambda i: self._temps[i])
        hottest = self._temps[hottest_idx]
        mean_c = sum(self._temps) / self._n
        if self._inj_motor_c is not None:
            hottest = max(hottest, self._inj_motor_c)
        batt = self._ambient + self._battery_alpha * max(0.0, mean_c - self._ambient)
        if self._inj_batt_c is not None:
            batt = self._inj_batt_c
        soc = self._inj_soc if self._inj_soc is not None else self._soc
        return ThermalSnapshot(
            hottest_motor_c=round(hottest, 2), hottest_motor_idx=hottest_idx,
            mean_motor_c=round(mean_c, 2), battery_temperature_c=round(batt, 2),
            soc=round(soc, 4), charging=self._charging,
            faults=sorted(self._inj_faults),
        )
