# Fleet Coordinator — Closed-Loop Intelligent Dispatch (Design Spec)

> **Date**: 2026-06-06
> **Branch**: `feature/coordinator-design`
> **Builds on**: [`2026-06-06-fleet-foundation-design.md`](./2026-06-06-fleet-foundation-design.md) (the read-only Phase-1 foundation) and [`docs/coordinator-design.md`](../../coordinator-design.md) (the full architecture & roadmap).
> **Status**: design approved via brainstorming; pending spec review.

---

## 1. Goal (one paragraph)

Extend the existing **read-only** fleet foundation into a **closed-loop, task-level intelligent dispatch** system in which an AI Coordinator command center:

1. reads each robot's **real joint/sensor telemetry** (plus a synthesized battery/thermal channel) from **two G1 robots running in MuJoCo**;
2. **autonomously perceives anomalies** (battery overheat, hot motor, fall, low SOC, staleness) with a deterministic detector;
3. on anomaly, **safely puts the affected robot to sleep** and **reassigns its task to a healthy robot**;
4. also accepts **human commands** (natural language via an optional LLM layer, or a structured grammar) to drive **multi-robot collaboration**;
5. throughout, **each robot keeps its own fast/slow brain** and **retains final local safety authority** — the coordinator only publishes typed, leased, refusable capability contracts and never touches motors.

The acceptance bar: **demonstrate two G1 robots simultaneously under unified intelligent dispatch in MuJoCo**, end-to-end, replayable from the event log.

## 2. Locked decisions (from brainstorming)

| Fork | Decision | Consequence |
|---|---|---|
| Task-handoff fidelity | **Dispatch-level + visible posture** | Robots change posture (active/patrol ↔ damp/sleep); no free-walking floor handoff. The "智能调度" is 100% real at the task/contract/FSM/telemetry layer. Faithful to the doc's task-level (not motion-level) authority. |
| Coordinator intelligence | **Deterministic engine + optional LLM explain/parse layer** | Deterministic detection + reassignment is the **final scheduler/safety authority** (doc §20.3). LLM only parses NL commands and explains decisions from real evidence; degrades to a command grammar when no API key. Verification never depends on the LLM. |
| Anomaly source | **Thermal model + injection hook** | Per-robot thermal/battery model driven by **real `tau_est`**; plus a deterministic `inject()` hook so verification reliably triggers an overheat. |
| Tier-2 standing method | **RL self-balance (target) with elastic-PD fallback** | Headline: both G1s self-balance via the existing combo controller. Reliability fallback: elastic-band + PD postures. Pure-Python mock is the always-green CI proof. |

## 3. Architecture

```text
        ┌───────────────────────── AI Coordinator ─────────────────────────┐
        │  AnomalyDetector ─▶ DispatchEngine ─▶ LeaseManager ─▶ CommandGW   │  deterministic = AUTHORITY
        │        ▲                                    │                      │
        │  real telemetry (heartbeat ↑)        CommandEnvelope (↓)           │
        │        │                                    │                      │
        │  [optional CoordinatorAgent (LLM): parse NL · explain decisions]   │  PROPOSES / EXPLAINS only
        └────────┼────────────────────────────────────┼─────────────────────┘
            FleetBus over WebSocket — NOW BIDIRECTIONAL
            ↑ register / heartbeat / event / admission     ↓ command
        ┌────────┴───────────────────┐      ┌─────────────┴───────────────┐
        │     SimRobotHarness #1      │      │     SimRobotHarness #2       │   each = its own 快慢脑
        │  AdmissionGate  (fast/gate) │      │  AdmissionGate               │
        │  RobotFsm+watchdog (fast)   │      │  LocalPlanner    (slow)      │
        │  ThermalModel(real τ+inject)│      │  MotionBackend → LowCmd      │
        └────────┬────────────────────┘      └─────────────┬───────────────┘
              DDS domain 1                              DDS domain 2
        ┌────────┴────────────────────┐      ┌─────────────┴───────────────┐
        │    unitree_mujoco  G1 #1     │      │    unitree_mujoco  G1 #2     │   real physics · real LowState
        └─────────────────────────────┘      └─────────────────────────────┘
```

