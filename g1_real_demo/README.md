# g1_real_demo

Real-hardware deployment scripts for the Unitree G1, paired with the mujoco
demos in [`../g1_sim_demo/`](../g1_sim_demo/). The two trees share the same
RL policy and gesture set; this one targets the physical robot, the sibling
targets `unitree_mujoco`.

## What's here

| File | Purpose |
|---|---|
| `g1_real_rl_combo.py` | Single-process controller: ONNX velocity policy on legs/waist + keyboard arm gestures, with real-robot startup hardening (`MotionSwitcher` release, bounded lowstate wait, `lying` test mode). |
| `docs/demo-QA7.md` | Walks through the `lying` mode used to verify wiring/DDS without standing the robot up. |
| `issue/realmachine.md` | Diagnosis log for the "press 1/2/3 and the robot does nothing" symptom — root cause was the onboard high-level controller still owning `rt/lowcmd`. |

## Real vs. sim — what's different

The real-robot script differs from `../g1_sim_demo/g1_sim_rl_combo.py` in:

1. **MotionSwitcher release on init.** The G1's onboard `ai`/`normal`/
   `advanced` controller owns `rt/lowcmd` until released — without this,
   our commands silently lose to the high-level writer.
2. **Bounded `lowstate` wait.** Times out with an actionable checklist
   (wrong interface, wrong DDS domain, robot in high-level mode, link
   down, multicast blocked) instead of busy-waiting forever.
3. **`lying` CLI mode.** Skip boot ramp and policy entirely; hold the
   measured pose at low Kp and let keys 1..7 trigger small per-joint arm
   wiggles. Use when the robot can't stand (cable too short, etc.) and
   you only want to confirm motors respond.
4. **CycloneDDS tracing override.** Silences DDS tracing noise on real
   hardware.

The mujoco simulator does not implement `MotionSwitcher`, so the real
script auto-detects sim mode (no `<iface>` arg, or `lo`/`sim`) and skips
the release call.

## Quick start

```bash
conda activate unitree

# real robot — find the interface on the G1's 192.168.123.0/24 subnet
ip -br addr | grep 192.168.123
python g1_real_rl_combo.py <iface>           # e.g. eno3
# walking + arm gestures, after MotionSwitcher release

# real robot, can't stand — wiring/DDS check only
python g1_real_rl_combo.py <iface> lying     # e.g. eno3 lying

# simulator (mujoco) — same script
cd ../unitree_mujoco/simulate_python && python unitree_mujoco.py   # term 1
python g1_real_rl_combo.py                                          # term 2
```

Always keep the e-stop within reach when running on the real robot.
