"""reset_memory — operator CLI for memory subsystem recovery.

Usage:
    python -m g1_brain.tools.reset_memory --rebuild-state
    python -m g1_brain.tools.reset_memory --rebuild-git
    python -m g1_brain.tools.reset_memory --reset-md
    python -m g1_brain.tools.reset_memory --nuke --confirm --confirm

Multiple ops can be combined (e.g. --rebuild-state --reset-md).
--nuke requires --confirm passed twice to avoid accidents.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _default_root() -> Path:
    return Path("~/.unitree/g1_brain").expanduser()


def cmd_rebuild_state(root: Path) -> int:
    db = root / "state.sqlite"
    if not db.exists():
        print(f"[reset] state.sqlite not present at {db}; nothing to do")
        return 0
    backup = db.with_name(
        f"state.sqlite.broken.{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    )
    try:
        db.replace(backup)
        print(f"[reset] backed up state.sqlite → {backup}")
    except OSError as e:
        print(f"[reset] cannot backup state.sqlite: {e}", file=sys.stderr)
        return 2
    # Recreate schema by spinning up StorageLayer briefly
    from g1_brain.memory.storage import StorageLayer
    try:
        s = StorageLayer(root)
        s.init()
        s.close()
        print("[reset] state.sqlite rebuilt with schema_version=1")
    except Exception as e:  # noqa: BLE001
        print(f"[reset] state.sqlite rebuild failed: {e}", file=sys.stderr)
        return 2
    return 0


def cmd_rebuild_git(root: Path) -> int:
    mem = root / "memories"
    git = mem / ".git"
    if git.exists():
        try:
            shutil.rmtree(git)
            print(f"[reset] removed {git}")
        except OSError as e:
            print(f"[reset] cannot remove {git}: {e}", file=sys.stderr)
            return 2
    if not mem.exists():
        mem.mkdir(parents=True)
    try:
        subprocess.run(["git", "init", "-q"], cwd=mem, check=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "memory@g1-brain.local"],
                       cwd=mem, check=True, timeout=5)
        subprocess.run(["git", "config", "user.name", "G1 Brain Memory"],
                       cwd=mem, check=True, timeout=5)
        gi = mem / ".gitignore"
        if not gi.exists():
            gi.write_text("*.tmp.*\nphase2_workspace_diff.md\n")
        subprocess.run(["git", "add", "-A"], cwd=mem, check=True, timeout=10)
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m",
                        "reset: rebuild baseline"],
                       cwd=mem, check=True, timeout=15)
        print(f"[reset] git baseline reinitialized at {mem}")
    except subprocess.SubprocessError as e:
        print(f"[reset] git baseline init failed: {e}", file=sys.stderr)
        return 2
    return 0


def cmd_reset_md(root: Path) -> int:
    mem = root / "memories"
    targets = [
        mem / "MEMORY.md",
        mem / "memory_summary.md",
        mem / "raw_memories.md",
        mem / "rollout_summaries",
    ]
    removed: list[str] = []
    for t in targets:
        if t.is_file():
            try:
                t.unlink()
                removed.append(str(t))
            except OSError as e:
                print(f"[reset] cannot remove {t}: {e}", file=sys.stderr)
        elif t.is_dir():
            try:
                shutil.rmtree(t)
                removed.append(str(t))
            except OSError as e:
                print(f"[reset] cannot remove {t}: {e}", file=sys.stderr)
    print(f"[reset] removed: {removed or '(nothing)'}")
    # Re-init storage to recreate MEMORY.md marker + rollout_summaries/ dir
    from g1_brain.memory.storage import StorageLayer
    try:
        s = StorageLayer(root)
        s.init()
        s.close()
        print("[reset] re-initialized storage; MEMORY.md marker rewritten")
    except Exception as e:  # noqa: BLE001
        print(f"[reset] storage re-init failed: {e}", file=sys.stderr)
        return 2
    return 0


def cmd_nuke(root: Path) -> int:
    if not root.exists():
        print(f"[reset] {root} does not exist; nothing to nuke")
        return 0
    try:
        shutil.rmtree(root)
        print(f"[reset] removed entire {root}")
    except OSError as e:
        print(f"[reset] cannot remove {root}: {e}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reset G1 memory subsystem state.",
    )
    parser.add_argument(
        "--root", type=Path, default=None,
        help="Memory root (default: ~/.unitree/g1_brain).",
    )
    parser.add_argument(
        "--rebuild-state", action="store_true",
        help="Backup + recreate state.sqlite with current schema. "
             "All stage1_outputs and job state are lost.",
    )
    parser.add_argument(
        "--rebuild-git", action="store_true",
        help="Remove memories/.git and re-init baseline. "
             "Phase2 will treat everything as new diff next run.",
    )
    parser.add_argument(
        "--reset-md", action="store_true",
        help="Delete MEMORY.md / memory_summary.md / raw_memories.md / "
             "rollout_summaries/. Stage1 outputs in DB are preserved, "
             "so Phase2 rebuilds them on next run.",
    )
    parser.add_argument(
        "--nuke", action="store_true",
        help="Delete the entire root directory. DANGEROUS. Requires "
             "--confirm passed TWICE.",
    )
    parser.add_argument(
        "--confirm", action="count", default=0,
        help="Required for --nuke. Pass twice.",
    )
    args = parser.parse_args(argv)

    root = (args.root.expanduser() if args.root else _default_root()).resolve()

    if not any([args.rebuild_state, args.rebuild_git, args.reset_md, args.nuke]):
        parser.error("no action specified; use --help to see options")

    if args.nuke and args.confirm < 2:
        parser.error("--nuke requires --confirm passed twice "
                     "(e.g. --confirm --confirm)")

    print(f"[reset] target: {root}")
    rc = 0
    if args.rebuild_state:
        rc |= cmd_rebuild_state(root)
    if args.rebuild_git:
        rc |= cmd_rebuild_git(root)
    if args.reset_md:
        rc |= cmd_reset_md(root)
    if args.nuke:
        rc |= cmd_nuke(root)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
