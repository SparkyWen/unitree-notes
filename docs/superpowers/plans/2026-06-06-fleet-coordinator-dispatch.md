# Fleet Coordinator — Closed-Loop Intelligent Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn the read-only fleet foundation into a closed-loop system where an AI coordinator reads two MuJoCo G1s' telemetry, autonomously detects a battery overheat, safely sleeps the hot robot, and reassigns its task to the healthy robot — plus a human-command path — with each robot keeping its own fast/slow brain and final safety veto.

**Architecture:** Add a bidirectional WebSocket command path on top of the existing telemetry-up bus; a per-robot `SimRobotHarness` (fast `RobotFsm`+`AdmissionGate`, slow `LocalPlanner`, `ThermalModel`, pluggable `MotionBackend`); and a deterministic coordinator dispatch brain (`AnomalyDetector`, `DispatchEngine`, `LeaseManager`, `CommandGateway`) with an optional degradable LLM parse/explain layer. Verify two tiers: pure-Python mock e2e (CI) and two real G1s in MuJoCo.

**Tech Stack:** Python 3.11 (`agi` conda env), pydantic v2, aiohttp, unitree_sdk2py (DDS), mujoco 3.5, onnxruntime, openai (optional). Run from `g1_brain/` so `g1_brain.fleet.*` imports resolve; `pytest tests/fleet`.

**Spec:** [`docs/superpowers/specs/2026-06-06-fleet-coordinator-dispatch-design.md`](../specs/2026-06-06-fleet-coordinator-dispatch-design.md)

**Conventions:** All commands run with `cd ~/unitree/unitree-notes/g1_brain && conda run -n agi python ...`. Tests: `conda run -n agi pytest tests/fleet/<f>::<t> -q`. Commit after each task (branch `feature/coordinator-design`).

---

## Phase A — Contracts + bidirectional bus  (Task #3)

### Task A1: Promote command/telemetry contracts

**Files:** Modify `g1_brain/g1_brain/fleet/contracts/models.py`; Test `tests/fleet/test_contracts_dispatch.py`

- [ ] **A1.1 Write failing tests** — round-trip + defaults + payload_hash:

```python
# tests/fleet/test_contracts_dispatch.py
from g1_brain.fleet.contracts.models import (
    CommandEnvelope, AdmissionDecision, TaskSpec, Mission, ReplanProposal,
    Lease, SafetyEnvelope, Battery, Health, CoreState, EventType,
)

def test_command_envelope_make_sets_hash_and_ids():
    env = CommandEnvelope.make(issued_by="coord", issued_to="g1_a",
                               capability="sleep", payload={"reason": "overheat"},
                               ttl_s=30.0, trace_id="t1")
    assert env.command_id and env.idempotency_key and env.expires_at > env.issued_at_epoch
    assert env.payload_hash.startswith("sha256:")
    assert env.capability == "sleep"
    j = env.model_dump(mode="json"); assert CommandEnvelope.model_validate(j) == env

def test_admission_decision_roundtrip():
    d = AdmissionDecision(command_id="c1", robot_id="g1_a", decision="refused",
                          reason_code="EXPIRED", reason_detail="ttl", ts="2026-06-06T00:00:00Z")
    assert AdmissionDecision.model_validate(d.model_dump(mode="json")) == d

def test_core_state_has_battery_health():
    cs = CoreState(battery=Battery(soc=0.4, temperature_c=72.0, charging=False),
                   health=Health(level="warning", faults=["battery_hot"]))
    assert cs.battery.temperature_c == 72.0 and "battery_hot" in cs.health.faults

def test_new_event_types_exist():
    for n in ["anomaly_detected","command_issued","command_accepted","command_refused",
              "task_assigned","task_reassigned","robot_sleeping","robot_resumed","lease_expired"]:
        assert any(e.value == n for e in EventType)
```

