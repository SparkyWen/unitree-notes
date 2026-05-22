"""Persistent Codex MCP daemon for ask_slow_brain.

Spawns `codex mcp-server` as a long-lived subprocess. Speaks JSON-RPC 2.0
over its stdio. Provides ask_slow_brain(query) → AskResult with timeout,
cancel-event, and queue cap.

Failure isolation:
  - Daemon crashes never raise to callers. They return AskResult with a
    status field describing what happened.
  - In-flight asks return partial text on timeout/cancel/crash.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

from .schemas import AskResult

log = logging.getLogger(__name__)


# Daemon state machine values
STATE_INIT = "init"
STATE_STARTING = "starting"
STATE_READY = "ready"
STATE_CRASHED = "crashed"
STATE_DEAD = "dead"
STATE_STOPPED = "stopped"

# Recognized quota / rate-limit strings
_QUOTA_PATTERNS = ("rate_limit", "quota_exceeded", "rate limit")


def _looks_like_quota(s: str) -> bool:
    low = s.lower()
    return any(p in low for p in _QUOTA_PATTERNS)


class CodexDaemon:
    """Persistent codex mcp-server subprocess + thin MCP client."""

    def __init__(
        self,
        *,
        codex_bin: str = "codex",
        workdir: Path,
        codex_home: Optional[Path] = None,
        sandbox: str = "read-only",
        model_override: Optional[str] = None,
        ping_interval_s: float = 30.0,
        max_restart_attempts: int = 5,
        ask_queue_max: int = 2,
        stdout_buffer_bytes: int = 16 * 1024 * 1024,
        reasoning_effort: str = "high",
        reasoning_summary: str = "concise",
        service_tier: str = "fast",
        conversations_dir: Optional[Path] = None,
    ):
        self._bin = codex_bin
        self._workdir = workdir.expanduser().resolve()
        self._codex_home = codex_home.expanduser().resolve() if codex_home else None
        self._sandbox = sandbox
        self._model_override = model_override
        self._ping_interval_s = ping_interval_s
        self._max_restart_attempts = max_restart_attempts
        self._ask_queue_max = ask_queue_max
        self._stdout_buffer_bytes = max(int(stdout_buffer_bytes), 1 << 20)
        self._reasoning_effort = (reasoning_effort or "").strip()
        self._reasoning_summary = (reasoning_summary or "").strip()
        self._service_tier = (service_tier or "").strip()
        self._conversations_dir = (
            conversations_dir.expanduser().resolve()
            if conversations_dir else None
        )

        self._state = STATE_INIT
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._stdin: Optional[asyncio.StreamWriter] = None
        self._stdout: Optional[asyncio.StreamReader] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._send_lock = asyncio.Lock()
        self._ask_mutex = asyncio.Lock()
        self._in_flight = 0
        self._stderr_tail: List[bytes] = []
        self._quota_until_ms: int = 0    # epoch ms before which we return quota_exhausted
        self._tool_name: Optional[str] = None  # codex tool name learned via tools/list

        # JSON-RPC: id → Future for response; plus a separate map for
        # progress accumulators keyed by request id (we treat tools/call as
        # the single in-flight op so only one is active at a time anyway).
        self._next_id = 1
        self._pending: Dict[int, asyncio.Future] = {}
        self._partial_text_parts: Dict[int, List[str]] = {}
        # Set on stop() so a retry-loop sleep wakes immediately instead of
        # blocking shutdown for up to 5 minutes. Lazily allocated inside
        # start() so __init__ doesn't require a running event loop.
        self._stop_event: Optional[asyncio.Event] = None
        # Tracks the in-flight start() task so stop() can cancel it cleanly,
        # avoiding "Task was destroyed but it is pending!" on Ctrl+C.
        self._start_task: Optional[asyncio.Task] = None

    # ---------- public API ----------

    @property
    def state(self) -> str:
        return self._state

    def is_available(self) -> bool:
        return shutil.which(self._bin) is not None

    async def start(self) -> None:
        """Spawn subprocess, MCP initialize, list tools, mark READY.

        Idempotent: if already running, no-op. Also bails out if a stop()
        has already moved us to STOPPED while a queued restart task was
        about to run.
        """
        if self._state == STATE_READY or self._state == STATE_STOPPED:
            return
        if not self.is_available():
            log.warning("codex binary not found: %s", self._bin)
            self._state = STATE_DEAD
            return

        # Lazily allocate the stop-event on the running loop. Track the
        # current task so stop() can cancel it.
        if self._stop_event is None:
            self._stop_event = asyncio.Event()
        try:
            self._start_task = asyncio.current_task()
        except RuntimeError:
            self._start_task = None

        self._state = STATE_STARTING
        attempt = 0
        delays = (1, 5, 30, 60, 300)
        try:
            while True:
                if self._state == STATE_STOPPED:
                    return
                try:
                    await self._spawn_and_initialize()
                    self._state = STATE_READY
                    self._ping_task = asyncio.create_task(self._ping_loop())
                    log.info("codex daemon ready (tool=%s)", self._tool_name)
                    return
                except Exception as e:
                    attempt += 1
                    stderr_tail = b"".join(self._stderr_tail).decode(
                        "utf-8", errors="replace",
                    )[-512:]
                    rc = self._proc.returncode if self._proc is not None else None
                    log.warning(
                        "codex daemon start attempt %d failed: %r (rc=%s) stderr=%s",
                        attempt, e, rc, stderr_tail or "<empty>",
                    )
                    await self._cleanup_proc()
                    if attempt >= self._max_restart_attempts:
                        self._state = STATE_DEAD
                        log.error("codex daemon dead after %d attempts", attempt)
                        return
                    if self._state == STATE_STOPPED:
                        return
                    # Race the back-off sleep against the stop event so
                    # memory.stop() doesn't have to wait up to 300s for the
                    # next sleep to expire. wait_for raises TimeoutError when
                    # the delay elapses without a stop signal — that's the
                    # normal retry path.
                    delay = delays[min(attempt - 1, len(delays) - 1)]
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(), timeout=delay,
                        )
                        # stop_event fired during sleep → bail out.
                        return
                    except asyncio.TimeoutError:
                        pass
        finally:
            self._start_task = None

    async def stop(self) -> None:
        """Best-effort shutdown."""
        if self._state == STATE_STOPPED:
            return
        # Flip state FIRST so any concurrent restart-after-crash task that
        # races with us sees STOPPED and bails out without spawning a new
        # subprocess.
        self._state = STATE_STOPPED
        # Wake any retry-loop sleep so start() returns immediately instead
        # of blocking shutdown for up to 5 minutes.
        if self._stop_event is not None:
            self._stop_event.set()
        # If start() is still running in a background task, cancel and
        # await it. Without this, agent_main's 10-s memory.stop timeout
        # leaves a dangling task → "Task was destroyed but it is pending!".
        start_task = self._start_task
        if start_task is not None and not start_task.done():
            start_task.cancel()
            try:
                await start_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        # Cancel in-flight asks
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_result({"_canceled_by_shutdown": True})
        self._pending.clear()
        await self._cleanup_proc()

    async def ask_slow_brain(
        self,
        query: str,
        *,
        timeout_s: float = 20.0,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AskResult:
        """Send a query through the daemon. Returns AskResult.

        Never raises; all errors are mapped to AskResult.status values.
        """
        t0 = time.time()
        # Quota cool-down check
        now_ms = int(time.time() * 1000)
        if now_ms < self._quota_until_ms:
            return AskResult("quota_exhausted", "", 0, False)

        if self._state in (STATE_DEAD, STATE_STOPPED):
            return AskResult("daemon_dead", "", 0, False)

        if self._in_flight >= self._ask_queue_max:
            return AskResult("queue_full", "", 0, False)

        if self._state != STATE_READY:
            # Try a lazy restart once
            await self.start()
            if self._state != STATE_READY:
                return AskResult("daemon_dead", "", 0, False)

        self._in_flight += 1
        try:
            async with self._ask_mutex:
                return await self._do_one_ask(query, timeout_s, cancel_event, t0)
        finally:
            self._in_flight -= 1

    async def _do_one_ask(
        self,
        query: str,
        timeout_s: float,
        cancel_event: Optional[asyncio.Event],
        t0: float,
    ) -> AskResult:
        req_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        self._partial_text_parts[req_id] = []

        tool_name = self._tool_name or "codex"
        wrapped = self._wrap_recall_prompt(query)
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {"prompt": wrapped, "cwd": str(self._workdir)},
            },
        }
        try:
            await self._send(request)
        except (OSError, ConnectionError, RuntimeError) as e:
            self._pending.pop(req_id, None)
            self._partial_text_parts.pop(req_id, None)
            log.warning("codex daemon send failed: %s", e)
            self._state = STATE_CRASHED
            asyncio.create_task(self._restart_after_crash())
            return AskResult("daemon_dead", "", 0, False)

        # Wait for either: response, timeout, or cancel
        cancel_waiter: Optional[asyncio.Task] = None
        if cancel_event is not None:
            cancel_waiter = asyncio.create_task(cancel_event.wait())

        try:
            wait_tasks = [fut]
            if cancel_waiter is not None:
                wait_tasks.append(cancel_waiter)
            done, _ = await asyncio.wait(
                wait_tasks,
                timeout=timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if cancel_waiter is not None and cancel_waiter in done:
                await self._send_cancellation(req_id)
                partial = "".join(self._partial_text_parts.get(req_id, []))
                latency_ms = int((time.time() - t0) * 1000)
                return AskResult("canceled", partial, latency_ms, True)

            if fut in done:
                resp = fut.result()
                if isinstance(resp, dict) and resp.get("_canceled_by_shutdown"):
                    partial = "".join(self._partial_text_parts.get(req_id, []))
                    return AskResult("canceled", partial,
                                      int((time.time() - t0) * 1000), True)
                # Check for protocol error
                if isinstance(resp, dict) and "error" in resp:
                    err = resp.get("error") or {}
                    msg = err.get("message", "") if isinstance(err, dict) else str(err)
                    if _looks_like_quota(msg):
                        self._quota_until_ms = (
                            int(time.time() * 1000) + 30 * 60 * 1000
                        )
                        return AskResult("quota_exhausted", "",
                                          int((time.time() - t0) * 1000), False)
                    return AskResult("protocol_error", msg,
                                      int((time.time() - t0) * 1000), False)
                # Normal: extract content
                text = self._extract_response_text(resp) or "".join(
                    self._partial_text_parts.get(req_id, [])
                )
                return AskResult("ok", text,
                                  int((time.time() - t0) * 1000), False)

            # Timeout
            await self._send_cancellation(req_id)
            partial = "".join(self._partial_text_parts.get(req_id, []))
            return AskResult("timeout", partial,
                              int((time.time() - t0) * 1000), True)
        finally:
            if cancel_waiter is not None and not cancel_waiter.done():
                cancel_waiter.cancel()
            self._pending.pop(req_id, None)
            self._partial_text_parts.pop(req_id, None)

    # ---------- internal: prompt wrap ----------

    def _wrap_recall_prompt(self, query: str) -> str:
        """Prepend recall context so codex actually does the search.

        Codex's default base_instructions cast it as a coding agent. Without
        this preamble it ignores AGENTS.md "recall procedure" headers and
        gives generic answers (or runs `ls` once and gives up). The preamble
        names absolute paths to MEMORY.md and the JSONL transcripts, tells
        codex to use rg/cat/sed, and caps the answer length so realtime TTS
        stays snappy.
        """
        memories = str(self._workdir)
        convs = (
            str(self._conversations_dir)
            if self._conversations_dir is not None else
            "<conversations_dir not configured>"
        )
        preamble = (
            "# Slow brain — robot memory recall task\n"
            "\n"
            "You are the slow brain for Sparky (G1 humanoid). The fast brain "
            "exhausted its local recall budget and is asking you to find one "
            "specific fact from prior sessions.\n"
            "\n"
            "## Filesystem layout (read-only)\n"
            "\n"
            f"- Memory registry:   `{memories}/MEMORY.md`\n"
            f"- Raw entries:       `{memories}/raw_memories.md`\n"
            f"- Per-session notes: `{memories}/rollout_summaries/*.md`\n"
            f"- High-level digest: `{memories}/memory_summary.md`\n"
            f"- Raw JSONL transcripts: `{convs}/*.jsonl` "
            "(one event per line; lines can be >2 KB)\n"
            "\n"
            "## Recall procedure (≤6 shell calls; STOP as soon as you can answer)\n"
            "\n"
            "1. `rg -n --max-columns=600 <keywords> "
            f"{memories}/MEMORY.md {memories}/raw_memories.md`\n"
            "2. If a hit names a `rollout_summaries/<slug>.md`, "
            f"`cat {memories}/rollout_summaries/<slug>.md`.\n"
            "3. For exact evidence (commands, args, scene fields), "
            f"`rg -n --max-columns=600 <keywords> {convs}/*.jsonl`.\n"
            "4. For Chinese terms DO NOT use `\\b` word boundaries — they do "
            "not match between CJK chars. Use the bare term or `-F` "
            "(literal). Also try common English synonyms (cylinder, cuboid, "
            "obstacle, step back, take N steps back, walk vx=-).\n"
            "5. After 4–6 unproductive shell calls, stop and answer "
            "'I can't find that in prior sessions.'\n"
            "\n"
            "## Output\n"
            "\n"
            "Plain text, ≤120 Chinese chars or 80 English words. Cite "
            "`session_id` 8-char prefix + turn_id (e.g., `7f33e260 t-0012`) "
            "when you quote a transcript. Do NOT echo the procedure or list "
            "files you grep'd; just answer the user's question.\n"
            "\n"
            "## User query (verbatim)\n"
            "\n"
            f"{query}\n"
        )
        return preamble

    # ---------- internal: spawn / initialize ----------

    async def _spawn_and_initialize(self) -> None:
        # codex 0.128.0's `mcp-server` subcommand only accepts -c/--enable/
        # --disable. Flags valid for `codex exec` (-C/-s/--skip-git-repo-check/
        # --ignore-user-config/-m) are rejected here with "unexpected argument"
        # and the subprocess exits immediately (stdout EOF). Translate the
        # ones we need into `-c key=value` overrides; cwd is passed per-call
        # in tools/call arguments (see _do_one_ask), so -C is redundant.
        args = [
            self._bin, "mcp-server",
            "-c", "approval_policy=never",
            "-c", f'sandbox_mode="{self._sandbox}"',
        ]
        # Default-on reasoning + speed knobs ("high" + "1.5x" priority tier).
        # The user explicitly asked these be the floor for every codex call.
        # Pass "" / "auto" via config to opt out. service_tier value here is
        # the TOML serde variant name ("fast"/"flex"), not the API
        # request_value ("priority") — codex's deserializer rejects the
        # latter.
        if self._reasoning_effort:
            args.extend(["-c", f'model_reasoning_effort="{self._reasoning_effort}"'])
        if self._reasoning_summary:
            args.extend(["-c", f'model_reasoning_summary="{self._reasoning_summary}"'])
        if self._service_tier and self._service_tier != "auto":
            args.extend(["-c", f'service_tier="{self._service_tier}"'])
        if self._model_override:
            args.extend(["-c", f'model="{self._model_override}"'])

        env = os.environ.copy()
        if self._codex_home is not None:
            env["CODEX_HOME"] = str(self._codex_home)

        log.debug("spawning codex mcp-server: %s", args)
        # `limit=` raises the StreamReader buffer well above the asyncio default
        # 64 KB. Codex mcp-server emits progress notifications whose `content`
        # may carry full tool-call output on one JSONL line; with the default
        # limit we get LimitOverrunError("Separator is found, but chunk is
        # longer than limit") and the read loop dies, taking the daemon with
        # it. 16 MB is generous; codex 0.128 events stay well below that.
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=self._stdout_buffer_bytes,
        )
        assert self._proc.stdin and self._proc.stdout and self._proc.stderr
        self._stdin = self._proc.stdin
        self._stdout = self._proc.stdout
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_drain())

        # MCP handshake: initialize
        init_req = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "g1-brain-memory",
                    "version": "0.1.0",
                },
            },
        }
        # initialize uses id=0; track separately
        loop = asyncio.get_event_loop()
        init_fut: asyncio.Future = loop.create_future()
        self._pending[0] = init_fut
        await self._send(init_req)

        try:
            await asyncio.wait_for(init_fut, timeout=10.0)
        finally:
            self._pending.pop(0, None)

        # MCP initialized notification
        await self._send({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        # tools/list to find codex's exposed tool
        list_req = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/list",
        }
        self._next_id += 1
        list_fut: asyncio.Future = loop.create_future()
        self._pending[list_req["id"]] = list_fut
        await self._send(list_req)
        try:
            resp = await asyncio.wait_for(list_fut, timeout=5.0)
            tools = []
            if isinstance(resp, dict):
                result = resp.get("result") or {}
                if isinstance(result, dict):
                    tools = result.get("tools") or []
            # Pick the "codex" tool by name if present, else the first tool
            for t in tools:
                if isinstance(t, dict) and t.get("name") == "codex":
                    self._tool_name = "codex"
                    break
            if self._tool_name is None and tools:
                first = tools[0]
                if isinstance(first, dict) and "name" in first:
                    self._tool_name = first["name"]
            if self._tool_name is None:
                log.warning("codex mcp-server exposed no tools; using 'codex' as fallback")
                self._tool_name = "codex"
        finally:
            self._pending.pop(list_req["id"], None)

    # ---------- internal: read / write ----------

    async def _send(self, msg: dict) -> None:
        if self._stdin is None:
            raise RuntimeError("daemon stdin not available")
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        async with self._send_lock:
            self._stdin.write(line.encode("utf-8"))
            await self._stdin.drain()

    async def _send_cancellation(self, request_id: int) -> None:
        try:
            await self._send({
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": request_id, "reason": "client requested"},
            })
        except (OSError, ConnectionError, RuntimeError):
            pass

    async def _read_loop(self) -> None:
        cancelled = False
        try:
            assert self._stdout is not None
            while True:
                line = await self._stdout.readline()
                if not line:
                    log.warning("codex daemon stdout EOF")
                    break
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                self._dispatch_msg(msg)
        except asyncio.CancelledError:
            cancelled = True
            return
        except Exception as e:  # noqa: BLE001
            log.warning("codex daemon read loop error: %s", e)
        finally:
            # Only kick off a restart on natural EOF / I/O error. If the
            # task was cancelled (clean shutdown), we deliberately do
            # nothing so asyncio.run() can return promptly.
            if not cancelled and self._state == STATE_READY:
                self._state = STATE_CRASHED
                for fut in list(self._pending.values()):
                    if not fut.done():
                        fut.set_result({"_canceled_by_shutdown": True})
                asyncio.create_task(self._restart_after_crash())

    def _dispatch_msg(self, msg: dict) -> None:
        # Response to a request we sent
        if "id" in msg and "method" not in msg:
            req_id = msg["id"]
            fut = self._pending.get(req_id)
            if fut is not None and not fut.done():
                fut.set_result(msg)
            return
        # Notification (no id)
        if "method" in msg:
            method = msg.get("method") or ""
            if method.startswith("notifications/"):
                self._handle_notification(method, msg.get("params") or {})

    def _handle_notification(self, method: str, params: dict) -> None:
        # codex emits various progress / event notifications. We accumulate
        # text-like content for the current in-flight request as partial.
        # The exact event vocabulary varies across codex versions; we
        # accept any string fields named "text", "message", "content".
        if not self._partial_text_parts:
            return
        # Default to the highest pending id (most recent ask)
        req_id = max(self._partial_text_parts.keys())
        parts = self._partial_text_parts[req_id]

        for key in ("text", "message"):
            if isinstance(params.get(key), str):
                parts.append(params[key])

        content = params.get("content")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict):
                    txt = c.get("text") or c.get("message")
                    if isinstance(txt, str):
                        parts.append(txt)

    @staticmethod
    def _extract_response_text(resp: dict) -> str:
        """Extract assistant text from a tools/call response."""
        if not isinstance(resp, dict):
            return ""
        result = resp.get("result")
        if not isinstance(result, dict):
            return ""
        content = result.get("content")
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    txt = c.get("text")
                    if isinstance(txt, str):
                        parts.append(txt)
            if parts:
                return "".join(parts)
        # Some servers return a flat "text" or "output" field
        for key in ("text", "output", "message"):
            v = result.get(key)
            if isinstance(v, str):
                return v
        return ""

    async def _stderr_drain(self) -> None:
        try:
            assert self._proc is not None and self._proc.stderr is not None
            while True:
                chunk = await self._proc.stderr.read(4096)
                if not chunk:
                    return
                self._stderr_tail.append(chunk)
                # Keep only the last ~16 KB
                total = sum(len(c) for c in self._stderr_tail)
                while total > 16 * 1024 and len(self._stderr_tail) > 1:
                    removed = self._stderr_tail.pop(0)
                    total -= len(removed)
                # Quota detection
                text = b"".join(self._stderr_tail).decode("utf-8", errors="replace")
                if _looks_like_quota(text):
                    self._quota_until_ms = int(time.time() * 1000) + 30 * 60 * 1000
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            return

    async def _ping_loop(self) -> None:
        try:
            while self._state == STATE_READY:
                await asyncio.sleep(self._ping_interval_s)
                if self._state != STATE_READY:
                    return
                # Lightweight tools/list ping
                ping_id = self._next_id
                self._next_id += 1
                loop = asyncio.get_event_loop()
                fut: asyncio.Future = loop.create_future()
                self._pending[ping_id] = fut
                try:
                    await self._send({
                        "jsonrpc": "2.0",
                        "id": ping_id,
                        "method": "tools/list",
                    })
                    await asyncio.wait_for(fut, timeout=2.0)
                except (asyncio.TimeoutError, OSError, ConnectionError):
                    log.warning("codex daemon ping failed; marking stale")
                    self._state = STATE_CRASHED
                    asyncio.create_task(self._restart_after_crash())
                    return
                finally:
                    self._pending.pop(ping_id, None)
        except asyncio.CancelledError:
            return

    async def _restart_after_crash(self) -> None:
        await self._cleanup_proc()
        if self._state == STATE_STOPPED:
            return
        log.info("restarting codex daemon after crash")
        await self.start()

    async def _cleanup_proc(self) -> None:
        # Cancel and drain background tasks first
        for task_attr in ("_reader_task", "_stderr_task", "_ping_task"):
            task = getattr(self, task_attr, None)
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            setattr(self, task_attr, None)

        proc = self._proc
        # Close stdin so subprocesses that exit on EOF shut down gracefully.
        if self._stdin is not None:
            try:
                self._stdin.close()
            except (OSError, ConnectionResetError):
                pass
        if proc is not None:
            try:
                if proc.returncode is None:
                    # Very short EOF grace period, then SIGKILL. We do NOT
                    # use SIGTERM because subprocesses that ignore it would
                    # hang tests; SIGKILL on a misbehaving daemon is safe
                    # since memory pipeline state is durable in SQLite.
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=0.5)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=1.0)
                        except asyncio.TimeoutError:
                            log.error("codex daemon refused to die")
                # Close stdout/stderr transports to release fds promptly.
                # Without this, asyncio.subprocess can leave the event loop
                # with dangling pipe readers that block clean shutdown.
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None:
                        try:
                            stream.feed_eof()
                        except (AttributeError, Exception):  # noqa: BLE001
                            pass
                transport = getattr(proc, "_transport", None)
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:  # noqa: BLE001
                        pass
            except (ProcessLookupError, OSError):
                pass
        self._proc = None
        self._stdin = None
        self._stdout = None
