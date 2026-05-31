# Dev 模式设计 — 真实但隔离

> **核心命题**:dev 环境要让**代码行为和 prod 一模一样**(同代码、同框架、同真实 OpenAI/SDK 调用),但**不能让任何写操作落到 prod 的共享资源上**。
>
> 本文档是 2026-04-30 给 Clariose 搭 dev 模式时的完整决策记录,既是「这次做了什么」的存档,也是「以后其他项目怎么照着做」的复用模板。

---

## 0. TL;DR

> **「我新建一个测试数据库就够了对吧?」 ❌ 不够。**

测试库**只**隔离了 *Postgres 行*。一个真实的后端进程还会通过这些通道污染 prod:

| # | 通道 | 不隔离会发生什么 |
|---|---|---|
| 1 | Postgres | 写到 prod 表 |
| 2 | Redis | 写到 prod keyspace,prod 队列读到测试任务 |
| 3 | 监听端口 | 和 prod 端口冲突,起不来或挤掉 prod |
| 4 | 文件系统 | 写到 prod 共享目录(`.data/`、上传目录、缓存) |
| 5 | JWT / Session 密钥 | dev 签的 token 能登 prod |
| 6 | 后台 cron / 队列 | dev 起来就触发 prod-scope 的定时任务 |
| 7 | 第三方副作用 | 给真用户**发邮件/短信/推送/钱**(最危险) |

「彻底隔离」就是把这 7 条全部切开。下面 §2 一条条讲。

---

## 1. 总体架构

dev 和 prod **共享一份代码 checkout**(`/home/ubuntu/Zai`),不开 worktree、不复制源码。这样你在 IDE 里改的代码,dev 立即能跑到。隔离全部走**环境变量**和**资源命名**,不靠物理隔离。

```
┌──────────────────────────────────────────────────────────────┐
│  /home/ubuntu/Zai (单一 checkout)                              │
│  ├── backend/.env          ← prod (PM2 读)                    │
│  ├── backend/.env.test     ← dev override (~/.bashrc 别名读)   │
│  ├── .data/                ← prod 写                          │
│  └── .data-test/           ← dev 写                           │
└──────────────────────────────────────────────────────────────┘
       │                                  │
       ▼ PM2                              ▼ npm run dev (你手起)
   ┌─────────┐                        ┌─────────┐
   │  prod   │  4400 / 3300           │   dev   │  4401 / 3301
   │         │  Redis db 0            │         │  Redis db 1
   │         │  clariose              │         │  clariose_test
   │         │  .data/                │         │  .data-test/
   │         │  prod JWT              │         │  dev JWT
   └─────────┘                        └─────────┘
```

---

## 2. 七个隔离维度 — 逐条说明

### 2.1 数据库 (Postgres / MySQL / SQLite)

**做法**:同实例上建一个 `_test` 后缀的库,改 `DATABASE_URL`。

```bash
# 一次性创建
PGPASSWORD=<pw> createdb -h 127.0.0.1 -U <user> clariose_test
# 推 schema(Prisma)
DATABASE_URL="...clariose_test..." npx prisma db push
```

**陷阱**:
- 不要跨**实例**(那叫 staging,不叫 dev)。同实例同账户够用。
- Schema 改了之后必须重新 push。生产用 migrate,dev 用 push 就行 — push 是直接把 schema.prisma 同步到库,**不留 migration 历史**,所以**只能对测试库用**。
- 别忘了**初始 seed**。如果应用对「至少一个 admin 用户」有强依赖,dev 起不来就是因为这个。

### 2.2 Redis / Memcached

**做法**:用同实例的不同 logical db。

```
prod: REDIS_URL=redis://127.0.0.1:6379    (默认 db 0)
dev:  REDIS_URL=redis://127.0.0.1:6379/1  (db 1)
```

**陷阱**:
- ⚠️ **BullMQ 不只看 db,还看 key 前缀**。如果你的代码硬编码了 `prefix: 'bull'`,即使换了 db,只要业务代码用 `KEYS bull:*` 这种全 db 扫描就会出问题(Redis 命令是 db-scoped 的,所以实际安全;但要小心代码层有没有跨 db 操作)。
- Redis Cluster 没有 logical db 概念。如果是 cluster,只能用 **key 前缀** 隔离(`prefix: 'dev:'` vs `prefix: 'prod:'`)或独立部署。
- pub/sub 频道**不受 db 隔离**(全实例广播)。如果用 pub/sub,改频道名(`channel:dev:*`)。