**Layer responsibilities (unchanged from doc §1):** Coordinator = strategy/semantics/explanation/audit; Robot harness = local admission + execution + final safety veto. The new code only adds the **downlink contract path** and the **deterministic dispatch logic** — it does not add a center→motor path.

## 4. Contracts (`fleet/contracts/models.py`)

Promote the reserved stubs to real typed models (pydantic v2, JSON-Schema-exported like the rest).

### 4.1 Telemetry additions (north-bound, extend `CoreState`)
- `Battery`: `soc: float` (0..1), `temperature_c: float`, `charging: bool`.
- `Health`: `level: Literal["ok","warning","fault"]`, `faults: list[str]`.
- `CoreState` gains `battery: Optional[Battery]`, `health: Health`.
- `extensions.g1_sim` gains `hottest_motor_c`, `hottest_motor_idx`, `mean_motor_c`.

Rationale: keep the core small (doc §8.4) but battery/health are first-class dispatch signals, so they are typed in core; per-joint detail stays in `extensions`.

### 4.2 Command path (down-bound)
- `Lease`: `lease_id`, `heartbeat_interval_s`, `ttl_s`, `on_expire: Literal["safe_pause","sleep"]`.
- `SafetyEnvelope`: `max_speed_mps`, `allowed_capabilities: list[str]`, `human_approval_id: Optional[str]`.
- `CommandEnvelope.v1`: `command_id`, `trace_id`, `issued_by`, `issued_to` (robot_id), `issued_at`, `expires_at`, `idempotency_key`, `capability: Literal["sleep","wake","patrol","idle","resume_task","stop"]`, `payload: dict`, `safety_envelope`, `lease: Optional[Lease]`. Carries `payload_hash` like `RobotEvent`.
- `AdmissionDecision.v1`: `command_id`, `robot_id`, `decision: Literal["accepted","refused","deferred"]`, `reason_code`, `reason_detail`, `ts`.

### 4.3 Task / mission / replan
- `TaskSpec.v1`: `task_id`, `mission_id`, `type: Literal["patrol","idle","charge"]`, `required_capabilities: list[str]`, `params: dict`, `success_criteria: list[str]`, `cancel_policy: dict`.
- `Mission.v1`: `mission_id`, `created_by`, `intent_text`, `priority`, `tasks: list[TaskSpec]`.
- `ReplanProposal.v1`: `trigger`, `evidence: list[dict]`, `actions: list[dict]`, `risk_level`, `requires_human_approval: bool`, `explanation: Optional[str]`. (LLM output type; deterministic engine fills `actions`, LLM may fill `explanation`.)

### 4.4 New event types (`EventType`)
`anomaly_detected`, `command_issued`, `command_accepted`, `command_refused`, `task_assigned`, `task_reassigned`, `robot_sleeping`, `robot_resumed`, `lease_expired`. Every coordinator decision and robot admission writes one — the existing append-only `EventLog` already supports replay by `trace_id`.

## 5. Bus — make it bidirectional (`fleet/bus/`)

- `FrameKind` gains `COMMAND` and `ADMISSION`; `messages.py` `_MODEL_FOR` maps them to `CommandEnvelope` / `AdmissionDecision`.
- `ws_server.py`: track live connections per `robot_id` in `app["fleet_conns"]`; on `REGISTER`, record `robot_id → ws`. Add `async send_command(robot_id, envelope)` used by the coordinator. Inbound `ADMISSION` frames → `app["admission_sink"]` (and event log). Telemetry-up path unchanged.
- `ws_client.py` (`FleetBusClient`): handle inbound `COMMAND` frames by invoking a registered `on_command` callback (the harness `AdmissionGate`), then send back an `ADMISSION` frame. Keep reconnect/backoff.
- `bus/base.py`: extend the abstract `FleetBus` with `send_command`/`on_command` seam so the in-process test bus and the WS bus share one interface.

## 6. SimRobotHarness — headless per-robot fast/slow brain (`fleet/agent/`)

A new `SimRobotHarness` that genuinely runs a G1 in MuJoCo **without** the heavy voice/vision/codex stack (so two can run side-by-side on WSL2). It is the per-robot 快慢脑 the coordinator talks to.

