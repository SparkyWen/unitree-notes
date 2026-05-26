# Clariose / Clariose PM2 操作指南

PM2 进程清单源于 `ecosystem.config.cjs`：
- `clariose-backend` — NestJS API（fork × 1，端口 `127.0.0.1:4400`，nginx `https://zai.gold/api/`）
- `clariose-frontend` — Nuxt 3 SSR（fork × 1，端口 `127.0.0.1:3300`，nginx `https://zai.gold/`）

> ⚠️ 不要把 backend 切到 cluster 模式。CareNote / Consult 都依赖进程内状态（agent run cache、VisitState、Realtime broker 内存）。

---

## 常用 PM2 命令

```bash
# 状态总览
pm2 status

# 查看日志（最近 100 行）
pm2 logs clariose-backend --lines 100
pm2 logs clariose-frontend --lines 100

# 实时跟随日志
pm2 logs clariose-backend
pm2 logs clariose-frontend

# 单 app 重启 / 重载
pm2 restart clariose-backend
pm2 restart clariose-frontend

# 全部重启 / 全部停止 / 全部删除
pm2 restart all
pm2 stop all
pm2 delete all
```

---

## 部署 / 重载

```bash
# 一条命令完成构建 + prisma migrate deploy + PM2 reload + pm2 save
scripts/deploy.sh

scripts/deploy.sh --install        # 先 npm ci
scripts/deploy.sh --backend        # 只动后端
scripts/deploy.sh --frontend       # 只动前端
scripts/deploy.sh --no-migrate     # 跳过 prisma migrate deploy
```

`npm run build` 自带 `postbuild` 钩子（`scripts/pm2-auto-reload.cjs`），构建成功才 reload；构建失败 PM2 继续跑上一份 dist。

---

## 让 PM2 daemon 与 ecosystem 文件对齐

```bash
# 首次启动 / 改了 ecosystem.config.cjs / 加了新环境变量
pm2 startOrReload ecosystem.config.cjs --update-env

# 把当前进程列表持久化（开机自启依赖）
pm2 save

# 验证 dump 已落盘
test -s ~/.pm2/dump.pm2 && echo "pm2 save: ok" || echo "pm2 save: MISSING"
```

> 改完 `ecosystem.config.cjs` 之后必须用 `--update-env` 重载，否则新加的环境变量不生效。

---

## 编辑后端 `.env` 之后

```bash
# .env 不会自动 reload，必须手动并带 --update-env
pm2 reload clariose-backend --update-env
pm2 save
```

---

## 验证部署是否上线

```bash
# 进程在跑
pm2 list | grep clariose-

# 端口在听
ss -ltnp | grep -E ':(3300|4400)'

# 后端启动横幅
pm2 logs clariose-backend --lines 30 --nostream | grep -E 'Nest application|listening'

# 健康检查
curl -i https://zai.gold/api/health
```

---

## 监控 / 排错

```bash
# 实时监控（CPU、内存、PID、重启次数）
pm2 monit

# 查看某个 app 的完整描述（环境变量、cwd、log path）
pm2 describe clariose-backend
pm2 describe clariose-frontend

# 清空 PM2 自身的日志缓冲（只清 PM2 的，不清磁盘 logs/*.log）
pm2 flush

# 看磁盘日志
tail -F logs/clariose-backend-out.log  logs/clariose-backend-error.log
tail -F logs/clariose-frontend-out.log logs/clariose-frontend-error.log
```

---

## CareNote / M7 调试时常用组合

```bash
# 把 CareNote 的 PHI 脱敏关掉（仅本地！上线绝不要）
DEBUG_CARENOTE_PHI=true pm2 restart clariose-backend --update-env

# 强制 Codex runtime（覆盖 auto-select）
CARENOTE_CODEX_RUNTIME=codex-cli pm2 restart clariose-backend --update-env
CARENOTE_CODEX_RUNTIME=stub      pm2 restart clariose-backend --update-env

# 跟随 CareNote 相关日志
pm2 logs clariose-backend | grep -E 'CareNote|carenote|visit\.|ingest'
```

---

## 开机自启（一次性配置）

```bash
# 让 systemd 在启动时拉起 PM2 daemon
pm2 startup systemd -u $USER --hp $HOME
# 按提示把生成的 sudo 命令贴回 shell 执行
pm2 save
```

> systemd 只负责把 PM2 daemon 拉起来；具体 app 由 `~/.pm2/dump.pm2`（即 `pm2 save` 落盘）决定。