### 2.3 监听端口

**做法**:dev 全部 +1 或 +N,避开 prod。

```
prod: backend 4400 / frontend 3300
dev:  backend 4401 / frontend 3301
```

**陷阱**:
- ⚠️ **`NUXT_PUBLIC_*` / `VITE_*` / `NEXT_PUBLIC_*` 这类前缀里禁止出现 `localhost` / `127.0.0.1`**。它们会被打包进送往浏览器的 JS,字面量 `127.0.0.1:4401` 在浏览器看来是**用户自己的笔记本**,不是 server。SSH 隧道 / 端口转发场景下必然 `ERR_CONNECTION_REFUSED`。dev 也要让浏览器**同源**说话,前端连后端走相对路径 `NUXT_PUBLIC_API_BASE=/api`,然后用 dev server 的 proxy(Nuxt `nitro.devProxy` / Vite `server.proxy` / Next `rewrites`)把 `/api` 转给 dev 后端。本项目用 `nitro.devProxy`(见 `frontend/nuxt.config.ts`),prod 走 nginx,两边浏览器视角一致。
- dev 后端通常不需要单独打开 CORS — devProxy 之后浏览器看到的就是同源。如果你确实让浏览器跨域访问 dev 后端,才需要 `NODE_ENV=development` 触发宽松 CORS。
- 端口冲突最常见原因:**dev 进程没干净关掉**(reparent 到 PID 1)。`kill <pid>` 时确认 `lsof -iTCP:<port>` 真的清空了。

### 2.4 文件系统(写盘)

**这是最容易遗漏的一条**。Postgres、Redis、端口都好查,只有「这段代码到底往哪写盘」需要逐个 grep。

**做法**:
1. 找出所有写盘点 — `grep -rn 'writeFile\|mkdir\|fs\.\|resolve(.*data\|".data/' src/`。
2. 看每个点的根目录是怎么算出来的:
   - **Env 控制** ✓ — 已经能隔离,改 env 即可
   - **`__dirname` 相对** ⚠️ — 同 checkout 下 dev 和 prod 算出同一个绝对路径,**必须改源码**加 env 支持
   - **`process.cwd()` 相对** ⚠️ — 取决于你 cd 哪里,可能 OK 也可能不,谨慎
   - **`os.homedir()` 相对** ⚠️ — dev 和 prod 同用户就同路径,要么改 env,要么显式指 dev 路径
3. 加一个**统一的根 env**(本项目用 `CLARIOSE_DATA_ROOT`),所有非-env-控制的写盘点都尊重它,默认仍是 `<repo>/.data` 保持 prod 行为不变。

**陷阱**:
- 别只看 *运行时* 的写盘 — 服务**构造函数**里的 `mkdirSync` 也算写盘(本项目 `TeamRecapService` 在启动时就 mkdir 了 `.data/carenote/recaps`,即使 dev 没调任何 carenote 接口,启动那一刻就会污染 prod 目录)。
- 上传目录、缓存目录、调试 dump、PID 文件、socket 文件 全部算。
- 共享 NAS / 网络挂载更危险 — 多机共享时换路径不够,要换挂载点。

### 2.5 JWT / Session 密钥

**做法**:dev 用一个明显不同的 `JWT_SECRET`。

**为什么**:
- 攻击面隔离:dev 数据库被攻破不会拿到 prod 用户能用的 token。
- 误操作隔离:dev 颁发的 token 不能用来登 prod;反之亦然。
- 排查用户问题:用户上报 token 有问题,dev 复制过来不会真的能用,避免「能复现就以为没事」。

**陷阱**:
- `bcrypt` / `argon2` 的 password hash 不需要换 — 它是单向的,dev 库里的 hash 不会泄密。
- OAuth client secret 通常**不区分**(Google/GitHub 是按 redirect_uri 区分);如果你的 OAuth 只配了 prod 域名,dev 走不通,需要在 OAuth 提供方加一个 `http://localhost:3301/...` 的 redirect。

### 2.6 后台任务(cron / 队列 worker)