### 6.1 Fast brain
- Real `RobotFsm` with one **additive** state `DORMANT` (transitions `STANDING↔DORMANT`, `DORMANT→EMERGENCY_STOP/FAULT`). Additive only — existing transitions/tests stay valid; production `agent_main` is untouched.
- A **sleep-aware minimal watchdog**: while `DORMANT`, suspend the `rl_policy`/`pose` watchdogs (a deliberately quiescent robot must not trip EMERGENCY_STOP). Lowstate-staleness watchdog still active.
- **`AdmissionGate`** (`fleet/agent/admission_gate.py`): the local final authority. Validates every `CommandEnvelope`: not expired, idempotency not seen, capability in descriptor, capability allowed in current FSM state, safety envelope ok. Returns `AdmissionDecision`. **It can refuse** — refusal is a first-class outcome (doc §5.7).

### 6.2 Slow brain
- **`LocalPlanner`** (`fleet/agent/local_planner.py`): maps an admitted capability → a posture/skill plan for the `MotionBackend` (doc §18.3: slow brain interprets task, selects skill; fast brain executes). Deterministic. Optional `explain()` hook can call the LLM but is never on the control path.
- `sleep` → `SLEEP` posture + FSM `DORMANT`; `wake`/`resume_task` → `ACTIVE`/`PATROL` + FSM `STANDING`; `patrol` → periodic patrol motion; `idle` → quiet stand; `stop` → zero motion.

### 6.3 Thermal model
- **`ThermalModel`** (`fleet/agent/thermal_model.py`): per-joint temperature `T_i += k·τ_i²·dt − c·(T_i − T_amb)·dt`, battery temp from aggregate load + base, SOC drains with load + time. Reads **real `tau_est`** from LowState. `inject(temperature_c=…, soc=…, fault=…)` forces deterministic values for the demo/test. Feeds `HarnessCore.get_state()` battery/health/extensions.

### 6.4 Motion backends (pluggable — `fleet/agent/motion/`)
A `MotionBackend` protocol: `set_posture(Posture)`, `step()`, `read_lowstate()`, `close()`. Three implementations:
- `RLBalanceBackend` (target): wraps the existing `g1_sim_rl_combo.ComboController` (`init_dds/start/set_command(vx,vy,wz)/release_arms/stop_and_settle`). `ACTIVE/PATROL` = balance + small `wz`/`vx`/arm motion; `SLEEP` = `set_command(0,0,0)` + `release_arms` (damp) + `DORMANT`.
- `ElasticPDBackend` (fallback): elastic band holds the G1; harness sends LowCmd PD targets for distinct postures (stand / patrol-wave / crouch-damp). Most reliable on WSL2.
- `MockBackend` (CI): no DDS/MuJoCo; synthesizes LowState-like telemetry (configurable `tau_est`) and records posture transitions. Powers Tier-1.

Backend chosen by config/flag; the harness, admission gate, thermal model, planner, and bus path are identical across backends.

### 6.5 HarnessCore reuse
Extend the existing read-only `HarnessCore` facade to (a) include battery/health/thermal in `get_state()`, (b) expose `admit(envelope) → AdmissionDecision` (no longer `NotImplementedError`), routing through `AdmissionGate → LocalPlanner → MotionBackend`. The read-only paths (`get_capabilities`, `subscribe_events`, `snapshot_scene`) are preserved.

## 7. Coordinator dispatch brain (`fleet/coordinator/`)

All deterministic; each emits typed events to the `EventLog`.

