// PM2 process manifest for Clariose (zai.gold).
//
// To bring a fresh PM2 daemon in line with this file:
//   pm2 startOrReload ecosystem.config.cjs --update-env
//   pm2 save
//
// Day-to-day deploys go through scripts/deploy.sh, which builds and then
// reloads via this file. The npm `postbuild` hooks in backend/ and frontend/
// also reload PM2 automatically whenever `npm run build` is invoked, so a
// stale dist can never linger across a build.
//
// Architecture: NestJS backend (fork+1) + Nuxt 3 SSR frontend (fork+1).
// nginx proxies https://zai.gold/api/ → clariose-backend (4400)
// and       https://zai.gold/        → clariose-frontend (3300).
//
// !! Do NOT switch the backend to cluster mode. Clariose holds in-process
//    state (consult-session orchestration, agent run cache). Cluster
//    workers do not share that memory and SSE / WebSocket fan-out would
//    silently break. If you need horizontal scale, move state into Redis
//    or Postgres first, then revisit.

const path = require('path');

module.exports = {
  apps: [
    // ── Backend: NestJS API ──────────────────────────────────────────────
    {
      name: 'clariose-backend',
      cwd: path.join(__dirname, 'backend'),
      script: 'dist/main.js',
      interpreter: 'node',
      exec_mode: 'fork',
      instances: 1,
      env_file: path.join(__dirname, 'backend', '.env'),
      env: {
        NODE_ENV: 'production',
        APP_PORT: '4400',
        NODE_OPTIONS: '--max-old-space-size=1024 --enable-source-maps',
        UV_THREADPOOL_SIZE: '16',
      },
      max_memory_restart: '1200M',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 3000,
      kill_timeout: 8000,    // grace after SIGINT before SIGKILL
      listen_timeout: 15000, // how long PM2 waits for the new process to bind
      time: true,
      log_date_format: 'YYYY-MM-DDTHH:mm:ss',
      error_file: path.join(__dirname, 'logs', 'clariose-backend-error.log'),
      out_file:   path.join(__dirname, 'logs', 'clariose-backend-out.log'),
      merge_logs: true,
    },

    // ── Frontend: Nuxt 3 SSR ─────────────────────────────────────────────
    {
      name: 'clariose-frontend',
      cwd: path.join(__dirname, 'frontend'),
      script: '.output/server/index.mjs',
      interpreter: 'node',
      exec_mode: 'fork',
      instances: 1,
      env: {
        NODE_ENV: 'production',
        HOST: '127.0.0.1',
        PORT: '3300',
        NITRO_PORT: '3300',
        NITRO_HOST: '127.0.0.1',
        NUXT_PUBLIC_API_BASE: '/api',
        NUXT_PUBLIC_SITE_URL: 'https://zai.gold',
        NODE_OPTIONS: '--max-old-space-size=1024',
      },
      max_memory_restart: '1200M',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 3000,
      kill_timeout: 8000,
      listen_timeout: 15000,
      time: true,
      log_date_format: 'YYYY-MM-DDTHH:mm:ss',
      error_file: path.join(__dirname, 'logs', 'clariose-frontend-error.log'),
      out_file:   path.join(__dirname, 'logs', 'clariose-frontend-out.log'),
      merge_logs: true,
    },
  ],
};
