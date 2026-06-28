"""SQLite + file-tree storage for the memory subsystem.

Owns:
  - state.sqlite schema and migrations
  - sessions / stage1_outputs CRUD
  - File-tree paths (memories/ root and its children)
  - Atomic markdown write helpers
  - git baseline init for memories/

Does NOT own:
  - Job claim/lease/retry (see jobs.py)
  - Worker logic (see phase1.py / phase2.py)
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, List, Optional

from .schemas import Stage1Output

log = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    rollout_path   TEXT NOT NULL UNIQUE,
    started_at     INTEGER NOT NULL,
    ended_at       INTEGER,
    robot_id       TEXT NOT NULL DEFAULT 'g1',
    git_sha        TEXT,
    mjcf_path      TEXT,
    config_hash    TEXT
);

CREATE TABLE IF NOT EXISTS stage1_outputs (
    session_id        TEXT PRIMARY KEY,
    source_updated_at INTEGER NOT NULL,
    raw_memory        TEXT NOT NULL,
    rollout_summary   TEXT NOT NULL,
    rollout_slug      TEXT,
    generated_at      INTEGER NOT NULL,
    usage_count       INTEGER NOT NULL DEFAULT 0,
    last_usage        INTEGER,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stage1_source_updated
    ON stage1_outputs(source_updated_at DESC, session_id DESC);

CREATE TABLE IF NOT EXISTS jobs (
    kind                    TEXT NOT NULL,
    job_key                 TEXT NOT NULL,
    status                  TEXT NOT NULL,
    worker_id               TEXT,
    ownership_token         TEXT,
    started_at              INTEGER,
    finished_at             INTEGER,
    lease_until             INTEGER,
    retry_at                INTEGER,
    retry_remaining         INTEGER NOT NULL,
    last_error              TEXT,
    input_watermark         INTEGER,
    last_success_watermark  INTEGER,
    PRIMARY KEY (kind, job_key)
);

CREATE INDEX IF NOT EXISTS idx_jobs_kind_status_retry_lease
    ON jobs(kind, status, retry_at, lease_until);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def atomic_write(path: Path, content: str) -> None:
    """Atomic write: write to .tmp then os.replace.

    Crash mid-write leaves either old content or new content, never partial.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def host_codex_home() -> Path:
    """The codex home the operator's own `codex login` keeps fresh.

    Honours an explicit ``$CODEX_HOME`` (rare) and otherwise defaults to
    ``~/.codex`` — the dir the codex CLI reads/writes during normal use.
    """
    env = os.environ.get("CODEX_HOME")
    return Path(env).expanduser().resolve() if env else (Path.home() / ".codex")


def codex_access_token_expiry(auth_path: Path) -> Optional[float]:
    """Epoch-seconds expiry of the ChatGPT access_token in a codex auth.json.

    Returns None when the file is missing/unreadable or carries no decodable
    ``exp`` claim (e.g. API-key auth). Best-effort: never raises.
    """
    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tok = (data.get("tokens") or {}).get("access_token") if isinstance(data, dict) else None
    if not isinstance(tok, str) or tok.count(".") != 2:
        return None
    try:
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # restore base64 padding
        claims = json.loads(base64.urlsafe_b64decode(payload))
        exp = claims.get("exp")
        return float(exp) if exp is not None else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def sync_codex_auth(host_auth: Path, runtime_auth: Path, *, skew_s: float = 86400.0) -> str:
    """Copy a fresh host codex auth.json into an isolated CODEX_HOME.

    g1_brain runs codex with ``CODEX_HOME`` pointed at ``.codex_runtime`` so its
    memory sessions/config stay isolated from the operator's ``~/.codex``. The
    side effect is that ``.codex_runtime/auth.json`` is NEVER refreshed by
    ``codex login`` — its access_token expires (~10-day life) and, once the
    operator re-logs ``~/.codex``, its refresh_token is server-invalidated
    ("refresh token was already used"), so every slow-brain call 401s forever
    even though the operator IS logged in. We self-heal at startup by copying
    the live host token in whenever the runtime copy is missing, expired, or
    within ``skew_s`` of expiry (so it can't lapse mid-session).

    Only copies when the host token itself is valid, so we never overwrite a
    good runtime token with a worse one. Returns a short status string for
    logging; never raises.
    """
    try:
        if host_auth.resolve() == runtime_auth.resolve():
            return "noop_same_path"
    except OSError:
        pass
    if not host_auth.is_file():
        return "noop_no_host_auth"

    now = time.time()
    host_exp = codex_access_token_expiry(host_auth)
    if host_exp is not None and host_exp <= now:
        # The operator's own login is stale too — copying it would not help.
        return "noop_host_expired"

    runtime_exp = codex_access_token_expiry(runtime_auth)
    runtime_ok = (
        runtime_auth.is_file()
        and runtime_exp is not None
        and runtime_exp > now + skew_s
    )
    if runtime_ok:
        return "noop_runtime_fresh"

    try:
        runtime_auth.parent.mkdir(parents=True, exist_ok=True)
        tmp = runtime_auth.with_suffix(runtime_auth.suffix + f".tmp.{os.getpid()}")
        shutil.copyfile(host_auth, tmp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, runtime_auth)
        return "synced"
    except OSError as e:
        log.warning("codex auth sync failed (%s -> %s): %s", host_auth, runtime_auth, e)
        return "error"


