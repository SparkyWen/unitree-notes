"""One-command verification of the full DDS fleet path (no GUI needed).

Launches, as separate processes (the real GUI topology minus the viewer):
  coordinator  +  2 headless unitree_mujoco sims (domains 1/2)  +  2 robot nodes

g1_a holds a patrol task and self-injects a battery overheat; the coordinator
perceives it from real DDS telemetry, safely sleeps g1_a, and reassigns the task
to g1_b. Prints PASS/FAIL and exits non-zero on failure.

  conda run -n agi python -m g1_brain.fleet.sim.verify_dds_fleet
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_PY = sys.executable
_WS = Path(__file__).resolve().parents[4]
_G1B = _WS / "g1_brain"
_LOG = _G1B / "logs" / "fleet" / "dds"


def _get(url: str):
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.load(r)


def _post(url: str, body: dict):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.load(r)


def _primary_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        s.close()


def run(*, port: int = 8090, inject_after: float = 8.0, poll_s: float = 25.0,
        keep_alive: bool = False) -> bool:
    _LOG.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "FLEET_FALL_GZ": "2.0"}  # suspended rig tilts; not a fall
    base = f"http://127.0.0.1:{port}"
    procs = []

    def spawn(mod_args, name):
        fh = open(_LOG / f"{name}.log", "w")
        p = subprocess.Popen([_PY, "-m", *mod_args], cwd=str(_G1B), env=env,
                             stdout=fh, stderr=subprocess.STDOUT)
        procs.append((p, fh))
        return p

    try:
        print("[verify] launching coordinator + 2 headless G1 sims (domains 1/2)...", flush=True)
        spawn(["g1_brain.fleet.coordinator", "--port", str(port),
               "--db", "logs/fleet/dds/c.sqlite"], "coord")
        spawn(["g1_brain.fleet.sim.headless_sim", "--domain", "1"], "sim1")
        spawn(["g1_brain.fleet.sim.headless_sim", "--domain", "2"], "sim2")
        time.sleep(4)

        a_inject = 0.0 if keep_alive else inject_after  # in keep-alive the operator drives it
        print(f"[verify] bringing up robot node g1_a (domain 1, "
              f"{'no auto-inject' if keep_alive else 'self-overheat scheduled'})...", flush=True)
        spawn(["g1_brain.fleet.sim.robot_node", "--robot-id", "g1_a", "--domain", "1",
               "--coordinator", f"ws://127.0.0.1:{port}/fleet",
               "--inject-overheat-after", str(a_inject)], "node_a")
        time.sleep(3)
        print("[verify] dispatch patrol -> g1_a (sole candidate)", flush=True)
        _post(f"{base}/commands", {"op": "dispatch", "args": {"task": "patrol"}})
        time.sleep(1)
        print("[verify] bringing up robot node g1_b (domain 2)...", flush=True)
        spawn(["g1_brain.fleet.sim.robot_node", "--robot-id", "g1_b", "--domain", "2",
               "--coordinator", f"ws://127.0.0.1:{port}/fleet"], "node_b")
        time.sleep(2)

        holder = _get(f"{base}/dispatch")["assignments"].get("task-patrol")

        if keep_alive:
            ip = _primary_ip()
            bar = "=" * 64
            print(f"\n{bar}\n  LIVE: 2 G1s + coordinator running. Open the dashboard:\n", flush=True)
            print(f"    http://localhost:{port}", flush=True)
            print(f"    http://127.0.0.1:{port}", flush=True)
            if ip not in ("127.0.0.1",):
                print(f"    http://{ip}:{port}   <-- use this from Windows if localhost fails", flush=True)
            print(f"\n  patrol holder = {holder}. Drive it from the dashboard buttons "
                  f"(inject/sleep/wake/dispatch).\n  Ctrl-C to stop.\n{bar}\n", flush=True)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("[verify] stopping...", flush=True)
            return True

        print(f"[verify] patrol holder = {holder}; waiting for autonomous overheat dispatch...", flush=True)
        ok = False
        deadline = time.time() + poll_s
        while time.time() < deadline:
            time.sleep(1)
            disp = _get(f"{base}/dispatch")
            robots = {r["robot_id"]: r["state"] for r in _get(f"{base}/robots")}
            a = robots.get("g1_a", {})
            b = robots.get("g1_b", {})
            reassigned = disp["assignments"].get("task-patrol")
            if (a.get("fsm_state") == "DORMANT" and reassigned == "g1_b"
                    and (b.get("extensions", {}).get("g1_sim", {}).get("posture") == "PATROL")):
                ok = True
                break

        robots = {r["robot_id"]: r["state"] for r in _get(f"{base}/robots")}
        events = sorted({e["type"] for e in _get(f"{base}/events?limit=5000")})
        print("\n=== FINAL (real DDS telemetry) ===", flush=True)
        for rid, st in robots.items():
            ext = st.get("extensions", {}).get("g1_sim", {})
            batt = st.get("core", {}).get("battery", {})
            print(f"  {rid}: fsm={st['fsm_state']:<9} posture={ext.get('posture'):<7} "
                  f"batt={batt.get('temperature_c')}C gz={st['core']['safety_state']['gravity_proj_z']:.2f}",
                  flush=True)
        print(f"  assignments={_get(base + '/dispatch')['assignments']}", flush=True)
        print(f"  event types={events}", flush=True)

        need = {"anomaly_detected", "command_issued", "command_accepted",
                "task_reassigned", "robot_sleeping"}
        print("\n=== VERIFICATION ===", flush=True)
        checks = [
            (robots.get("g1_a", {}).get("fsm_state") == "DORMANT", "g1_a slept (DORMANT) on overheat"),
            (_get(f"{base}/dispatch")["assignments"].get("task-patrol") == "g1_b",
             "patrol reassigned to g1_b"),
            (robots.get("g1_b", {}).get("extensions", {}).get("g1_sim", {}).get("posture") == "PATROL",
             "g1_b patrolling"),
            (need <= set(events), f"event audit trail present ({sorted(need)})"),
            (robots.get("g1_b", {}).get("core", {}).get("safety_state", {}).get("gravity_proj_z", 0) < -0.5,
             "g1_b still upright in MuJoCo"),
        ]
        allok = True
        for cond, label in checks:
            print(f"  [{'PASS' if cond else 'FAIL'}] {label}", flush=True)
            allok = allok and cond
        print("=== {} ===".format("ALL CHECKS PASSED" if allok else "SOME CHECKS FAILED"), flush=True)
        return allok and ok
    finally:
        for p, _ in procs:
            p.terminate()
        time.sleep(1)
        for p, fh in procs:
            p.kill()
            fh.close()


def main() -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--inject-after", type=float, default=8.0)
    ap.add_argument("--keep-alive", action="store_true",
                    help="launch coordinator+2 G1s and stay up for the browser dashboard")
    args = ap.parse_args()
    return 0 if run(port=args.port, inject_after=args.inject_after,
                    keep_alive=args.keep_alive) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