- [ ] **A1.2 Run** `pytest tests/fleet/test_contracts_dispatch.py -q` → FAIL (imports missing).
- [ ] **A1.3 Implement** in `models.py`: add `Battery`, `Health` and wire into `CoreState`; add `Lease`, `SafetyEnvelope`; replace reserved `CommandEnvelope`/`TaskSpec`/`AdmissionDecision` with real models; add `Mission`, `ReplanProposal`. `CommandEnvelope.make(...)` mirrors `RobotEvent.make` (uuid id, `idempotency_key` default = `command_id`, `issued_at`/`issued_at_epoch`, `expires_at = issued_at_epoch + ttl_s`, `payload_hash`). Extend `EventType` enum with the 9 new values.
- [ ] **A1.4 Run** → PASS. Run full `pytest tests/fleet/test_contracts_models.py -q` (existing) → still PASS.
- [ ] **A1.5 Update** `contracts/json_schema_export.py` to include the new models; run `tests/fleet/test_json_schema_export.py` → PASS.
- [ ] **A1.6 Commit** `feat(fleet): promote command/task contracts + battery/health telemetry`.

### Task A2: Bidirectional bus frames

**Files:** Modify `fleet/bus/messages.py`, `fleet/bus/base.py`; Test `tests/fleet/test_bus_command_frames.py`

- [ ] **A2.1 Failing test:**

```python
from g1_brain.fleet.bus.messages import encode_frame, decode_frame, FrameKind
from g1_brain.fleet.contracts.models import CommandEnvelope, AdmissionDecision

def test_command_frame_roundtrip():
    env = CommandEnvelope.make(issued_by="c", issued_to="r", capability="wake", payload={})
    kind, model = decode_frame(encode_frame(FrameKind.COMMAND, env))
    assert kind == FrameKind.COMMAND and model == env

def test_admission_frame_roundtrip():
    d = AdmissionDecision(command_id="c1", robot_id="r", decision="accepted",
                          reason_code="OK", reason_detail="", ts="2026-06-06T00:00:00Z")
    kind, model = decode_frame(encode_frame(FrameKind.ADMISSION, d))
    assert kind == FrameKind.ADMISSION and model == d
```

- [ ] **A2.2 Run** → FAIL. **A2.3 Implement**: add `COMMAND`/`ADMISSION` to `FrameKind` and to `_MODEL_FOR`. **A2.4 Run** → PASS.
- [ ] **A2.5** Extend `bus/base.py` `FleetBus` ABC with `async def send_command(self, robot_id, envelope)` and an `on_command` callback attribute (default no-op); keep existing methods. Add an in-process `LoopbackBus` test double (used by Tier-1) implementing connect/heartbeat/publish/send_command/on_command over `asyncio.Queue`s.
- [ ] **A2.6 Commit** `feat(fleet): bidirectional bus frames + loopback test bus`.

### Task A3: WS server — per-robot routing + admission sink

**Files:** Modify `fleet/bus/ws_server.py`; Test `tests/fleet/test_ws_command_routing.py`

- [ ] **A3.1 Failing test** (aiohttp test client): a client connects, sends `REGISTER`; server `send_command("g1_a", env)` is received by that client; client replies `ADMISSION`; server routes it to `admission_sink`.
- [ ] **A3.2 Run** → FAIL. **A3.3 Implement**: `app["fleet_conns"]: dict[str, WebSocketResponse]`; on `REGISTER` store `robot_id→ws` (and pop on disconnect in `finally`); `app["admission_sink"]` (a callback / asyncio.Queue); on inbound `ADMISSION` call the sink + `event_log` lifecycle event; add `async def send_command(app, robot_id, env)` that looks up the conn and `ws.send_str(encode_frame(COMMAND, env))` (raise/log if absent). **A3.4 Run** → PASS.
- [ ] **A3.5** Update `build_fleet_app(...)` signature to accept `admission_sink=None`; keep back-compat for the read-only callers. Run existing `tests/fleet/test_ws_server.py` → PASS.
- [ ] **A3.6 Commit** `feat(fleet): WS per-robot command routing + admission sink`.

### Task A4: WS client — inbound command handling

**Files:** Modify `fleet/bus/ws_client.py`; Test `tests/fleet/test_ws_client_command.py`

- [ ] **A4.1 Failing test:** stand up the server app, connect a `FleetBusClient` with an `on_command` that records the envelope and returns an `AdmissionDecision`; server `send_command(...)`; assert the client invoked `on_command` and the server's `admission_sink` saw the decision.
- [ ] **A4.2 Run** → FAIL. **A4.3 Implement**: in the client read loop, on `COMMAND` frame call `await self.on_command(env)` → send back `ADMISSION` frame. Preserve reconnect/backoff. **A4.4 Run** → PASS; existing `test_ws_client.py` still PASS.
- [ ] **A4.5 Commit** `feat(fleet): WS client inbound command + admission reply`.

---

