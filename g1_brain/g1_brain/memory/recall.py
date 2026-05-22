"""Recall tools: grep / read / glob over the memory tree, sandboxed.

These are exposed as SkillServer tools. The fast brain (Realtime LLM) and
the slow brain (Codex daemon, via its own built-in tools) both use them
to dig into prior-session memory.

Sandbox: every path resolves under one of ALLOWED_ROOTS. Symlinks and
".." escapes are caught by `.resolve().relative_to(root)`.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from .schemas import (
    PathSandboxError,
    RECALL_STATUS_FILE_NOT_FOUND,
    RECALL_STATUS_FILE_TOO_LARGE,
    RECALL_STATUS_OK,
    RECALL_STATUS_PATH_OUTSIDE_SANDBOX,
    RECALL_STATUS_TOOL_UNAVAILABLE,
)

log = logging.getLogger(__name__)


class RecallSearcher:
    """Wraps rg / Path.read / Path.glob with sandboxed path resolution.

    The two allowed roots are:
      1. <robot>/memories/  — Phase 2 outputs + AGENTS.md
      2. <g1_brain_repo>/logs/conversations/  — raw JSONL transcripts

    A scope enum maps to a subset of these roots so the LLM cannot pass
    an arbitrary base.
    """

    def __init__(
        self,
        *,
        memories_dir: Path,
        conversations_dir: Path,
        rg_bin: str = "rg",
        default_max_lines: int = 50,
        read_max_bytes: int = 4096,
    ):
        self._memories_dir = memories_dir.expanduser().resolve()
        self._conversations_dir = conversations_dir.expanduser().resolve()
        self._rg_bin = rg_bin
        self._default_max_lines = default_max_lines
        self._read_max_bytes = read_max_bytes
        self._allowed_roots = (self._memories_dir, self._conversations_dir)

    # ---------- public tool methods ----------

    async def grep(
        self,
        *,
        pattern: str,
        scope: str = "registry",
        session_id: Optional[str] = None,
        max_lines: Optional[int] = None,
    ) -> dict:
        if max_lines is None:
            max_lines = self._default_max_lines
        max_lines = max(1, min(100, int(max_lines)))

        cwd, globs, jsonl_target = self._resolve_scope(scope, session_id)
        if cwd is None:
            return {
                "status": RECALL_STATUS_PATH_OUTSIDE_SANDBOX,
                "reason": f"scope={scope!r} requires session_id",
            }

        # Prefer rg; fall back to grep -rn; final fallback Python re
        if shutil.which(self._rg_bin):
            return await self._rg_search(
                cwd=cwd, pattern=pattern, globs=globs,
                jsonl_target=jsonl_target, max_lines=max_lines,
            )
        if shutil.which("grep"):
            return await self._grep_search(
                cwd=cwd, pattern=pattern, globs=globs,
                jsonl_target=jsonl_target, max_lines=max_lines,
            )
        return await self._python_search(
            cwd=cwd, pattern=pattern, globs=globs,
            jsonl_target=jsonl_target, max_lines=max_lines,
        )

    async def read(
        self,
        *,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> dict:
        try:
            resolved = self._resolve_safe_path(path)
        except PathSandboxError as e:
            return {
                "status": RECALL_STATUS_PATH_OUTSIDE_SANDBOX,
                "reason": str(e),
            }
        if not resolved.exists() or not resolved.is_file():
            return {"status": RECALL_STATUS_FILE_NOT_FOUND, "path": path}

        try:
            size = resolved.stat().st_size
        except OSError:
            return {"status": RECALL_STATUS_FILE_NOT_FOUND, "path": path}

        # Hard cap to avoid loading huge JSONL into memory
        hard_cap = max(self._read_max_bytes, 1 << 20)  # at least 1 MB sliding window
        if size > hard_cap and end_line is None:
            return {
                "status": RECALL_STATUS_FILE_TOO_LARGE,
                "size": size,
                "reason": (
                    f"file is {size} bytes; specify start_line/end_line, "
                    "or use recall_grep first to find the relevant span"
                ),
            }

        # Read line range
        start_line = max(1, int(start_line))
        try:
            lines: list[str] = []
            with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
                for idx, ln in enumerate(fh, start=1):
                    if idx < start_line:
                        continue
                    if end_line is not None and idx > int(end_line):
                        break
                    lines.append(ln.rstrip("\n"))
                    # Cap by bytes
                    if sum(len(s) + 1 for s in lines) > self._read_max_bytes:
                        lines.append("…[trimmed]")
                        break
        except OSError as e:
            return {"status": RECALL_STATUS_FILE_NOT_FOUND, "reason": str(e)}

        return {
            "status": RECALL_STATUS_OK,
            "path": str(resolved),
            "start_line": start_line,
            "lines": lines,
            "truncated": len(lines) > 0 and lines[-1] == "…[trimmed]",
        }

    async def glob(self, *, pattern: str, limit: int = 50) -> dict:
        limit = max(1, min(200, int(limit)))
        results: list[str] = []
        for root in self._allowed_roots:
            if not root.exists():
                continue
            try:
                # Path.glob does not allow "..".
                if pattern.startswith(("/", "..")):
                    continue
                for p in root.glob(pattern):
                    if not p.exists():
                        continue
                    try:
                        # Confirm inside root (defensive)
                        p.resolve().relative_to(root)
                    except ValueError:
                        continue
                    results.append(str(p.relative_to(root)))
                    if len(results) >= limit:
                        break
            except OSError as e:
                log.warning("recall_glob OSError under %s: %s", root, e)
                continue
            if len(results) >= limit:
                break
        return {"status": RECALL_STATUS_OK, "matches": results,
                "truncated": len(results) >= limit}

    # ---------- internal ----------

    def _resolve_scope(
        self, scope: str, session_id: Optional[str],
    ) -> tuple[Optional[Path], list[str], Optional[Path]]:
        """Returns (cwd, globs, jsonl_target).

        - registry: cwd=memories, globs=["MEMORY.md","raw_memories.md","AGENTS.md"]
        - rollouts: cwd=memories, globs=["rollout_summaries/*.md"]
        - jsonl:    cwd=conversations, globs=[<session_id>*.jsonl] if given
                    else ["*.jsonl"]
        - all:      cwd=memories, globs=["MEMORY.md","raw_memories.md",
                    "AGENTS.md","rollout_summaries/*.md"]
        """
        if scope == "registry":
            return (self._memories_dir,
                    ["MEMORY.md", "raw_memories.md", "AGENTS.md"],
                    None)
        if scope == "rollouts":
            return (self._memories_dir,
                    ["rollout_summaries/*.md"],
                    None)
        if scope == "jsonl":
            if session_id is None:
                return (self._conversations_dir, ["*.jsonl"], None)
            # Match files containing the session_id substring
            safe = re.sub(r"[^a-fA-F0-9]+", "", session_id)[:32]
            if not safe:
                return (self._conversations_dir, ["*.jsonl"], None)
            return (self._conversations_dir, [f"*{safe[:8]}*.jsonl"], None)
        if scope == "all":
            return (self._memories_dir,
                    ["MEMORY.md", "raw_memories.md", "AGENTS.md",
                     "rollout_summaries/*.md"],
                    None)
        # Unknown scope → treat as registry by default
        return (self._memories_dir,
                ["MEMORY.md", "raw_memories.md", "AGENTS.md"],
                None)

    def _resolve_safe_path(self, rel: str) -> Path:
        if not isinstance(rel, str) or not rel:
            raise PathSandboxError("empty path")
        if Path(rel).is_absolute():
            raise PathSandboxError(f"absolute path forbidden: {rel}")
        # The fast brain often re-uses paths it saw in recall_grep output or
        # in the tool description and prefixes them with the root name. The
        # roots ARE those directories, so accept and strip common prefixes
        # before the sandbox check. This keeps the model from getting stuck
        # in a "FILE_NOT_FOUND" loop on what is really the right file.
        candidates_rel = self._candidate_rel_paths(rel)

        # Two-pass: first try roots that ACTUALLY contain the file (after
        # symlink resolution). Only accept if the resolved real path stays
        # under the root. If the file exists in the join but resolves out,
        # raise sandbox (don't fall through to a different root where the
        # path doesn't exist).
        first_match: Optional[Path] = None
        for r in candidates_rel:
            for root in self._allowed_roots:
                joined = root / r
                if not joined.exists():
                    continue
                candidate = joined.resolve(strict=False)
                try:
                    candidate.relative_to(root.resolve())
                except ValueError:
                    # Symlink (or other) leaves the sandbox root
                    raise PathSandboxError(
                        f"path resolves outside sandbox: {rel} → {candidate}"
                    )
                first_match = candidate
                break
            if first_match is not None:
                break
        if first_match is not None:
            return first_match
        # Nothing existed — fall back to returning a path under the first
        # root for the not-found branch. Still sandbox-validate.
        for r in candidates_rel:
            for root in self._allowed_roots:
                candidate = (root / r).resolve(strict=False)
                try:
                    candidate.relative_to(root.resolve())
                except ValueError:
                    continue
                return candidate
        raise PathSandboxError(f"path not in allowed roots: {rel}")

    @staticmethod
    def _candidate_rel_paths(rel: str) -> list[str]:
        """Return rel with common root-name prefixes stripped.

        Caller may legitimately send e.g. 'logs/conversations/foo.jsonl' or
        'conversations/foo.jsonl' or 'memories/MEMORY.md' even though those
        directories ARE the sandbox roots. Try the literal path first, then
        each prefix-stripped variant.
        """
        out = [rel]
        # Normalise leading "./" once
        if rel.startswith("./"):
            out.append(rel[2:])
        prefixes = (
            "logs/conversations/",
            "conversations/",
            "memories/",
        )
        for p in prefixes:
            if rel.startswith(p):
                stripped = rel[len(p):]
                if stripped and stripped not in out:
                    out.append(stripped)
        return out

    async def _rg_search(
        self, *, cwd: Path, pattern: str, globs: list[str],
        jsonl_target: Optional[Path], max_lines: int,
    ) -> dict:
        # JSONL lines can be 0.5–5 kB each; a tight --max-columns turns every
        # match into "[Omitted long matching line]" which is useless to the
        # caller. Use a generous cap plus --max-columns-preview so truncated
        # lines still show their first ~2 kB (long enough to expose role +
        # text content of typical user/assistant/tool events).
        args = [
            self._rg_bin,
            "--line-number", "--color=never", "--no-heading",
            "--max-columns=2000",
            "--max-columns-preview",
            f"--max-count={max_lines}",
        ]
        for g in globs:
            args.append(f"-g={g}")
        args.append(pattern)
        args.append(".")

        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # 3 s was too tight for jsonl scope (single transcript can be 75 KB
        # and there can be 20+ of them). 8 s keeps the fast brain responsive
        # while letting most realistic queries finish.
        try:
            out, _err = await asyncio.wait_for(proc.communicate(), timeout=8.0)
        except asyncio.TimeoutError:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            return {"status": RECALL_STATUS_TOOL_UNAVAILABLE,
                    "reason": "rg timed out"}
        text = out.decode("utf-8", errors="replace")
        lines = text.splitlines()[:max_lines]
        return {
            "status": RECALL_STATUS_OK,
            "matches": lines,
            "truncated": len(text.splitlines()) > max_lines,
            "scope_cwd": str(cwd),
        }

    async def _grep_search(
        self, *, cwd: Path, pattern: str, globs: list[str],
        jsonl_target: Optional[Path], max_lines: int,
    ) -> dict:
        # Simpler fallback: grep -rn --include=GLOB PATTERN .
        args = ["grep", "-rn", "--color=never"]
        for g in globs:
            args.append(f"--include={g}")
        args.append(pattern)
        args.append(".")
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _err = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except (asyncio.TimeoutError, OSError, ProcessLookupError):
            return {"status": RECALL_STATUS_TOOL_UNAVAILABLE,
                    "reason": "grep unavailable or timed out"}
        lines = out.decode("utf-8", errors="replace").splitlines()[:max_lines]
        return {"status": RECALL_STATUS_OK, "matches": lines,
                "truncated": len(lines) >= max_lines,
                "scope_cwd": str(cwd)}

    async def _python_search(
        self, *, cwd: Path, pattern: str, globs: list[str],
        jsonl_target: Optional[Path], max_lines: int,
    ) -> dict:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return {"status": RECALL_STATUS_TOOL_UNAVAILABLE,
                    "reason": f"bad regex: {e}"}
        results: list[str] = []
        for g in globs:
            for f in cwd.glob(g):
                if not f.is_file():
                    continue
                try:
                    with open(f, "r", encoding="utf-8", errors="replace") as fh:
                        for idx, ln in enumerate(fh, start=1):
                            if regex.search(ln):
                                rel = f.relative_to(cwd)
                                results.append(
                                    f"{rel}:{idx}:{ln.rstrip()[:240]}"
                                )
                                if len(results) >= max_lines:
                                    break
                except OSError:
                    continue
                if len(results) >= max_lines:
                    break
            if len(results) >= max_lines:
                break
        return {"status": RECALL_STATUS_OK, "matches": results,
                "truncated": len(results) >= max_lines,
                "scope_cwd": str(cwd)}