**做法**:意识到 dev 进程会**自动运行 prod 同样的 cron / worker**,然后选一种处理:
- **A. 接受**:让它跑,反正 DB / Redis / 文件系统都隔离了,跑也是跑测试库的数据。**真实最高**。
- **B. 关掉**:加 `*_ENABLED=false` 的 env 开关,只在 dev 关。Clariose 有 `CARENOTE_DREAM_ENABLED`、`CARENOTE_RECALL_ENABLED`,默认 dev 不关。

**陷阱**:
- ⚠️ **Cron 闹钟会消耗真 OpenAI / 真第三方 API 额度**,即使数据落到测试库。如果 cron 调 `gpt-image-1` 这种贵的模型,半夜跑一次就是几块钱。**对成本敏感的项目,默认关掉 cron**。
- 队列 worker(BullMQ、SQS、Celery)如果还在监听同一个队列,即使 db 隔离了也可能因为队列名重叠导致 dev worker 抢 prod 任务。**队列名要带前缀**(本项目通过 Redis db 隔离间接解决)。

### 2.7 第三方副作用(钱、邮件、短信、推送)⚠️ 最危险

**做法**:**永远不要让 dev 拿 prod 凭据调 send 类 API**。
- **邮件 / 短信 / 推送**:dev 用 mailtrap / mailhog / 本地 stub。或者用**域名白名单**(只发到 `@example.com` / 只发到自己手机)。
- **支付**:dev 用 Stripe test mode key (`sk_test_...`),不是 `sk_live_...`。
- **AI 模型**(OpenAI / Anthropic)— 这条**例外**:通常用 prod 的 key,因为没有「test mode」概念,而且 dev 调 AI 是为了真实测试模型行为。但要注意:
  - 计费照算
  - 如果模型有 fine-tune / file upload 这种持久化副作用,要用独立 org/workspace
  - 别把 dev 的提示词污染到 prod 的 fine-tune 数据集

**陷阱**:
- 「我 dev 时手快不会真去测发邮件 API 的」← 这是错的。某次集成测试一拉跑 50 条用例,每条都 send 一封,你的真用户邮箱就被你刷了。
- Webhooks / outbound HTTP 也算第三方 — dev 不要往 prod 监听器发。

### 2.8 进程监督(PM2 / systemd / docker-compose)

**做法**:dev **不要**进 PM2/systemd 列表。手起手停,Ctrl-C 关掉。理由:
- PM2 命令(`pm2 reload all`、`pm2 startOrReload ecosystem.config.cjs`)如果新增了 dev 条目,会**意外把 dev 当 prod 来管**,断网重启时 dev 也跟着拉起,占用端口。
- dev 进程退出时干净 — orphaned 子进程必须 `kill <pid>`,不要用 `pm2 delete` 的肌肉记忆。

---

## 3. Clariose 这次具体做了什么

### 3.1 三处源码补丁(必要,因为有 `__dirname` 写死的路径)

| 文件 | 改动 | 默认行为 |
|---|---|---|
| `backend/src/modules/carenote/api/visitFolder.service.ts` | 加入 `CLARIOSE_DATA_ROOT` env 检测 | 不设 env → 仍写 `<repo>/.data/carenote/visits` |
| `backend/src/modules/carenote/recap/teamRecap.service.ts` | 同上 | 不设 env → 仍写 `<repo>/.data/carenote/recaps` |
| `backend/src/modules/carenote/api/codexHarnessApi.ts` | 同上,加在 `debugDir` 计算处 | 不设 env → 仍写 `<repo>/.data/carenote/debug/codex-runs` |

补丁模式(每处都长这样):

```ts
// CLARIOSE_DATA_ROOT lets dev/test point writes outside the prod tree.
const override = process.env.CLARIOSE_DATA_ROOT?.trim();
this.root = override
  ? resolve(override, "carenote/visits")
  : resolve(__dirname, "../../../../..", VISITS_ROOT_REL);
```

**关键**:**默认行为完全不变**。prod 不设 `CLARIOSE_DATA_ROOT`,走原路径。这意味着这 3 个 commit 可以安全合到 main,prod 零风险。

### 3.2 `backend/.env.test` — only-overrides