- **`AnomalyDetector`** (`anomaly.py`): rules over `FleetRegistry` states — `battery.temperature_c ≥ T_hot` (default 70 °C), `extensions.g1_sim.hottest_motor_c ≥ M_hot`, `gravity_proj_z > −0.85` (fall), `status in {stale,offline}`, `battery.soc ≤ soc_min`. Emits typed `Anomaly` + `anomaly_detected` events. Debounced/hysteretic to avoid flapping.
- **`DispatchEngine`** (`dispatch.py`): owns missions/tasks + assignments. `assign(task)` picks the best **healthy, available, capable** robot. On an anomaly for robot R holding task T: issue `sleep` to R, mark R unavailable, **reassign T to the best healthy candidate**, issue `resume_task`/`patrol` to it. Emits `task_reassigned`. Pure function of state — the final scheduler (doc §20.3).
- **`LeaseManager`** (`lease.py`): tracks leases, heartbeat liveness, `on_expire → safe_pause` command.
- **`CommandGateway`** (`gateway.py`): wraps `bus.send_command`, assigns `command_id`/`idempotency_key`/`expires_at`, records `command_issued` + the returned `AdmissionDecision`. Single choke point for all down-bound commands.
- **`CoordinatorAgent`** (`agent_llm.py`, optional): `parse(nl) → StructuredOp | None` (e.g. "让机群去巡逻" → dispatch patrol to fleet; "让2号接替1号" → reassign) and `explain(decision, evidence) → str` grounded in real state snapshots. Backed by OpenAI (`OPENAI_API_KEY`); **degrades to a deterministic command grammar** (`dispatch|sleep|wake|takeover|status …`) when absent. Output is always re-validated by the deterministic engine before any command issues (doc §6.4).

Wire into `coordinator/app.py`: add a periodic detector tick + new HTTP routes `POST /missions`, `POST /commands` (sleep/wake/dispatch/inject), `GET /anomalies`, `GET /dispatch`.

## 8. Operator console (`fleet/console/cli.py`)

Extend the read-only console to a small operator surface:
- `status` — fleet table + anomalies + active leases + last decisions (existing read path + new fields).
- `dispatch <mission>` / `sleep <robot>` / `wake <robot>` / `takeover <from> <to>` / `inject <robot> --temp <c>` — POST to the coordinator.
- `explain <trace_id>` — show the decision chain + LLM explanation (or templated evidence) for a trace.
Pure formatting + HTTP calls; matches the existing CLI style. (A web UI is explicitly out of scope.)

## 9. Verification — two tiers (both delivered)

### Tier 1 — pure-Python, always-green (CI)  `tests/fleet/test_e2e_dispatch.py`
In-process bus + `MockBackend` harnesses + coordinator. Scenario asserts the full loop deterministically:
1. two robots register, both `ACTIVE`, patrol task assigned to R1;
2. `inject(R1, temp=75)` → detector emits `anomaly_detected`;
3. coordinator issues `sleep` → R1 `AdmissionDecision=accepted` → FSM `DORMANT`;
4. task reassigned → R2 receives `resume_task`/`patrol`, accepts, becomes `PATROL`;
5. human command "takeover"/"wake" path exercised;
6. assert via event-log replay: ordered `anomaly_detected → command_issued(sleep) → command_accepted → task_reassigned → command_issued(patrol) → command_accepted`, and final states (R1 DORMANT, R2 PATROL).

### Tier 2 — real MuJoCo, the actual ask  `fleet/sim/scenario_two_g1.py`
A scenario runner that launches **2 `unitree_mujoco` G1s (DDS domains 1 & 2)** + **2 `SimRobotHarness`** (RL backend, elastic-PD fallback) + **1 coordinator**, then runs:
- **Autonomous**: real telemetry flows; `inject` (or real-load) overheat on R1 → coordinator detects → R1 visibly damps to SLEEP → R2 visibly starts patrol motion; printed dispatch trace + event log.
- **Human-command**: operator console issues an NL/grammar command → fleet collaborates (both robots take roles).
Run during the verification step before delivery; capture console + event-log evidence. `config.py` gets `DOMAIN_ID = int(os.environ.get("UNITREE_DOMAIN_ID", DOMAIN_ID))` so two sims coexist.

## 10. Safety invariants (must hold; mapped to doc)

1. Coordinator emits only typed `CommandEnvelope`s — never `/lowcmd`, velocities, or torques (doc §3.1.1).
2. Every command has `expires_at` + `idempotency_key` + optional `lease` (doc §3.1.4).
3. The robot `AdmissionGate` can refuse any command; refusal is normal (doc §3.1.2).
4. Safety-critical actions (`sleep`, `stop`) are **deterministic** via gate→planner→backend, never LLM-decided; the LLM only explains (doc §6.4).
5. LLM output is re-validated by the deterministic engine before issue; unknown robot/task ⇒ rejected (doc §6.4).
6. Coordinator loss ⇒ lease `on_expire` drives the robot to `safe_pause`/`sleep` locally (doc §11.2).
7. `DORMANT` is additive; production `agent_main`/`RobotFsm` consumers keep working.