## Phase B — SimRobotHarness fast/slow brain  (Task #4)

### Task B1: DORMANT FSM state (additive)

**Files:** Modify `g1_brain/g1_brain/safety/state_machine.py`; Test `tests/test_state_machine_dormant.py` (or extend existing FSM test)

- [ ] **B1.1 Failing test:** `DORMANT` exists; `STANDING→DORMANT` and `DORMANT→STANDING` legal; `DORMANT→EMERGENCY_STOP`/`FAULT` legal; pre-existing transitions unchanged (assert one previously-illegal pair still raises).
- [ ] **B1.2 Run** → FAIL. **B1.3 Implement**: add `DORMANT = "DORMANT"`; add to `_ALLOWED` (`STANDING` gains `DORMANT`; new `DORMANT: {STANDING, EMERGENCY_STOP, FAULT}`). Additive only. **B1.4 Run** → PASS; run repo's existing state-machine tests → PASS.
- [ ] **B1.5 Commit** `feat(safety): additive DORMANT FSM state for fleet sleep`.

### Task B2: ThermalModel

**Files:** Create `fleet/agent/thermal_model.py`; Test `tests/fleet/test_thermal_model.py`

- [ ] **B2.1 Failing tests:**

```python
from g1_brain.fleet.agent.thermal_model import ThermalModel

def test_load_raises_temp():
    tm = ThermalModel(n_joints=4, ambient_c=25.0, k=0.5, cooling=0.1)
    for _ in range(50): tm.update(tau=[10.0]*4, dt=0.1)
    s = tm.snapshot(); assert s.hottest_motor_c > 25.0 and s.battery_temperature_c > 25.0

def test_cooling_decays_temp():
    tm = ThermalModel(n_joints=2, ambient_c=25.0, k=0.5, cooling=0.5)
    for _ in range(20): tm.update(tau=[20.0]*2, dt=0.1)
    hot = tm.snapshot().hottest_motor_c
    for _ in range(200): tm.update(tau=[0.0]*2, dt=0.1)
    assert tm.snapshot().hottest_motor_c < hot

def test_inject_overrides():
    tm = ThermalModel(n_joints=2)
    tm.inject(battery_temperature_c=75.0, soc=0.3, fault="battery_hot")
    s = tm.snapshot()
    assert s.battery_temperature_c == 75.0 and s.soc == 0.3 and "battery_hot" in s.faults
```

- [ ] **B2.2 Run** → FAIL. **B2.3 Implement**: dataclass `ThermalSnapshot(hottest_motor_c, hottest_motor_idx, mean_motor_c, battery_temperature_c, soc, charging, faults)`. Per-joint `T += k*tau_i^2*dt - cooling*(T-ambient)*dt`; battery temp = ambient + α·mean_motor_excess; SOC decays `soc -= (base_drain + load_drain*mean|tau|)*dt`. `inject()` sets a one-shot override merged into the next `snapshot()`. **B2.4 Run** → PASS. **B2.5 Commit** `feat(fleet): tau-driven thermal/battery model + inject hook`.

### Task B3: MotionBackend protocol + MockBackend

**Files:** Create `fleet/agent/motion/__init__.py`, `fleet/agent/motion/base.py`, `fleet/agent/motion/mock.py`; Test `tests/fleet/test_motion_mock.py`

- [ ] **B3.1 Failing test:** `Posture` enum (`ACTIVE,PATROL,SLEEP,WAKE,IDLE,STOP`); `MockBackend.set_posture(SLEEP)` records last posture; `read_lowstate()` returns an object exposing `tau_est()` list (configurable) and `gravity_proj_z`; `set_load(...)` lets a test drive tau.
- [ ] **B3.2 Run** → FAIL. **B3.3 Implement**: `MotionBackend` Protocol (`set_posture`, `step`, `read_lowstate`, `close`); `MockLowstate` with `tau_est()`, `gravity_proj_z`; `MockBackend` storing posture + synthetic tau (SLEEP/IDLE→low tau, PATROL/ACTIVE→higher tau). **B3.4 Run** → PASS. **B3.5 Commit** `feat(fleet): MotionBackend protocol + mock backend`.

### Task B4: AdmissionGate (fast-brain local authority)

**Files:** Create `fleet/agent/admission_gate.py`; Test `tests/fleet/test_admission_gate.py`

