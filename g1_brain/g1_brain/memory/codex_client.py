"""Thin async wrapper around the `codex exec --json` subprocess.

Used by Phase1 and Phase2 workers for one-shot extraction / consolidation
tasks. Each call spawns a fresh `codex exec` process, streams the JSONL
events from stdout, and returns the final assistant message text.

The persistent ask_slow_brain daemon uses `codex mcp-server` instead;
that lives in daemon.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)


class CodexExecError(Exception):
    """Raised when codex exec returns no usable text or hits an unrecoverable error."""


class CodexQuotaExhausted(CodexExecError):
    """Raised when codex returns a recognizable rate-limit / quota error."""


@dataclass
class CodexExecResult:
    text: str
    stderr_tail: str
    returncode: int


# Recognized quota / rate-limit strings in stderr or events
_QUOTA_PATTERNS = (
    "rate_limit",
    "quota_exceeded",
    "quota_exhausted",
    "insufficient_quota",
    "rate limit",
    "quota exceeded",
    "quota exhausted",
    "you exceeded your current quota",
)


def _looks_like_quota(s: str) -> bool:
    low = s.lower()
    return any(p in low for p in _QUOTA_PATTERNS)


class CodexClient:
    """Async wrapper around `codex exec --json` invocations."""

    def __init__(
        self,
        *,
        codex_bin: str = "codex",
        workdir: Path,
        codex_home: Optional[Path] = None,
        sandbox: str = "read-only",
        extra_args: Optional[List[str]] = None,
        stdout_buffer_bytes: int = 16 * 1024 * 1024,
        reasoning_effort: str = "high",
        reasoning_summary: str = "concise",
        service_tier: str = "fast",
    ):
        self._bin = codex_bin
        self._workdir = workdir.expanduser().resolve()
        self._codex_home = codex_home.expanduser().resolve() if codex_home else None
        self._sandbox = sandbox
        self._extra_args = list(extra_args or [])
        self._stdout_buffer_bytes = max(int(stdout_buffer_bytes), 1 << 20)
        self._reasoning_effort = (reasoning_effort or "").strip()
        self._reasoning_summary = (reasoning_summary or "").strip()
        self._service_tier = (service_tier or "").strip()

    def is_available(self) -> bool:
        return shutil.which(self._bin) is not None

    async def exec_once(
        self,
        prompt: str,
        *,
        timeout_s: float = 120.0,
        model_override: Optional[str] = None,
        ephemeral: bool = True,
    ) -> CodexExecResult:
        """Spawn `codex exec --json`, write prompt to stdin, return final text.

        Raises:
            CodexExecError if the process fails, times out, or produces
            no recognizable assistant message.
            CodexQuotaExhausted if stderr or events match a rate-limit pattern.
        """
        if not self.is_available():
            raise CodexExecError(f"codex binary not found: {self._bin}")

        args = [
            self._bin, "exec", "--json",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "-C", str(self._workdir),
            "-s", self._sandbox,
            "-c", "approval_policy=never",
        ]
        # Default-on reasoning + speed knobs ("high" + "1.5x" priority tier),
        # applied to every Phase1/Phase2 extraction as well as one-shot exec
        # calls. Pass empty / "auto" to opt out from MemoryConfig.
        if self._reasoning_effort:
            args.extend(["-c", f'model_reasoning_effort="{self._reasoning_effort}"'])
        if self._reasoning_summary:
            args.extend(["-c", f'model_reasoning_summary="{self._reasoning_summary}"'])
        if self._service_tier and self._service_tier != "auto":
            args.extend(["-c", f'service_tier="{self._service_tier}"'])
        if ephemeral:
            args.append("--ephemeral")
        if model_override:
            args.extend(["-m", model_override])
        args.extend(self._extra_args)

        env = os.environ.copy()
        if self._codex_home is not None:
            env["CODEX_HOME"] = str(self._codex_home)

        log.debug("codex exec args: %s", args)

        # See daemon.py for the rationale on `limit=`: codex --json stdout
        # lines can carry large tool-call payloads in one event, and the
        # asyncio default 64 KB buffer raises LimitOverrunError mid-stream.
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=self._stdout_buffer_bytes,
        )
        assert proc.stdin and proc.stdout and proc.stderr

        # Write prompt to stdin and close it so codex knows input is done
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
        finally:
            try:
                proc.stdin.close()
            except (OSError, ConnectionResetError):
                pass

        try:
            text, stderr_tail = await asyncio.wait_for(
                self._consume(proc), timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            log.warning("codex exec timed out after %ss; SIGTERM", timeout_s)
            await self._kill(proc)
            raise CodexExecError(f"codex exec timeout after {timeout_s}s")

        rc = proc.returncode if proc.returncode is not None else -1
        if _looks_like_quota(stderr_tail) or _looks_like_quota(text):
            raise CodexQuotaExhausted(
                f"quota signal detected (rc={rc}): {stderr_tail[-200:]}"
            )
        if rc != 0 and not text:
            raise CodexExecError(
                f"codex exec failed rc={rc}, stderr={stderr_tail[-200:]}"
            )
        if not text:
            raise CodexExecError(
                f"codex exec produced no assistant text; stderr={stderr_tail[-200:]}"
            )
        return CodexExecResult(text=text, stderr_tail=stderr_tail, returncode=rc)

    async def _consume(self, proc: asyncio.subprocess.Process) -> tuple[str, str]:
        """Read stdout JSONL events and stderr concurrently. Returns (final_text, stderr_tail)."""
        final_text_parts: List[str] = []
        stderr_chunks: List[bytes] = []

        async def read_stdout():
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    return
                try:
                    ev = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                # codex exec --json emits various event types; we look for
                # the final assistant message text. Different codex versions
                # use slightly different shapes; we try several.
                self._extract_final_text(ev, final_text_parts)

        async def read_stderr():
            assert proc.stderr is not None
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    return
                stderr_chunks.append(chunk)

        await asyncio.gather(
            read_stdout(), read_stderr(), proc.wait(),
            return_exceptions=False,
        )

        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")
        # Concatenate accumulated parts; if multiple final messages were
        # emitted (e.g. one per agent turn), take the last one.
        if final_text_parts:
            text = final_text_parts[-1]
        else:
            text = ""
        return text, stderr_text

    @staticmethod
    def _extract_final_text(ev: dict, sink: List[str]) -> None:
        """Best-effort extraction across codex event shape variations.

        Accepted shapes (older codex versions through codex-cli 0.128):
        - {"type":"agent_message", "message":"..."}
        - {"type":"message", "role":"assistant", "content":[{"type":"text","text":"..."}]}
        - {"type":"task_complete", "last_agent_message":"..."}
        - {"msg":{"type":"agent_message","message":"..."}}
        - {"type":"final_assistant_message", "text":"..."}
        - {"type":"item.completed", "item":{"type":"agent_message","text":"..."}}  (codex 0.128)
        - {"type":"item.completed", "item":{"type":"message","role":"assistant",
                                              "content":[{"type":"text","text":"..."}]}}
        """
        if not isinstance(ev, dict):
            return

        # codex-cli 0.128+ wraps assistant output in an item.completed envelope.
        if ev.get("type") == "item.completed":
            item = ev.get("item")
            if isinstance(item, dict):
                # Recurse into the nested item: same parser handles it.
                CodexClient._extract_final_text(item, sink)
            return

        # Unwrap a common "msg" envelope used by some intermediate codex builds.
        body = ev.get("msg") if isinstance(ev.get("msg"), dict) else ev

        t = body.get("type") or ev.get("type")
        if t == "agent_message":
            # Old shape uses "message"; 0.128 nested-item shape uses "text".
            for k in ("message", "text"):
                v = body.get(k)
                if isinstance(v, str) and v:
                    sink.append(v)
                    return
            return
        if t == "task_complete" and isinstance(body.get("last_agent_message"), str):
            sink.append(body["last_agent_message"])
            return
        if t == "final_assistant_message" and isinstance(body.get("text"), str):
            sink.append(body["text"])
            return
        if t == "message" and body.get("role") == "assistant":
            content = body.get("content")
            if isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        txt = c.get("text") or ""
                        if isinstance(txt, str):
                            parts.append(txt)
                if parts:
                    sink.append("".join(parts))

    @staticmethod
    async def _kill(proc: asyncio.subprocess.Process) -> None:
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                log.error("codex exec subprocess wouldn't die")
