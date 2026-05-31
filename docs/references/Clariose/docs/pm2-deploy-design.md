# PM2 deployment pattern — Clariose (zai.gold)

> **Status:** production. Adapted from the Qzone (`qai.zone`) pattern, but
> with the postbuild auto-reload hook removed — Clariose deploys stay
> explicit and manual.
> All operational decisions in this repo flow from this document.

This file captures **why** the deploy pipeline is shaped the way it is,
**what** the artifacts are, and **how** a new operator can reuse the
same pattern on the next site without having to re-derive it.

---

## 1. The bug this pattern exists to prevent

The classic three-way collision:

- A `*.service` systemd unit tries to bind a port at boot.
- A PM2-managed instance of the same app is already bound to that port.
- `npm run build` produces a fresh `dist/`, but **nothing reloads PM2**.

Symptoms:

- `systemctl status` shows `activating (auto-restart)` — restart loop.
- `pm2 list` shows the app `online`, but it's running an *older* binary.
- The new code on disk is correct; production is silently stale.

This pattern eliminates that failure class by making three invariants
true at all times:

1. **PM2 is the only process supervisor.** No systemd unit per app, no
   ad-hoc `node dist/main.js`, no tmux. systemd's only job is to bring
   PM2 itself up at boot via `pm2 startup`.
2. **`npm run build` is build-only; reloading PM2 is an explicit, separate step.**
   No `postbuild` hook auto-reloads production. Deploys go through
   `scripts/deploy.sh` (which calls `pm2 startOrReload ... --update-env`
   after the build) or through a manual `pm2 reload <name> --update-env`
   after a hand-run `npm run build`. The trade-off vs. the auto-reload
   pattern: you can't accidentally promote a build to production by
   running `npm run build`, but you also can't forget to reload — so
   the verification checklist in §10 is mandatory after every deploy.
3. **A fresh box is one command away.** `scripts/deploy.sh` builds,
   migrates, registers with PM2, and saves the process list — same
   workflow on day 1 as on day 1000.

---

## 2. Architecture — two pieces, one contract

```
                 ┌──────────────────────────────────────┐
                 │       scripts/deploy.sh              │
                 │  (or:  npm run build                 │
                 │        + manual pm2 reload)          │
                 └─────────────┬────────────────────────┘
                               │
                               ▼
            ┌──────────────────────────────────────────────┐
            │  build:  nest build  /  nuxt build           │
            │          (produces dist/  or  .output/)      │
            └─────────────┬────────────────────────────────┘
                          │  (build-only — does NOT touch PM2)
                          ▼
            ┌──────────────────────────────────────┐
            │  pm2 startOrReload ecosystem.config  │
            │     --update-env       (or:          │
            │  pm2 reload <name> --update-env)     │
            └─────────────┬────────────────────────┘
                          │
                          ▼
            ┌──────────────────────────────────────┐
            │  PM2 daemon swaps in new dist        │
            │  (config still anchored in           │
            │   ecosystem.config.cjs)              │
            └──────────────────────────────────────┘
```

| Artifact                      | Where                | Job                                                          |
| ----------------------------- | -------------------- | ------------------------------------------------------------ |
| `ecosystem.config.cjs`        | repo root            | Source of truth for **how** each app runs (cwd, script, env, exec_mode, memory limit, log paths). Survives reboots via `pm2 save`. |
| `scripts/deploy.sh`           | `scripts/`           | Single-command bootstrap + redeploy. Wraps `npm ci` (optional) → `prisma generate` + `prisma migrate deploy` (skippable with `--no-migrate`) → `npm run build` on each side → `pm2 startOrReload ecosystem.config.cjs --update-env` → `pm2 save`. **Reload is explicit inside the script — there is no postbuild hook.** |
| `scripts/pm2-auto-reload.cjs` | `scripts/`           | Legacy helper kept for reference. Currently **not wired up** anywhere; left in tree in case a future site reuses the auto-reload pattern. Do not re-introduce it as a `postbuild` hook for Clariose without changing this doc first. |

The previous version of this design hooked PM2 reload into each `package.json`'s `postbuild`. That hook was deliberately removed for Clariose so production reloads stay explicit. The cost: an ad-hoc `npm run build` no longer deploys; you must `pm2 reload <name> --update-env` yourself, or run `scripts/deploy.sh` (which still ends with an explicit `pm2 startOrReload`).

---

## 3. The "serves latest build after deploy" guarantee — how it composes

1. **Stable PM2 names.** Every app in `ecosystem.config.cjs` has a
   fixed `name` (`clariose-backend`, `clariose-frontend`). Humans type
   the same name into `pm2 logs` / `pm2 reload`.