- [ ] **B4.1 Failing tests:** accept a valid `sleep` (returns `decision="accepted"`, FSM→DORMANT applied via planner callback); refuse expired (`reason_code="EXPIRED"`); refuse duplicate idempotency (`"DUPLICATE"`); refuse unknown capability (`"UNSUPPORTED_CAPABILITY"`); refuse capability illegal in current FSM state (`"FSM_FORBIDDEN"`, e.g. `patrol` while DORMANT requires wake first).
- [ ] **B4.2 Run** → FAIL. **B4.3 Implement**: `AdmissionGate(fsm, planner, capabilities, clock)` with `admit(env)->AdmissionDecision`. Order: expiry → idempotency cache → capability supported → FSM legality (map capability→required state precondition) → delegate to `planner.apply(env)` → build decision. On accept, record idempotency key. **B4.4 Run** → PASS. **B4.5 Commit** `feat(fleet): local admission gate (final refusal authority)`.

### Task B5: LocalPlanner (slow-brain capability→skill)

**Files:** Create `fleet/agent/local_planner.py`; Test `tests/fleet/test_local_planner.py`

- [ ] **B5.1 Failing tests:** `apply(sleep)` → backend posture SLEEP + FSM STANDING→DORMANT; `apply(wake)`/`apply(resume_task)` → WAKE/PATROL + DORMANT→STANDING; `apply(patrol)` → PATROL; `apply(stop)` → STOP; emits the matching lifecycle `RobotEvent`s to the event sink.
- [ ] **B5.2 Run** → FAIL. **B5.3 Implement**: `LocalPlanner(fsm, backend, event_sink)` with `apply(env)`; capability→(posture, fsm_target, event_type) table; pushes `robot_sleeping`/`robot_resumed`/`task_assigned` events. Optional `explain_hook` attribute (unused on control path). **B5.4 Run** → PASS. **B5.5 Commit** `feat(fleet): local planner (slow-brain capability mapping)`.

### Task B6: HarnessCore.admit + battery/health state; SimRobotHarness assembly

**Files:** Modify `fleet/harness_core/core.py`; Create `fleet/agent/sim_harness.py`; Test `tests/fleet/test_harness_admit.py`, `tests/fleet/test_sim_harness.py`

- [ ] **B6.1 Failing test (core):** `get_state()` now includes `core.battery`/`core.health` from an injected `ThermalModel`; `admit(env)` delegates to `AdmissionGate` and returns an `AdmissionDecision` (no more `NotImplementedError`).
- [ ] **B6.2 Run** → FAIL. **B6.3 Implement**: extend `HarnessCore.__init__` to accept optional `thermal`, `admission_gate`; `get_state` populates battery/health + `extensions.g1_sim` hottest-motor; `admit` → gate. Keep read-only constructor path working (gate/thermal optional). **B6.4 Run** → PASS; existing `test_harness_core.py` → PASS.
- [ ] **B6.5 Failing test (harness):** `SimRobotHarness.from_mock(robot_id)` builds fsm+thermal+backend+planner+gate+core; feeding load via the mock backend raises reported `battery.temperature_c`; `harness.on_command(env)` (the bus callback) routes to `core.admit` and returns a decision; a `sleep` command drives FSM to DORMANT and backend to SLEEP.
- [ ] **B6.6 Run** → FAIL. **B6.7 Implement** `SimRobotHarness`: owns fsm, thermal, backend, planner, gate, HarnessCore, a `tick()` that pulls `backend.read_lowstate().tau_est()` → `thermal.update(...)`, and `on_command` = `core.admit`. Factory `from_mock(...)`; factory `from_dds(domain_id, backend=...)` (deferred wiring used in Phase D). **B6.8 Run** → PASS. **B6.9 Commit** `feat(fleet): SimRobotHarness (fast/slow brain) + HarnessCore admit`.

### Task B7: RobotAgent command path

**Files:** Modify `fleet/agent/robot_agent.py`; Test `tests/fleet/test_robot_agent_command.py`

- [ ] **B7.1 Failing test:** wire a `RobotAgent` to a `LoopbackBus` and a `SimRobotHarness`; coordinator side `bus.send_command(robot_id, sleep_env)` → agent invokes `harness.on_command` → an `AdmissionDecision(accepted)` flows back; harness FSM is DORMANT.
- [ ] **B7.2 Run** → FAIL. **B7.3 Implement**: in `RobotAgent.start`, set `self._bus.on_command = self._core.admit` (and ensure heartbeats now carry battery/health). **B7.4 Run** → PASS; existing `test_robot_agent.py` → PASS. **B7.5 Commit** `feat(fleet): robot-agent command intake → admission`.