```env
NODE_ENV=development
APP_PORT=4401
APP_BASE_URL=http://localhost:3301

DATABASE_URL=postgresql://zai:123456@127.0.0.1:5432/clariose_test?schema=public
REDIS_URL=redis://127.0.0.1:6379/1

CLARIOSE_DATA_ROOT=/home/ubuntu/Zai/.data-test
CARENOTE_MEMORY_ROOT=/home/ubuntu/Zai/.data-test/carenote/memory
CARENOTE_TEAMS_ROOT=/home/ubuntu/Zai/.data-test/carenote/teams
CARENOTE_TASKS_ROOT=/home/ubuntu/Zai/.data-test/carenote/tasks
RECALL_MEMORY_ROOT=/home/ubuntu/Zai/.data-test/recall-memories

JWT_SECRET=dev-only-test-secret-do-not-use-in-prod-3f7a8b9c1d2e
```

**关键设计点**:
- **只放需要不同的值** — 不抄 prod `.env`(否则把 `OPENAI_API_KEY` 等密钥又落了一份)。
- **加载顺序**:先 `source .env`(拿密钥),再 `source .env.test`(用 override)。第二次 source 的同名 key 会覆盖第一次。
- chmod 600,不可读给其他用户(虽然密钥不在这里,但 JWT 还是私的)。
- `.gitignore` 已经 cover `.env.*`,不会进 git。

### 3.3 `~/.bashrc` 别名

```bash
# --- Zai dev environment (clariose_test DB, ports 4401/3301, .data-test/) ---
_zai_load_dev_env() {
  set -a
  [ -f /home/ubuntu/Zai/backend/.env ]      && . /home/ubuntu/Zai/backend/.env
  [ -f /home/ubuntu/Zai/backend/.env.test ] || { echo "missing .env.test" >&2; return 1; }
  . /home/ubuntu/Zai/backend/.env.test
  set +a
}
alias zai-be-dev='( _zai_load_dev_env && cd /home/ubuntu/Zai/backend && npm run dev )'
alias zai-fe-dev='( cd /home/ubuntu/Zai/frontend && HOST=127.0.0.1 PORT=3301 NITRO_HOST=127.0.0.1 NITRO_PORT=3301 NUXT_PUBLIC_API_BASE=/api npm run dev )'
alias zai-db-push='( _zai_load_dev_env && cd /home/ubuntu/Zai/backend && npx prisma generate && npx prisma db push )'
alias zai-db-psql='PGPASSWORD=123456 psql -h 127.0.0.1 -U zai -d clariose_test'
# --- end Zai dev environment ---
```

**设计点**:
- `_zai_load_dev_env` 是函数不是别名,因为 `set -a; source ...; set +a` 这种多语句序列在 alias 里不优雅。
- 每个 alias 用 `( ... )` 子 shell 包起来,函数内 export 的 env 不会污染交互 shell。下一次 `zai-be-dev` 又从干净状态开始。
- 前端 alias 不走 `_zai_load_dev_env` — 前端不读 `.env.test`,需要的 env 是 inline 给的。这样前端别名独立,不需要后端 env 文件就能用。
- `zai-db-psql` 不需要 env,直接用 PG 密码连到 `clariose_test`。

### 3.4 测试目录树

```bash
mkdir -p /home/ubuntu/Zai/.data-test/carenote/{memory,teams,tasks,visits,recaps,debug/codex-runs} \
         /home/ubuntu/Zai/.data-test/recall-memories
```

**为什么要预建**:有的服务(本项目 `TeamRecapService`)在构造函数里 `mkdirSync({ recursive: true })`,即使你不预建它也会自己建。但预建有两个好处:
- 启动日志更安静(没 mkdir 副作用)
- 你能 `ls -ld .data-test` 一眼看到这套目录已经规划好了

---

## 4. 端到端验证清单

每次搭完 dev 模式,**必须**按这套流程验证一遍才能放心用。

### 4.1 快照 prod 状态

```bash
echo "=== PROD SNAPSHOT BEFORE ==="
pm2 list | grep <app-name>                                # 进程在跑
ss -ltn 'sport = :<prod-port>' | tail -n +2               # 端口在听
PGPASSWORD=<pw> psql -U <user> -d <prod-db> -tAc \
  "SELECT count(*) FROM <some-table>;"                    # DB 行数
du -sh <prod-data-dir> && find <prod-data-dir> -type f | wc -l  # 文件数
redis-cli -n 0 DBSIZE                                     # Redis prod db
redis-cli -n 1 DBSIZE                                     # Redis dev db (应该是 0)
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:<prod-port>/health
```

### 4.2 跑一次 schema push,验证只动测试库

