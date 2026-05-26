#!/usr/bin/env node
// Auto-reload a PM2 app after a build, iff that app is currently online.
//
// Wired into backend/ and frontend/ as the npm `postbuild` hook so that
// `npm run build` always swaps in the freshly compiled dist — no separate
// `pm2 reload` step, no chance of an old build lingering.
//
// Behavior:
//   - PM2 not installed         → silent no-op (CI / dev box without PM2).
//   - App not registered in PM2 → silent no-op (first-time bootstrap).
//   - App registered & online   → `pm2 reload <name> --update-env`.
//   - App registered but stopped/errored → `pm2 restart <name> --update-env`.
//
// Usage: node pm2-auto-reload.cjs <app-name>

const { spawnSync } = require('node:child_process');

const appName = process.argv[2];
if (!appName) {
  console.error('[pm2-auto-reload] missing app name argument');
  process.exit(0); // never fail the build
}

function run(cmd, args, opts = {}) {
  return spawnSync(cmd, args, { encoding: 'utf8', ...opts });
}

const which = run('which', ['pm2']);
if (which.status !== 0 || !which.stdout.trim()) {
  console.log('[pm2-auto-reload] pm2 not on PATH — skipping');
  process.exit(0);
}

const list = run('pm2', ['jlist']);
if (list.status !== 0) {
  console.log('[pm2-auto-reload] pm2 jlist failed — skipping');
  process.exit(0);
}

let apps;
try {
  apps = JSON.parse(list.stdout);
} catch {
  console.log('[pm2-auto-reload] could not parse pm2 jlist — skipping');
  process.exit(0);
}

const app = apps.find((a) => a.name === appName);
if (!app) {
  console.log(`[pm2-auto-reload] ${appName} not in PM2 — skipping (run scripts/deploy.sh to bootstrap)`);
  process.exit(0);
}

const status = app.pm2_env && app.pm2_env.status;
const action = status === 'online' ? 'reload' : 'restart';
console.log(`[pm2-auto-reload] ${action} ${appName} (was ${status})`);

const result = run('pm2', [action, appName, '--update-env'], { stdio: 'inherit' });
if (result.status !== 0) {
  console.error(`[pm2-auto-reload] pm2 ${action} ${appName} exited ${result.status}`);
  // Still don't fail the build — operator can investigate, dist is on disk.
}