---

## Phase C — Coordinator dispatch brain  (Task #5)

### Task C1: AnomalyDetector

**Files:** Create `fleet/coordinator/anomaly.py`; Test `tests/fleet/test_anomaly.py`

- [ ] **C1.1 Failing tests:** given registry states, detect `battery_overheat` when `temperature_c≥70`; `motor_overheat` when `hottest_motor_c≥80`; `fall` when `gravity_proj_z>-0.85`; `low_soc` when `soc≤0.15`; `stale`/`offline` from registry status; hysteresis: once cleared below `70-margin`, re-arms. Each yields a typed `Anomaly(robot_id, kind, severity, evidence, ts)`.
- [ ] **C1.2 Run** → FAIL. **C1.3 Implement** `AnomalyDetector(thresholds)` with `scan(registry)->list[Anomaly]`, internal per-robot armed-state for hysteresis. **C1.4 Run** → PASS. **C1.5 Commit** `feat(fleet): deterministic anomaly detector`.

### Task C2: DispatchEngine

**Files:** Create `fleet/coordinator/dispatch.py`; Test `tests/fleet/test_dispatch.py`

- [ ] **C2.1 Failing tests:** `assign(task)` picks a healthy/available/capable robot (skips offline/dormant/overheating); `handle_anomaly(battery_overheat on R1 holding T)` returns an ordered plan `[sleep(R1), reassign(T→R2), patrol(R2)]`; with no healthy candidate returns `[sleep(R1), hold(T)]` + a `needs_operator` flag; `human takeover(R1→R2)` plan moves the task. Plans are lists of `CommandEnvelope`s + bookkeeping, not yet sent.
- [ ] **C2.2 Run** → FAIL. **C2.3 Implement** `DispatchEngine(registry)` holding `assignments: dict[task_id, robot_id]` and `tasks`. Candidate scoring: available ∧ capable ∧ `health.level==ok` ∧ not dormant, tiebreak by SOC desc. **C2.4 Run** → PASS. **C2.5 Commit** `feat(fleet): dispatch engine (assign + sleep/reassign)`.

### Task C3: LeaseManager + CommandGateway

**Files:** Create `fleet/coordinator/lease.py`, `fleet/coordinator/gateway.py`; Test `tests/fleet/test_lease.py`, `tests/fleet/test_gateway.py`

- [ ] **C3.1 Failing tests (lease):** grant lease with ttl; `tick(now)` past ttl with no heartbeat → `expired` → yields a `safe_pause` command for that robot; heartbeat renews.
- [ ] **C3.2 Implement** `LeaseManager` (grant/heartbeat/tick). Run → PASS.
- [ ] **C3.3 Failing tests (gateway):** `issue(env)` assigns idempotency/expiry, calls `bus.send_command`, writes `command_issued` to the event log; on duplicate idempotency key it no-ops; records the returned `AdmissionDecision` as `command_accepted|command_refused`.
- [ ] **C3.4 Implement** `CommandGateway(bus, event_log, clock)`. Run → PASS. **C3.5 Commit** `feat(fleet): lease manager + command gateway`.

### Task C4: CoordinatorAgent (optional LLM, degradable)

**Files:** Create `fleet/coordinator/agent_llm.py`; Test `tests/fleet/test_agent_llm.py`

- [ ] **C4.1 Failing tests (no key path):** with `client=None`, `parse("dispatch patrol --to fleet")` → `StructuredOp(kind="dispatch", ...)` via the grammar; `parse("让2号接替1号")`/unparseable → grammar miss returns `None`; `explain(decision, evidence)` returns a templated string citing the evidence (temperature, robot ids). LLM path is mocked (inject a fake client) and asserted to be re-validated (an op naming an unknown robot is rejected).
- [ ] **C4.2 Run** → FAIL. **C4.3 Implement** `CoordinatorAgent(client=None)`: a regex/argparse command grammar always available; if `client` set, `parse` first tries an LLM structured call then falls back to grammar; `explain` uses LLM if present else a template. A `validate(op, registry)` gate every op passes through. **C4.4 Run** → PASS. **C4.5 Commit** `feat(fleet): optional LLM parse/explain layer (degrades to grammar)`.

