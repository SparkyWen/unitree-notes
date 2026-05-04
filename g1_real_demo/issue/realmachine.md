# Real-machine: "1/2/3 do nothing" on `g1_real_rl_combo.py eno3 lying`

Record of the diagnosis and fix for the symptom: running

```
python g1_real_rl_combo.py eno3 lying
```

against the real G1 produced no reaction when the user pressed `1`, `2`, or
`3` (the lying-mode arm wiggles).

---

## 1. Symptom

- User invoked `python g1_real_rl_combo.py eno3 lying` against the real
  robot on interface `eno3`.
- Pressing `1` / `2` / `3` produced no visible motion and no log line
  like `[combo] arm gesture '1' = ...`.
- The script appeared "alive" but unresponsive.

## 2. Diagnosis

Two distinct things were wrong; either alone reproduces the symptom.

### 2.1 Script was hung in `start()` waiting for the first `rt/lowstate`

`g1_real_rl_combo.py` (pre-fix) had:

```python
def start(self):
    print("[combo] waiting for first /rt/lowstate ...")
    while not self.first_state_received:
        time.sleep(0.05)
    ...
```

This is an unbounded busy-wait. The keyboard reader (`RawKeyReader`) is only
opened **after** `start()` returns, in `main()`:

```python
ctl.start()
...
with RawKeyReader() as kb:
    while True:
        ch = kb.get(0.1)
        ...
```

So if no `rt/lowstate` ever lands on the bus, the script hangs at the
busy-wait, the keyboard reader never opens, and keypresses fall through to
the terminal as ordinary stdin. From the user's perspective: "I press 1
and nothing happens."

### 2.2 The robot's high-level controller owns `rt/lowcmd`

On the real G1, when the robot powers up the onboard "MotionSwitcher"
service starts a high-level controller — typically mode `ai` (or
`normal` / `advanced`). That controller continuously writes its own
balance/idle commands to `rt/lowcmd` at the same rate (or faster) than we
do. Even if `rt/lowstate` is flowing fine, our motor commands are
overwritten by the high-level loop before the motors execute them.

This is the canonical reason the SDK's own
`unitree_sdk2_python/example/g1/low_level/g1_low_level_example.py`
calls `MotionSwitcherClient.CheckMode()` + `ReleaseMode()` before
publishing any `rt/lowcmd`:

```python
self.msc = MotionSwitcherClient()
self.msc.SetTimeout(5.0)
self.msc.Init()

status, result = self.msc.CheckMode()
while result['name']:
    self.msc.ReleaseMode()
    status, result = self.msc.CheckMode()
    time.sleep(1)
```

Our `g1_real_rl_combo.py` skipped this step entirely, so even if (2.1) had
been benign, `rt/lowcmd` writes would have been silently overwritten.

## 3. Fix

All changes are in `g1_real_demo/g1_real_rl_combo.py`.

### 3.1 Import `MotionSwitcherClient`

Added near the other unitree_sdk2py imports:

```python
from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import (
    MotionSwitcherClient,
)
```

### 3.2 Track real-robot vs simulator mode in the controller

`ComboController.__init__` now takes a `real_robot: bool` flag and stashes
a slot for the MotionSwitcher RPC client:

```python
def __init__(self, cfg, policy, lying_mode=False, real_robot=False):
    ...
    self.real_robot = real_robot
    self._msc: Optional[MotionSwitcherClient] = None
```

A class constant was also added:

```python
LOWSTATE_WAIT_TIMEOUT = 5.0   # seconds
```

### 3.3 Release the high-level mode in `init_dds()` (real-robot only)

`init_dds()` now releases the MotionSwitcher mode **before** opening our
own `rt/lowcmd` publisher, so there's never a window where two writers
fight on the bus. Sim path is unchanged because the simulate_python
bridge has no MotionSwitcher RPC.

```python
def init_dds(self):
    if self.real_robot:
        self._release_high_level_mode()
    self.cmd_pub = ChannelPublisher("rt/lowcmd", LowCmd_)
    self.cmd_pub.Init()
    self.state_sub = ChannelSubscriber("rt/lowstate", LowState_)
    self.state_sub.Init(self._on_state, 10)
```

The new `_release_high_level_mode()`:

- Constructs `MotionSwitcherClient`, sets timeout to 5s, calls `Init()`.
- Calls `CheckMode()`. If `result['name']` is empty, prints "no
  high-level mode active. OK." and returns.
- Otherwise prints `releasing high-level mode '<name>' ...` and loops
  `ReleaseMode()` + `CheckMode()` with 0.5s gaps until `name` is empty
  or an 8-second deadline expires.