```bash
zai-db-push  # 或对应别名
```
日志里**必须**看到测试库名:
```
Datasource "db": PostgreSQL database "clariose_test" ...
```
看到 prod 库名 → 立即 Ctrl-C,有 bug。

跑完后,prod 行数对比 4.1 的快照,**必须不变**。

### 4.3 启动 dev,验证端口 + 路径

```bash
zai-be-dev   # 在另一个终端
```
12 秒后:
- `ss -ltn 'sport = :<dev-port>'` — dev 端口已绑
- `ss -ltn 'sport = :<prod-port>'` — prod 端口仍在(没被挤掉)
- `curl http://127.0.0.1:<dev-port>/health` → 200
- 启动日志里**搜 `<test-data-root>` 关键词**,确认服务在那里建目录。比如本项目看到:
  ```
  [RoleWorkspace] role workspaces ready: 11 roles under /home/ubuntu/Zai/.data-test/carenote/teams
  ```
- prod data dir 文件数对比快照 — **不变**。
- prod DB 行数对比快照 — **不变**。

### 4.4 关掉 dev,确认无残留

```bash
# 终端里 Ctrl-C
# 然后另一个 shell 验:
ss -ltn 'sport = :<dev-port>'  # 应该没了
pgrep -af '<your-app>'          # 只剩 prod 那一份
```

如果有 orphan 进程(reparent 到 PID 1),手动 `kill <pid>`。

---

## 5. 给其他项目复用的标准流程

照这 8 步走:

### Step 1 — 列出所有共享资源

```bash
# 在项目根跑
grep -rEn 'process\.env\.(DATABASE_URL|REDIS_URL|.*_PORT|.*_HOST|.*_KEY|.*_SECRET|.*_ROOT|.*_PATH)' \
  --include='*.ts' --include='*.js' --include='*.py' --include='*.go' src/ | sort -u
grep -rn '\.data\|/var/\|os\.homedir\|__dirname' src/ | grep -v node_modules | head -30
grep -rn 'sendmail\|mailgun\|sendgrid\|twilio\|stripe\|sns\.publish' src/ | head -20
```

### Step 2 — 决定每个资源的隔离方式

照 §2 的表过一遍,写下来。例子:
| 资源 | 隔离方式 | dev 值 |
|---|---|---|
| Postgres | 同实例新库 | `<app>_test` |
| Redis | logical db 切换 | db 1 |
| 端口 | +1 | 8081 |
| 文件 | 新根 + env 控制 | `/var/<app>-test/` |
| JWT | 不同密钥 | `dev-only-...` |
| 邮件 | 关掉 | `MAILER_ENABLED=false` |
| Stripe | test key | `sk_test_...` |

### Step 3 — 找写死的路径,加 env 支持

`grep -rn '__dirname\|os\.homedir\|process\.cwd' src/` 的每一处,看它是不是用来定位写盘根。是的话:加一个**统一的项目级 env**(`<APP>_DATA_ROOT`),逐个改。**保留默认行为,确保 prod 不受影响**。

模板(TS):
```ts
const root = process.env.<APP>_DATA_ROOT?.trim()
  ? resolve(process.env.<APP>_DATA_ROOT, '<sub-path>')
  : resolve(__dirname, '<original-relative>', '<sub-path>');
```

### Step 4 — 建测试库 + 推 schema

```bash
createdb <app>_test
DATABASE_URL=...<app>_test... <migrate-or-push-command>
```

### Step 5 — 写 `.env.test`(only overrides)

不抄 prod 全量,只写差异。chmod 600。`.gitignore` 里加 `.env.*`。

### Step 6 — 写 `~/.bashrc` 别名块

照 §3.3 的模板,改 4 处:
- 函数名(`_<app>_load_dev_env`)
- alias 前缀(`<app>-be-dev` / `<app>-fe-dev` / `<app>-db-push` / `<app>-db-psql`)
- 路径(`/home/<user>/<repo>/`)
- 数据库连接命令(psql / mysql / sqlite3)

### Step 7 — 建测试目录树

按 §3.4 预建,不留启动副作用。

### Step 8 — 验证(按 §4 全流程跑一遍)

**少做这一步等于没做**。我见过最痛的事故都是「我以为隔离了」。

---

## 6. 常见坑(踩过的)

