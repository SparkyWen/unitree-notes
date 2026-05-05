"""End-to-end test of the EstopClient flag mechanism.

Doesn't need DDS or any other subsystem. Verifies:
  - engage() flips is_engaged() -> True
  - the reason string round-trips through the file
  - release() flips it back to False
  - timing for engage / poll / release on this filesystem

Useful as a smoke test after install ("does the file path I configured even
work on this OS?") and as a bake-off if you ever swap to e.g. POSIX shared
memory.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path


log = logging.getLogger("g1_brain.estop_test")


def main() -> int:
    p = argparse.ArgumentParser(description="g1_brain E-stop client end-to-end test")
    p.add_argument("--flag-path", type=str, default=None,
                   help="override flag path (default: read from config or /tmp)")
    p.add_argument("--poll-iters", type=int, default=20,
                   help="how many is_engaged() polls to time after engage")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from ..safety.estop_client import EstopClient

    flag_path = args.flag_path
    if flag_path is None:
        flag_path = os.environ.get("G1_BRAIN_ESTOP_FLAG", "/tmp/g1_brain_estop_test")
    p_flag = Path(flag_path)

    client = EstopClient(p_flag)

    print(f"flag path: {p_flag}")
    print(f"initial is_engaged: {client.is_engaged()}")

    # Make sure we start clean.
    client.release()
    if client.is_engaged():
        print("ERROR: release() did not clear is_engaged()", file=sys.stderr)
        return 2

    # Engage
    t0 = time.perf_counter()
    client.engage("test")
    t1 = time.perf_counter()
    print(f"engage(): {(t1 - t0) * 1000:.2f} ms")
    if not client.is_engaged():
        print("ERROR: engage() did not flip is_engaged() to True", file=sys.stderr)
        return 3
    reason = client.reason()
    print(f"reason: {reason!r}")
    if not reason or "test" not in reason:
        print("WARN: reason did not round-trip 'test'", file=sys.stderr)

    # Poll loop timing
    t0 = time.perf_counter()
    for _ in range(args.poll_iters):
        client.is_engaged()
    t1 = time.perf_counter()
    per_poll_ms = (t1 - t0) * 1000 / max(args.poll_iters, 1)
    print(f"is_engaged poll: {per_poll_ms:.3f} ms / call (n={args.poll_iters})")

    # Release
    t0 = time.perf_counter()
    client.release()
    t1 = time.perf_counter()
    print(f"release(): {(t1 - t0) * 1000:.2f} ms")
    if client.is_engaged():
        print("ERROR: release() did not flip is_engaged() to False", file=sys.stderr)
        return 4

    # Re-release should be a no-op.
    client.release()
    print("re-release() ok (no error)")

    print("\nestop_test: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