- Every step is wrapped in try/except: failures are logged as `WARN`
  but don't abort the script. Older firmware without MotionSwitcher
  produces a warning instructing the user to release the high-level
  mode manually (L2+R2 / damping on the remote).

### 3.4 Bound the `start()` wait for `rt/lowstate`

The infinite busy-wait was replaced with a deadline:

```python
def start(self):
    print(
        f"[combo] waiting for first /rt/lowstate "
        f"(timeout {self.LOWSTATE_WAIT_TIMEOUT:.1f}s) ..."
    )
    deadline = time.monotonic() + self.LOWSTATE_WAIT_TIMEOUT
    while not self.first_state_received:
        if time.monotonic() > deadline:
            raise RuntimeError(
                "no rt/lowstate received within "
                f"{self.LOWSTATE_WAIT_TIMEOUT:.1f}s. Common causes:\n"
                "  * wrong network interface (check `ip -br addr`)\n"
                "  * wrong DDS domain (real robot=0, sim=1)\n"
                "  * robot still in high-level mode and not publishing\n"
                "    lowstate to subscribers (try power-cycle)\n"
                "  * robot powered off / Ethernet link down\n"
                "  * firewall / multicast blocked on this interface"
            )
        time.sleep(0.05)
    ...
```

This converts the silent hang into an actionable error.

### 3.5 Plumb `real_robot` through `main()`

`main()` derives the flag from argv, announces the release plan on real
hardware, and passes the flag to the controller:

```python
real_robot = bool(pos_args) and pos_args[0] not in ("lo", "sim")
if real_robot:
    ChannelFactoryInitialize(0, pos_args[0])
    ...
    print(
        "[combo] will release any active high-level mode "
        "(ai/normal/advanced) before taking low-level control."
    )
else:
    ChannelFactoryInitialize(1, "lo")
    ...
```

```python
ctl = ComboController(cfg, policy, lying_mode=lying_mode, real_robot=real_robot)
ctl.init_dds()
try:
    ctl.start()
except RuntimeError as e:
    print(f"[combo] startup aborted: {e}")
    return
```

The `try/except` keeps the failure mode clean: the user gets the error
message above instead of a stack trace from a daemon thread.

## 4. Verification

- `python3 -m py_compile g1_real_demo/g1_real_rl_combo.py` — passes.
- Re-read of every edited region matches intent.

Expected new console output on `python3 g1_real_rl_combo.py eno3 lying`:

```
[combo] LYING TEST MODE on eno3 (domain 0).
[combo] No policy, no boot ramp. Robot holds measured pose.
[combo] will release any active high-level mode (ai/normal/advanced) before taking low-level control.
[combo] loaded deploy.yaml (...)
[combo] loaded policy: .../policy.onnx
[combo] MotionSwitcher: releasing high-level mode 'ai' ...
[combo] MotionSwitcher: high-level mode released.
[combo] waiting for first /rt/lowstate (timeout 5.0s) ...
[combo] LYING-DOWN TEST MODE. Holding measured pose at kp_scale=0.20. No policy, no boot ramp.

==== G1 RL walk + arm gesture combo ====
LYING-DOWN TEST MODE — robot stays at measured pose.
...
  1        wiggle right shoulder pitch +0.15
  2        wiggle left shoulder pitch +0.15
  3        wiggle right elbow +0.20
  ...
```

Pressing `1` should now log `[combo] arm gesture '1' = wiggle right
shoulder pitch +0.15` and produce visible motion at the right shoulder.

## 5. Caveats

- Releasing the high-level mode means the robot is now under our PD
  targets only. Keep the e-stop in reach the first time.
- If the firmware predates MotionSwitcher, you'll get a `WARN` line and
  the script continues. Put the robot in `damping` mode manually
  (L2+R2 on the remote) and re-run.
- The lying-mode lowcmd publishes the snapshot pose at
  `LYING_KP_SCALE = 0.2`. If the robot is on its side and you see
  drift, that's the low gain holding pose, not a controller bug.
- The fix only touches the real-robot path. Simulator behavior
  (`python g1_real_rl_combo.py` with no args, or with `lo`/`sim`)
  is unchanged.

## 6. File reference

- Edited: `g1_real_demo/g1_real_rl_combo.py`
  - new import block (~line 144)
  - new class constant `LOWSTATE_WAIT_TIMEOUT` and `__init__` signature
    (~line 582)
  - new `init_dds` body and new `_release_high_level_mode` method
    (~line 658)
  - bounded wait in `start()` (~line 813)
  - `real_robot` flag and try/except in `main()` (~line 1186)
- Reference for the canonical release pattern:
  `unitree_sdk2_python/example/g1/low_level/g1_low_level_example.py`
  lines 90-98.
