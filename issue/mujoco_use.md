# MuJoCo / Unitree SDK2 启动报错：`/tmp/cdds.LOG: cannot open for writing`

## 现场报错

同学在 `techlab-compute` 共享服务器上、`unitree_mujoco` 这个 conda 环境中启动 `g1_sim_rl_combo.py` 时出现：

```
(unitree_mujoco) capstone-cs47-2@techlab-compute:~/unitree-notes/g1_sim_demo$ python3 g1_sim_rl_combo.py
1777863486.506265 [1] python3: /tmp/cdds.LOG: cannot open for writing
[ChannelFactory] create domain error. msg: Occurred upon initialisation of a cyclonedds.domain.Domain
Traceback (most recent call last):
  File ".../g1_sim_rl_combo.py", line 1010, in <module>
    main()
  File ".../g1_sim_rl_combo.py", line 928, in main
    ChannelFactoryInitialize(1, "lo")
  File ".../unitree_sdk2_python/unitree_sdk2py/core/channel.py", line 301, in ChannelFactoryInitialize
    raise Exception("channel factory init error.")
Exception: channel factory init error.
```

## 这是什么错误？不是 MuJoCo 的错

虽然脚本叫 `g1_sim_*`，看起来像 MuJoCo 仿真挂了，但**真正报错的不是 MuJoCo**，而是 Unitree SDK2 底层用来做机器人通信的 **CycloneDDS** 中间件。

调用链是这样的：

1. `g1_sim_rl_combo.py` → `ChannelFactoryInitialize(1, "lo")`
   说明这个脚本要建立 DDS 通信域（domain id = 1，绑定到 loopback 网卡 `lo`），用来在仿真器和策略进程之间互发 LowState / LowCmd 消息。
2. `unitree_sdk2py/core/channel.py:300` 调用 `factory.Init(...)`，里面会去构造一个 `cyclonedds.domain.Domain`。
3. CycloneDDS 在初始化 Domain 时，**默认会打开 `/tmp/cdds.LOG` 这个 trace/日志文件来写入**（即便你没显式开 tracing，它也会尝试 open 一下）。
4. 当前用户对 `/tmp/cdds.LOG` **没有写权限** → `cannot open for writing` → Domain 创建失败 → `factory.Init` 返回 False → SDK 抛 `channel factory init error`。

所以根因是：**`/tmp/cdds.LOG` 这个文件存在，但它的 owner 不是当前登录的用户，而你又对它没有写权限。**

## 为什么会出现这种情况？

这是**多用户共享 Linux 主机**最经典的坑之一。`/tmp` 一般是 1777 权限（sticky bit + 全员可写），任何用户都能在里面建文件，但**建好的文件归谁所有就只有谁能写**。

典型场景：

- 之前另外一个同学（比如 `capstone-cs47-1`）先在这台机器上跑过 Unitree 脚本，CycloneDDS 自动建了 `/tmp/cdds.LOG`，owner 是他。
- 或者有人之前用 `sudo` 跑过一次，文件 owner 变成了 `root`，权限 `-rw-r--r--`。
- 后来 `capstone-cs47-2` 再跑同一个脚本，open() 那个文件就 EACCES。

可以用下面这条命令直接确认：

```bash
ls -l /tmp/cdds.LOG
```

如果输出类似 `-rw-r--r-- 1 someone_else someone_else  ... /tmp/cdds.LOG`，并且 `someone_else` 不是你自己，那就是这个问题。

## 解决方法（按推荐顺序）

### 方法 1：删掉那个文件（最简单，推荐先试）

```bash
rm /tmp/cdds.LOG
```

如果是自己之前残留的文件，这条就够了。下次脚本启动时 CycloneDDS 会重新建一个，owner 就是你。

如果提示 `Operation not permitted`，说明文件不归你 —— 因为 `/tmp` 有 sticky bit，**只有 owner 或 root 能删**。这时候用：

```bash
sudo rm /tmp/cdds.LOG
```

或者让原 owner 自己删。

### 方法 2：把日志文件改到你自己 home 目录下（永久方案）

如果这台机器经常多人轮流用，每次都要 `rm /tmp/cdds.LOG` 很烦，可以让 CycloneDDS 把日志写到自己 home 下，互相不冲突。新建一个配置文件，比如 `~/cyclonedds.xml`：

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<CycloneDDS xmlns="https://cdds.io/config"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:schemaLocation="https://cdds.io/config https://raw.githubusercontent.com/eclipse-cyclonedds/cyclonedds/master/etc/cyclonedds.xsd">
  <Domain Id="any">
    <Tracing>
      <OutputFile>/home/capstone-cs47-2/cdds.log</OutputFile>
      <Verbosity>warning</Verbosity>
    </Tracing>
  </Domain>
</CycloneDDS>
```

然后在 shell 里 export（建议直接写进 `~/.bashrc` 或者 conda env 的 `activate.d`）：

```bash
export CYCLONEDDS_URI="file://$HOME/cyclonedds.xml"
```

之后无论谁来跑，日志都落在各自 `$HOME` 下，绝对不会撞车。

### 方法 3：粗暴一点 —— 一次性把权限改全员可写

```bash
sudo chmod 666 /tmp/cdds.LOG
```

不太推荐，因为下次有人 `rm` 了它，下一个用户重建后又是 644，问题会反复出现。当作临时救急可以。

## 怎么避免再次踩到

- **共享机器上跑 Unitree SDK2 / cyclonedds 之前**，先 `ls -l /tmp/cdds.LOG`，看一眼 owner 是不是自己；不是就先 `rm`。
- 长期用同一台机器的话，建议直接走**方法 2**，把 `CYCLONEDDS_URI` 写进自己的 conda env activation 脚本里，永绝后患。
- 注意这个错误**和 MuJoCo 本身、和 Python 版本、和 conda 环境完整性都没有关系**，看到 `ChannelFactoryInitialize` + `cyclonedds.domain.Domain` 这两行就直接朝 `/tmp/cdds.LOG` 权限去查。

## 顺手核对：环境本身有没有问题

如果删了 `/tmp/cdds.LOG` 之后还是报 `channel factory init error`，再依次检查：

1. **网卡参数**：`ChannelFactoryInitialize(1, "lo")` 第二个参数是网卡名。本地 sim 用 `lo` 没问题；如果是连真机就要改成实际能通到机器人的网卡（比如 `eth0`、`enp3s0`）。`ip addr` 看一下网卡名对不对。
2. **Domain ID 冲突**：`1` 是仿真常用的 domain id（真机一般是 `0`）。如果同一台机器上还有别的进程也开了 domain 1 并占了端口，可能会失败 —— `ss -lup | grep -E '74(00|01)'` 看一下 7400/7401 系列端口（DDS 默认）。
3. **`unitree_sdk2py` 是不是装在当前 conda env 里**：
   ```bash
   python -c "import unitree_sdk2py, cyclonedds; print(unitree_sdk2py.__file__); print(cyclonedds.__file__)"
   ```
   两个都能 import 出来才说明环境是齐的。