| 现象 | 真因 |
|---|---|
| 「我只改了 `DATABASE_URL`,为什么 dev 起不来?」 | `APP_PORT` 没改,和 prod 撞了 |
| 「dev 跑完 prod 的 .data 多了几个文件」 | 服务构造函数 `mkdirSync` 用 `__dirname` 算的路径 |
| 「dev 的 BullMQ 任务被 prod worker 拿走了」 | Redis db 没换,或换了 db 但队列前缀写死 |
| 「我前端连不上 dev 后端,CORS 错」 | `NODE_ENV` 没改 → 后端 CORS 锁了 prod 域 |
| 「dev 半夜花了我 $50 OpenAI」 | dream cron / 后台任务在 dev 也跑,且没限速 |
| 「dev 给真用户发了邮件」 | 邮件服务 prod 凭据没禁,DEV_FAIL 了 |
| 「我用 dev token 登进 prod 了」 | JWT_SECRET 没换 |
| 「dev 后端进程 Ctrl-C 后端口没释放」 | 子进程 reparent 到 PID 1 没回收,`kill <pid>` 自己处理 |
| 「dev 的 `.env.test` 不生效」 | dotenv `override:false` — `.env.test` 必须**后**加载;或用 shell `set -a; source` 提前注入 process.env |
| 「重启电脑后 dev 跑不起来」 | 测试库忘了在重启后存在(SQLite)或服务没起(local Postgres),不是代码问题 |

---

## 7. ⭐ 可复用的 Agent Prompt(给其他项目用)

下次想给一个新项目搭 dev 模式,**完整复制**下面这段发给你的 agent。它会自动按本文档的流程走完。

```
我要给当前项目搭一个本地 dev 模式。要求:dev 行为和 prod 一模一样(同代码、同真实第三方 API),
但绝对不能污染 prod 的任何共享资源。请按照下面的流程走完,并在每一步把发现/改动告诉我。

# 你必须遵守的核心原则

1. **prod 零风险**:你做的所有源码改动必须是 additive 的(加 env 支持、不动默认行为)。
   prod 不设 dev 专属 env 时,prod 必须和现在完全一样。
2. **真实但隔离**:dev 应该用真 OpenAI / 真 Stripe-test / 真 Redis,但写到隔离的 namespace。
   不要用 mock / fixture 替换真实调用,除非该资源(邮件/短信/支付)会产生不可逆副作用。
3. **彻底隔离**:不只是数据库。下面 7 个维度全部都要切开。

# Step 0 — 摸清现状(只读,先报告再动手)

跑这些命令并把结果给我看:
- 项目根的 `package.json` / `pyproject.toml` / `go.mod` 等(确认技术栈)
- prod 进程在哪跑(PM2? systemd? docker?),用什么端口
- 当前 `.env` / `.env.local` / `.env.production` 全部 key 列出来(value 不需要)
- `grep -rEn 'process\.env\.[A-Z_]+' src/` 找出所有读 env 的地方
- `grep -rn '__dirname\|process\.cwd\|os\.homedir' src/` 找出可能写死路径的位置
- `grep -rin 'mailgun\|sendgrid\|twilio\|stripe\|sns\|sendmail\|smtp' src/` 找第三方副作用
- 数据库类型 + 连接串格式
- Redis 用法(如果有):是否用 BullMQ / 是否用 pub-sub / 是否用 cluster

报告里告诉我:
- 当前 prod 运行在哪些端口
- 当前 prod 写盘的所有目录(逐条列出来)
- 当前依赖的所有外部服务(PG / Redis / S3 / OpenAI / 邮件 / 支付 / ...)
- 哪些路径是 env 控制的(✓),哪些是写死的(⚠️ 要改源码)

# Step 1 — 7 个维度的隔离方案(给我看,等我确认)

按照下表填好,先给我审,**不要直接动手**:

| 维度 | prod 值 | dev 值 | 改动方式 |
|---|---|---|---|
| 数据库 | `<prod-db>` | `<prod-db>_test` 或 `<prod-db>_dev` | 同实例新库 |
| Redis | db 0 | db 1 | URL 加 `/1` |
| 端口 | `<prod-port>` | `<prod-port>+1` | env |
| 文件路径 | `<list>` | `<list-with-test-suffix>` | env or patch |
| JWT/Session | `<prod-secret>` | dev 专用值 | env |
| Cron/Worker | 全开 | 默认全开 / 看你说 | env flag |
| 邮件/短信/支付 | 真凭据 | 关闭或 test mode | env |

注意:
- **AI 模型 API**(OpenAI / Anthropic / Gemini)用 prod 同一个 key,因为没有 test mode 概念,
  且 dev 调 AI 是为了真实测试。但要告诉我每月 cron 大概会花多少钱。
- **邮件 / 短信 / 支付** 默认在 dev 关闭,除非我明确说要测。

# Step 2 — 改写死的路径(每个文件改完都给我 diff)

对 Step 0 找到的每个 `__dirname` / `os.homedir` 写盘点,加 `<APP>_DATA_ROOT` env 支持。
模板:
```ts
const override = process.env.<APP>_DATA_ROOT?.trim();
const root = override
  ? resolve(override, '<sub-path>')
  : resolve(__dirname, '<original-relative>', '<sub-path>');