### Task C5: Coordinator app wiring

**Files:** Modify `fleet/coordinator/app.py`, `fleet/coordinator/__main__.py`; Test `tests/fleet/test_coordinator_dispatch_app.py`

- [ ] **C5.1 Failing test:** build the app with a `LoopbackBus`; POST `/commands {op:"inject", robot:"g1_a", temp:75}` then run one detector tick → assert an `anomaly_detected` + `command_issued(sleep)` appear in `/events`; `GET /anomalies` lists the battery_overheat; `GET /dispatch` shows the reassignment.
- [ ] **C5.2 Run** → FAIL. **C5.3 Implement**: instantiate detector/dispatch/lease/gateway/agent in `build_coordinator_app`; add a `DispatchController` that on each tick: `scan→for each anomaly: plan=dispatch.handle_anomaly→gateway.issue(...)`; expose routes `POST /missions`, `POST /commands`, `GET /anomalies`, `GET /dispatch`. Add a background tick task (started in `on_startup`, cancelled in `on_cleanup`). **C5.4 Run** → PASS; existing `test_coordinator_app.py` → PASS. **C5.5 Commit** `feat(fleet): coordinator dispatch wiring + routes`.

---

## Phase D — Console + Tier-1 e2e  (Task #6)

### Task D1: Operator console

**Files:** Modify `fleet/console/cli.py`; Test `tests/fleet/test_console_ops.py`

- [ ] **D1.1 Failing test:** `format_fleet` renders battery temp + anomalies + leases; a `post_command(base, op)` helper builds the right JSON body for `dispatch/sleep/wake/takeover/inject/status/explain`.
- [ ] **D1.2 Run** → FAIL. **D1.3 Implement** the formatter additions + an argparse subcommand surface (`status|dispatch|sleep|wake|takeover|inject|explain`) calling the coordinator routes. **D1.4 Run** → PASS. **D1.5 Commit** `feat(fleet): operator console commands`.

### Task D2: Tier-1 pure-Python e2e

**Files:** Create `tests/fleet/test_e2e_dispatch.py`

- [ ] **D2.1 Write the e2e test** (the spec §9 Tier-1 scenario) over a `LoopbackBus`, 2 `SimRobotHarness.from_mock`, and the `DispatchController`: register → assign patrol to R1 → `inject(R1,75)` → tick → assert ordered events `anomaly_detected → command_issued(sleep) → command_accepted → task_reassigned → command_issued(patrol/resume_task) → command_accepted`; assert R1 FSM `DORMANT`+posture `SLEEP`, R2 posture `PATROL`; then human `takeover`/`wake` path; assert R1 resumes.
- [ ] **D2.2 Run** `pytest tests/fleet/test_e2e_dispatch.py -q` → iterate until PASS.
- [ ] **D2.3** Run the whole suite `pytest tests/fleet -q` → all PASS. **D2.4 Commit** `test(fleet): tier-1 pure-python dispatch e2e`.

---

## Phase E — Tier-2 MuJoCo + verify  (Task #7)

### Task E1: Two-sim DDS support

**Files:** Modify `unitree_mujoco/simulate_python/config.py`; (no test — config)

- [ ] **E1.1 Implement:** `DOMAIN_ID = int(os.environ.get("UNITREE_DOMAIN_ID", DOMAIN_ID))` and `INTERFACE = os.environ.get("UNITREE_INTERFACE", INTERFACE)`. Keep defaults. **E1.2 Smoke:** launch one sim headless, confirm `rt/lowstate` on domain 1; launch a second with `UNITREE_DOMAIN_ID=2`, confirm isolation. **E1.3 Commit** `feat(sim): env-overridable DDS domain for multi-robot`.

### Task E2: DDS motion backends

**Files:** Create `fleet/agent/motion/rl_balance.py`, `fleet/agent/motion/elastic_pd.py`; Test `tests/fleet/test_motion_backends_import.py` (import/contract only; physics is system-tested)