2. **Build and reload are two distinct steps, both inside `deploy.sh`.**
   The script runs the build first; if `build` fails, `set -euo pipefail`
   aborts the script *before* it reaches `pm2 startOrReload`. PM2 keeps
   serving the previous good build. Failure mode is "old build keeps
   running", never "half-new half-old". A hand-run `npm run build`
   followed by a forgotten reload **also** leaves the old build running
   — same failure mode, but you have to remember to come back and reload.
3. **`pm2 reload` is zero-downtime.** PM2 spawns the new process,
   waits up to `listen_timeout` for it to bind, then swaps the port.
   The old process gets SIGINT and `kill_timeout` ms to drain.
4. **`pm2 startOrReload` covers fresh-box bootstrap.** First deploy
   on a new VPS hits this branch (no app registered yet → `start`);
   every subsequent deploy hits the reload branch. Same command, no
   special-casing.
5. **Source of truth lives in git.** `ecosystem.config.cjs` is
   committed. `~/.pm2/dump.pm2` is a derived snapshot — it lets
   `pm2 resurrect` recover the process list across reboots, but it
   loses to the ecosystem file on the next deploy.

---

## 4. PM2 command vocabulary

| Command                                               | When                                        | Notes                                                        |
| ----------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------ |
| `pm2 start ecosystem.config.cjs`                      | **Never** in this workflow                  | Not idempotent. Fails with "Script already launched" if the app exists. |
| `pm2 startOrReload ecosystem.config.cjs --update-env` | First-time bootstrap; end of `deploy.sh`    | The only "from-config" command you should run by hand.       |
| `pm2 reload <name> --update-env`                      | After any single-app code change            | Zero-downtime swap. Re-reads env from ecosystem. Run this manually after a hand-run `npm run build`. |
| `pm2 restart <name> --update-env`                     | App in `errored` / `stopped` state          | Hard restart. Used by the helper as a fallback.              |
| `pm2 save`                                            | After any structural change                 | Persists list to `~/.pm2/dump.pm2` for `pm2 resurrect`.      |
| `pm2 resurrect`                                       | After reboot / daemon crash                 | Replays the dump. Wired via `pm2 startup` (see §7).          |

**Anti-patterns:**

- `pm2 start dist/main.js --name foo` — bypasses ecosystem file. Forbidden.
- `pm2 reload all` after a single-side build — wastes a reload. Use the named form.
- `pm2 reload <name>` without `--update-env` after editing the ecosystem file — env vars don't refresh.

---

## 5. Why the backend stays on `fork + 1 instance`

PM2 cluster mode load-balances across N workers via the node cluster
module. **Do not enable it for the Clariose backend.** Clariose holds:

- Consult-session orchestration in process memory
- Agent-run cache (medication / risk / family / reminder drafts)
- A potential SSE channel for streaming agent output to the consult page

In cluster mode, requests are randomly routed; a session cached on
worker A will 404 on worker B; SSE on A misses events from B. The
symptom is intermittent "sometimes the agent panel is empty" bugs
that look like application errors but are actually routing.

If horizontal scale is ever needed: move state to Redis/Postgres
**first**, then change the ecosystem file. The comment block at the
top of `ecosystem.config.cjs` spells this out so the next person
doesn't flip the flag without thinking.

---

## 6. The commands an operator needs to remember

### Daily deploy (schema unchanged — the common case)

```bash
scripts/deploy.sh --no-migrate
```

### Schema changed (Prisma migration to apply)

```bash
scripts/deploy.sh
```

### Dependencies changed

```bash
scripts/deploy.sh --install --no-migrate    # add or drop --no-migrate as needed
```

### Single side only

```bash
scripts/deploy.sh --backend  --no-migrate
scripts/deploy.sh --frontend --no-migrate
```

### Manual sequence (when you want full control over each step)

```bash
cd /home/ubuntu/Zai/backend
npm run build                                       # build only
pm2 reload clariose-backend --update-env            # explicit reload

cd /home/ubuntu/Zai/frontend
npm run build
pm2 reload clariose-frontend --update-env

pm2 save                                            # persist process list
```

### Reload-only fallback (no rebuild — e.g. you edited `.env` or the ecosystem file)

```bash
pm2 startOrReload /home/ubuntu/Zai/ecosystem.config.cjs --update-env && pm2 save
```

---

## 7. New-machine bootstrap