class StorageLayer:
    """Owns paths, DB connection, and basic CRUD.

    All public methods are sync. Workers wrap them in asyncio.to_thread
    where they need to avoid blocking the event loop.
    """

    def __init__(self, robot_root: Path):
        self.robot_root = robot_root.expanduser().resolve()
        self.memories_dir = self.robot_root / "memories"
        self.rollout_summaries_dir = self.memories_dir / "rollout_summaries"
        self.state_db_path = self.robot_root / "state.sqlite"
        self.codex_runtime_dir = self.robot_root / ".codex_runtime"
        self._conn: Optional[sqlite3.Connection] = None

    # ---------- lifecycle ----------

    def init(self) -> None:
        """Create directories, init DB schema, init git baseline if missing."""
        self.robot_root.mkdir(parents=True, exist_ok=True)
        self.memories_dir.mkdir(parents=True, exist_ok=True)
        self.rollout_summaries_dir.mkdir(parents=True, exist_ok=True)
        self.codex_runtime_dir.mkdir(parents=True, exist_ok=True)
        self.sync_codex_auth()

        self._open_db()
        self._migrate()

        self._init_git_baseline_if_missing()
        self._write_memory_enabled_marker_if_missing()
        self._write_default_agents_md_if_missing()

    def sync_codex_auth(self) -> str:
        """Refresh the isolated codex home's auth from the operator's ~/.codex.

        Keeps ask_slow_brain / phase1 / phase2 working without a manual
        ``cp ~/.codex/auth.json .codex_runtime/`` after each ``codex login``.
        See module-level ``sync_codex_auth`` for the full rationale.
        """
        status = sync_codex_auth(
            host_codex_home() / "auth.json",
            self.codex_runtime_dir / "auth.json",
        )
        if status == "synced":
            log.info("codex auth synced into %s from host login", self.codex_runtime_dir)
        elif status in ("noop_no_host_auth", "noop_host_expired"):
            log.warning(
                "codex auth NOT synced (%s) — slow brain may 401; run `codex login`",
                status,
            )
        else:
            log.debug("codex auth sync: %s", status)
        return status

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None

    def _open_db(self) -> None:
        # check_same_thread=False because we'll call from asyncio.to_thread
        # which may use a different thread per call. We serialize via our
        # own connection-level lock when needed.
        try:
            self._conn = sqlite3.connect(
                self.state_db_path,
                isolation_level=None,  # autocommit; we BEGIN/COMMIT explicitly when needed
                check_same_thread=False,
                timeout=10.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.DatabaseError as e:
            log.error("state.sqlite open failed: %s — backing up and recreating", e)
            self._backup_corrupt_db()
            self._conn = sqlite3.connect(
                self.state_db_path,
                isolation_level=None,
                check_same_thread=False,
                timeout=10.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")

    def _backup_corrupt_db(self) -> None:
        if self.state_db_path.exists():
            backup = self.state_db_path.with_suffix(f".sqlite.broken.{now_ms()}")
            try:
                self.state_db_path.replace(backup)
                log.warning("backed up corrupt state.sqlite to %s", backup)
            except OSError as e:
                log.error("cannot backup corrupt DB: %s", e)
                try:
                    self.state_db_path.unlink()
                except OSError:
                    pass

    def _migrate(self) -> None:
        assert self._conn is not None
        cur = self._conn.cursor()
        cur.executescript(_SCHEMA_V1)
        row = cur.execute(
            "SELECT version FROM schema_version LIMIT 1"
        ).fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO schema_version(version) VALUES (?)",
                (CURRENT_SCHEMA_VERSION,),
            )
        elif row["version"] != CURRENT_SCHEMA_VERSION:
            log.warning(
                "schema_version=%s expected %s; migration not implemented yet",
                row["version"], CURRENT_SCHEMA_VERSION,
            )

    def _init_git_baseline_if_missing(self) -> None:
        git_dir = self.memories_dir / ".git"
        if git_dir.exists():
            return
        try:
            subprocess.run(
                ["git", "init", "-q"],
                cwd=self.memories_dir, check=True, timeout=10,
            )
            # Set a local identity so commits work in headless environments
            subprocess.run(
                ["git", "config", "user.email", "memory@g1-brain.local"],
                cwd=self.memories_dir, check=True, timeout=5,
            )
            subprocess.run(
                ["git", "config", "user.name", "G1 Brain Memory"],
                cwd=self.memories_dir, check=True, timeout=5,
            )
            (self.memories_dir / ".gitignore").write_text(
                "*.tmp.*\nphase2_workspace_diff.md\n", encoding="utf-8",
            )
            subprocess.run(
                ["git", "add", ".gitignore"],
                cwd=self.memories_dir, check=True, timeout=5,
            )
            subprocess.run(
                ["git", "commit", "-q", "-m", "memory: initial baseline"],
                cwd=self.memories_dir, check=True, timeout=10,
            )
        except (subprocess.SubprocessError, OSError) as e:
            log.warning("git init failed in %s: %s", self.memories_dir, e)

    def _write_memory_enabled_marker_if_missing(self) -> None:
        memory_md = self.memories_dir / "MEMORY.md"
        if memory_md.exists():
            return
        from datetime import datetime, timezone
        iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        atomic_write(
            memory_md,
            f"# Memory enabled at {iso}\n\n"
            "_This file is curated by the memory consolidation worker. "
            "Do not edit by hand unless you know what you are doing._\n",
        )

    def _write_default_agents_md_if_missing(self) -> None:
        """Sync the packaged default AGENTS.md if missing or stale.

        We own AGENTS.md (the consolidation agent only touches MEMORY.md /
        memory_summary.md / raw_memories.md / rollout_summaries/). The
        packaged default carries a version marker in the first line:

            <!-- g1_brain.agents_md_version: <N> -->

        If the on-disk file is missing, has no marker, or has an older
        version, overwrite it. This lets new releases ship updated recall
        guidance without forcing every user to delete the old file.
        """
        agents_md = self.memories_dir / "AGENTS.md"
        default_path = Path(__file__).parent / "prompts" / "default_agents_md.md"
        if not default_path.exists():
            if not agents_md.exists():
                atomic_write(agents_md, "# G1 robot memory — read path\n")
            return

        default_text = default_path.read_text(encoding="utf-8")
        default_ver = self._extract_agents_md_version(default_text)
        if not agents_md.exists():
            atomic_write(agents_md, default_text)
            return
        existing_ver = self._extract_agents_md_version(
            agents_md.read_text(encoding="utf-8", errors="replace"),
        )
        if default_ver > existing_ver:
            log.info(
                "AGENTS.md version %s -> %s; refreshing %s",
                existing_ver, default_ver, agents_md,
            )
            atomic_write(agents_md, default_text)

    @staticmethod
    def _extract_agents_md_version(text: str) -> int:
        """Read `<!-- g1_brain.agents_md_version: N -->` from first ~5 lines."""
        import re as _re
        for line in text.splitlines()[:5]:
            m = _re.search(r"g1_brain\.agents_md_version:\s*(\d+)", line)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    return 0
        return 0

    # ---------- generic DB helpers ----------

    @contextmanager
    def _txn(self):
        assert self._conn is not None
        self._conn.execute("BEGIN")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        assert self._conn is not None
        return self._conn.execute(sql, params)

    def executemany(self, sql: str, seq: Iterable[tuple]) -> sqlite3.Cursor:
        assert self._conn is not None
        return self._conn.executemany(sql, seq)

    # ---------- sessions ----------

    def upsert_session(
        self,
        *,
        session_id: str,
        rollout_path: Path,
        robot_id: str = "g1",
        git_sha: Optional[str] = None,
        mjcf_path: Optional[str] = None,
        config_hash: Optional[str] = None,
    ) -> None:
        self.execute(
            """
            INSERT INTO sessions (id, rollout_path, started_at, robot_id,
                                  git_sha, mjcf_path, config_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                rollout_path = excluded.rollout_path,
                git_sha      = COALESCE(excluded.git_sha, sessions.git_sha),
                mjcf_path    = COALESCE(excluded.mjcf_path, sessions.mjcf_path),
                config_hash  = COALESCE(excluded.config_hash, sessions.config_hash)
            """,
            (session_id, str(rollout_path), now_ms(), robot_id,
             git_sha, mjcf_path, config_hash),
        )

    def mark_session_ended(self, session_id: str) -> None:
        self.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?",
            (now_ms(), session_id),
        )

    def get_session(self, session_id: str) -> Optional[sqlite3.Row]:
        row = self.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row

    # ---------- stage1_outputs ----------

    def upsert_stage1_output(
        self, session_id: str, out: Stage1Output, source_updated_at: int,
    ) -> None:
        self.execute(
            """
            INSERT INTO stage1_outputs
                (session_id, source_updated_at, raw_memory, rollout_summary,
                 rollout_slug, generated_at, usage_count, last_usage)
            VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
            ON CONFLICT(session_id) DO UPDATE SET
                source_updated_at = excluded.source_updated_at,
                raw_memory        = excluded.raw_memory,
                rollout_summary   = excluded.rollout_summary,
                rollout_slug      = COALESCE(excluded.rollout_slug, stage1_outputs.rollout_slug),
                generated_at      = excluded.generated_at
            """,
            (session_id, source_updated_at, out.raw_memory,
             out.rollout_summary, out.rollout_slug, now_ms()),
        )

    def get_stage1_output(self, session_id: str) -> Optional[sqlite3.Row]:
        return self.execute(
            "SELECT * FROM stage1_outputs WHERE session_id = ?", (session_id,)
        ).fetchone()

    def list_stage1_for_phase2(
        self, max_count: int, max_unused_days: int,
    ) -> List[sqlite3.Row]:
        """Return top-N stage1 outputs eligible for Phase2 consolidation."""
        cutoff_ms = now_ms() - max_unused_days * 86_400 * 1000
        rows = self.execute(
            """
            SELECT * FROM stage1_outputs
            WHERE raw_memory <> ''
              AND (last_usage IS NULL OR last_usage >= ?)
            ORDER BY usage_count DESC,
                     COALESCE(last_usage, generated_at) DESC,
                     session_id DESC
            LIMIT ?
            """,
            (cutoff_ms, max_count),
        ).fetchall()
        return list(rows)

    def bump_stage1_usage(self, session_id: str) -> None:
        self.execute(
            """
            UPDATE stage1_outputs
            SET usage_count = usage_count + 1, last_usage = ?
            WHERE session_id = ?
            """,
            (now_ms(), session_id),
        )

    # ---------- file ops ----------

    def write_raw_memories_md(self, rows: List[sqlite3.Row]) -> None:
        """Rebuild raw_memories.md from a deterministic ordering of stage1 rows."""
        sorted_rows = sorted(rows, key=lambda r: r["session_id"])
        parts: List[str] = ["# Raw Memories\n"]
        parts.append(
            "_Merged stage-1 raw memories (stable ascending session-id order)._\n",
        )
        for r in sorted_rows:
            slug = r["rollout_slug"] or "untitled"
            parts.append(f"\n## Session `{r['session_id']}` — {slug}\n")
            parts.append(r["raw_memory"].rstrip() + "\n")
        content = "\n".join(parts)
        atomic_write(self.memories_dir / "raw_memories.md", content)

    def write_rollout_summary(self, row: sqlite3.Row) -> Path:
        """Write per-session rollout_summary file. Returns the path."""
        slug = row["rollout_slug"] or "untitled"
        # Compose deterministic filename
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(
            row["generated_at"] / 1000, tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H-%M-%SZ")
        safe_slug = "".join(
            ch if (ch.isalnum() or ch in "-_") else "-"
            for ch in slug.lower()
        )[:60] or "untitled"
        fname = f"{row['session_id'][:8]}-{ts}-{safe_slug}.md"
        path = self.rollout_summaries_dir / fname
        body = (
            f"# {slug}\n\n"
            f"- session_id: `{row['session_id']}`\n"
            f"- generated_at: {ts}\n\n"
            f"## Summary\n\n{row['rollout_summary'].strip()}\n"
        )
        atomic_write(path, body)
        return path

    def evict_old_rollout_summaries(self, keep_max: int = 200) -> int:
        """Delete oldest rollout_summary files beyond keep_max. Returns deleted count."""
        try:
            files = sorted(
                self.rollout_summaries_dir.glob("*.md"),
                key=lambda p: p.stat().st_mtime,
            )
        except OSError:
            return 0
        excess = max(0, len(files) - keep_max)
        deleted = 0
        for f in files[:excess]:
            try:
                f.unlink()
                deleted += 1
            except OSError:
                continue
        return deleted

    # ---------- git ----------

    def git_status_porcelain(self) -> str:
        try:
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.memories_dir, capture_output=True, text=True, timeout=10,
            )
            return r.stdout
        except (subprocess.SubprocessError, OSError) as e:
            log.warning("git status failed: %s", e)
            return ""

    def git_diff_text(self) -> str:
        try:
            r = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=self.memories_dir, capture_output=True, text=True, timeout=10,
            )
            return r.stdout
        except (subprocess.SubprocessError, OSError) as e:
            log.warning("git diff failed: %s", e)
            return ""

    def git_commit_baseline(self, message: str) -> bool:
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self.memories_dir, check=True, timeout=10,
            )
            # Use --allow-empty to make this idempotent across runs
            r = subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m", message],
                cwd=self.memories_dir, capture_output=True, timeout=15,
            )
            return r.returncode == 0
        except (subprocess.SubprocessError, OSError) as e:
            log.warning("git commit failed: %s", e)
            return False


def config_hash_of(d: dict) -> str:
    import json as _json
    blob = _json.dumps(d, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
