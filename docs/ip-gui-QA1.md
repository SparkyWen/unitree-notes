# QA1：为什么 `localhost:8090` 打不开，但 `http://192.168.101.242:8090` 可以？

> 现象：在 Windows 浏览器里访问 fleet coordinator 仪表盘，
> `http://localhost:8090` 连不上（一直转圈 / `ERR_CONNECTION_REFUSED`），
> 但换成 `http://192.168.101.242:8090` 就能正常打开。

**一句话结论**：这两个地址走的是**两条完全不同的网络路径**。`192.168.101.242` 是
WSL2 虚拟机在 NAT 虚拟交换机上的真实 IP，Windows 主机有一条直达路由，**不经过任何中转**，
所以稳定可用；而 `localhost` 依赖一个叫 **localhost forwarding 的 Windows 中转进程**
（`wslhost.exe`）把 Windows 回环口的流量代理进 WSL2 —— 这个中转在
**Windows 10 + NAT** 组合下本来就脆弱，最常见的就是 **IPv6 (`::1`) 与 IPv4 (`127.0.0.1`)
不匹配**导致连接落空。

---

## 1. 本机的真实网络拓扑（NAT 模式）

```
┌─────────────────────────────── Windows 10 主机 (build 19045) ───────────────────────────────┐
│                                                                                             │
│   浏览器 (Chrome)                                                                            │
│     │  http://localhost:8090  ── 解析 ──▶ ::1 (IPv6 回环)  ┐                                  │
│     │                          └─ 或 ──▶ 127.0.0.1 (IPv4) ┘                                  │
│     │                                          │                                            │
│     │                                          ▼                                            │
│     │                            wslhost.exe (localhostForwarding 中转)  ← 脆弱 / 可能不在    │
│     │                                          │  仅代理 127.0.0.1，常漏掉 ::1               │
│     │                                                                                       │
│   vEthernet (WSL) 适配器：192.168.96.1/20   ◀── 直达路由 ──┐                                  │
│                                                            │                                │
└────────────────────────────────────────────────────────────┼──────────────────────────────┘
                                                              │  Hyper-V NAT 虚拟交换机
┌─────────────────────────────────────────────────────────────┼──────────────────────────────┐
│  WSL2 虚拟机                                                  ▼                              │
│    eth0：192.168.101.242/20    coordinator 监听 0.0.0.0:8090  ◀── http://192.168.101.242:8090 │
│    lo  ：127.0.0.1             （0.0.0.0 = 同时监听 eth0 和 lo）                              │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

本机实测数据（`ip addr` / `ip route` / `.wslconfig`）：

| 项 | 值 |
|---|---|
| WSL2 网络模式 | `networkingMode=nat`（`C:\Users\Helios\.wslconfig`） |
| localhost 转发 | `localhostForwarding=true` |
| WSL2 `eth0` IP | `192.168.101.242/20` |
| WSL2 默认网关（= Windows 端 vEthernet(WSL)） | `192.168.96.1` |
| coordinator 监听地址 | `0.0.0.0:8090`（见 `coordinator/__main__.py` 默认 `--host`） |
| Windows 版本 | 10 22H2 / build 19045（mirrored 模式需 Win11 22621+，故回落 NAT） |

---

## 2. 为什么 `192.168.101.242:8090` 一定能通

1. NAT 模式下，WSL2 跑在一块 Hyper-V「vEthernet (WSL)」虚拟交换机后面，主机在这块交换机上的地址是 `192.168.96.1`，WSL2 虚拟机是 `192.168.101.242`，两者在同一个 `192.168.96.0/20` 子网里。
2. Windows 主机对这个子网有一条**直连路由**，可以像访问局域网里另一台机器一样直接连到 `192.168.101.242`。
3. coordinator 监听在 `0.0.0.0:8090`，`0.0.0.0` 表示「本机所有网卡」，自然**包含 `eth0`（192.168.101.242）**。
4. 于是 `http://192.168.101.242:8090` 是「主机 → 虚拟交换机 → 虚拟机网卡 → 监听端口」一条**纯直连**链路，**没有任何用户态中转进程**，所以稳定。

> 唯一缺点：这个 IP **每次 `wsl --shutdown` / 重启后可能变化**（NAT 是动态分配）。这正是启动横幅每次都重新计算并打印该 IP 当 fallback 的原因（`_primary_ip()`）。