## 11. File-level change map

```
fleet/contracts/models.py        promote CommandEnvelope/AdmissionDecision/TaskSpec; add
                                 Mission/ReplanProposal/Lease/SafetyEnvelope/Battery/Health; new EventTypes
fleet/contracts/json_schema_export.py   export the new models
fleet/bus/messages.py            COMMAND/ADMISSION frame kinds
fleet/bus/base.py                send_command/on_command seam
fleet/bus/ws_server.py           per-robot conn registry + send_command + admission sink
fleet/bus/ws_client.py           inbound COMMAND → on_command → ADMISSION reply
safety/state_machine.py          + DORMANT state (additive)
fleet/agent/admission_gate.py    NEW — local final-authority gate
fleet/agent/local_planner.py     NEW — slow-brain capability→skill mapping
fleet/agent/thermal_model.py     NEW — τ-driven thermal/battery + inject()
fleet/agent/motion/base.py       NEW — MotionBackend protocol + Posture
fleet/agent/motion/rl_balance.py NEW — wraps g1_sim_rl_combo.ComboController
fleet/agent/motion/elastic_pd.py NEW — elastic-band + LowCmd PD postures
fleet/agent/motion/mock.py       NEW — CI backend
fleet/agent/robot_agent.py       wire command path (on_command → core.admit)
fleet/harness_core/core.py       battery/health in get_state; implement admit()
fleet/coordinator/anomaly.py     NEW — deterministic detector
fleet/coordinator/dispatch.py    NEW — task allocation + sleep/reassign
fleet/coordinator/lease.py       NEW — lease/heartbeat/expire
fleet/coordinator/gateway.py     NEW — command choke point + event log
fleet/coordinator/agent_llm.py   NEW — optional LLM parse/explain (degrades)
fleet/coordinator/app.py         detector tick + new routes
fleet/console/cli.py             operator commands
fleet/sim/scenario_two_g1.py     NEW — Tier-2 runner
unitree_mujoco/simulate_python/config.py   DOMAIN_ID from env (2-sim support)
tests/fleet/*                    unit tests per module + Tier-1 e2e
instructions.md                  §7 run guide (added at delivery)
```

## 12. Out of scope (YAGNI)

Free-walking floor navigation/localization; multi-vendor adapters (VDA5050/Open-RMF/ROS2); resource locks / traffic / MAPF; web UI; RBAC/ABAC, mTLS, SBOM; persistence beyond the existing SQLite event log; >2 robots (design stays N-robot-general but we verify 2). These map to later phases in `docs/coordinator-design.md`.

## 13. Risks & fallbacks

| Risk | Fallback |
|---|---|
| RL self-balance unreliable headless on WSL2 (two policies @50Hz) | `ElasticPDBackend` gives a reliable, visibly-distinct posture demo; Tier-1 mock proves the dispatch logic regardless. |
| `DORMANT` while RL-balancing = robot would fall if policy stops | SLEEP = zero-velocity + arm-damp while still balancing (quiescent but upright); elastic-PD does a true crouch-damp. |
| Two MuJoCo viewers heavy | run headless (`MUJOCO_GL=egl`/offscreen) with state assertions; viewer optional. |
| LLM/key absent or flaky | command-grammar + templated evidence; verification is LLM-independent. |

## 14. Test plan

Unit: contracts round-trip + JSON-Schema; bus COMMAND/ADMISSION encode/decode + per-robot routing; admission gate (accept/refuse/expired/idempotent); thermal model (load→temp, inject); local planner (capability→posture); anomaly detector (each rule + hysteresis); dispatch engine (assign, sleep+reassign, no-candidate); lease expiry; gateway idempotency; LLM parser degradation. Integration: Tier-1 e2e (above). System: Tier-2 MuJoCo runner. Gate to "done": full `pytest tests/fleet` green **and** a captured Tier-2 run showing the autonomous + human-command scenarios.