- [ ] **E2.1 Implement `RLBalanceBackend`**: in `__init__(domain_id, interface)` build/`init_dds`/`start` a `g1_sim_rl_combo.ComboController`; `set_posture`: ACTIVE/IDLE→`set_command(0,0,0)`, PATROL→small periodic `wz`/`vx` (+ optional arm gesture), SLEEP→`set_command(0,0,0)`+`release_arms()`, STOP→`stop_and_settle()`; `read_lowstate()` exposes the combo's latest LowState (tau_est, imu). `close()`→stop.
- [ ] **E2.2 Implement `ElasticPDBackend`** (fallback): own DDS LowCmd publisher + LowState subscriber; postures = PD target sets (stand / patrol-wave / crouch-damp); `read_lowstate` from the subscription.
- [ ] **E2.3** Import/contract test only (no DDS in CI): both classes satisfy the `MotionBackend` protocol and map every `Posture`. **E2.4 Commit** `feat(fleet): DDS RL + elastic-PD motion backends`.

### Task E3: Tier-2 scenario runner

**Files:** Create `fleet/sim/__init__.py`, `fleet/sim/scenario_two_g1.py`; (system test, manual run)

- [ ] **E3.1 Implement** an async runner: start the coordinator app (aiohttp) in-process; build 2 `SimRobotHarness.from_dds(domain_id=1/2, backend="rl"|"elastic")` each wrapped in a `RobotAgent` connected to the coordinator WS; assign a patrol mission to R1; then drive the **autonomous** scenario (`inject` overheat on R1 → observe sleep + reassign) and the **human-command** scenario (console op). Print a timestamped dispatch trace and dump the event-log replay. Flags: `--backend rl|elastic`, `--headless`, `--inject-after S`.
- [ ] **E3.2 Pre-reqs check:** assert `unitree_sdk2py`, `mujoco`, `onnxruntime` importable in `agi`; locate the G1 RL policy artifact used by `g1_sim_rl_combo`.
- [ ] **E3.3 Commit** `feat(fleet): tier-2 two-G1 mujoco scenario runner`.

### Task E4: VERIFY (the acceptance bar)

- [ ] **E4.1** Launch sim #1: `cd unitree_mujoco/simulate_python && conda run -n agi env UNITREE_DOMAIN_ID=1 MUJOCO_GL=egl python unitree_mujoco.py` (headless) — confirm telemetry.
- [ ] **E4.2** Launch sim #2 with `UNITREE_DOMAIN_ID=2`.
- [ ] **E4.3** Run `conda run -n agi python -m g1_brain.fleet.sim.scenario_two_g1 --backend rl --inject-after 8` (fall back to `--backend elastic` if RL balance is unreliable — log which).
- [ ] **E4.4 Observe + capture evidence:** both robots report real telemetry; R1 overheats → coordinator detects → R1 → SLEEP (DORMANT) → task reassigned → R2 → PATROL; human-command scenario collaborates. Save console + event-log output under `g1_brain/logs/fleet/`.
- [ ] **E4.5** If RL unreliable: record that, deliver via `elastic`, and note the RL path as machine-dependent (per spec §13). Do NOT claim the RL visual if it didn't run.
- [ ] **E4.6** Use `superpowers:verification-before-completion` to confirm evidence before marking done.

---

## Phase F — Deliver  (Task #8)

- [ ] **F1** Full suite: `cd g1_brain && conda run -n agi pytest tests/fleet -q` → all PASS; paste the summary line.
- [ ] **F2** Write `instructions.md` §7 "Fleet coordinator — intelligent dispatch (two G1s)": the exact launch commands (2 sims + scenario runner), the console ops, the anomaly→sleep→reassign walkthrough, and the env/fallback notes.
- [ ] **F3** `superpowers:requesting-code-review` on the branch diff; address blocking findings.
- [ ] **F4** Commit `docs(instructions): §7 fleet intelligent dispatch run guide` and **push** `feature/coordinator-design`.

---

## Self-review notes
- **Spec coverage:** contracts §4→A1; bus §5→A2-A4; harness §6→B1-B7; coordinator §7→C1-C5; console §8→D1; verification §9→D2(Tier-1)/E3-E4(Tier-2); safety invariants §10 enforced in A1(TTL/idempotency), B4(refusal), B5/C-(deterministic sleep), C4(re-validate), C3(lease expire); file map §11→all tasks; risks §13→E2 dual backend + E4.5.
- **Type consistency:** `CommandEnvelope.make(...)`, `AdmissionDecision(decision=...)`, `Posture`, `ThermalSnapshot`, `Anomaly`, `StructuredOp`, `MotionBackend`, `SimRobotHarness.from_mock/from_dds` are used consistently across phases.
- **No placeholders:** every task has concrete files, test code or assertions, and commit messages.