```bash
# 1. Clone repo + drop secrets into backend/.env
chmod 600 backend/.env

# 2. Provision Postgres role + db, Redis if needed
PGPASSWORD=… psql -h 127.0.0.1 -U zai -d postgres -c "CREATE DATABASE clariose OWNER zai;"

# 3. Install global PM2 (once per VPS)
npm i -g pm2

# 4. First deploy — installs deps, migrates, builds, registers with PM2
scripts/deploy.sh --install

# 5. Make supervision survive reboots — the ONLY systemd unit allowed
pm2 save
pm2 startup systemd -u ubuntu --hp /home/ubuntu
# → run the sudo command PM2 prints

# 6. Drop the nginx vhost in place + reload nginx
sudo cp nginx-zai.gold.conf /etc/nginx/sites-available/zai.gold
sudo ln -sf /etc/nginx/sites-available/zai.gold /etc/nginx/sites-enabled/zai.gold
sudo nginx -t && sudo systemctl reload nginx

# 7. Smoke test
curl -i https://zai.gold/api/health
```

---

## 8. Migrating an old systemd-managed site to this pattern

```bash
# 1. Disable & remove systemd units
sudo systemctl disable --now <project>-backend <project>-frontend
sudo rm -f /etc/systemd/system/<project>-{backend,frontend}.service
sudo systemctl daemon-reload

# 2. Delete *.service files from the repo (and any "systemctl restart" lines from README)

# 3. Add the four PM2 artifacts (ecosystem, helper, deploy.sh, postbuild)

# 4. Run the deploy script
scripts/deploy.sh
```

If PM2 was *already* running an older build alongside systemd, the
first `npm run build` swaps it via the postbuild hook. To be safe,
manually `pm2 reload <name> --update-env` once before relying on the
hook.

---

## 9. Pitfalls — the ones that keep biting

- **`npm run build` is build-only — forgetting to reload is now possible.**
  This is the explicit trade-off vs. the auto-reload pattern. After a
  hand-run `npm run build`, run `pm2 reload <name> --update-env`
  yourself, or use `scripts/deploy.sh` which does it for you. The
  verification checklist in §10 (especially step #3) catches this.
- **A failed `build` aborts the deploy chain — by design.** `deploy.sh`
  uses `set -euo pipefail`, so a TypeScript error stops the script
  before `pm2 startOrReload` runs. PM2 keeps serving the previous
  version. Always check the build exit and `pm2 logs --lines 5` afterwards.
- **`--no-migrate` also skips `prisma generate`.** They sit in the same
  `if` block in `deploy.sh`. In normal use this is fine (`@prisma/client`
  has its own `postinstall` that runs `prisma generate`), but if you
  *changed `schema.prisma`* and ran with `--no-migrate`, the client is
  stale. Either run a full `scripts/deploy.sh`, or call
  `npm run prisma:generate` by hand before building.
- **`.env` edits don't auto-trigger reload.** Run `pm2 reload <name> --update-env` manually.
- **Forgetting `pm2 save`.** If you `pm2 delete` an app and then
  reboot, the app comes back from the previous dump. The deploy
  script saves at the end; manual changes need a manual save.
- **One PM2 daemon per user.** If `ubuntu` and `root` both started
  PM2, you get two daemons, two dumps, and port collisions. Always
  deploy as the same operator user.
- **Logs grow without rotation.** Run once per VPS:
  `pm2 install pm2-logrotate`.

---

## 10. Verification checklist (run after every deploy)

```bash
# 1. PM2 says the apps are online and PIDs are recent.
pm2 list | grep clariose-

# 2. The PIDs actually hold the ports nginx routes to.
ss -ltnp | grep -E ':(3300|4400)'

# 3. The running binary is the freshly built one.
pm2 logs clariose-backend --lines 30 --nostream | grep -E 'Nest application|listening'

# 4. The process list will survive a reboot.
test -s ~/.pm2/dump.pm2 && echo "pm2 save: ok" || echo "pm2 save: MISSING"

# 5. Smoke test the actual endpoint.
curl -i https://zai.gold/api/health
```

A negative for any of these means the chain broke — most commonly #3
(you ran `npm run build` and forgot the `pm2 reload`, so you're serving
stale dist).

---

## 11. Reference: how Clariose uses this

- `ecosystem.config.cjs` at repo root — fork+1 for both apps; comment
  block at top explains why backend cluster mode is forbidden.
- `scripts/deploy.sh` — explicit `pm2 startOrReload --update-env` after
  the build; Prisma migrate gated behind `--no-migrate`.
- `scripts/pm2-auto-reload.cjs` — legacy helper, kept in tree but **not
  wired up** in either `package.json`. Do not re-add as a `postbuild` hook.
- `backend/package.json` — `build` runs `nest build` only.
- `frontend/package.json` — `build` runs `nuxt build` only.
- No `*.service` files anywhere in the repo. No systemd unit at
  `/etc/systemd/system/clariose-*` either.

If a future site wants the original auto-reload variant of this pattern
(build = deploy), re-add a `postbuild` line in each `package.json`
pointing at `scripts/pm2-auto-reload.cjs <name>`, and update §1, §2, §9
of this doc accordingly. Clariose deliberately does **not** do this.