---

## 3. 为什么 `localhost:8090` 经常打不开

`localhost` 在 Windows 这一侧根本到不了 WSL2 的网卡，它必须靠 `localhostForwarding=true` 启动的中转进程 `wslhost.exe`：在 Windows 的回环口监听同样的端口，再把流量代理进 WSL2。这套机制在 **Windows 10 + NAT** 下出名地不稳定，常见失败原因（按概率排序）：

1. **IPv6 `::1` vs IPv4 `127.0.0.1` 不匹配（最常见）**
   现代 Windows 把 `localhost` **优先解析为 IPv6 `::1`**，但 WSL2 的 localhost 转发中转**通常只在 IPv4 `127.0.0.1` 上建代理**。于是浏览器连 `::1:8090`，Windows 端没人监听 → 直接失败；而你手敲 IP 走的是 IPv4，绕开了这个坑。
   - 自检：Windows PowerShell 里 `ping localhost`，若回显 `::1` 就是命中此因。

2. **中转进程没起来 / 已失效（很常见）**
   `localhostForwarding` 的代理是在 WSL **首次绑定端口时**由 Windows 侧动态建立的，且在 **睡眠唤醒、`wsl --shutdown`、WSL IP 变化、coordinator 重启**后经常不重建，变成「陈旧转发」。表现就是 IP 能通、localhost 不通。

3. **Windows 10 上该特性本身就在被放弃**
   微软已把可靠的「localhost 直通」迁移到 **mirrored 网络模式**（需要 Win11 22H2+）。本机是 Win10，只能用 NAT + 老的 localhostForwarding，先天不可靠 —— 这也是 `.wslconfig` 注释里写明「mirrored 需要 Win11，本机回落 NAT」的原因。

4. **其它拦截**：第三方 VPN / 代理 / 安全软件接管了回环口，或 Windows 防火墙挡了 `wslhost.exe`。

---

## 4. 怎么办（按推荐顺序）

1. **直接用 WSL2 IP（当前做法，最省事）**
   用启动横幅打印的 `http://192.168.101.242:8090`。缺点：重启后 IP 可能变，需要看新横幅。

2. **把 `localhost` 强制成 IPv4**
   在 Windows 浏览器里改用 `http://127.0.0.1:8090`（绕开 `::1`）。若仍不行，多半是中转进程没起（见第 3 条），转第 3 步。

3. **重建转发：`wsl --shutdown` 后重开**
   Windows PowerShell 执行 `wsl --shutdown`，等几秒重新打开 WSL 终端再启动 coordinator。这会让 `wslhost.exe` 重新建立 localhost 代理。（注意：重启后 WSL IP 可能变，请以新横幅为准。）

4. **加一条固定端口转发（让 localhost 永久可用，IP 变也不怕）**
   在 Windows **管理员** PowerShell 里把回环口的 8090 代理到当前 WSL IP：
   ```powershell
   # 取当前 WSL IP
   $wsl = (wsl hostname -I).Trim().Split(' ')[0]
   # IPv4 回环转发
   netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=8090 connectaddress=$wsl connectport=8090
   # 防火墙放行
   netsh advfirewall firewall add rule name="wsl-8090" dir=in action=allow protocol=TCP localport=8090
   ```
   删除：`netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=8090`。
   因为 WSL IP 每次重启会变，建议把上面两行 `netsh` 写成一个开机脚本（先 `delete` 再 `add`）。

5. **根治：升级到 Windows 11 并改用 mirrored 模式**
   `.wslconfig` 改 `networkingMode=mirrored`，`wsl --shutdown` 重启后，WSL2 与主机共享网络命名空间，`localhost:8090` 与 `127.0.0.1:8090` 都能**直接、可靠**地访问。本机是 Win10，暂不可用。

---

## 5. 一句话排查口诀

> **IP 能开、localhost 打不开 = WSL2 的 localhost 中转出问题了**（多半是 `::1`/`127.0.0.1` 之争或中转失效），
> 跟 coordinator 本身无关 —— 它已经正确监听 `0.0.0.0:8090`。**先用横幅里的 WSL IP，要长期省心就上第 4 步的 portproxy 或 Win11 mirrored。**