```
**保留默认行为不变**。改完跑一次 typecheck / build,确认没破坏。

# Step 3 — 创建 `.env.test`

放在和 `.env` 同目录,**只放 override**,不抄密钥。chmod 600。在 `.gitignore` 确认它已被排除。

# Step 4 — 创建测试数据库 + 推 schema

包括 schema 同步、必要的 seed。给我完整命令,我自己跑(不要你直接连 DB)。

# Step 5 — 创建测试目录树

按 Step 1 表里的「dev 值」预建所有目录。

# Step 6 — 写 `~/.bashrc` 别名

形如:
- `<app>-be-dev` — 启后端 dev
- `<app>-fe-dev` — 启前端 dev(如有)
- `<app>-db-push` — schema 同步
- `<app>-db-psql`(或 `mysql` / `sqlite3`)— 直连测试库

要求:
- 每个 alias 用 `( ... )` 子 shell 包起,不污染交互 shell
- 加载顺序:先 source prod `.env`,再 source `.env.test`(后者覆盖前者)
- 加一个 `<app>-load-dev-env` 函数封装 source 逻辑,失败时报错

# Step 7 — 端到端验证(必须做)

按下面顺序跑,每一步把输出给我:

1. 快照 prod 状态(进程、端口、DB 行数、目录文件数、Redis db 0 keys、health endpoint)
2. 跑 `<app>-db-push`,确认日志里**只**出现测试库名
3. 启 `<app>-be-dev`,12 秒后验:
   - dev 端口已绑,prod 端口仍在
   - dev health endpoint 200
   - 启动日志里看到 dev 数据根路径(关键词搜)
   - prod data 目录文件数 vs 快照 → **不变**
   - prod DB 行数 vs 快照 → **不变**
4. Ctrl-C 关 dev,验端口释放,无 orphan 进程
5. 把整套快照前后对比给我看

# 最终交付

- 一份「这次做了什么」的 markdown(放在 `docs/design/dev-design.md` 或对应位置)
- bashrc 别名块的完整代码
- `.env.test` 的完整模板(注释清楚每条为什么要 override)
- 验证步骤的可重跑脚本

如果中途遇到任何「这一步可能影响 prod」的判断模糊,**停下来问我**,不要凭直觉跳过。
```

---

## 8. 维护

- `.env.test` 改了之后,**必须重启 `zai-be-dev`** — Nest 进程不会热加载 env。
- `~/.bashrc` 改了之后,新开终端才生效;或当前终端 `source ~/.bashrc`。
- 测试库 schema 漂移:`zai-db-push` 检测到差异会自动同步,不会报错就是好的;但**永远只对测试库 push,prod 走 migrate**。
- 添加新 env-controlled 写盘点时,**两件事都要做**:加进 `.env.test`、加进本文档 §3.4 的 mkdir 列表。

---

## 9. 与 prod 的接缝

这次 §3.1 的三处源码改动是**唯一**会随 feature 分支合到 main 的代码变更。它们 100% 默认行为兼容,prod 不需要做任何配置变更:

```
prod (无 CLARIOSE_DATA_ROOT)  → 走 __dirname 老路径,行为同今天
dev  (CLARIOSE_DATA_ROOT 已设) → 走 .data-test/
```

未来如果想把 prod 的 `.data/` 也搬到别的位置(比如 `/var/lib/clariose/`),直接在 `ecosystem.config.cjs` 里给 prod 加 `CLARIOSE_DATA_ROOT=/var/lib/clariose`,prod 也能用上同一个 env knob。所以这个改动是双向有用的。
